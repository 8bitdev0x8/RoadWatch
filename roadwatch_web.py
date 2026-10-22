"""Local RoadWatch operator interface. Run on p039: py roadwatch_web.py."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import datetime as dt
from pathlib import Path
import secrets
import threading
import urllib.error
import uuid

import roadwatch_check
import roadwatch_event

ROOT = Path(__file__).resolve().parent
TOKEN = secrets.token_urlsafe(32)
LOCK = threading.Lock()
HOST = '127.0.0.1:8765'


def results():
    output = []
    for path in (ROOT / 'runtime').glob('*.json'):
        try:
            uuid.UUID(path.stem)
            value = json.loads(path.read_text(encoding='utf-8'))
            value.update(roadwatch_check.interpret(value.get('raw_response', '')))
            marker = path.with_name(path.stem + '.event-submission.json')
            value['submission'] = json.loads(marker.read_text(encoding='utf-8')).get('status', 'attempting') if marker.exists() else 'not_sent'
            review = path.with_name(path.stem + '.review.json')
            value['human_review'] = json.loads(review.read_text(encoding='utf-8')) if review.exists() else None
            incident = path.with_name(path.stem + '.incident.json')
            value['incident'] = json.loads(incident.read_text(encoding='utf-8')) if incident.exists() else {'status': 'new', 'history': []}
            value['camera_name'] = ('vehicle_breakdown_traffic_queue' if value.get('camera_id') ==
                                    '3ccadc04-93aa-46ea-823a-6c0f3de83055' else value.get('camera_id', 'Unknown camera'))
            output.append(value)
        except (ValueError, OSError):
            continue
    return sorted(output, key=lambda value: value.get('end_utc', ''), reverse=True)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # Do not log request bodies or credentials.

    def reply(self, status, value, kind='application/json'):
        data = (json.dumps(value) if kind == 'application/json' else value).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', kind + '; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(data)

    def valid_host(self):
        return self.headers.get('Host') == HOST

    def do_GET(self):
        if not self.valid_host():
            return self.reply(403, {'error': 'Use http://' + HOST})
        if self.path == '/':
            return self.reply(200, (ROOT / 'web/index.html').read_text(encoding='utf-8').replace('__TOKEN__', TOKEN), 'text/html')
        if self.path == '/api/results':
            return self.reply(200, results())
        if self.path == '/app.css':
            return self.reply(200, (ROOT / 'web/app.css').read_text(encoding='utf-8'), 'text/css')
        return self.reply(404, {'error': 'Not found'})

    def do_POST(self):
        if (not self.valid_host() or self.headers.get('Origin') != 'http://' + HOST or
                not secrets.compare_digest(self.headers.get('X-RoadWatch-Token', ''), TOKEN)):
            return self.reply(403, {'error': 'Reload the local RoadWatch page.'})
        if self.path not in {'/api/check', '/api/send', '/api/review', '/api/incident'}:
            return self.reply(404, {'error': 'Not found'})
        if not LOCK.acquire(blocking=False):
            return self.reply(409, {'error': 'Another operation is running. Wait for it to finish.'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 8192:
                raise ValueError('Invalid request size')
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError('Expected a JSON object')
            if self.path == '/api/incident':
                summary = str(uuid.UUID(body['summary_id']))
                path = ROOT / 'runtime' / (summary + '.json')
                if not path.exists():
                    raise ValueError('Assessment not found')
                state = body.get('status')
                if state not in {'new', 'acknowledged', 'responding', 'cleared', 'dismissed'}:
                    raise ValueError('Invalid incident status')
                note = body.get('note', '')
                if not isinstance(note, str) or not note.strip() or len(note) > 2000:
                    raise ValueError('Add an action or evidence note (1-2000 characters)')
                if state == 'cleared' and body.get('clearance_verified') is not True:
                    raise ValueError('Verify clearance against footage or a field report before closing')
                target = path.with_name(summary + '.incident.json')
                incident = json.loads(target.read_text(encoding='utf-8')) if target.exists() else {'status': 'new', 'history': []}
                if body.get('expected_status') != incident['status']:
                    return self.reply(409, {'error': 'Incident changed. Refresh before updating.'})
                incident['history'].append({'from_status': incident['status'], 'status': state,
                    'note': note.strip(), 'time_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                    'clearance_verified': state == 'cleared'})
                incident['status'] = state
                temp = target.with_suffix('.tmp')
                temp.write_text(json.dumps(incident, indent=2), encoding='utf-8')
                temp.replace(target)
                self.reply(200, {'message': 'RoadWatch status saved. XProtect alarm state is unchanged.'})
                return
            if self.path == '/api/review':
                summary = str(uuid.UUID(body['summary_id']))
                path = ROOT / 'runtime' / (summary + '.json')
                if not path.exists():
                    raise ValueError('Assessment not found')
                verdict = body.get('verdict')
                if verdict not in {'correct', 'false_alarm', 'missed_hazard', 'uncertain'}:
                    raise ValueError('Choose a review verdict')
                notes = body.get('notes', '')
                if not isinstance(notes, str) or len(notes) > 2000:
                    raise ValueError('Review notes must be at most 2000 characters')
                review = {'verdict': verdict, 'notes': notes,
                          'reviewed_utc': dt.datetime.now(dt.timezone.utc).isoformat()}
                path.with_name(summary + '.review.json').write_text(json.dumps(review, indent=2), encoding='utf-8')
                self.reply(200, {'message': 'Human review saved. No Hafnia request or XProtect event sent.'})
                return
            password = body.pop('password', '')
            if not isinstance(password, str) or not password:
                raise ValueError('Enter the password for this operation')
            if self.path == '/api/check':
                camera = str(uuid.UUID(body['camera_id']))
                seconds = int(body.get('seconds', 15))
                if not 5 <= seconds <= 60:
                    raise ValueError('Clip duration must be 5-60 seconds')
                value = roadwatch_check.main(['--camera-id', camera, '--seconds', str(seconds)], password=password)
                self.reply(200, {'message': 'Assessment saved. No alarm sent.', 'result': value})
            else:
                summary = str(uuid.UUID(body['summary_id']))
                event_type = str(uuid.UUID(body['event_type_id']))
                user = body.get('user', '').strip()
                if not user:
                    raise ValueError('Enter the XProtect basic username')
                path = ROOT / 'runtime' / (summary + '.json')
                roadwatch_event.main(['--user', user, '--event-type-id', event_type, '--result', str(path)], password=password)
                self.reply(200, {'message': 'XProtect accepted the event. Confirm the alarm in Smart Client.'})
        except urllib.error.HTTPError as exc:
            self.reply(502, {'error': f'Upstream HTTP {exc.code}. Check credentials and Smart Client History. No automatic retry.'})
        except (ValueError, KeyError, FileNotFoundError) as exc:
            self.reply(400, {'error': str(exc)})
        except RuntimeError as exc:
            self.reply(502, {'error': str(exc)})
        except Exception:
            self.reply(502, {'error': 'Operation interrupted. Check History and Alarm Manager before retrying; delivery may be uncertain.'})
        finally:
            LOCK.release()


if __name__ == '__main__':
    print('RoadWatch: http://' + HOST)
    print('Open in Edge ON p039. Manual operations only. Ctrl+C stops the server.')
    ThreadingHTTPServer(('127.0.0.1', 8765), Handler).serve_forever()
