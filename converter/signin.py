"""User-controlled Scioly sign-in in an ephemeral Firecrawl browser."""
import json
import re
import threading
import webbrowser
from urllib.parse import urlparse

LOGIN='https://scioly.org/forums/ucp.php?mode=login&redirect=%2Ftests'
HOST='scioly-tests.s3.us-east-005.backblazeb2.com'

def allowed_download(url):
    p=urlparse(url)
    return p.scheme=='https' and p.hostname in ('scioly.org',HOST) and p.port in (None,443) and not p.username and (p.hostname==HOST or p.path.startswith('/w/images/'))

def live_url(url):
    p=urlparse(url)
    return p.scheme=='https' and p.hostname in ('liveview.firecrawl.dev','api.firecrawl.dev') and p.port in (None,443) and not p.username

class SignIn:
    def __init__(self):
        self.lock=threading.RLock();self.client=None;self.session=None;self.verified=False;self.expires=None;self.message='Not connected. Public archive searches still work.'
    def public(self):
        return dict(active=bool(self.session),verified=self.verified,expiresAt=self.expires,message=self.message)
    def execute(self,code):
        if not self.session:raise ValueError('Open the Scioly sign-in page first.')
        result=self.client.call('interact/'+self.session+'/execute',{'code':'await (async () => {\n'+code+'\n})();','language':'node','timeout':60})
        if result.get('killed') or result.get('exitCode',0) not in (0,None):raise ValueError('The signed-in browser could not complete this step. Reopen sign-in if the session expired.')
        output=result.get('stdout') or result.get('result') or ''
        try:return json.loads(output.strip().splitlines()[-1])
        except (ValueError,IndexError,AttributeError):raise ValueError('The signed-in browser returned no usable result. Verify sign-in again.') from None
    def open(self,client,opener=webbrowser.open):
        with self.lock:
            if self.session:self.close()
            self.client=client
            result=client.call('interact',{'ttl':1800,'activityTtl':600,'streamWebView':True})
            id=result.get('id','');url=result.get('interactiveLiveViewUrl','')
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',id):raise ValueError('Firecrawl did not provide a usable browser session.')
            self.session=id;self.expires=result.get('expiresAt');self.verified=False
            try:
                if not live_url(url):raise ValueError('Firecrawl did not provide a supported interactive sign-in page.')
                self.execute('await page.goto('+json.dumps(LOGIN)+', {waitUntil:"domcontentloaded"}); console.log(JSON.stringify({opened:true}));')
                self.message='Sign in on the opened Scioly page, then click Verify sign-in here.'
                opener(url)
                return {'message':self.message,'signInUrl':url}
            except Exception:
                try:self.close()
                except Exception:pass
                raise
    def verify(self):
        with self.lock:
            result=self.execute('await page.goto("https://scioly.org/tests", {waitUntil:"domcontentloaded"}); const signedIn=await page.locator("a[href*=\\\"mode=logout\\\"]").count()>0; console.log(JSON.stringify({signedIn}));')
            self.verified=result.get('signedIn') is True
            self.message='Scioly sign-in verified. Downloads will use this session.' if self.verified else 'Scioly still shows you as signed out. Finish signing in, then verify again.'
            return {'message':self.message,'verified':self.verified}
    def close(self):
        with self.lock:
            if self.session:
                # Keep the handle on failure so the user can retry closing it.
                self.client.call('interact/'+self.session,None,method='DELETE')
            self.session=None;self.client=None;self.verified=False;self.expires=None;self.message='Signed-in browser closed. Public archive searches remain available.'
            return {'message':self.message}
    def find_download(self,source_url,filename):
        p=urlparse(source_url)
        if p.scheme!='https' or p.hostname!='scioly.org' or not re.fullmatch(r'/tests/[A-Za-z0-9_-]+',p.path):return None
        with self.lock:
            if not self.session or not self.verified:return None
            code='''
const source=SOURCE, filename=FILENAME;
await page.goto(source,{waitUntil:'domcontentloaded'});
if(await page.locator('a[href*="mode=logout"]').count()===0){console.log(JSON.stringify({needsLogin:true}));}
else {
 const downloads=[];
 const onDownload=d=>downloads.push({name:d.suggestedFilename(),url:d.url()});
 page.on('download',onDownload);
 try {
  const checkout=page.getByRole('button',{name:'Checkout and download',exact:true});
  if(await checkout.isVisible().catch(()=>false)){await checkout.click();await page.waitForTimeout(1500);}
  const link=page.getByRole('link',{name:filename,exact:true});
  if(await link.count()===1 && await link.isVisible()) {
   const href=await link.getAttribute('href');
   if(href){downloads.push({name:filename,url:new URL(href,page.url()).href});}
   else {await link.click();await page.waitForTimeout(1500);}
  }
  const rows=page.locator('li').filter({has:page.getByText(filename,{exact:true})});
  if(downloads.length===0 && await rows.count()===1){
   const download=rows.getByRole('button',{name:'Download',exact:true});
   if(await download.count()===1 && await download.isVisible()){await download.click();await page.waitForTimeout(1500);}
  }
  const button=page.getByRole('button',{name:filename,exact:true});
  if(downloads.length===0 && await button.count()===1 && await button.isVisible()){await button.click();await page.waitForTimeout(1500);}
  const anchors=await page.locator('a:visible').evaluateAll(nodes=>nodes.map(n=>({name:n.textContent.trim(),url:n.href})));
  downloads.push(...anchors.filter(a=>a.name===filename));
  console.log(JSON.stringify({downloads}));
 } finally {page.off('download',onDownload);}
}
'''.replace('SOURCE',json.dumps(source_url)).replace('FILENAME',json.dumps(filename))
            try:result=self.execute(code)
            except ValueError:
                self.verified=False;self.message='Sign-in needs to be verified again; the browser may have expired.';raise
            if result.get('needsLogin'):
                self.verified=False;self.message='Scioly signed out. Reopen the sign-in page to continue.';raise ValueError(self.message)
            for item in result.get('downloads',[]):
                if item.get('name')==filename and allowed_download(item.get('url','')):return item['url']
            return None
