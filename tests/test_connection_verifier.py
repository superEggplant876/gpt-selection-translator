import base64
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

spec = importlib.util.spec_from_file_location('verifier', Path(__file__).resolve().parents[1] / 'verify_connection.py')
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)
test_root = Path(__file__).resolve().parent / 'verifier-test-temp'
assert test_root.resolve().is_relative_to(Path(__file__).resolve().parent)
test_root.mkdir(exist_ok=True)
tempfile.tempdir = str(test_root)


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        p = cls.key.public_key().public_numbers()
        enc = lambda i: v.b64encode(i.to_bytes((i.bit_length()+7)//8, 'big'))
        cls.jwks = {'keys':[{'kid':'test-key','kty':'RSA','n':enc(p.n),'e':enc(p.e)}]}

    def token(self, **changes):
        claims = {'iss':v.AUTH,'aud':'oaiapp_test','sub':'test-user','nonce':'test-nonce','iat':time.time(),'exp':time.time()+600}
        claims.update(changes)
        h = v.b64encode(json.dumps({'kid':'test-key','alg':'RS256'}).encode())
        c = v.b64encode(json.dumps(claims).encode())
        s = self.key.sign((h+'.'+c).encode(), padding.PKCS1v15(), hashes.SHA256())
        return h+'.'+c+'.'+v.b64encode(s)

    def test_valid_signed_identity(self):
        self.assertEqual(v.validate_identity(self.token(), 'oaiapp_test', 'test-nonce', self.jwks)['sub'], 'test-user')

    def test_wrong_nonce_issuer_audience_expiry_rejected(self):
        for changes in [{'nonce':'wrong'}, {'iss':'https://example.org'}, {'aud':'wrong'}, {'exp':time.time()-1}, {'iat':time.time()+3600}, {'aud':['oaiapp_test','other']}, {'azp':'wrong'}]:
            with self.subTest(changes=changes), self.assertRaises(v.VerificationError):
                v.validate_identity(self.token(**changes), 'oaiapp_test', 'test-nonce', self.jwks)

    def test_tampered_signature_rejected(self):
        token=self.token().split('.')
        sig=bytearray(v.b64decode(token[2])); sig[0]^=1; token[2]=v.b64encode(sig)
        with self.assertRaises(v.VerificationError):
            v.validate_identity('.'.join(token), 'oaiapp_test', 'test-nonce', self.jwks)

    def test_unsigned_identity_rejected(self):
        token=self.token().split('.'); token[0]=v.b64encode(b'{"alg":"none"}')
        with self.assertRaises(v.VerificationError):
            v.validate_identity('.'.join(token), 'oaiapp_test', 'test-nonce', self.jwks)

    def test_windows_encryption_roundtrip(self):
        plain=b'FAKE TEST CREDENTIAL - NOT AN ACCOUNT TOKEN'
        encrypted=v.dpapi(plain)
        self.assertNotIn(plain,encrypted)
        self.assertEqual(v.dpapi(encrypted, decrypt=True),plain)

    def test_requires_completed_and_nonempty_response(self):
        lines=lambda events:io.BytesIO(b''.join(b'data: '+json.dumps(e).encode()+b'\n\n' for e in events))
        good=[{'type':'response.output_text.delta','delta':'hello'}, {'type':'response.completed'}]
        self.assertEqual(v.read_stream(lines(good)),'hello')
        for events in [good[:1],[{'type':'response.completed'}],[{'type':'response.incomplete'}],[{'type':'response.failed','response':{'error':{'code':'subscription_sharing_usage_limit_exceeded'}}}]]:
            with self.assertRaises(v.VerificationError):v.read_stream(lines(events))

    def test_bad_callback_preserves_pending_denial_consumes(self):
        with tempfile.TemporaryDirectory() as folder:
            app=v.App(folder); url=app.authorization('http://127.0.0.1:1234')
            params=urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            self.assertEqual(params['redirect_uri'],['http://127.0.0.1:1234/auth/callback'])
            self.assertEqual(params['client_id'],['dynamic_agent_client'])
            with self.assertRaises(v.VerificationError):app.consume_callback('state=wrong&code=fake&client_id=oaiapp_x')
            self.assertIsNotNone(app.pending)
            state=app.pending['state']
            with self.assertRaises(v.VerificationError):app.consume_callback(urllib.parse.urlencode({'state':state,'error':'access_denied'}))
            self.assertIsNone(app.pending)
            with self.assertRaises(v.VerificationError):app.consume_callback(urllib.parse.urlencode({'state':state,'code':'fake'}))
            app.authorization('http://127.0.0.1:1234'); old=app.pending['state']
            app.authorization('http://127.0.0.1:1234')
            self.assertNotEqual(app.pending['state'],old)

    def test_local_http_rejects_cross_origin_and_bad_host(self):
        with tempfile.TemporaryDirectory() as folder:
            app=v.App(folder); server=v.serve(app)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                with urllib.request.urlopen(server.origin) as r:
                    self.assertIn(b'Continue with ChatGPT',r.read())
                    self.assertIn('frame-ancestors',r.headers['Content-Security-Policy'])
                req=urllib.request.Request(server.origin+'/login', data=urllib.parse.urlencode({'csrf':app.csrf}).encode(),headers={'Origin':'https://example.org'})
                with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(req)
                self.assertEqual(e.exception.code,403)
                req=urllib.request.Request(server.origin,headers={'Host':'example.org'})
                with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(req)
                self.assertEqual(e.exception.code,403)
                req=urllib.request.Request(server.origin+'/login', data=urllib.parse.urlencode({'csrf':app.csrf}).encode(),headers={'Origin':server.origin})
                with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.build_opener(v.NoRedirect()).open(req)
                self.assertEqual(e.exception.code,303)
                self.assertTrue(e.exception.headers['Location'].startswith(v.AUTH+'/api/accounts/authorize?'))
            finally:
                server.shutdown();server.server_close();thread.join(timeout=2)


if __name__=='__main__':unittest.main(verbosity=2)

