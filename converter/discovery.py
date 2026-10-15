"""User-started Firecrawl discovery, bounded downloads and verified local attachment."""
import base64
import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlparse, unquote
import pymupdf
from .gemini import crypt, NoRedirect
from .signin import SignIn, allowed_download
from .store import atomic, digest

ARCHIVE='https://scioly.org/wiki/Test_Exchange_Archive'

def pdf_url(url):
    p=urlparse(url)
    return p.scheme=='https' and p.hostname=='scioly.org' and p.port in (None,443) and not p.username and p.path.startswith('/w/images/') and p.path.lower().endswith('.pdf')

def download_pdf(url):
    if not allowed_download(url):raise ValueError('Only Scioly PDF download hosts are allowed.')
    try:
        with urllib.request.build_opener(NoRedirect).open(urllib.request.Request(url,headers={'User-Agent':'ScienceOlympiadBatchConverter/1.0'}),timeout=45) as response:
            data=response.read(50*1024*1024+1)
    except urllib.error.HTTPError as e:
        status=e.code;e.close();raise ValueError(f'Download unavailable (HTTP {status}). Sign-in or manual download may be required.') from None
    if len(data)>50*1024*1024 or not data.startswith(b'%PDF-'):raise ValueError('The download was not a PDF under 50 MB. It was not attached.')
    with pymupdf.open(stream=data,filetype='pdf') as doc:
        if doc.needs_pass or not len(doc):raise ValueError('The PDF is locked or empty.')
    return data

class FirecrawlClient:
    def __init__(self,key):self.key=key
    def call(self,endpoint,body,method=None):
        if endpoint not in ('search','scrape','interact') and not re.fullmatch(r'interact/[A-Za-z0-9_-]{1,100}(/execute)?',endpoint):raise ValueError('Unsupported Firecrawl request.')
        req=urllib.request.Request('https://api.firecrawl.dev/v2/'+endpoint,data=json.dumps(body).encode() if body is not None else None,method=method or 'POST',headers={'Authorization':'Bearer '+self.key,'Content-Type':'application/json'})
        try:
            with urllib.request.build_opener(NoRedirect).open(req,timeout=90) as r:result=json.load(r)
        except urllib.error.HTTPError as e:
            status=e.code;e.close()
            raise ValueError({401:'Firecrawl rejected the API key.',402:'Firecrawl credits are exhausted.',429:'Firecrawl rate limit reached. Retry later.'}.get(status,f'Firecrawl request failed (HTTP {status}).')) from None
        except (urllib.error.URLError,TimeoutError):raise ValueError('Firecrawl could not be reached. Retry manually.') from None
        if result.get('success') is False:raise ValueError('Firecrawl could not complete the request.')
        return result.get('data',result)
    def links(self,url):
        return self.call('scrape',{'url':url,'formats':['links'],'onlyMainContent':False}).get('links',[])
    def search(self,query):
        data=self.call('search',{'query':query,'limit':3,'sources':['web']})
        return data.get('web',[]) if isinstance(data,dict) else data

