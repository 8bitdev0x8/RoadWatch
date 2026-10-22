"""Local-only upstream clients and application operations."""
import base64
import datetime as dt
import json
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from roadwatch_check import main as assess
from roadwatch_event import make_event
from roadwatch_store import instant, now


class UpstreamError(RuntimeError):
    pass


class Client:
    def __init__(self, gateway=False):
        self.gateway = gateway
        self.base = 'https://localhost:15443' if gateway else 'http://localhost'
        handlers = [urllib.request.ProxyHandler({})]
        if gateway:
            handlers.append(urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
        self.opener = urllib.request.build_opener(*handlers)
        self.token = None

    def call(self, method, path, body=None, form=False):
        headers = {'Content-Type': 'application/x-www-form-urlencoded' if form else 'application/json'}
        if self.token:
            headers['X-Session-Id' if self.gateway else 'Authorization'] = self.token if self.gateway else 'Bearer ' + self.token
        data = None if body is None else ((urllib.parse.urlencode(body) if form else json.dumps(body)).encode())
        try:
            with self.opener.open(urllib.request.Request(self.base + path, data=data, headers=headers, method=method), timeout=30) as response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            raise UpstreamError(f'Upstream HTTP {exc.code} during {path.split("?")[0]}. Check connection, credentials and permissions. No automatic retry.') from None
        except OSError:
            raise UpstreamError('Local upstream unavailable. Run RoadWatch on p039; check services. Do not retry an uncertain event before inspecting Alarm Manager.') from None

    def login(self, user, password):
        if self.gateway:
            _, data = self.call('POST', '/api/Sessions/Login', {'Name': user, 'Password': password})
            self.token = data['Id']
        else:
            _, data = self.call('POST', '/API/IDP/connect/token', {'grant_type': 'password', 'client_id': 'GrantValidatorClient', 'username': user, 'password': password}, form=True)
            self.token = data['access_token']


SYNTHETIC = {'vehicle_breakdown_traffic_queue','bin_pushed_over_onto_sidewalk','escooter_left_across_sidewalk','school_gate_break_in_night','person_on_railway_tracks','graffiti_on_standing_train'}


class Services:
    def __init__(self, store):
        self.store = store
        self.credentials = None
        self.xp = None
        self.connected = False
        self.operation = threading.Lock()
        self.last_error = None

    def connect(self, user, password, gateway_password):
        if not user or not password or not gateway_password:
            raise ValueError('Enter both connection passwords')
        xp = Client()
        xp.login(user, password)
        _, cameras = xp.call('GET', '/api/rest/v1/cameras')
        gateway = Client(True)
        gateway.login('administrator', gateway_password)
        gateway.call('POST', '/api/Sessions/Logout', {'Id': gateway.token})
        self.xp = xp
        self.credentials = {'user': user, 'password': password, 'gateway_password': gateway_password}
        self.connected = True
        previous = self.store.cameras(include_retired=True)
        current_ids = {c.get('id') for c in cameras.get('array', [])}
        for old_camera in previous:
            if old_camera['id'] not in current_ids:
                self.store.save_camera({**old_camera, 'retired':True})
        for raw in cameras.get('array', []):
            name, cid = raw.get('name') or raw.get('displayName'), raw.get('id')
            if not name or not cid:
                continue
            old = next((c for c in previous if c['id'] == cid), None)
            if old is None:
                old = next((c for c in previous if c['name'] == name), {})
                old = {**old, 'region_reviewed':False}
            self.store.save_camera({**old, 'id': cid, 'name': name, 'retired':False,
                'synthetic': old.get('synthetic', name in SYNTHETIC), 'looping': old.get('looping',True), 'enabled': old.get('enabled', False)})
        try:
            _, types = xp.call('GET', '/api/rest/v1/analyticsEvents')
            self.store.set_setting('event_types', [{'id': i['id'], 'name': i.get('name', i['id'])} for i in types.get('array', [])])
            matching = [i for i in types.get('array', []) if i.get('name') == 'RoadWatch candidate obstruction']
            if len(matching) == 1:
                self.store.set_setting('event_type', matching[0]['id'])
        except UpstreamError:
            pass
        return {'message': 'Connected. Credentials stay in server memory until disconnect or restart.', 'cameras': self.store.cameras()}

    def disconnect(self):
        self.credentials = None
        self.xp = None
        self.connected = False

    def quota(self):
        _, info = Client(True).call('GET', '/api/System/Information')
        q = info.get('QuotaInformation')
        if not q or type(q.get('DailySummaryCount')) is not int or type(q.get('DailySummaryQuota')) is not int:
            raise UpstreamError('Gateway quota unavailable. Checks are paused until quota can be verified.')
        return {'used': q['DailySummaryCount'], 'limit': q['DailySummaryQuota'], 'reset': q.get('DailySummaryReset')}

    def check(self, cid, seconds=15, start=None, end=None):
        if not self.connected or not self.credentials:
            raise ValueError('Connect to XProtect and Hafnia first')
        cid = str(uuid.UUID(cid))
        camera = next((c for c in self.store.cameras() if c['id'] == cid), None)
        if not camera:
            raise ValueError('Select a discovered camera')
        settings = self.store.setting('policy', {'daily_cap': 100, 'reserve': 50})
        quota = self.quota()
        if quota['used'] >= quota['limit'] - settings['reserve']:
            raise ValueError('Gateway reserve reached. Save remaining requests for manual work.')
        self.store.reserve(settings['daily_cap'])
        args = ['--camera-id', cid, '--seconds', str(seconds)]
        if start and end:
            args += ['--start', start, '--end', end]
        try:
            value = assess(args, password=self.credentials['gateway_password'])
        except Exception:
            raise UpstreamError('Assessment did not complete. Reservation retained conservatively. Inspect Smart Client History before another check.') from None
        value['camera_name'] = camera['name']
        value['synthetic'] = camera.get('synthetic', True)
        iid = self.store.ingest(value)
        return {'observation': value, 'incident_id': iid}

    def xp_call(self, method, path, body=None):
        if not self.connected or not self.xp or not self.credentials:
            raise ValueError('Connect first')
        # Refresh token once before operation; never automatically retry a POST.
        self.xp.login(self.credentials['user'], self.credentials['password'])
        return self.xp.call(method, path, body)

    def snapshot(self, cid):
        cid = str(uuid.UUID(cid))
        _, value = self.xp_call('POST', f'/api/rest/v1/cameras/{cid}?task=JpegGetLive', {'width': 1280, 'height': 720})
        frame = value.get('result', {})
        raw = base64.b64decode(frame['jpegDataAsBase64'], validate=True)
        if len(raw) > 3_000_000 or not raw.startswith(b'\xff\xd8'):
            raise ValueError('Invalid JPEG response')
        folder = self.store.root / 'frames'
        folder.mkdir(exist_ok=True)
        (folder / (cid + '.jpg')).write_bytes(raw)
        return {'url': '/frames/' + cid + '.jpg', 'frame_time': frame.get('frameDateTime'), 'note': 'Current setup reference, not incident evidence.'}

    def send(self, iid):
        item = self.store.incident(iid)
        if item['status'] in {'cleared', 'dismissed'} or item['kind'] == 'review':
            raise ValueError('Only an open candidate incident can be sent')
        if item['delivery']['status'] != 'not_sent':
            raise ValueError('Delivery already attempted. Check Alarm Manager.')
        event_type = self.store.setting('event_type')
        if not event_type:
            raise ValueError('Choose the RoadWatch event type in Settings')
        latest = next((o for o in item['observations'] if o['disposition'] == 'candidate_obstruction'), None)
        if not latest:
            raise ValueError('No eligible candidate')
        tag = 'RoadWatch candidate ' + item['id']
        event = make_event(event_type, item['camera'], tag, latest['end_utc'])
        # Authenticate before claiming; uncertain event submissions never retry.
        if not self.credentials or not self.xp:
            raise ValueError('Connect first')
        self.xp.login(self.credentials['user'], self.credentials['password'])
        self.store.claim_delivery(iid, {'tag': tag, 'observation_id': latest['summary_id'], 'time': now()})
        status, response = self.xp.call('POST', '/api/rest/v1/events', event)
        if status != 202:
            raise UpstreamError('Event response was not HTTP 202. Inspect Alarm Manager before retrying.')
        delivery = {'tag': tag, 'observation_id': latest['summary_id'], 'response': response, 'time': now()}
        self.store.finish_delivery(iid, delivery)
        return {'message': 'Event accepted. Confirm the alarm in XProtect.', 'delivery': delivery}

    def bookmark(self, iid):
        item = self.store.incident(iid)
        key = 'bookmark:' + iid
        if self.store.setting(key):
            raise ValueError('Bookmark already attempted. Check Smart Client before repeating.')
        latest = item['observations'][0]
        body = {'header': 'RoadWatch ' + iid[:8], 'description': latest.get('assessment', {}).get('evidence', 'Review candidate') + '\nIncident: ' + iid,
                'timeBegin': latest['start_utc'], 'timeEnd': latest['end_utc'], 'timeTriggered': latest['end_utc'],
                'devicePath': {'type': 'cameras', 'id': item['camera']}, 'reference': str(uuid.uuid4())}
        if not self.credentials or not self.xp:
            raise ValueError('Connect first')
        self.xp.login(self.credentials['user'], self.credentials['password'])
        self.store.set_setting(key, {'status': 'attempting', 'time': now()})
        status, response = self.xp.call('POST', '/api/rest/v1/bookmarks', body)
        if status != 200:
            raise UpstreamError('Unexpected bookmark response. Check Smart Client.')
        self.store.set_setting(key, {'status': 'accepted', 'response': response})
        return {'message': 'Bookmark accepted. Open Smart Client bookmarks to review the clip.'}
