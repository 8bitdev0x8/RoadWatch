"""RoadWatch local application: durable workflow, bounded monitoring, explicit actions."""
import csv
import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import secrets
import threading
import uuid
import urllib.parse
import zipfile

from roadwatch_store import Store
from roadwatch_services import Services, UpstreamError
from roadwatch_monitor import Monitor, Jobs
from roadwatch_spatial import validate_regions, detect

ROOT = Path(__file__).resolve().parent


def integer(body, key, default, low, high):
    value = body.get(key, default)
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{key} must be {low}-{high}')
    return value


class Application:
    def __init__(self, root=ROOT, data_dir=None, demo=False):
        self.root = Path(root)
        self.demo = demo
        self.store = Store(data_dir or self.root / 'runtime')
        self.store.import_legacy()
        self.services = Services(self.store)
        self.monitor = Monitor(self.services)
        self.jobs = Jobs(self.services)
        self.token = secrets.token_urlsafe(32)
        self.api_lock = threading.Lock()
        self.quota_cache = None
        if not self.store.cameras():
            self.store.save_camera({'id':'3ccadc04-93aa-46ea-823a-6c0f3de83055', 'name':'vehicle_breakdown_traffic_queue','synthetic':True,'looping':True})
        if not self.store.setting('policy'):
            self.store.set_setting('policy', {'daily_cap':100, 'reserve':50})
        if not self.store.setting('event_type'):
            self.store.set_setting('event_type', '99f5b1e9-0895-48c6-89ff-cc22713e08c1')

    def state(self):
        self.store.import_legacy()
        return {'demo':self.demo,'connected': self.services.connected, 'cameras': self.store.cameras(), 'incidents': self.store.incidents(),
                'monitor': self.monitor.snapshot(), 'job':self.jobs.snapshot(), 'budget': self.store.budget(),
                'quota':self.quota_cache, 'policy':self.store.setting('policy'), 'event_type':self.store.setting('event_type'),
                'event_types':self.store.setting('event_types', []), 'evaluation':self.store.evaluation()}

    def dispatch(self, path, body):
        if self.demo and path not in {'/api/incident','/api/review','/api/policy','/api/camera'}:
            raise ValueError('Demo workspace: live service actions are disabled. Restart without --demo on p039 for integration.')
        if path == '/api/connect':
            if self.monitor.snapshot()['status'] in {'running','stopping'}:
                raise ValueError('Stop monitoring before changing the connection')
            def connect():
                result = self.services.connect(body.get('user',''),body.get('password',''),body.get('gateway_password',''))
                try:
                    self.quota_cache = self.services.quota()
                except UpstreamError:
                    self.quota_cache = None
                return result
            return self.jobs.start(connect)
        if path == '/api/disconnect':
            self.monitor.stop()
            if self.services.operation.locked():
                raise ValueError('Stop requested. Wait for the current operation, then disconnect.')
            self.services.disconnect()
            return {'message':'Disconnected. Credentials removed from server memory.'}
        if path == '/api/check':
            cid = str(uuid.UUID(body['camera_id']))
            seconds = integer(body,'seconds',15,5,60)
            start,end = body.get('start'),body.get('end')
            if bool(start) != bool(end):
                raise ValueError('Provide both recorded start and end')
            return self.jobs.start(lambda:self.services.check(cid,seconds,start,end))
        if path == '/api/quota':
            def quota():
                self.quota_cache = self.services.quota()
                return {'message':'Gateway quota updated.'}
            return self.jobs.start(quota)
        if path == '/api/monitor/start':
            return {'message':'Bounded monitoring started. First check begins now.', 'monitor':self.monitor.start(body)}
        if path == '/api/monitor/stop':
            return {'message':'Stop requested. Any already submitted check will finish; no new check will start.', 'monitor':self.monitor.stop()}
        if path == '/api/policy':
            if self.monitor.snapshot()['status'] in {'running','stopping'}:
                raise ValueError('Stop monitoring before changing limits')
            policy = {'daily_cap':integer(body,'daily_cap',100,1,450),'reserve':integer(body,'reserve',50,10,499)}
            self.store.set_setting('policy',policy)
            if body.get('event_type'):
                self.store.set_setting('event_type',str(uuid.UUID(body['event_type'])))
            return {'message':'Settings saved. No credentials are written to disk.'}
        if path == '/api/camera':
            cid = str(uuid.UUID(body['camera_id']))
            camera = next((c for c in self.store.cameras() if c['id']==cid),None)
            if not camera:
                raise ValueError('Camera not found')
            if self.monitor.snapshot()['status'] in {'running','stopping'}:
                raise ValueError('Stop monitoring before changing camera configuration')
            camera['name'] = body.get('name',camera['name'])
            for key in ['synthetic','looping']:
                if key in body:
                    if type(body[key]) is not bool:
                        raise ValueError('Camera flags must be boolean')
                    camera[key] = body[key]
            if 'regions' in body:
                camera['regions'] = validate_regions(body['regions'])
                camera['region_reference_time'] = body.get('frame_time')
                camera['region_reviewed'] = body.get('region_reviewed') is True
            self.store.save_camera(camera)
            return {'message':'Camera configuration saved. Region geometry does not alter Hafnia assessments.'}
        if path == '/api/frame':
            cid = str(uuid.UUID(body['camera_id']))
            return self.jobs.start(lambda:self.services.snapshot(cid))
        if path == '/api/spatial':
            cid = str(uuid.UUID(body['camera_id']))
            camera = next((c for c in self.store.cameras() if c['id']==cid),None)
            if not camera or not camera.get('regions') or not camera.get('region_reviewed'):
                raise ValueError('Mark and review road regions first')
            def spatial():
                frame = self.services.snapshot(cid)
                outcome = detect(self.store.root/'frames'/(cid+'.jpg'),camera['regions'])
                return {**frame, 'spatial':outcome}
            return self.jobs.start(spatial)
        if path == '/api/incident':
            self.store.update(body['incident_id'],body.get('version'),body.get('status'),body.get('note'),body.get('clearance_verified'))
            return {'message':'Response saved in RoadWatch. XProtect alarm state is unchanged.'}
        if path == '/api/review':
            self.store.review(body['summary_id'],body.get('verdict'),body.get('notes',''))
            return {'message':'Evaluation saved. No upstream request.'}
        if path in {'/api/send','/api/bookmark'}:
            iid = str(uuid.UUID(body['incident_id']))
            return self.jobs.start(lambda:self.services.send(iid) if path=='/api/send' else self.services.bookmark(iid))
        raise ValueError('Unknown operation')


