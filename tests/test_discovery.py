import base64
import hashlib
import json
import threading
import unittest
import pymupdf
import test_converter as fixtures
from converter.discovery import Discovery,pdf_url,FirecrawlClient
from converter.store import atomic

URL='https://scioly.org/w/images/a/ab/test.pdf'
class DownloadTests(unittest.TestCase):
    setUp=fixtures.StoreTests.setUp
    tearDown=fixtures.StoreTests.tearDown
    source=fixtures.StoreTests.source
    prepared=fixtures.StoreTests.prepared
    def service(self,links=None,data=b'%PDF-fixture-test'):
        class Client:
            def __init__(self,key):pass
            def links(self,url):return [URL] if links is None else links
            def search(self,q):return []
        service=Discovery(self.store,threading.Event(),client_factory=Client,downloader=lambda u:data)
        service.save({'key':'fc-fake-unit-test-key-1234567890'})
        return service
    def missing(self):
        id,r=self.prepared();a=self.store.detail(id)['source']['assets'][0];(self.store.home/a['path']).unlink();return id,r
    def execute(self,service,id):
        service.start([id],True);service.thread.join(5);self.assertFalse(service.thread.is_alive());return service.public()
    def test_checksum_match_attaches_and_preserves_authored_review(self):
        id,r=self.missing();service=self.service();result=self.execute(service,id)
        self.assertEqual(result['results'][0]['status'],'attached')
        self.assertTrue(self.store.availability(self.store.detail(id)['source'])['hasTest'])
        self.assertEqual(self.store.detail(id)['review'],r)
    def test_different_checksum_requires_confirmation(self):
        id,r=self.missing();service=self.service(data=b'%PDF-other-version');result=self.execute(service,id);item=result['results'][0]
        self.assertEqual(item['status'],'candidate');self.assertFalse(self.store.availability(self.store.detail(id)['source'])['hasTest'])
        with self.assertRaises(ValueError):service.attach(item['id'])
        service.attach(item['id'],True);self.assertTrue(self.store.availability(self.store.detail(id)['source'])['hasTest'])
    def test_modified_source_blocks_candidate_attachment(self):
        id,r=self.missing();service=self.service(data=b'%PDF-other-version');item=self.execute(service,id)['results'][0]
        source=self.store.detail(id)['source'];source['assets'][0]['name']='different.pdf';self.store.enqueue(source)
        with self.assertRaisesRegex(ValueError,'source changed'):service.attach(item['id'],True)
    def test_no_match_never_invents_attachment(self):
        id,r=self.missing();service=self.service(links=[]);result=self.execute(service,id)
        self.assertEqual(result['results'][0]['status'],'unavailable');self.assertFalse(self.store.availability(self.store.detail(id)['source'])['hasTest'])
    def test_consent_and_key_required(self):
        id,r=self.missing();service=self.service()
        with self.assertRaises(ValueError):service.start([id],False)
        service.forget()
        with self.assertRaises(ValueError):service.start([id],True)
    def test_key_not_returned_or_stored_as_plaintext(self):
        service=self.service();self.assertNotIn('fc-fake',json.dumps(service.public()));self.assertFalse(service.keyfile.exists())
    def test_restart_does_not_resume_paid_requests(self):
        service=self.service();atomic(service.statefile,{'status':'running','message':'working','results':[]})
        fresh=Discovery(self.store,threading.Event());self.assertEqual(fresh.public()['status'],'interrupted');self.assertIsNone(fresh.thread)
    def test_cancel_before_search(self):
        service=self.service();service.cancel.set();service.run([],service.key);self.assertEqual(service.public()['status'],'cancelled')
    def test_local_browser_pdf_import_requires_exact_file_and_confirmation(self):
        id,_=self.missing();service=self.service();name=self.store.detail(id)['source']['assets'][0]['name']
        doc=pymupdf.open();doc.new_page().insert_text((40,40),'Different local version');data=doc.tobytes();doc.close()
        wrong=service.local_import(id,[{'name':'unrelated.pdf','data':base64.b64encode(data).decode()}])
        self.assertEqual(wrong['results'][0]['status'],'unmatched')
        self.assertFalse(self.store.availability(self.store.detail(id)['source'])['hasTest'])
        found=service.local_import(id,[{'name':name,'data':base64.b64encode(data).decode()}])
        self.assertEqual(found['results'][0]['status'],'candidate')
        item=service.public()['results'][-1]
        self.assertEqual(item['url'],'https://scioly.org/tests/example')
        service.attach(item['id'],True)
        self.assertTrue(self.store.availability(self.store.detail(id)['source'])['hasTest'])
    def test_local_browser_import_rejects_fake_pdf(self):
        id,_=self.missing();service=self.service();name=self.store.detail(id)['source']['assets'][0]['name']
        with self.assertRaises(ValueError):service.local_import(id,[{'name':name,'data':base64.b64encode(b'%PDF-fake').decode()}])
    def test_only_public_scioly_pdf_destinations(self):
        self.assertTrue(pdf_url(URL))
        for url in ['http://scioly.org/w/images/a.pdf','https://127.0.0.1/a.pdf','https://scioly.org.evil.example/w/images/a.pdf','https://scioly.org:99/w/images/a.pdf','https://user@scioly.org/w/images/a.pdf']:
            self.assertFalse(pdf_url(url))
    def test_unknown_api_endpoint_rejected_without_request(self):
        with self.assertRaises(ValueError):FirecrawlClient('fake').call('https://evil.example',{})

if __name__=='__main__':unittest.main()
