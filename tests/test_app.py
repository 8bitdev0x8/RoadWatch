import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from roadwatch_app import Application,handler_for,ThreadingHTTPServer
from test_core import observation


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        root=Path(self.temp.name)
        (root/'web').mkdir()
        for name in ['index.html','app.css','app.js']:
            (root/'web'/name).write_text((Path(__file__).resolve().parents[1]/'web'/name).read_text(encoding='utf-8'),encoding='utf-8')
        (root/'web/assets').mkdir()
        (root/'web/assets/road-logo.png').write_bytes((Path(__file__).resolve().parents[1]/'web/assets/road-logo.png').read_bytes())
        self.app=Application(root)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(self.app))
        self.base='http://127.0.0.1:'+str(self.server.server_port)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def tearDown(self):
        self.app.monitor.stop()
        self.server.shutdown();self.server.server_close();self.thread.join()
        self.temp.cleanup()
    def post(self,path,body,trusted=True):
        headers={'Content-Type':'application/json'}
        if trusted:
            headers.update({'Origin':self.base,'X-RoadWatch-Token':self.app.token})
        return self.opener.open(urllib.request.Request(self.base+path,data=json.dumps(body).encode(),headers=headers))
    def test_page_state_and_css(self):
        with self.opener.open(self.base) as response:
            self.assertIn('<title>RoadWatch</title>',response.read().decode())
            self.assertIn("script-src 'self';",response.headers['Content-Security-Policy'])
        with self.opener.open(self.base+'/api/state') as response:
            value=json.load(response)
            self.assertFalse(value['connected']);self.assertEqual(value['csrf'],self.app.token)
        with self.opener.open(self.base+'/app.css') as response:
            self.assertIn('text/css',response.headers['Content-Type'])
        with self.opener.open(self.base+'/assets/road-logo.png') as response:
            self.assertEqual(response.headers['Content-Type'],'image/png')
            self.assertTrue(response.read().startswith(b'\x89PNG'))
    def test_cross_origin_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.post('/api/connect',{},False)
        self.assertEqual(error.exception.code,403)
    def test_incident_update_and_backup(self):
        iid=self.app.store.ingest(observation())
        with self.post('/api/incident',{'incident_id':iid,'version':0,'status':'acknowledged','note':'Reviewed evidence'}):
            pass
        self.assertEqual(self.app.store.incident(iid)['status'],'acknowledged')
        with self.opener.open(self.base+'/api/backup') as response:
            archive=zipfile.ZipFile(io.BytesIO(response.read()))
            self.assertIn('roadwatch.sqlite3',archive.namelist())
    def test_review_csv_escapes_formulas(self):
        value=observation();self.app.store.ingest(value)
        with self.post('/api/review',{'summary_id':value['summary_id'],'verdict':'false_alarm','notes':'=unsafe()'}):
            pass
        with self.opener.open(self.base+'/api/evaluation.csv') as response:
            self.assertIn("'=unsafe()",response.read().decode())
    def test_secrets_not_in_state_or_configuration(self):
        self.app.services.credentials={'password':'fake-secret','gateway_password':'other-fake'}
        for path in ['/api/state','/api/export']:
            with self.opener.open(self.base+path) as response:
                text=response.read().decode();self.assertNotIn('fake-secret',text);self.assertNotIn('other-fake',text)
    def test_no_connection_means_no_request(self):
        self.app.services.connected=False
        with patch('roadwatch_services.assess') as assess:
            with self.assertRaises(ValueError):
                self.app.services.check('3ccadc04-93aa-46ea-823a-6c0f3de83055')
            assess.assert_not_called()


if __name__=='__main__':
    unittest.main()