def handler_for(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_):
            pass

        def reply(self,status,value,kind='application/json',filename=None):
            raw = value if isinstance(value,bytes) else (json.dumps(value) if kind=='application/json' else value).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type',kind + ('' if isinstance(value,bytes) else '; charset=utf-8'))
            self.send_header('Content-Length',str(len(raw)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; frame-ancestors 'none'; form-action 'self'")
            if filename:
                self.send_header('Content-Disposition','attachment; filename="'+filename+'"')
            self.end_headers()
            self.wfile.write(raw)

        def host(self):
            return '127.0.0.1:'+str(self.server.server_port)

        def do_GET(self):
            if self.headers.get('Host')!=self.host():
                return self.reply(403,{'error':'Use the printed 127.0.0.1 address'})
            try:
                path = urllib.parse.urlsplit(self.path).path
                if self.path=='/':
                    return self.reply(200,(app.root/'web/index.html').read_text(encoding='utf-8'),'text/html')
                if self.path in {'/app.css','/app.js'}:
                    return self.reply(200,(app.root/'web'/self.path[1:]).read_text(encoding='utf-8'),'text/css' if self.path.endswith('css') else 'text/javascript')
                if self.path=='/assets/road-logo.png':
                    return self.reply(200,(app.root/'web/assets/road-logo.png').read_bytes(),'image/png')
                if self.path=='/api/state':
                    return self.reply(200,{**app.state(),'csrf':app.token})
                if self.path=='/api/export':
                    return self.reply(200,{'cameras':app.store.cameras(),'policy':app.store.setting('policy'),'event_type':app.store.setting('event_type')},filename='roadwatch-configuration.json')
                if self.path=='/api/backup':
                    import sqlite3
                    target=app.store.root/('backup-'+uuid.uuid4().hex+'.sqlite3')
                    source=app.store.connect()
                    backup=sqlite3.connect(target)
                    try:
                        source.backup(backup)
                    finally:
                        backup.close();source.close()
                    data=io.BytesIO()
                    with zipfile.ZipFile(data,'w',zipfile.ZIP_DEFLATED) as archive:
                        archive.write(target,'roadwatch.sqlite3')
                        for frame in (app.store.root/'frames').glob('*.jpg'):
                            archive.write(frame,'frames/'+frame.name)
                    target.unlink(missing_ok=True)
                    return self.reply(200,data.getvalue(),'application/zip','roadwatch-backup.zip')
                if self.path=='/api/evaluation.csv':
                    stream=io.StringIO(newline='')
                    fields=['summary_id','camera_id','start_utc','end_utc','disposition','latency_seconds','verdict','notes']
                    writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
                    for row in app.store.evaluation():
                        review=row.get('human_review') or {}
                        values={k:row.get(k,'') for k in fields}
                        values.update(verdict=review.get('verdict',''),notes=review.get('notes',''))
                        # Prevent spreadsheet formula execution in exported notes.
                        writer.writerow({k:("'"+str(v) if str(v).startswith(('=','+','-','@')) else v) for k,v in values.items()})
                    return self.reply(200,stream.getvalue(),'text/csv','roadwatch-evaluation.csv')
                if path.startswith('/frames/') and path.endswith('.jpg'):
                    cid=str(uuid.UUID(path.removeprefix('/frames/').removesuffix('.jpg')))
                    return self.reply(200,(app.store.root/'frames'/(cid+'.jpg')).read_bytes(),'image/jpeg')
                self.reply(404,{'error':'Not found'})
            except (ValueError,FileNotFoundError):
                self.reply(404,{'error':'Not found'})

        def do_POST(self):
            if (self.headers.get('Host')!=self.host() or self.headers.get('Origin')!='http://'+self.host() or
                    not secrets.compare_digest(self.headers.get('X-RoadWatch-Token',''),app.token)):
                return self.reply(403,{'error':'Reload the RoadWatch page before trying again'})
            if not app.api_lock.acquire(blocking=False):
                return self.reply(409,{'error':'Another update is being saved. Try again shortly.'})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=100_000:
                    raise ValueError('Invalid request size')
                body=json.loads(self.rfile.read(size))
                if not isinstance(body,dict):
                    raise ValueError('Expected an object')
                self.reply(200,app.dispatch(self.path,body))
            except (ValueError,KeyError,TypeError) as exc:
                self.reply(400,{'error':str(exc)[:500]})
            except RuntimeError as exc:
                self.reply(502,{'error':str(exc)[:500]})
            except Exception:
                self.reply(500,{'error':'Operation failed. Check local state before repeating any submission.'})
            finally:
                app.api_lock.release()
    return Handler


def run():
    import argparse
    import tempfile
    parser=argparse.ArgumentParser(description='RoadWatch local operator workspace')
    parser.add_argument('--demo',action='store_true',help='Temporary sample data; no live upstream actions')
    args=parser.parse_args()
    temp=tempfile.TemporaryDirectory() if args.demo else None
    app=Application(data_dir=temp.name if temp else None,demo=args.demo)
    if args.demo:
        import datetime as dt
        for offset in [0,60,120]:
            start=dt.datetime.now(dt.timezone.utc)-dt.timedelta(seconds=300-offset)
            assessment={'assessment':'obstructed','road_context':'no_managed_closure_visible','obstruction_type':'vehicle','persists_within_clip':True,
                        'traffic_effect':'stopping_behind','visibility':'adequate','evidence':'DEMO: A stopped pickup occupies the traffic lane. Approaching vehicles wait behind it.'}
            app.store.ingest({'summary_id':str(uuid.uuid4()),'camera_id':'3ccadc04-93aa-46ea-823a-6c0f3de83055','start_utc':start.isoformat(),
                'end_utc':(start+dt.timedelta(seconds=15)).isoformat(),'latency_seconds':6.5,'disposition':'candidate_obstruction','assessment':assessment,'raw_response':json.dumps(assessment)})
    server=ThreadingHTTPServer(('127.0.0.1',8765),handler_for(app))
    print('RoadWatch: http://127.0.0.1:8765 — open Edge ON p039. Ctrl+C stops the server.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        app.monitor.stop()
    finally:
        server.server_close()
        if temp:
            temp.cleanup()


if __name__=='__main__':
    run()
