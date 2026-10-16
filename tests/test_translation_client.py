import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import translation_client as tc
import native_windows as native


class Tests(unittest.TestCase):
    def test_refresh_rotates_encrypted_credentials_and_preserves_scope(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as name:
            directory = Path(name)
            old = dict(access_token='synthetic-old', refresh_token='synthetic-refresh',
                       client_id='synthetic-client', saved_at=0, expires_in=1,
                       scope='openid chatgpt.tokens.use.direct')
            path = directory/'account.dpapi'
            path.write_bytes(tc.connection.dpapi(json.dumps(old).encode()))
            new = dict(access_token='synthetic-new', refresh_token='synthetic-rotated', expires_in=3600)
            client = tc.TranslationClient(directory)
            with patch.object(tc.connection, 'get_json', return_value=new) as request:
                self.assertEqual(client.access(), 'synthetic-new')
                self.assertEqual(request.call_args.kwargs['form']['client_id'], 'synthetic-client')
                saved = json.loads(tc.connection.dpapi(path.read_bytes(), decrypt=True))
                self.assertEqual(saved['refresh_token'], 'synthetic-rotated')
                self.assertIn('chatgpt.tokens.use.direct', saved['scope'])
                self.assertNotIn(b'synthetic-new', path.read_bytes())
                self.assertEqual(client.access(), 'synthetic-new')
                self.assertEqual(request.call_count, 1)

    def test_missing_refresh_rejected_without_changing_old_account(self):
        client = tc.TranslationClient(Path(__file__).parent)
        old = dict(access_token='synthetic-old', refresh_token='synthetic-refresh',
                   client_id='test', saved_at=0, expires_in=1)
        with patch.object(client, 'credentials', return_value=old), \
             patch.object(tc.connection, 'get_json', return_value={'access_token':'synthetic'}), \
             patch.object(tc.connection, 'atomic_write') as save:
            with self.assertRaises(tc.connection.VerificationError): client.access()
            save.assert_not_called()

    def test_request_uses_catalog_model_and_completed_stream(self):
        client = tc.TranslationClient('.')
        client.models = [{'slug':'catalog-model'}]
        events = [dict(type='response.output_text.delta',delta='测试'),
                  dict(type='response.completed',response={'status':'completed'})]
        stream = io.BytesIO(b''.join(('data: '+json.dumps(e)+'\n\n').encode() for e in events))
        deltas = []
        with patch.object(client, 'access', return_value='synthetic-token'), \
             patch.object(tc.connection, 'request', return_value=stream) as request:
            self.assertEqual(client.translate('Test', 'catalog-model', deltas.append), '测试')
            payload = request.call_args.kwargs['payload']
            self.assertFalse(payload['store']); self.assertTrue(payload['stream'])
            self.assertEqual(deltas, ['测试'])
        with self.assertRaises(tc.connection.VerificationError): client.translate('Test','unknown')

    def test_cancelled_stream_does_not_report_success(self):
        stream = io.BytesIO(b'data: {"type":"response.output_text.delta","delta":"test"}\n\n')
        def cancel(_): raise tc.connection.VerificationError('cancelled')
        with self.assertRaisesRegex(tc.connection.VerificationError,'cancelled'):
            tc.connection.read_stream(stream,cancel)

    def test_native_input_and_monitor_contract(self):
        self.assertEqual(native.C.sizeof(native.Input), 40 if native.C.sizeof(native.C.c_void_p)==8 else 28)
        left, top, right, bottom = native.work_area(*native.point())
        self.assertLess(left,right); self.assertLess(top,bottom)


if __name__ == '__main__': unittest.main(verbosity=2)

