import datetime
import hashlib
import json
import math
import shutil
import sys
import zipfile
from pathlib import Path
from .store import atomic, digest

def finite(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>=0

def validate(detail):
    review,draft,row=detail['review'],detail['draft'],detail['row']
    errors=[]
    if not review or not draft:return ['Extraction and a review file are required.']
    if review.get('sourceFingerprint')!=row['fingerprint'] or draft.get('fingerprint')!=row['fingerprint']:
        return ['Source changed. Start from the latest draft; old approval cannot be reused.']
    if not review.get('reviewer','').strip():errors.append('Enter the reviewer name.')
    for f in draft['flags']:
        if not str(review.get('resolutions',{}).get(f['id'],'')).strip():
            errors.append(f"Resolve {f['category']}: {f['message']}")
    m=review.get('metadata',{})
    for key in ['competition','eventId','sourceUrl','difficultyReason','alignment','scoringBasis','instructions']:
        if not isinstance(m.get(key),str) or not m[key].strip():errors.append(f'Metadata needs {key}.')
    if not m.get('sourceUrl','').startswith('https://'):errors.append('Supply the original HTTPS source URL.')
    if m.get('division') not in ['B','C']:errors.append('Select Division B or C.')
    event_file=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent.parent))/'events.json'
    if event_file.exists():
        events=json.loads(event_file.read_text(encoding='utf-8'))
        if m.get('eventId') not in [e['id'] for e in events.get(m.get('division'),[])]:errors.append('Event ID does not belong to the selected division.')
    if m.get('difficulty') not in ['Easy','Medium','Hard']:errors.append('Difficulty must be Easy, Medium or Hard.')
    if m.get('topicMatch') not in ['current','different','unverified']:errors.append('Select a valid topic alignment.')
    if not isinstance(m.get('topics'),list) or not m['topics'] or any(not isinstance(t,str) or not t.strip() for t in m['topics']):errors.append('Add the tested topics.')
    if m.get('level') not in [None,'Regionals','States','Nationals']:errors.append('Use a reported Regional, State or National level, or leave it blank.')
    if m.get('level') and not m.get('levelText'):errors.append('A reported competition level needs source evidence in levelText.')
    if not isinstance(m.get('year'),int) or not 1984<=m['year']<=2027:errors.append('Check the competition year.')
    if m.get('season')!=2027:errors.append('This Akoizo exporter targets season 2027.')
    fields=review.get('fields',[]);seen=set()
    if not fields:errors.append('No questions to export.')
    for f in fields:
        id=f.get('id');where=f'Question {id}'
        if not isinstance(id,str) or not id or id in seen:errors.append(where+': missing or repeated ID.')
        seen.add(id)
        if not isinstance(f.get('page'),int) or not 1<=f['page']<=draft['pageCounts'].get('test',0):errors.append(where+': invalid PDF page.')
        if not isinstance(f.get('prompt'),str) or not f['prompt'].strip():errors.append(where+': missing prompt.')
        if not finite(f.get('points')):errors.append(where+': invalid/missing points.')
        if not isinstance(f.get('answer'),str) or not f['answer'].strip():errors.append(where+': missing answer or exclusion explanation.')
        if f.get('type')=='mcq':
            choices=f.get('options',[]);ids=[c.get('id') for c in choices]
            if len(ids)<2 or len(set(ids))!=len(ids) or any(not c.get('id') or not c.get('text') for c in choices):errors.append(where+': incomplete answer choices.')
            correct=f.get('answer','').split(',')
            if any(c not in ids for c in correct) or (len(correct)>1 and not f.get('multiple')):errors.append(where+': invalid correct choices or multiple-selection setting.')
        elif f.get('type')!='frq':errors.append(where+': unknown question type.')
        if f.get('numeric'):
            n=f['numeric']
            if not isinstance(n.get('value'),(int,float)) or not math.isfinite(n['value']) or not finite(n.get('tolerance')) or not isinstance(n.get('units'),list):errors.append(where+': invalid numerical tolerance.')
        if f.get('criteria'):
            cs=f['criteria']
            if any(not c.get('id') or not c.get('answer') or not finite(c.get('points')) for c in cs) or len({c.get('id') for c in cs})!=len(cs):errors.append(where+': invalid rubric criteria.')
            elif not finite(f.get('points')) or abs(sum(c['points'] for c in cs)-f['points'])>1e-8:errors.append(where+': criterion points conflict with question points.')
    if all(finite(f.get('points')) for f in fields) and sum(f['points'] for f in fields)<=0:errors.append('The available score must be positive.')
    roles={a['role'] for a in detail['source'].get('assets',[]) if a.get('path')}
    for role in ['test','key','supplement']:
        if sum(a['role']==role for a in detail['source'].get('assets',[]))>1:errors.append(f'Multiple {role} files need to be combined and reviewed before export.')
    if any(not a.get('path') for a in detail['source'].get('assets',[])):errors.append('Supply every listed source file before export.')
    if not {'test','key'}<=roles:errors.append('This reviewed-rubric exporter requires both the original test and an answer-key PDF. Missing keys remain flagged; it never fabricates one.')
    return errors

