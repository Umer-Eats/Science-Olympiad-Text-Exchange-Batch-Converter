import threading
import unittest
from unittest.mock import patch
from converter.local_browser import is_scioly_test, LocalBrowser

class LocalBrowserTests(unittest.TestCase):
    def test_only_scioly_listing_urls_accepted(self):
        self.assertTrue(is_scioly_test('https://scioly.org/tests/SfNU3s5-NmM'))
        for url in ('http://scioly.org/tests/example','https://scioly.org.evil.test/tests/example',
                    'https://scioly.org/tests/../other','https://scioly.org/w/index.php',
                    'https://user@scioly.org/tests/example'):
            self.assertFalse(is_scioly_test(url))

    def test_signed_in_pdf_link_is_saved_when_browser_does_not_download(self):
        class Link:
            def count(self): return 1
            def is_visible(self): return True
            def get_attribute(self, name): return '/w/images/test.pdf'
        class Response:
            ok=True
            url='https://scioly.org/w/images/test.pdf'
            def body(self): return b'%PDF-1.4\nfixture'
        class Request:
            def get(self, url, **kwargs):
                self.url=url
                return Response()
        class Page:
            url='https://scioly.org/tests/example'
            def __init__(self):
                self.context=type('Context',(),{'request':Request()})()
            def get_by_role(self, role, name, exact=False): return Link()
            def locator(self, selector): return type('Row',(),{'filter':lambda self,**kwargs:self,'count':lambda self:0})()
        page=Page()
        with patch('converter.local_browser.allowed_download', return_value=True):
            data=LocalBrowser._fetch_file_link(page,'test.pdf')
        self.assertEqual(data,b'%PDF-1.4\nfixture')
        self.assertEqual(page.context.request.url,'https://scioly.org/w/images/test.pdf')

    def test_scioly_file_endpoint_is_scoped_to_listing(self):
        listing='https://scioly.org/tests/SfNU3s5-NmM'
        self.assertTrue(LocalBrowser._file_endpoint(listing+'/files/485',listing))
        for url in ('https://scioly.org/tests/other/files/485',
                    'https://scioly.org/tests/SfNU3s5-NmM/files/../485',
                    'https://evil.example/tests/SfNU3s5-NmM/files/485'):
            self.assertFalse(LocalBrowser._file_endpoint(url,listing))

    def test_released_checkout_does_not_need_checkout_button_to_reappear(self):
        class Body:
            def inner_text(self, timeout): return "You've already checked this test out. You're using 0 of 5 checkouts."
        class Page:
            def locator(self, selector): return Body()
        browser=LocalBrowser(None,None,threading.Event())
        self.assertTrue(browser._release_checkout(Page(),'https://scioly.org/tests/example',0))

    def test_local_browser_launch_uses_supported_viewport_option(self):
        import tempfile
        class Chromium:
            def launch_persistent_context(self, profile, **options):
                self.options=options
                return 'opened'
        with tempfile.TemporaryDirectory() as folder:
            browser=LocalBrowser(type('Store',(),{'home':__import__('pathlib').Path(folder)})(),None,threading.Event())
            playwright=type('Playwright',(),{'chromium':Chromium()})()
            self.assertEqual(browser._launch(playwright),'opened')
            self.assertTrue(playwright.chromium.options['no_viewport'])
            self.assertNotIn('no_default_viewport',playwright.chromium.options)

    def test_automatic_batch_cap_is_ten(self):
        browser=LocalBrowser(None,None,threading.Event())
        with self.assertRaisesRegex(ValueError,'1 to 10'):
            browser.start(['id']*11)

    def test_continue_all_queues_missing_scioly_listings_after_selection(self):
        class Store:
            def __init__(self):
                self.sources={
                    'selected': {'sourceUrl':'https://scioly.org/tests/selected','assets':[{'name':'a.pdf'}]},
                    'other': {'sourceUrl':'https://scioly.org/tests/other','assets':[{'name':'b.pdf'}]},
                    'complete': {'sourceUrl':'https://scioly.org/tests/complete','assets':[]},
                    'unsafe': {'sourceUrl':'https://example.org/tests/unsafe','assets':[{'name':'c.pdf'}]},
                }
            def detail(self,job): return {'source':self.sources[job]}
            def availability(self,source):
                count=len(source['assets'])
                return {'localFiles':0,'listedFiles':count}
            def snapshot(self):
                return {'jobs':[{'id':job,'availability':self.availability(source)}
                                for job,source in self.sources.items()]}
        browser=LocalBrowser(Store(),None,threading.Event())
        captured=[]
        with patch.object(browser,'_run',side_effect=lambda jobs:captured.extend(jobs)):
            browser.start(['selected'],continue_all=True)
            browser.thread.join(timeout=2)
        self.assertEqual(captured,['selected','other'])
        self.assertEqual(browser.public()['total'],2)

    def test_failed_release_restarts_browser_and_continues_queue(self):
        class Page:
            def goto(self,*args,**kwargs): pass
            def is_closed(self): return False
        class Context:
            def __init__(self): self.pages=[Page()]
            def close(self): pass
        class Playwright:
            def __enter__(self): return self
            def __exit__(self,*args): pass
        class Store:
            def detail(self,job):
                return {'source':{'sourceUrl':'https://scioly.org/tests/'+job,'competition':job}}
        browser=LocalBrowser(Store(),None,threading.Event())
        first,second=Context(),Context()
        browser.state.update(total=2)
        outcomes=[{'job':'one','files':[],'released':False,'checkoutBefore':0},
                  {'job':'two','files':[],'released':True,'checkoutBefore':0}]
        with patch('converter.local_browser.sync_playwright',return_value=Playwright()), \
             patch('converter.local_browser.signed_in',return_value=True), \
             patch.object(browser,'_launch',return_value=first), \
             patch.object(browser,'_reopen',return_value=(second,second.pages[0])) as reopen, \
             patch.object(browser,'_release_checkout',return_value=True), \
             patch.object(browser,'_process_one',side_effect=outcomes):
            browser._run(['one','two'])
        self.assertEqual(reopen.call_count,1)
        self.assertEqual(browser.public()['status'],'complete')
        self.assertEqual(browser.public()['done'],2)
        self.assertIn('released',browser.public()['results'][0]['recovery'])
