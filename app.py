"""Portable local application. All document processing stays on this computer."""
import argparse
import base64
import hashlib
import json
import logging
import os
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse
from converter.engine import convert
from converter.store import Store, atomic, job_id
from converter.review import approve, export, validate
from converter.gemini import AIService, GeminiClient

RESOURCES=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))

class InstanceLock:
    def __init__(self,path):self.path=path
    def __enter__(self):
        self.file=open(self.path,'a+b')
        if self.path.stat().st_size==0:self.file.write(b'1');self.file.flush()
        self.file.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.file.close();raise AlreadyRunning('The converter is already running for this folder. Open its dashboard.')
        return self
    def __exit__(self,*args):self.file.close()

class AlreadyRunning(RuntimeError):pass

def worker(home,id):
    store=Store(home);row=store.get(id);source=json.loads(row['source'])
    folder=store.home/'jobs'/id/'runs'/row['fingerprint']
    draft,review=convert(source,store.home,folder,row['fingerprint'],ocr=True)
    review_path=store.home/'jobs'/id/'review.json'
    if not review_path.exists():atomic(review_path,review)
    # Always save a clean new review template, but never overwrite manual work.
    atomic(folder/'review-template.json',review)
    store.complete(row,folder,draft)

def process_queue(store,stop,once=False,limit=None):
    processed=0
    while not stop.is_set():
        try:
            store.scan()
            if store.setting('paused')=='yes':
                if once:break
                stop.wait(3);continue
            row=store.claim()
            if not row:
                if once:break
                stop.wait(15);continue
            args=[sys.executable]
            if not getattr(sys,'frozen',False):args.append(str(RESOURCES/'app.py'))
            args += ['--home',str(store.home),'--worker',row['id']]
            env=os.environ.copy();env.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
            logpath=store.home/'logs'/f"{row['id']}.log"
            with open(logpath,'ab') as log:
                child=subprocess.Popen(args,stdout=log,stderr=log,env=env,
                      creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                deadline=time.monotonic()+600
                while child.poll() is None and not stop.wait(.5):
                    if time.monotonic()>deadline:break
                if child.poll() is None:
                    child.terminate()
                    try:child.wait(5)
                    except subprocess.TimeoutExpired:child.kill();child.wait()
                    if stop.is_set():
                        with store.db() as db:db.execute("UPDATE jobs SET status='queued' WHERE id=? AND status='processing'",(row['id'],))
                    else:store.fail(row,'Processing exceeded 10 minutes. Split this paper or review its OCR, then retry.')
                elif child.returncode:
                    store.fail(row,'Extraction failed. See logs/'+logpath.name+'. Fix the source or dependencies and retry.')
            processed+=1
            if limit and processed>=limit:break
        except Exception:
            logging.exception('Queue error')
            if once:raise
            stop.wait(10)

def make_handler(store,stop,token,port,ai=None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def allowed_host(self):return self.headers.get('Host') in [f'127.0.0.1:{port}',f'localhost:{port}']
        def send(self,status,data,kind='application/json'):
            if kind=='application/json':data=json.dumps(data,ensure_ascii=False,allow_nan=False).encode('utf-8')
            self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(data)))
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('X-Frame-Options','SAMEORIGIN')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-src 'self'; object-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'self'")
            self.end_headers();self.wfile.write(data)
        def do_GET(self):
            if not self.allowed_host():return self.send(403,{'error':'Use the local dashboard address.'})
            path=unquote(urlparse(self.path).path)
            try:
                if path=='/api/status':return self.send(200,store.snapshot())
                if path=='/api/ai' and ai:return self.send(200,ai.snapshot())
                if path=='/api/session':return self.send(200,{'token':token})
                if path=='/api/events':return self.send(200,json.loads((RESOURCES/'events.json').read_text(encoding='utf-8')))
                if path.startswith('/api/job/'):
                    detail=store.detail(job_id(path.split('/')[-1]));detail['validation']=validate(detail)
                    detail['aiBusy']=ai.busy(detail['row']['id']) if ai else False
                    return self.send(200,detail)
                if path=='/health':return self.send(200,{'app':'science-olympiad-batch-converter','running':True})
                if path.startswith('/sources/') or path.startswith('/exports/') or path.startswith('/jobs/'):
                    file=(store.home/path.lstrip('/')).resolve()
                    if not file.is_relative_to(store.home) or not file.is_file() or file.suffix not in ['.pdf','.png','.zip','.json']:
                        return self.send(404,{'error':'File not found.'})
                    kind={'.pdf':'application/pdf','.png':'image/png','.zip':'application/zip','.json':'application/json'}[file.suffix]
                    if file.suffix=='.json':return self.send(200,json.loads(file.read_text(encoding='utf-8')))
                    return self.send(200,file.read_bytes(),kind)
                names={'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),'/style.css':('style.css','text/css; charset=utf-8'),'/batch.js':('batch.js','text/javascript; charset=utf-8'),'/ai.js':('ai.js','text/javascript; charset=utf-8')}
                if path not in names:return self.send(404,{'error':'Not found'})
                name,kind=names[path];return self.send(200,(RESOURCES/'web'/name).read_bytes(),kind)
            except Exception as error:self.send(400,{'error':str(error)[:1200]})
        def do_POST(self):
            if not self.allowed_host() or not secrets.compare_digest(self.headers.get('X-Converter-Token',''),token):
                return self.send(403,{'error':'Reload the local dashboard before making changes.'})
            origin=self.headers.get('Origin')
            if origin and origin not in [f'http://127.0.0.1:{port}',f'http://localhost:{port}']:
                return self.send(403,{'error':'Local dashboard requests only.'})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if size<=0 or size>150*1024*1024:raise ValueError('Upload is too large. Use the inbox for PDFs larger than 100 MB.')
                body=json.loads(self.rfile.read(size));path=urlparse(self.path).path
                if path.startswith('/api/ai-'):
                    if ai is None:raise ValueError('AI service is unavailable.')
                    if path=='/api/ai-settings':return self.send(200,ai.keys.save(body))
                    if path=='/api/ai-forget':return self.send(200,ai.keys.clear())
                    if path=='/api/ai-test':
                        if not ai.keys.key:raise ValueError('Save your API key first.')
                        return self.send(200,GeminiClient(ai.keys.key,ai.keys.public()['model'],threading.Event()).test())
                    if path=='/api/ai-run':
                        if body.get('consent') is not True:raise ValueError('Confirm sending the selected PDFs to Google before AI repair.')
                        return self.send(200,ai.enqueue(body.get('ids'),bool(body.get('autoApprove')),bool(body.get('autoExport'))))
                    if path=='/api/ai-cancel':return self.send(200,ai.cancel_all())
                    raise ValueError('Unknown AI operation.')
                if path=='/api/pause':
                    store.setting('paused','yes' if body.get('paused') else 'no');return self.send(200,{'message':'Paused after the current paper.' if body.get('paused') else 'Processing resumed.'})
                if path=='/api/stop':
                    stop.set();
                    if ai:ai.cancel_all()
                    return self.send(200,{'message':'Converter stopped. You can close this tab; use Start Converter to resume later.'})
                if path=='/api/upload':
                    meta=body['metadata'];assets=[]
                    if meta.get('division') not in ['B','C']:raise ValueError('Select Division B or C.')
                    if not isinstance(meta.get('year'),int) or not 1984<=meta['year']<=2027:raise ValueError('Choose a competition year from 1984 to 2027.')
                    for key in ['competition','eventId','sourceUrl']:
                        if not isinstance(meta.get(key),str) or not meta[key].strip():raise ValueError(f'Enter {key} before uploading.')
                    if not meta['sourceUrl'].startswith('https://'):raise ValueError('Use the original HTTPS source link.')
                    total=0
                    for f in body['files']:
                        if f['role'] not in ['test','key','supplement']:raise ValueError('Invalid file role.')
                        data=base64.b64decode(f['data'],validate=True)
                        total+=len(data)
                        if total>100*1024*1024:raise ValueError('Each test packet must be under 100 MB combined. Use the inbox for larger packets.')
                        if len(data)>100*1024*1024 or not data.startswith(b'%PDF-'):raise ValueError('Choose PDF files under 100 MB.')
                        sha=hashlib.sha256(data).hexdigest();p=store.home/'sources'/f'{sha}.pdf'
                        if not p.exists():
                            temp=p.with_name(p.name+'.'+str(time.time_ns())+'.tmp');temp.write_bytes(data);os.replace(temp,p)
                        assets.append(dict(role=f['role'],name=Path(f['name']).name,sha256=sha,path=f'sources/{sha}.pdf'))
                    tests=[a for a in assets if a['role']=='test'];keys=[a for a in assets if a['role']=='key']
                    if len(tests)!=1 or len(keys)>1:raise ValueError('Choose one test and at most one answer-key PDF.')
                    id=job_id('local-'+tests[0]['sha256'][:14]+'-'+str(meta.get('division','')).lower())
                    if body.get('skipExisting'):
                        with store.db() as db:
                            known=[dict(r) for r in db.execute('SELECT id,source FROM jobs')]
                        existing=None
                        for candidate in known:
                            saved=json.loads(candidate['source'])
                            if saved.get('division')==meta['division'] and any(a.get('role')=='test' and a.get('sha256')==tests[0]['sha256'] for a in saved.get('assets',[])):
                                existing=candidate['id'];break
                        if existing:return self.send(200,{'message':'This paper is already in the queue for this division; it was skipped.', 'id':existing,'alreadyExists':True})
                    source={k:meta.get(k) for k in ['competition','eventId','division','year','sourceUrl']}
                    source.update(id=id,level=None,assets=assets)
                    store.enqueue(source);return self.send(200,{'message':'Added to the local queue. Missing keys will be flagged.', 'id':id})
                id=job_id(body['id'])
                if ai and ai.busy(id):raise ValueError('AI repair is in progress for this test. Cancel it or wait before editing, retrying or exporting.')
                if path=='/api/save':store.save_review(id,body['review']);return self.send(200,{'message':'Review saved. Approval is required again after edits.'})
                if path=='/api/reset-review':
                    row=store.get(id)
                    if not row.get('folder'):raise ValueError('Extraction has not finished.')
                    review_path=store.home/'jobs'/id/'review.json'
                    if review_path.exists():shutil_copy=review_path.with_name(f'review-backup-{time.time_ns()}.json');shutil_copy.write_bytes(review_path.read_bytes())
                    template=json.loads((store.home/row['folder']/'review-template.json').read_text(encoding='utf-8'))
                    store.save_review(id,template);return self.send(200,{'message':'Started from the latest draft. Previous review saved as a backup.'})
                if path=='/api/approve':return self.send(200,approve(store,id))
                if path=='/api/export':return self.send(200,export(store,id))
                if path=='/api/retry':
                    with store.db() as db:db.execute("UPDATE jobs SET status='queued',approval_hash=NULL,error=NULL WHERE id=? AND status!='processing'",(id,))
                    return self.send(200,{'message':'Queued again. Manual review edits will be preserved.'})
                return self.send(404,{'error':'Unknown operation.'})
            except Exception as error:self.send(400,{'error':str(error)[:8000]})
    return Handler

def desktop(url,home,stop=None,debug_port=None):
    try:import webview
    except ImportError:raise RuntimeError('Desktop components are missing. Run Start Converter to install the current requirements.') from None
    webview.settings['ALLOW_DOWNLOADS']=True
    if debug_port:webview.settings['REMOTE_DEBUGGING_PORT']=debug_port
    window=webview.create_window('Science Olympiad Test Exchange — Batch Converter',url,width=1360,height=900,min_size=(800,600),background_color='#f5f4ef',confirm_close=False)
    if stop:
        window.events.closed += lambda:stop.set()
        def close_when_stopped():
            stop.wait()
            try:window.destroy()
            except Exception:pass
        threading.Thread(target=close_when_stopped,daemon=True).start()
    webview.start(gui='edgechromium' if os.name=='nt' else None,private_mode=True,storage_path=str(home/'state'/'desktop'))


def main():
    parser=argparse.ArgumentParser(description='Local Science Olympiad PDF conversion and review.')
    parser.add_argument('--home',type=Path);parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--browser',action='store_true',help='Optional browser mode; desktop is the default')
    parser.add_argument('--desktop-debug-port',type=int,help=argparse.SUPPRESS)
    parser.add_argument('--headless',action='store_true');parser.add_argument('--once',action='store_true')
    parser.add_argument('--limit',type=int);parser.add_argument('--worker')
    args=parser.parse_args()
    base=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent
    home=(args.home or base/'data').resolve();store=Store(home)
    logging.basicConfig(filename=home/'logs'/'app.log',level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    if args.worker:
        worker(home,job_id(args.worker));return
    url=f'http://127.0.0.1:{args.port}'
    try:
        lock=InstanceLock(home/'state'/'instance.lock');lock.__enter__()
    except AlreadyRunning:
        if not args.headless and not args.once:
            if args.browser:webbrowser.open(store.setting('dashboard') or url)
            else:desktop(store.setting('dashboard') or url,home,None,args.desktop_debug_port)
        return
    try:
        store.recover();stop=threading.Event()
        if args.once:process_queue(store,stop,once=True,limit=args.limit);return
        ai=AIService(store,stop)
        server=ThreadingHTTPServer(('127.0.0.1',args.port),make_handler(store,stop,secrets.token_urlsafe(32),args.port,ai))
        thread=threading.Thread(target=process_queue,args=(store,stop),daemon=True);thread.start()
        ai_thread=threading.Thread(target=ai.loop,daemon=True);ai_thread.start()
        server.timeout=1
        def serve():
            while not stop.is_set():server.handle_request()
        server_thread=threading.Thread(target=serve,daemon=True);server_thread.start()
        store.setting('dashboard',url)
        try:
            if not args.headless and not args.browser:desktop(url,home,stop,args.desktop_debug_port)
            else:
                if args.browser:webbrowser.open(url)
                while not stop.wait(1):pass
        except KeyboardInterrupt:pass
        finally:
            stop.set();ai.cancel_all();thread.join(timeout=10);server_thread.join(timeout=3);server.server_close()
    finally:lock.__exit__()

if __name__=='__main__':
    try:main()
    except Exception as error:
        logging.exception('Application stopped')
        if os.name=='nt' and (getattr(sys,'frozen',False) or Path(sys.executable).stem.lower()=='pythonw'):
            import ctypes
            ctypes.windll.user32.MessageBoxW(0,str(error),'Science Olympiad Batch Converter',0)
        else:raise
