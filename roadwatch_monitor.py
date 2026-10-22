"""Bounded, serialized checks. Credentials and schedules never auto-resume."""
import datetime as dt
import threading
import time
import uuid
from roadwatch_store import now


class Monitor:
    def __init__(self, services):
        self.services = services
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.thread = None
        self.state = {'status': 'stopped', 'completed': 0, 'attempted': 0, 'last_error': None, 'next_check': None}

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def start(self, options):
        if self.thread and self.thread.is_alive():
            raise ValueError('A monitoring session is already active')
        cameras = options.get('camera_ids', [])
        if not isinstance(cameras, list) or not 1 <= len(cameras) <= 3:
            raise ValueError('Choose 1-3 cameras')
        cameras = list(dict.fromkeys(str(uuid.UUID(c)) for c in cameras))
        interval = int(options.get('interval', 300))
        maximum = int(options.get('max_requests', 10))
        minutes = int(options.get('minutes', 30))
        if not 30 <= interval <= 3600 or not 1 <= maximum <= 20 or not 1 <= minutes <= 60:
            raise ValueError('Use interval 30-3600 seconds, 1-20 checks and 1-60 minutes')
        if not self.services.connected:
            raise ValueError('Connect before monitoring')
        known = {c['id']: c for c in self.services.store.cameras()}
        if any(c not in known for c in cameras):
            raise ValueError('Unknown camera')
        auto = options.get('auto_send') is True
        if auto and any(known[c].get('synthetic', True) or known[c].get('looping', True) for c in cameras):
            raise ValueError('Automatic alarm delivery is disabled for synthetic or looping cameras. Use operator review.')
        if auto and not self.services.store.setting('event_type'):
            raise ValueError('Configure an event type first')
        self.stop_event.clear()
        with self.lock:
            self.state = {'status': 'running', 'completed': 0, 'attempted': 0, 'last_error': None,
                          'next_check': now(), 'started': now(), 'camera_ids': cameras,
                          'interval': interval, 'max_requests': maximum, 'minutes': minutes, 'auto_send': auto}
        self.thread = threading.Thread(target=self.run, args=(cameras, interval, maximum, minutes, auto), daemon=True)
        self.thread.start()
        return self.snapshot()

    def run(self, cameras, interval, maximum, minutes, auto):
        deadline = time.monotonic() + minutes * 60
        failures = 0
        index = 0
        try:
            while not self.stop_event.is_set() and time.monotonic() < deadline:
                with self.lock:
                    if self.state['attempted'] >= maximum:
                        break
                if not self.services.operation.acquire(blocking=False):
                    if self.stop_event.wait(1):
                        break
                    continue
                try:
                    with self.lock:
                        self.state['attempted'] += 1
                        self.state['next_check'] = None
                        self.state['current_camera'] = cameras[index % len(cameras)]
                    result = self.services.check(cameras[index % len(cameras)])
                    failures = 0
                    with self.lock:
                        self.state['completed'] += 1
                        self.state['last_success'] = now()
                        self.state['last_error'] = None
                    if auto and result['incident_id']:
                        incident = self.services.store.incident(result['incident_id'])
                        if incident['independent_observations'] >= 2 and incident['delivery']['status'] == 'not_sent' and incident['kind'] != 'review':
                            self.services.send(incident['id'])
                except Exception as exc:
                    failures += 1
                    with self.lock:
                        # Application errors contain no request bodies or tokens.
                        self.state['last_error'] = str(exc)[:500] if isinstance(exc, (ValueError, RuntimeError)) else 'Check failed. Inspect upstream services.'
                    if failures >= 3 or 'cap' in str(exc).lower() or 'reserve' in str(exc).lower() or 'quota' in str(exc).lower():
                        with self.lock:
                            self.state['status'] = 'paused_error'
                        break
                finally:
                    self.services.operation.release()
                index += 1
                with self.lock:
                    if self.state['attempted'] >= maximum:
                        break
                wait = min(interval, max(0, deadline - time.monotonic()))
                with self.lock:
                    self.state['next_check'] = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=wait)).isoformat()
                if self.stop_event.wait(wait):
                    break
        finally:
            with self.lock:
                if self.state['status'] != 'paused_error':
                    self.state['status'] = 'stopped' if self.stop_event.is_set() else 'completed'
                self.state['next_check'] = None
                self.state['current_camera'] = None

    def stop(self):
        self.stop_event.set()
        with self.lock:
            if self.thread and self.thread.is_alive():
                self.state['status'] = 'stopping'
        return self.snapshot()


class Jobs:
    def __init__(self, services):
        self.services = services
        self.lock = threading.Lock()
        self.state = {'status': 'idle'}

    def snapshot(self):
        with self.lock:
            return dict(self.state)

    def start(self, fn):
        if not self.services.operation.acquire(blocking=False):
            raise ValueError('Another operation is active. Wait for it to finish.')
        with self.lock:
            self.state = {'status': 'running', 'started': now()}
        def run():
            try:
                result = fn()
                with self.lock:
                    self.state = {'status': 'completed', 'finished': now(), 'result': result}
            except Exception as exc:
                error = str(exc)[:500] if isinstance(exc, (ValueError, RuntimeError)) else 'Operation failed; inspect History and Alarm Manager before retrying.'
                with self.lock:
                    self.state = {'status': 'failed', 'finished': now(), 'error': error}
            finally:
                self.services.operation.release()
        threading.Thread(target=run, daemon=True).start()
        return {'message': 'Operation started. Progress appears in the status bar.'}