class Discovery:
    def __init__(self,store,stop,ai=None,client_factory=FirecrawlClient,downloader=download_pdf):
        self.store=store;self.stop=stop;self.ai=ai;self.factory=client_factory;self.downloader=downloader
        self.signin=SignIn();self.lock=threading.RLock();self.cancel=threading.Event();self.thread=None;self.key=''
        self.keyfile=store.home/'state'/'firecrawl-key.dpapi';self.statefile=store.home/'state'/'downloads.json'
        self.state={'status':'idle','message':'Add a Firecrawl key to find missing PDFs.','results':[]}
        if self.statefile.exists():
            try:self.state=json.loads(self.statefile.read_text(encoding='utf-8'))
            except (OSError,ValueError):pass
        if self.state['status']=='running':self.state.update(status='interrupted',message='Search stopped when the app closed. Start it again manually; no credits were spent on restart.')
        if self.keyfile.exists() and os.name=='nt':
            try:self.key=crypt(self.keyfile.read_bytes(),True).decode()
            except (ValueError,OSError):pass
    def public(self):
        with self.lock:return {'configured':bool(self.key),'remembered':self.keyfile.exists(),'canRemember':os.name=='nt','signIn':self.signin.public(),**json.loads(json.dumps(self.state))}
    def save(self,body):
        key=str(body.get('key','')).strip()
        if key:
            if not 20<=len(key)<=8192 or not re.fullmatch(r'[A-Za-z0-9_.=-]+',key):raise ValueError('Paste only the complete Firecrawl API key.')
        else:key=self.key
        if key!=self.key and self.thread and self.thread.is_alive():raise ValueError('Stop the current search before changing API keys.')
        if key!=self.key and self.signin.session:self.signin.close()
        if body.get('remember'):
            if not key:raise ValueError('Enter your Firecrawl key first.')
            temp=self.keyfile.with_suffix('.tmp');temp.write_bytes(crypt(key.encode()));os.replace(temp,self.keyfile)
        else:self.keyfile.unlink(missing_ok=True)
        self.key=key;return self.public()
    def forget(self):
        self.cancel.set();self.signin.close();self.key='';self.keyfile.unlink(missing_ok=True);return self.public()
    def persist(self):
        with self.lock:atomic(self.statefile,self.state)
    def check(self):
        if self.stop.is_set() or self.cancel.is_set():raise InterruptedError('Search cancelled. Already saved PDFs are retained.')
    def start(self,ids,consent=False):
        if not consent:raise ValueError('Confirm Firecrawl credit usage before searching.')
        if not self.key:raise ValueError('Save your own Firecrawl API key first. A Gemini key will not work here.')
        if not isinstance(ids,list) or not 1<=len(ids)<=20:raise ValueError('Choose 1 to 20 tests.')
        with self.lock:
            if self.thread and self.thread.is_alive():raise ValueError('A download search is already running.')
            for id in ids:self.store.get(id)
            self.cancel.clear();self.state={'status':'running','message':'Finding public archive links...','results':self.state.get('results',[])};self.persist()
            self.thread=threading.Thread(target=self.run,args=(list(dict.fromkeys(ids)),self.key),daemon=True);self.thread.start()
        return {'message':'Search started. Keep the app open; do not submit the same batch again.'}
    def add_result(self,result):
        with self.lock:self.state['results'].append(result);self.persist()
    def attach(self,result_id,confirmed=False):
        with self.lock:
            item=next((r for r in self.state['results'] if r.get('id')==result_id),None)
            if not item or item.get('status')!='candidate':raise ValueError('This download is no longer awaiting confirmation.')
            if not confirmed:raise ValueError('Confirm that the downloaded PDF matches this competition and file role.')
            self.apply(item);self.persist();return {'message':'PDF attached and test queued for extraction. Previous source and review are backed up.'}
    def local_import(self,job,files):
        """Attach PDFs the user downloaded in their own browser, without Firecrawl."""
        if not isinstance(files,list) or not 1<=len(files)<=5:
            raise ValueError('Choose 1 to 5 downloaded PDFs for one test.')
        results=[];total=0
        with self.lock:
            for incoming in files:
                name=Path(str(incoming.get('name',''))).name
                if not name.lower().endswith('.pdf') or not name:
                    raise ValueError('Choose PDF files only.')
                try:data=base64.b64decode(incoming.get('data',''),validate=True)
                except (ValueError,TypeError):raise ValueError('One downloaded file could not be read.') from None
                total+=len(data)
                if total>90*1024*1024 or len(data)>50*1024*1024:
                    raise ValueError('Choose up to 90 MB per import and 50 MB per PDF.')
                if not data.startswith(b'%PDF-'):
                    raise ValueError(f'{name} is not a PDF.')
                try:
                    with pymupdf.open(stream=data,filetype='pdf') as doc:
                        if doc.needs_pass or not len(doc):raise ValueError(f'{name} is locked or empty.')
                except pymupdf.FileDataError:raise ValueError(f'{name} is not a readable PDF.') from None
                detail=self.store.detail(job);source=detail['source']
                matches=[(i,a) for i,a in enumerate(source.get('assets',[]))
                         if a.get('name','').casefold()==name.casefold()
                         and not self.store.availability({'assets':[a]})['localFiles']]
                if len(matches)!=1:
                    results.append({'name':name,'status':'unmatched','message':'Filename does not uniquely match a missing file listed for this test. Check the expected names and try again.'})
                    continue
                index,asset=matches[0];sha=hashlib.sha256(data).hexdigest();path=self.store.home/'sources'/(sha+'.pdf')
                if not path.exists():
                    temp=path.with_suffix('.'+uuid.uuid4().hex+'.tmp');temp.write_bytes(data);os.replace(temp,path)
                item={'id':uuid.uuid4().hex,'job':job,'name':name,'role':asset['role'],'assetIndex':index,
                      'assetDigest':digest(asset),'url':source.get('sourceUrl',''),'path':str(path.relative_to(self.store.home)).replace('\\','/'),
                      'sha256':sha,'status':'candidate','message':'Imported from your browser. Preview the PDF and confirm its competition, year, division and role.'}
                if sha==asset.get('sha256'):
                    try:self.apply(item)
                    except ValueError as error:item['message']=str(error)+' Confirm attachment after it finishes.'
                self.add_result(item)
                results.append({'name':name,'status':item['status'],'message':item['message']})
        return {'message':f'{sum(r["status"]=="attached" for r in results)} attached, {sum(r["status"]=="candidate" for r in results)} awaiting confirmation, {sum(r["status"]=="unmatched" for r in results)} unmatched.','results':results}
    def apply(self,item):
        detail=self.store.detail(item['job'])
        if detail['row']['status']=='processing' or (self.ai and self.ai.busy(item['job'])):raise ValueError('Wait for this test to finish processing or repairing before attaching files.')
        source=detail['source'];index=item['assetIndex']
        if index>=len(source['assets']) or digest(source['assets'][index])!=item['assetDigest']:raise ValueError('The source changed. Run a new search before attaching this candidate.')
        path=(self.store.home/item['path']).resolve()
        if not path.is_relative_to(self.store.home/'sources') or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('The downloaded file changed or is missing.')
        old=source['assets'][index];backup=self.store.home/'jobs'/item['job']/('before-download-'+uuid.uuid4().hex)
        atomic(backup.with_suffix('.json'),detail)
        asset=self.store.add_asset(path,old['role'],old['name'],expected=item['sha256']);asset.update(downloadUrl=item['url'],previousSha256=old.get('sha256'))
        source['assets'][index]=asset
        # Preserve authored work; replace only untouched extraction templates.
        review=detail['review'];draft=detail['draft'] or {}
        pristine=review and not review.get('reviewer') and not review.get('reviewNotes') and not any(review.get('resolutions',{}).values()) and review.get('fields')==draft.get('fields')
        if pristine:
            rp=self.store.home/'jobs'/item['job']/'review.json'
            if rp.exists():rp.rename(backup.with_name(backup.name+'-review.json'))
        self.store.enqueue(source);item['status']='attached';item['message']='Attached locally; extraction queued.'
    def run(self,ids,key):
        try:
            client=self.factory(key);self.check();archive=client.links(ARCHIVE);self.check()
            for job in ids:
                detail=self.store.detail(job);source=detail['source']
                missing=[(i,a) for i,a in enumerate(source.get('assets',[])) if not self.store.availability({'assets':[a]})['localFiles']]
                if not missing:
                    self.add_result({'job':job,'status':'unavailable','message':'No missing listed attachments. Add a test/key role manually if the archive listing lacks one.'});continue
                # Bound credit consumption and downloadable candidates per test.
                for index,asset in missing[:4]:
                    self.check()
                    with self.lock:self.state['message']='Searching: '+str(source.get('competition'))+' / '+asset['name'];self.persist()
                    if any(r.get('job')==job and r.get('assetDigest')==digest(asset) and r.get('status')=='candidate' for r in self.state['results']):continue
                    name=asset['name'];signed_url=None
                    if self.signin.verified:
                        try:signed_url=self.signin.find_download(source.get('sourceUrl',''),name)
                        except ValueError as error:self.add_result({'job':job,'name':name,'status':'sign_in_required','message':str(error)})
                    normal=lambda x:re.sub(r'[^a-z0-9]','',x.lower())
                    candidates=[u for u in archive if pdf_url(u) and normal(unquote(urlparse(u).path.split('/')[-1]))==normal(name)]
                    if signed_url:candidates=[signed_url]
                    if not candidates:
                        query='site:scioly.org '+str(source.get('competition',''))+' '+str(source.get('year',''))+' '+str(source.get('eventId',''))+' "'+name+'"'
                        self.check();hits=client.search(query)
                        for hit in hits[:3]:
                            url=hit.get('url','')
                            if pdf_url(url):candidates.append(url)
                            elif urlparse(url).hostname=='scioly.org' and url.startswith('https://scioly.org/'):
                                self.check();candidates.extend(u for u in client.links(url) if pdf_url(u) and normal(unquote(urlparse(u).path.split('/')[-1]))==normal(name))
                    if not candidates:
                        self.add_result({'job':job,'name':name,'status':'unavailable','message':'No usable PDF link found. Open Scioly sign-in and verify it, or download this file manually.'});continue
                    found=False
                    for url in list(dict.fromkeys(candidates))[:2]:
                        self.check()
                        try:data=self.downloader(url)
                        except Exception:
                            self.add_result({'job':job,'name':name,'status':'unavailable','message':'This public link could not supply a readable PDF. Download manually if sign-in is required.'});continue
                        self.check();sha=hashlib.sha256(data).hexdigest();path=self.store.home/'sources'/(sha+'.pdf')
                        if not path.exists():
                            temp=path.with_suffix('.'+uuid.uuid4().hex+'.tmp');temp.write_bytes(data);os.replace(temp,path)
                        item={'id':uuid.uuid4().hex,'job':job,'name':name,'role':asset['role'],'assetIndex':index,'assetDigest':digest(asset),'url':source.get('sourceUrl') if url==signed_url else url,'path':str(path.relative_to(self.store.home)).replace('\\','/'),'sha256':sha,'status':'candidate','message':'Downloaded. Preview it and confirm the competition, year, division and file role; its checksum differs from the listing.'}
                        with self.lock:
                            self.check()
                            if sha==asset.get('sha256'):
                                try:self.apply(item)
                                except ValueError:item['message']='Exact checksum match downloaded. Attach after the current test operation finishes.'
                            self.add_result(item)
                        found=True
                        if item['status']=='attached':break
                if len(missing)>4:self.add_result({'job':job,'status':'unavailable','message':'Four-file limit reached for this test. Run another search after attaching these files.'})
            with self.lock:self.state.update(status='complete',message='Search finished. Exact checksum matches were attached; other downloaded candidates need your confirmation.');self.persist()
        except InterruptedError:
            with self.lock:self.state.update(status='cancelled',message='Search stopped. Saved PDFs and completed attachments are retained.');self.persist()
        except Exception as e:
            message=str(e) if isinstance(e,ValueError) else 'Search could not finish. Saved results are retained; retry manually.'
            with self.lock:self.state.update(status='failed',message=message.replace(key,'[redacted]'));self.persist()
