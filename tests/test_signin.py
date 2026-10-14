import json
import unittest
from converter.signin import SignIn,allowed_download,live_url

class Client:
    def __init__(self):self.calls=[];self.signed=True;self.downloads=[]
    def call(self,endpoint,body,method=None):
        self.calls.append((endpoint,body,method))
        if endpoint=='interact':return {'id':'session-123','interactiveLiveViewUrl':'https://liveview.firecrawl.dev/session-private','expiresAt':'later'}
        if method=='DELETE':return {'success':True}
        code=body['code']
        if 'const source=' in code:return {'stdout':json.dumps({'downloads':self.downloads})}
        if 'signedIn=' in code:return {'stdout':json.dumps({'signedIn':self.signed})}
        return {'stdout':'{"opened":true}'}

class SignInTests(unittest.TestCase):
    def test_opens_interactive_page_without_collecting_credentials(self):
        client=Client();session=SignIn();opened=[];session.open(client,opened.append)
        self.assertEqual(opened,['https://liveview.firecrawl.dev/session-private'])
        self.assertFalse(session.public()['verified']);self.assertNotIn('session-private',json.dumps(session.public()))
        self.assertNotIn('profile',client.calls[0][1]);self.assertEqual(client.calls[0][1]['ttl'],1800)
        self.assertTrue(session.verify()['verified'])
        session.close();self.assertFalse(session.public()['active']);self.assertEqual(client.calls[-1][2],'DELETE')
    def test_signed_out_is_not_verified(self):
        client=Client();client.signed=False;session=SignIn();session.open(client,lambda _:None)
        self.assertFalse(session.verify()['verified'])
    def test_only_matching_filename_on_allowed_host_is_used(self):
        client=Client();session=SignIn();session.open(client,lambda _:None);session.verify()
        client.downloads=[{'name':'wrong.pdf','url':'https://scioly.org/w/images/a.pdf'},{'name':'test.pdf','url':'https://evil.example/test.pdf'},{'name':'test.pdf','url':'https://scioly-tests.s3.us-east-005.backblazeb2.com/file.pdf?signature=private'}]
        self.assertIn('backblazeb2.com',session.find_download('https://scioly.org/tests/abc123','test.pdf'))
        self.assertNotIn('signature',json.dumps(session.public()))
    def test_arbitrary_source_and_live_hosts_rejected(self):
        self.assertFalse(live_url('https://evil.example/login'))
        self.assertFalse(live_url('https://liveview.firecrawl.dev.evil.example/'))
        self.assertFalse(allowed_download('https://127.0.0.1/file.pdf'))
        self.assertFalse(allowed_download('https://scioly.org/private/account'))
        self.assertIsNone(SignIn().find_download('https://evil.example/tests/a','test.pdf'))
    def test_expired_session_clears_verification(self):
        client=Client();session=SignIn();session.open(client,lambda _:None);session.verify()
        def expired(*args,**kwargs):raise ValueError('Expired')
        client.call=expired
        with self.assertRaises(ValueError):session.find_download('https://scioly.org/tests/abc123','test.pdf')
        self.assertFalse(session.verified)
    def test_bad_live_url_closes_created_session(self):
        client=Client();original=client.call
        def call(endpoint,body,method=None):
            if endpoint=='interact':return {'id':'bad-live','interactiveLiveViewUrl':'https://evil.example/'}
            return original(endpoint,body,method)
        client.call=call;session=SignIn()
        with self.assertRaises(ValueError):session.open(client,lambda _:self.fail('Must not open this URL'))
        self.assertFalse(session.public()['active'])

if __name__=='__main__':unittest.main()
