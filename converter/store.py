import hashlib
import json
import os
import re
import shutil
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from .engine import VERSION

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()

def atomic(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+f'.{os.getpid()}.{time.time_ns()}.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    os.replace(temp,path)

def job_id(value):
    if not isinstance(value,str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,100}',value):
        raise ValueError('Job ID must contain lowercase letters, numbers and hyphens only.')
    return value

class Store:
    def __init__(self,home):
        self.home=Path(home).resolve()
        for name in ['queue','inbox','sources','jobs','exports','state','logs']:
            (self.home/name).mkdir(parents=True,exist_ok=True)
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS jobs (
                  id TEXT PRIMARY KEY, source TEXT NOT NULL, fingerprint TEXT NOT NULL,
                  status TEXT NOT NULL, updated REAL NOT NULL, flags INTEGER DEFAULT 0,
                  fields INTEGER DEFAULT 0, folder TEXT, error TEXT, approval_hash TEXT);
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
            ''')

    @contextmanager
    def db(self):
        db=sqlite3.connect(self.home/'state'/'converter.sqlite3',timeout=20)
        db.row_factory=sqlite3.Row
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def get(self,id):
        with self.db() as db:
            row=db.execute('SELECT * FROM jobs WHERE id=?',(job_id(id),)).fetchone()
        if not row:raise ValueError('Job not found.')
        return dict(row)

    def setting(self,key,value=None):
        with self.db() as db:
            if value is not None:
                db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',(key,value))
            row=db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
            return row[0] if row else None

    def add_asset(self,path,role,name=None,expected=None):
        path=Path(path);data=path.read_bytes();sha=hashlib.sha256(data).hexdigest()
        if data[:5]!=b'%PDF-':raise ValueError(f'{path.name} is not a PDF.')
        if expected and sha!=expected:raise ValueError(f'Archive hash mismatch: {path.name}')
        dest=self.home/'sources'/f'{sha}.pdf'
        if not dest.exists():
            temp=dest.with_suffix('.tmp');temp.write_bytes(data);os.replace(temp,dest)
        return dict(role=role,name=name or path.name,sha256=sha,path=f'sources/{sha}.pdf')

    def enqueue(self,source):
        id=job_id(source['id'])
        atomic(self.home/'queue'/f'{id}.json',source)
        self.register(source)

    def register(self,source):
        id=job_id(source['id'])
        # Asset files are content-addressed and immutable; changes require re-import.
        fp=digest(dict(version=VERSION,source=source))
        with self.db() as db:
            old=db.execute('SELECT fingerprint FROM jobs WHERE id=?',(id,)).fetchone()
            if old and old[0]==fp:return
            db.execute('''INSERT INTO jobs(id,source,fingerprint,status,updated) VALUES(?,?,?,'queued',?)
                          ON CONFLICT(id) DO UPDATE SET source=excluded.source,fingerprint=excluded.fingerprint,
                          status='queued',updated=excluded.updated,approval_hash=NULL,error=NULL''',
                       (id,json.dumps(source),fp,time.time()))

    def scan(self):
        for path in sorted((self.home/'queue').glob('*.json')):
            try:self.register(json.loads(path.read_text(encoding='utf-8-sig')))
            except Exception as error:self.setting('last_scan_error',f'{path.name}: {str(error)[:180]}')
        # A new inbox folder needs metadata.json + test.pdf; key.pdf is optional but flagged.
        for folder in sorted((self.home/'inbox').iterdir()):
            if not folder.is_dir() or not (folder/'metadata.json').is_file():continue
            try:
                stamp=digest([(p.name,p.stat().st_size,p.stat().st_mtime_ns) for p in sorted(folder.iterdir()) if p.is_file()])
                if self.setting('inbox:'+folder.name)==stamp:continue
                meta=json.loads((folder/'metadata.json').read_text(encoding='utf-8-sig'))
                meta['id']=job_id(meta.get('id',folder.name.lower().replace(' ','-')))
                meta['assets']=[]
                for path in sorted(folder.glob('*.pdf')):
                    role='test' if path.name.lower()=='test.pdf' else 'key' if path.name.lower()=='key.pdf' else 'supplement'
                    meta['assets'].append(self.add_asset(path,role))
                self.enqueue(meta);self.setting('inbox:'+folder.name,stamp)
            except Exception as error:self.setting('last_scan_error',f'Inbox {folder.name}: {str(error)[:180]}')

    def recover(self):
        with self.db() as db:
            db.execute("UPDATE jobs SET status='queued',error='Resuming interrupted extraction' WHERE status='processing'")

    def claim(self):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY updated,id LIMIT 1").fetchone()
            if not row:return None
            db.execute("UPDATE jobs SET status='processing',updated=? WHERE id=?",(time.time(),row['id']))
            return dict(row)

    def complete(self,row,folder,draft):
        with self.db() as db:
            db.execute("UPDATE jobs SET status='needs_review',flags=?,fields=?,folder=?,error=NULL,updated=? WHERE id=? AND fingerprint=?",
                       (len(draft['flags']),len(draft['fields']),str(folder.relative_to(self.home)),time.time(),row['id'],row['fingerprint']))

    def fail(self,row,message):
        with self.db() as db:
            db.execute("UPDATE jobs SET status='failed',error=?,updated=? WHERE id=? AND fingerprint=?",(message[:1000],time.time(),row['id'],row['fingerprint']))

    def detail(self,id):
        row=self.get(id);source=json.loads(row['source']);draft=review=None
        if row.get('folder'):
            path=self.home/row['folder']/'draft.json'
            if path.exists():draft=json.loads(path.read_text(encoding='utf-8'))
        review_path=self.home/'jobs'/id/'review.json'
        if review_path.exists():review=json.loads(review_path.read_text(encoding='utf-8'))
        return dict(row=row,source=source,draft=draft,review=review)

    def save_review(self,id,review):
        row=self.get(id)
        if row['status'] in ['queued','processing']:raise ValueError('Wait until extraction finishes.')
        if review.get('id')!=id or review.get('sourceFingerprint')!=row['fingerprint']:
            raise ValueError('This review belongs to an older source. Refresh the review from the current draft before saving.')
        atomic(self.home/'jobs'/id/'review.json',review)
        with self.db() as db:db.execute("UPDATE jobs SET status='needs_review',approval_hash=NULL,updated=? WHERE id=?",(time.time(),id))

    def snapshot(self):
        with self.db() as db:
            rows=[dict(r) for r in db.execute('SELECT id,source,status,updated,flags,fields,error FROM jobs ORDER BY updated DESC')]
        for r in rows:
            source=json.loads(r.pop('source'))
            r.update({k:source.get(k) for k in ['competition','eventId','division','year']})
        return dict(jobs=rows,paused=self.setting('paused')=='yes',lastScanError=self.setting('last_scan_error'),home=str(self.home),version=VERSION)
