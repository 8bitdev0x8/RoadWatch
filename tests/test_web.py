import json
from pathlib import Path
import sys
import threading
import tempfile
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
            self.assertIn('Incident queue', page)
            self.assertNotIn('__TOKEN__', page)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
        with self.opener.open(self.base + '/api/results') as response:
            self.assertIsInstance(json.load(response), list)
        with self.opener.open(self.base + '/app.css') as response:
            self.assertIn('text/css', response.headers['Content-Type'])
            self.assertIn('#081927', response.read().decode())

    def test_untrusted_post_rejected(self):
        request = urllib.request.Request(self.base + '/api/check', data=b'{}')
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.opener.open(request)
        self.assertEqual(error.exception.code, 403)

    def test_review_persists_without_upstream_calls(self):
        summary = '7c3f3eb7-fd94-4536-adfd-b7f4f1020f8e'
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'runtime').mkdir()
            (root / 'runtime' / (summary + '.json')).write_text('{}')
            request = urllib.request.Request(self.base + '/api/review',
                data=json.dumps({'summary_id': summary, 'verdict': 'false_alarm', 'notes': 'Managed merge only'}).encode(),
                headers={'Origin': self.base, 'X-RoadWatch-Token': web.TOKEN})
            with patch.object(web, 'ROOT', root), patch.object(web.roadwatch_check, 'main') as check, patch.object(web.roadwatch_event, 'main') as send:
                with self.opener.open(request) as response:
                    self.assertEqual(response.status, 200)
                review = json.loads((root / 'runtime' / (summary + '.review.json')).read_text())
                self.assertEqual(review['verdict'], 'false_alarm')
                check.assert_not_called()
                send.assert_not_called()

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

    def test_incident_clearance_and_stale_update(self):
        summary = '7c3f3eb7-fd94-4536-adfd-b7f4f1020f8e'
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'runtime').mkdir()
            (root / 'runtime' / (summary + '.json')).write_text('{}')
            def submit(body):
                request = urllib.request.Request(self.base + '/api/incident',
                    data=json.dumps({'summary_id': summary, **body}).encode(),
                    headers={'Origin': self.base, 'X-RoadWatch-Token': web.TOKEN})
                return self.opener.open(request)
            with patch.object(web, 'ROOT', root), patch.object(web.roadwatch_event, 'main') as send:
                with self.assertRaises(urllib.error.HTTPError) as error:
                    submit({'status': 'cleared', 'expected_status': 'new', 'note': 'Claimed clearance'})
                self.assertEqual(error.exception.code, 400)
                with submit({'status': 'acknowledged', 'expected_status': 'new', 'note': 'Reviewed clip'}):
                    pass
                with self.assertRaises(urllib.error.HTTPError) as error:
                    submit({'status': 'responding', 'expected_status': 'new', 'note': 'Stale update'})
                self.assertEqual(error.exception.code, 409)
                with submit({'status': 'cleared', 'expected_status': 'acknowledged',
                             'note': 'Field report confirmed route clear', 'clearance_verified': True}):
                    pass
                saved = json.loads((root / 'runtime' / (summary + '.incident.json')).read_text())
                self.assertEqual(saved['status'], 'cleared')
                self.assertEqual(len(saved['history']), 2)
                self.assertEqual(saved['history'][0]['note'], 'Reviewed clip')
                send.assert_not_called()


if __name__ == '__main__':
    unittest.main()