def approve(store,id):
    detail=store.detail(id);errors=validate(detail)
    if errors:raise ValueError('\n'.join(errors[:40]))
    review=detail['review']
    with store.db() as db:
        db.execute("UPDATE jobs SET status='approved',approval_hash=? WHERE id=? AND fingerprint=?",(digest(review),id,review['sourceFingerprint']))
    return {'message':'Approved for export. Nothing has been added to Akoizo.'}

def export(store,id):
    detail=store.detail(id);row=detail['row'];r=detail['review']
    if row['status'] not in ['approved','exported'] or not r or row['approval_hash']!=digest(r):raise ValueError('Approve this exact review before exporting. Editing invalidates approval.')
    errors=validate(detail)
    if errors:raise ValueError('\n'.join(errors[:20]))
    m=r['metadata'];test={k:m[k] for k in ['sourceUrl','division','eventId','competition','year','level','season','difficulty','difficultyReason','topics','topicMatch','alignment','scoringBasis','instructions']}
    test.update(id=id,sourceId=m.get('sourceId'),reviewedOn=datetime.date.today().isoformat(),gradingMode='published-key',minutes=50,
                rulesUrl=f"/rules/2027/{m['division'].lower()}/{m['eventId']}.pdf",levelEvidence=None,questions=[],keys={})
    if m.get('level'):test['levelEvidence']=dict(sourceUrl=m['sourceUrl'],text=m['levelText'],basis='Explicitly reviewed source evidence; not an inferred competition tier.')
    for f in r['fields']:
        q={k:f[k] for k in ['id','page','prompt','type','points']};q['label']='Question '+f['id'];q['context']=f.get('context','')
        if f['type']=='mcq':
            q.update(options=f['options'],multiple=bool(f.get('multiple')))
            key={'correctOptions':f['answer'].split(',')} if q['multiple'] else {'correctOption':f['answer']}
        else:
            c=dict(id='answer',answer=f['answer'],points=f['points'],accepted=f.get('accepted',[]))
            if f.get('numeric'):c['numeric']=f['numeric']
            key={'criteria':f.get('criteria') or [c]}
        test['questions'].append(q);test['keys'][q['id']]=key
    test.update(questionCount=len(test['questions']),maxScore=sum(q['points'] for q in test['questions']))
    # Bundle originals byte-for-byte. Multiple supplements are retained individually for later review/import.
    assets=[]
    for a in detail['source']['assets']:
        if not a.get('path'):continue
        path=(store.home/a['path']).resolve()
        if not path.is_relative_to(store.home):raise ValueError('Asset path leaves the application folder.')
        data=path.read_bytes()
        if not data.startswith(b'%PDF-') or hashlib.sha256(data).hexdigest()!=a['sha256']:raise ValueError('Source PDF changed. Re-import and review again.')
        assets.append((a,data))
    test['paperUrl']=f'/practice/{id}/test.pdf';test['keyUrl']=f'/practice/{id}/key.pdf'
    supplements=[a for a,data in assets if a['role']=='supplement']
    if len(supplements)==1:test['supplementUrl']=f'/practice/{id}/images.pdf'
    if len(supplements)>1:raise ValueError('Multiple supplements: combine/review an image packet before export. Originals remain available; no attachment is silently dropped.')
    dest=store.home/'exports'/f'{id}.zip';temp=dest.with_suffix('.zip.tmp')
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr(f'{id}.json',json.dumps(test,ensure_ascii=False,indent=2))
        z.writestr('review-evidence.json',json.dumps(dict(approvalHash=row['approval_hash'],review=r,flags=detail['draft']['flags']),ensure_ascii=False,indent=2))
        z.writestr('source-manifest.json',json.dumps(detail['source'],ensure_ascii=False,indent=2))
        for a,data in assets:
            name={'test':'test.pdf','key':'key.pdf','supplement':'images.pdf'}[a['role']]
            z.writestr(f'public/practice/{id}/{name}',data)
        z.writestr('IMPORT.txt','Reviewed local bundle. Validate the JSON with Akoizo validatePracticeCatalog, copy public assets and merge the test by its stable ID. This export does not deploy or change Akoizo. Keep the review evidence with the import.')
    temp.replace(dest)
    with store.db() as db:db.execute("UPDATE jobs SET status='exported' WHERE id=?",(id,))
    return {'message':'Reviewed bundle created. It has not been published.', 'download':f'/exports/{id}.zip'}
