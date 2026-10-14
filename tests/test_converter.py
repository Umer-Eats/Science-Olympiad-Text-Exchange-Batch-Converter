import copy
import base64
import hashlib
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from http.server import ThreadingHTTPServer
from converter.engine import inspect_text, numbered, convert, points
from converter.store import Store, atomic, digest, job_id
from converter.review import approve, export, validate
from app import make_handler, InstanceLock, AlreadyRunning

def pages(text):return [dict(page=1,text=text,method='pdf_text')]

class ExtractionTests(unittest.TestCase):
    def test_mcq_and_written(self):
        fields,flags,_=inspect_text(pages('1. (2 points) Which gas?\nA. Oxygen\nB. Carbon dioxide\n2. (3 points) Explain diffusion.'),pages('1. A\n2. Movement down a concentration gradient. (3 points)'))
        self.assertEqual([f['type'] for f in fields],['mcq','frq']);self.assertEqual(fields[0]['answer'],'A');self.assertEqual(fields[1]['points'],3)
        self.assertFalse(any(f['category']=='missing_answers' for f in flags))
    def test_missing_answer_not_invented(self):
        fields,flags,_=inspect_text(pages('1. Name a bone.'),[])
        self.assertEqual(fields[0]['answer'],'');self.assertIsNone(fields[0]['points']);self.assertIn('missing_answer',[f['code'] for f in flags])
    def test_conflicting_scores(self):
        _,flags,_=inspect_text(pages('Total points: 8\n1. (2 points) Name a bone.'),pages('1. Femur (3 points)'))
        codes=[f['code'] for f in flags];self.assertIn('question_weight_mismatch',codes);self.assertIn('total_mismatch',codes)
    def test_subpart_total(self):self.assertEqual(points('(5 points) Explain. a. (2 points) b. (3 points)'),5)
    def test_repeated_number_ambiguous_key(self):
        fields,flags,_=inspect_text(pages('1. First?\n1. Second?'),pages('1. One\n1. Two'))
        self.assertEqual(len(set(f['id'] for f in fields)),2);self.assertTrue(all(not f['answer'] for f in fields));self.assertTrue(any(f['code']=='repeated_number' for f in flags))
    def test_page_continuation(self):
        qs,_=numbered(pages('1. Beginning')+[dict(page=2,text='continuation\n2. Next')]);self.assertIn('continuation',qs[0]['text'])
    def test_subparts_not_falsely_mcq(self):
        fields,flags,_=inspect_text(pages('1. Explain:\na. Cause\nb. Effect'),pages('1. Different written explanations.'))
        self.assertEqual(fields[0]['type'],'frq');self.assertTrue(any(f['code']=='multipart_rubric' for f in flags))

class StoreTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def source(self):return dict(id='example-c',competition='Example',division='C',year=2026,eventId='anatomy-and-physiology',sourceUrl='https://scioly.org/tests/example',level=None,assets=[])
    def prepared(self):
        source=self.source()
        # Signature-only bytes suffice to test immutable packaging, not PDF extraction.
        for role in ['test','key']:
            path=Path(self.temp.name)/(role+'.pdf');path.write_bytes(b'%PDF-fixture-'+role.encode());source['assets'].append(self.store.add_asset(path,role))
        self.store.enqueue(source);row=self.store.claim();folder=self.store.home/'jobs'/row['id']/'runs'/row['fingerprint'];folder.mkdir(parents=True)
        field=dict(id='1',page=1,prompt='Which one?',type='mcq',points=2,answer='A',options=[dict(id='A',text='Correct'),dict(id='B',text='Other')])
        draft=dict(fingerprint=row['fingerprint'],flags=[dict(id='check',category='review_required',message='Verify source')],pageCounts={'test':1,'key':1},fields=[field])
        meta={**source,'season':2027,'difficulty':'Easy','difficultyReason':'Basic recall','topics':['Cells'],'topicMatch':'unverified','alignment':'Not verified against current rules.','scoringBasis':'2 points from key','instructions':'Answer all questions.'}
        review=dict(id=row['id'],sourceFingerprint=row['fingerprint'],metadata=meta,fields=[field],resolutions={'check':'Compared original PDF and key.'},reviewer='Test reviewer',reviewNotes='')
        atomic(folder/'draft.json',draft);self.store.complete(row,folder,draft);self.store.save_review(row['id'],review);return row['id'],review
    def test_queue_idempotent_and_resume(self):
        source=self.source();self.store.enqueue(source);row=self.store.claim();self.store.enqueue(source);self.assertEqual(self.store.get(row['id'])['status'],'processing');self.store.recover();self.assertEqual(self.store.get(row['id'])['status'],'queued')
    def test_approval_export_and_edit_invalidation(self):
        id,r=self.prepared();self.assertEqual(validate(self.store.detail(id)),[]);approve(self.store,id);bundle=export(self.store,id)
        with zipfile.ZipFile(self.store.home/bundle['download'].lstrip('/')) as z:
            result=json.loads(z.read(id+'.json'));self.assertEqual(result['maxScore'],2);self.assertEqual(result['keys']['1']['correctOption'],'A');self.assertIn('review-evidence.json',z.namelist())
        r['fields'][0]['points']=3;self.store.save_review(id,r)
        with self.assertRaises(ValueError):export(self.store,id)
    def test_missing_resolution_answer_score_blocks(self):
        id,r=self.prepared();r['resolutions']={};r['fields'][0]['answer']='';r['fields'][0]['points']=None;self.store.save_review(id,r)
        with self.assertRaises(ValueError):approve(self.store,id)
    def test_source_tamper_blocks_export(self):
        id,r=self.prepared();approve(self.store,id);asset=self.store.detail(id)['source']['assets'][0];(self.store.home/asset['path']).write_bytes(b'%PDF-changed')
        with self.assertRaises(ValueError):export(self.store,id)
    def test_old_review_cannot_approve(self):
        id,r=self.prepared();source=self.store.detail(id)['source'];source['year']=2025;self.store.enqueue(source)
        self.assertIn('Source changed',validate(self.store.detail(id))[0])
    def test_missing_or_duplicate_attachments_blocks(self):
        id,r=self.prepared();d=self.store.detail(id);d['source']['assets'].append(copy.deepcopy(d['source']['assets'][0]));self.assertTrue(any('Multiple test' in e for e in validate(d)))
    def test_path_traversal_id(self):
        with self.assertRaises(ValueError):job_id('../outside')
    def test_second_instance_does_not_touch_running_queue(self):
        with InstanceLock(self.store.home/'state'/'instance.lock'):
            with self.assertRaises(AlreadyRunning):
                with InstanceLock(self.store.home/'state'/'instance.lock'):pass
    def test_non_pdf_rejected(self):
        p=self.store.home/'fake.pdf';p.write_text('<html>Sign in</html>')
        with self.assertRaises(ValueError):self.store.add_asset(p,'test')
    def test_server_csrf_and_path_guard(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.store,threading.Event(),'secret',0));port=server.server_port;server.RequestHandlerClass=make_handler(self.store,threading.Event(),'secret',port)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            base=f'http://127.0.0.1:{port}'
            self.assertEqual(json.load(urllib.request.urlopen(base+'/health'))['running'],True)
            with self.assertRaises(urllib.error.HTTPError) as failure:urllib.request.urlopen(urllib.request.Request(base+'/api/pause',data=b'{"paused":true}',method='POST'))
            self.assertEqual(failure.exception.code,403)
            req=urllib.request.Request(base+'/api/pause',data=b'{"paused":true}',headers={'X-Converter-Token':'secret','Origin':'https://evil.example'},method='POST')
            with self.assertRaises(urllib.error.HTTPError):urllib.request.urlopen(req)
            with self.assertRaises(urllib.error.HTTPError):urllib.request.urlopen(base+'/sources/%2e%2e/%2e%2e/outside.pdf')
        finally:server.shutdown();thread.join();server.server_close()
    def test_duplicate_upload_preserves_imported_job_and_review(self):
        id,r=self.prepared();approve(self.store,id);before=self.store.get(id)
        source=self.store.detail(id)['source'];files=[dict(role=a['role'],name=a['name'],data=base64.b64encode((self.store.home/a['path']).read_bytes()).decode()) for a in source['assets']]
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.store,threading.Event(),'secret',0));port=server.server_port;server.RequestHandlerClass=make_handler(self.store,threading.Event(),'secret',port)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            body=dict(metadata={**source,'competition':'Changed upload name'},files=files,skipExisting=True)
            request=urllib.request.Request(f'http://127.0.0.1:{port}/api/upload',data=json.dumps(body).encode(),headers={'X-Converter-Token':'secret'},method='POST')
            result=json.load(urllib.request.urlopen(request));self.assertTrue(result['alreadyExists']);self.assertEqual(result['id'],id);self.assertEqual(self.store.get(id)['approval_hash'],before['approval_hash']);self.assertEqual(len(self.store.snapshot()['jobs']),1)
        finally:server.shutdown();thread.join();server.server_close()

if __name__=='__main__':unittest.main()
