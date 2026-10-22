"""Durable local incident ledger. No credentials are stored here."""
import datetime as dt
import json
from pathlib import Path
import sqlite3
import uuid

UTC = dt.timezone.utc
class Connection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()

def now():
    return dt.datetime.now(UTC).isoformat()
def instant(value):
    result = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Timestamp must include timezone')
    return result.astimezone(UTC)


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'roadwatch.sqlite3'
        self._legacy_seen = {}
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS observations(id TEXT PRIMARY KEY,camera TEXT NOT NULL,start TEXT NOT NULL,end TEXT NOT NULL,body TEXT NOT NULL,incident TEXT);
            CREATE TABLE IF NOT EXISTS incidents(id TEXT PRIMARY KEY,camera TEXT NOT NULL,kind TEXT NOT NULL,status TEXT NOT NULL,first TEXT NOT NULL,last TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY,incident TEXT NOT NULL,time TEXT NOT NULL,action TEXT NOT NULL,note TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS cameras(id TEXT PRIMARY KEY,body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reviews(observation TEXT PRIMARY KEY,body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS deliveries(incident TEXT PRIMARY KEY,status TEXT NOT NULL,body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reservations(id TEXT PRIMARY KEY,day TEXT NOT NULL,status TEXT NOT NULL);
            ''')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10, factory=Connection)
        db.row_factory = sqlite3.Row
        return db

    def setting(self, key, default=None):
        with self.connect() as db:
            row = db.execute('SELECT body FROM settings WHERE key=?', (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, json.dumps(value)))

    def cameras(self, include_retired=False):
        with self.connect() as db:
            values = [json.loads(r[0]) for r in db.execute('SELECT body FROM cameras ORDER BY id')]
            return values if include_retired else [c for c in values if not c.get('retired')]

    def save_camera(self, value):
        value = dict(value)
        value['id'] = str(uuid.UUID(value['id']))
        if not isinstance(value.get('name'), str) or not value['name'].strip():
            raise ValueError('Camera needs a name')
        value['name'] = value['name'][:200]
        if type(value.get('synthetic', True)) is not bool:
            raise ValueError('Synthetic flag must be boolean')
        value.setdefault('synthetic', True)
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO cameras VALUES (?,?)', (value['id'], json.dumps(value)))

    def ingest(self, value):
        """Group same-camera/type candidates; a group is not proof of persistence."""
        value = dict(value)
        oid, camera = str(uuid.UUID(value['summary_id'])), str(uuid.UUID(value['camera_id']))
        start, end = instant(value['start_utc']), instant(value['end_utc'])
        if end <= start:
            raise ValueError('Invalid observation interval')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT incident FROM observations WHERE id=?', (oid,)).fetchone()
            if existing:
                return existing[0]
            incident = None
            if value.get('disposition') in {'candidate_obstruction', 'needs_review'}:
                kind = value.get('assessment', {}).get('obstruction_type', 'unknown')
                # Uncertain observations are kept separate from candidate episodes.
                if value.get('disposition') == 'needs_review':
                    kind = 'review'
                recent = db.execute("SELECT * FROM incidents WHERE camera=? AND kind=? AND status NOT IN ('cleared','dismissed') ORDER BY last DESC LIMIT 1", (camera, kind)).fetchone()
                if recent and 0 <= (end - instant(recent['last'])).total_seconds() <= 600:
                    incident = recent['id']
                    db.execute('UPDATE incidents SET last=?,version=version+1 WHERE id=?', (end.isoformat(), incident))
                else:
                    incident = str(uuid.uuid4())
                    db.execute('INSERT INTO incidents(id,camera,kind,status,first,last) VALUES (?,?,?,?,?,?)',
                               (incident, camera, kind, 'new', start.isoformat(), end.isoformat()))
                    db.execute('INSERT INTO history(incident,time,action,note) VALUES (?,?,?,?)',
                               (incident, now(), 'opened', 'Observation needs operator review.'))
            db.execute('INSERT INTO observations VALUES (?,?,?,?,?,?)',
                       (oid, camera, start.isoformat(), end.isoformat(), json.dumps(value), incident))
            return incident

    def observation(self, oid):
        with self.connect() as db:
            row = db.execute('SELECT body FROM observations WHERE id=?', (str(uuid.UUID(oid)),)).fetchone()
            if not row:
                raise ValueError('Observation not found')
            return json.loads(row[0])

    def incidents(self):
        cameras = {c['id']: c for c in self.cameras(include_retired=True)}
        with self.connect() as db:
            output = []
            for row in db.execute('SELECT * FROM incidents ORDER BY last DESC'):
                item = dict(row)
                observations = [json.loads(r[0]) for r in db.execute('SELECT body FROM observations WHERE incident=? ORDER BY end DESC', (item['id'],))]
                item['observations'] = observations
                item['camera_name'] = cameras.get(item['camera'], {}).get('name', item['camera'])
                item['synthetic'] = cameras.get(item['camera'], {}).get('synthetic', True)
                item['history'] = [dict(r) for r in db.execute('SELECT time,action,note FROM history WHERE incident=? ORDER BY id DESC', (item['id'],))]
                delivery = db.execute('SELECT status,body FROM deliveries WHERE incident=?', (item['id'],)).fetchone()
                item['delivery'] = {'status': delivery['status'], **json.loads(delivery['body'])} if delivery else {'status': 'not_sent'}
                # Non-overlap is necessary, but not sufficient, for persistence.
                distinct, last_end = [], None
                for obs in sorted(observations, key=lambda o: o['start_utc']):
                    if obs['disposition'] != 'candidate_obstruction':
                        continue
                    a, b = instant(obs['start_utc']), instant(obs['end_utc'])
                    if last_end is None or a >= last_end:
                        distinct.append(obs)
                        last_end = b
                item['independent_observations'] = len(distinct)
                item['observed_seconds'] = sum((instant(o['end_utc']) - instant(o['start_utc'])).total_seconds() for o in distinct)
                item['elapsed_seconds'] = (instant(item['last']) - instant(item['first'])).total_seconds()
                item['persistence_verified'] = False
                output.append(item)
            return output

    def incident(self, iid):
        found = next((i for i in self.incidents() if i['id'] == str(uuid.UUID(iid))), None)
        if not found:
            raise ValueError('Incident not found')
        return found

    def update(self, iid, version, state, note, verified=False):
        iid = str(uuid.UUID(iid))
        if state not in {'new', 'acknowledged', 'responding', 'cleared', 'dismissed'}:
            raise ValueError('Invalid state')
        if not isinstance(note, str) or not note.strip() or len(note) > 2000:
            raise ValueError('Add an evidence or action note (1-2000 characters)')
        if state == 'cleared' and verified is not True:
            raise ValueError('Verify clearance before closing')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT version FROM incidents WHERE id=?', (iid,)).fetchone()
            if not row or row[0] != version:
                raise ValueError('Incident changed. Refresh before updating.')
            db.execute('UPDATE incidents SET status=?,version=version+1 WHERE id=?', (state, iid))
            db.execute('INSERT INTO history(incident,time,action,note) VALUES (?,?,?,?)', (iid, now(), state, note.strip()))

    def reserve(self, daily_cap):
        """Charge attempts conservatively, including ambiguous upstream outcomes."""
        day = now()[:10]
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            count = db.execute('SELECT COUNT(*) FROM reservations WHERE day=?', (day,)).fetchone()[0]
            if count >= daily_cap:
                raise ValueError('RoadWatch daily request cap reached')
            rid = str(uuid.uuid4())
            db.execute('INSERT INTO reservations VALUES (?,?,?)', (rid, day, 'reserved'))
            return rid

    def budget(self):
        with self.connect() as db:
            count = db.execute('SELECT COUNT(*) FROM reservations WHERE day=?', (now()[:10],)).fetchone()[0]
            return {'day_utc': now()[:10], 'reserved_today': count}

    def claim_delivery(self, iid, body):
        with self.connect() as db:
            try:
                db.execute('INSERT INTO deliveries VALUES (?,?,?)', (iid, 'attempting', json.dumps(body)))
            except sqlite3.IntegrityError:
                raise ValueError('Delivery already attempted. Check XProtect before any retry.') from None

    def finish_delivery(self, iid, body):
        with self.connect() as db:
            db.execute('UPDATE deliveries SET status=?,body=? WHERE incident=?', ('accepted', json.dumps(body), iid))

    def review(self, oid, verdict, notes):
        self.observation(oid)
        if verdict not in {'correct', 'false_alarm', 'missed_hazard', 'uncertain'}:
            raise ValueError('Invalid review verdict')
        if not isinstance(notes, str) or len(notes) > 2000:
            raise ValueError('Notes must be at most 2000 characters')
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO reviews VALUES (?,?)', (oid, json.dumps({'verdict': verdict, 'notes': notes, 'time': now()})))

    def evaluation(self):
        with self.connect() as db:
            rows = []
            for row in db.execute('SELECT o.id,o.body,r.body AS review FROM observations o LEFT JOIN reviews r ON r.observation=o.id ORDER BY o.end DESC'):
                value = json.loads(row['body'])
                rows.append({**value, 'human_review': json.loads(row['review']) if row['review'] else None})
            return rows

    def import_legacy(self):
        from roadwatch_check import interpret
        for path in self.root.glob('*.json'):
            try:
                uuid.UUID(path.stem)
                related = [path] + [path.with_name(path.stem + suffix) for suffix in
                                   ['.event-submission.json','.incident.json','.review.json']]
                fingerprint = tuple(p.stat().st_mtime_ns if p.exists() else None for p in related)
                if self._legacy_seen.get(path.name) == fingerprint:
                    continue
                value = json.loads(path.read_text(encoding='utf-8'))
                value.update(interpret(value.get('raw_response', '')))
                iid = self.ingest(value)
                if iid:
                    marker = path.with_name(path.stem + '.event-submission.json')
                    if marker.exists():
                        delivery = json.loads(marker.read_text(encoding='utf-8'))
                        with self.connect() as db:
                            db.execute('INSERT OR IGNORE INTO deliveries VALUES (?,?,?)',
                                       (iid, delivery.get('status', 'attempting'), json.dumps(delivery)))
                    legacy = path.with_name(path.stem + '.incident.json')
                    with self.connect() as db:
                        key = 'legacy:' + path.stem
                        if legacy.exists() and not db.execute('SELECT 1 FROM settings WHERE key=?', (key,)).fetchone():
                            old = json.loads(legacy.read_text(encoding='utf-8'))
                            if old.get('status') in {'new','acknowledged','responding','cleared','dismissed'}:
                                db.execute('UPDATE incidents SET status=? WHERE id=?', (old['status'], iid))
                                for h in old.get('history', []):
                                    db.execute('INSERT INTO history(incident,time,action,note) VALUES (?,?,?,?)',
                                        (iid, h.get('time_utc', now()), h.get('status', 'imported'), h.get('note', 'Imported operator record')))
                            db.execute('INSERT INTO settings VALUES (?,?)', (key, 'true'))
                review = path.with_name(path.stem + '.review.json')
                if review.exists():
                    old = json.loads(review.read_text(encoding='utf-8'))
                    with self.connect() as db:
                        db.execute('INSERT OR IGNORE INTO reviews VALUES (?,?)', (path.stem, json.dumps(old)))
                self._legacy_seen[path.name] = fingerprint
            except (ValueError, KeyError, OSError, TypeError):
                continue
