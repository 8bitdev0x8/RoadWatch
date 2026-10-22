import json
from pathlib import Path
import sys
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import roadwatch_web as web


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = web.ThreadingHTTPServer(('127.0.0.1', 0), web.Handler)
        cls.host = '127.0.0.1:' + str(cls.server.server_port)
        cls.base = 'http://' + cls.host
        cls.previous = web.HOST
        cls.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        web.HOST = cls.host
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        web.HOST = cls.previous

    def test_page_and_history(self):
        with self.opener.open(self.base) as response:
            page = response.read().decode()
            self.assertIn('Assessment history', page)
            self.assertNotIn('__TOKEN__', page)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
        with self.opener.open(self.base + '/api/results') as response:
            self.assertIsInstance(json.load(response), list)

    def test_untrusted_post_rejected(self):
        request = urllib.request.Request(self.base + '/api/check', data=b'{}')
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.opener.open(request)
        self.assertEqual(error.exception.code, 403)

    def test_explicit_check_uses_password_without_echo(self):
        body = {'camera_id': '3ccadc04-93aa-46ea-823a-6c0f3de83055', 'seconds': 15, 'password': 'fake-test-only'}
        request = urllib.request.Request(self.base + '/api/check', data=json.dumps(body).encode(), headers={
            'Origin': self.base, 'X-RoadWatch-Token': web.TOKEN, 'Content-Type': 'application/json'})
        with patch.object(web.roadwatch_check, 'main', return_value={'disposition': 'needs_review'}) as check:
            with self.opener.open(request) as response:
                text = response.read().decode()
                self.assertNotIn('fake-test-only', text)
                self.assertEqual(json.loads(text)['result']['disposition'], 'needs_review')
            self.assertEqual(check.call_count, 1)


if __name__ == '__main__':
    unittest.main()
