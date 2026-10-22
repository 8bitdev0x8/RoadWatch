"""One manual RoadWatch assessment, using the HackathonKit gateway contract.

Run on p039 with Python 3.11+. One completed assessment costs one request.
No alarms, scheduled requests, or spatial detection are enabled.
"""
import argparse
import datetime as dt
import getpass
import json
from pathlib import Path
import ssl
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parent
ALLOWED = {
    'assessment': {'obstructed', 'clear', 'uncertain'},
    'road_context': {'managed_roadworks', 'no_managed_closure_visible', 'uncertain'},
    'obstruction_type': {'person', 'vehicle', 'object', 'none', 'unknown'},
    'traffic_effect': {'stopping_behind', 'unexpected_avoidance', 'managed_merge', 'none_visible', 'unknown'},
    'visibility': {'adequate', 'limited'},
}


def interpret(raw):
    """Untrusted model output never directly authorizes an alarm or clearance."""
    try:
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError('Expected a JSON object')
        for key, choices in ALLOWED.items():
            if not isinstance(value.get(key), str) or value[key] not in choices:
                raise ValueError(f'Invalid or missing {key}')
        if 'persists_within_clip' not in value or (value['persists_within_clip'] is not None and type(value['persists_within_clip']) is not bool):
            raise ValueError('Invalid or missing persists_within_clip')
        if not isinstance(value.get('evidence'), str) or not value['evidence'].strip():
            raise ValueError('Missing evidence')
        conflict = (value['assessment'] == 'clear' and
                    (value['obstruction_type'] != 'none' or value['persists_within_clip'] is not False))
        conflict |= value['assessment'] == 'obstructed' and value['obstruction_type'] in {'none', 'unknown'}
        # Our manual roadworks test produced this combination while its evidence
        # described only a closed work area. It requires review, not suppression.
        conflict |= (value['assessment'] == 'obstructed' and
                     value['road_context'] == 'managed_roadworks' and
                     value['traffic_effect'] == 'managed_merge')
        review = conflict or value['assessment'] == 'uncertain' or value['visibility'] == 'limited'
        if value['assessment'] == 'obstructed' and (value['persists_within_clip'] is not True or value['road_context'] == 'uncertain'):
            review = True
        return {'disposition': 'needs_review' if review else
                ('candidate_obstruction' if value['assessment'] == 'obstructed' else 'no_target_observed'),
                'assessment': value, 'conflicting_fields': bool(conflict)}
    except (ValueError, TypeError) as exc:
        return {'disposition': 'needs_review', 'validation_error': str(exc)}


def main(argv=None, password=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--camera-id', required=True, type=uuid.UUID)
    parser.add_argument('--seconds', type=int, choices=range(5, 61), default=15, metavar='5..60')
    parser.add_argument('--start', help='Optional recorded clip start, ISO UTC')
    parser.add_argument('--end', help='Optional recorded clip end, ISO UTC')
    args = parser.parse_args(argv)
    if bool(args.start) != bool(args.end):
        raise ValueError('Supply both start and end times')
    clip_end = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=5)
    clip_start = clip_end - dt.timedelta(seconds=args.seconds)
    if args.start:
        from roadwatch_store import instant
        clip_start, clip_end = instant(args.start), instant(args.end)
        if not 5 <= (clip_end - clip_start).total_seconds() <= 60:
            raise ValueError('Recorded interval must be 5-60 seconds')
        age = (dt.datetime.now(dt.timezone.utc) - clip_start).total_seconds()
        if age > 86400 or clip_end > dt.datetime.now(dt.timezone.utc):
            raise ValueError('Use a past interval within the retained 24 hours')
    prompt = (ROOT / 'prompts/road-obstruction.txt').read_text(encoding='utf-8')
    # This client accepts only the provisioned local gateway's self-signed cert.
    context = ssl._create_unverified_context()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
    session = None

    def call(method, path, body=None):
        request = urllib.request.Request('https://localhost:15443' + path, method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={'Content-Type': 'application/json', **({'X-Session-Id': session} if session else {})})
        with opener.open(request, timeout=60) as response:
            content = response.read()
            return json.loads(content) if content else None

    try:
        print('One-shot check: at most one new summary request. No automatic retries or alarms.')
        if password is None:
            password = getpass.getpass('Local Hafnia gateway password (not saved): ')
        session = call('POST', '/api/Sessions/Login', {'Name': 'administrator', 'Password': password})['Id']
        del password
        end, start = clip_end, clip_start
        stamp = lambda value: value.strftime('%Y-%m-%dT%H:%M:%SZ')
        began = time.monotonic()
        summary = call('POST', '/api/Summaries', {'Prompt': prompt, 'VideoUris': [
            f'xprotect://localhost/cameras/{args.camera_id}?StartTime={stamp(start)}&EndTime={stamp(end)}']})
        print('Summary ID:', summary['Id'])
        deadline = time.monotonic() + 600
        while summary['Progress'] not in {'Completed', 'Failed'}:
            if time.monotonic() >= deadline:
                raise RuntimeError('Timed out; check History before submitting another request.')
            time.sleep(3)
            summary = call('GET', '/api/Summaries/' + str(uuid.UUID(summary['Id'])))
        if summary['Progress'] == 'Failed':
            raise RuntimeError('Summary failed; inspect LastError in Smart Client History.')
        raw = summary.get('Response', '')
        result = {'summary_id': summary['Id'], 'camera_id': str(args.camera_id),
                  'start_utc': stamp(start), 'end_utc': stamp(end),
                  'latency_seconds': round(time.monotonic() - began, 2),
                  'raw_response': raw, **interpret(raw)}
        output = ROOT / 'runtime'
        output.mkdir(exist_ok=True)
        target = output / f'{uuid.UUID(summary["Id"])}.json'
        target.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print('Disposition:', result['disposition'])
        print('Saved:', target)
        return result
    finally:
        if session:
            try:
                call('POST', '/api/Sessions/Logout', {'Id': session})
            except Exception:
                pass


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Do not dump request bodies, credentials, or sessions into the console.
        raise SystemExit(f'Check stopped ({type(exc).__name__}). Check gateway availability and Smart Client History; no automatic retry was made.')
