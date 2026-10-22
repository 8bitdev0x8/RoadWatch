"""Send one explicitly requested XProtect event on p039. No Hafnia requests.

API contract: https://doc.developer.milestonesys.com/mipvmsapi/api/events-rest/v1/
"""
import argparse
import datetime as dt
import getpass
import json
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
import uuid

from roadwatch_check import interpret


def make_event(event_type, camera, tag, when=None):
    return {'type': str(uuid.UUID(str(event_type))),
            'source': 'cameras/' + str(uuid.UUID(str(camera))),
            'time': when or dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00', 'Z'),
            'datatype': 'analytics', 'data': {}, 'tag': tag}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--event-type-id', required=True, type=uuid.UUID)
    parser.add_argument('--user', required=True, help='XProtect BASIC user, not gateway administrator')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--test-camera-id', type=uuid.UUID, help='Send one TEST event for this camera')
    mode.add_argument('--result', type=Path, help='Explicitly send one saved candidate assessment')
    args = parser.parse_args()
    marker = None
    if args.result:
        saved = json.loads(args.result.read_text(encoding='utf-8'))
        if interpret(saved.get('raw_response', ''))['disposition'] != 'candidate_obstruction':
            raise ValueError('Saved response is not a validated candidate obstruction')
        summary_id = str(uuid.UUID(saved['summary_id']))
        # A submission marker prevents automatic replay after ambiguous outcomes.
        marker = args.result.with_name(summary_id + '.event-submission.json')
        if marker.exists():
            raise ValueError('Submission already attempted. Inspect marker and Alarm Manager before any manual retry.')
        when = dt.datetime.fromisoformat(saved['end_utc'].replace('Z', '+00:00'))
        if when.tzinfo is None:
            raise ValueError('Result timestamp must have a timezone')
        event = make_event(args.event_type_id, saved['camera_id'], 'RoadWatch candidate ' + summary_id,
                           when.astimezone(dt.timezone.utc).isoformat().replace('+00:00', 'Z'))
    else:
        event = make_event(args.event_type_id, args.test_camera_id, 'RoadWatch TEST ' + str(uuid.uuid4()))

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    stage = 'login'
    token = None

    def request(path, body, content_type):
        headers = {'Content-Type': content_type}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        req = urllib.request.Request('http://localhost' + path, data=body, headers=headers, method='POST')
        with opener.open(req, timeout=30) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None

    print('Sends ONE event to XProtect. This may create an operator alarm. No Hafnia request.')
    password = getpass.getpass('XProtect basic-user password (not saved): ')
    try:
        _, login = request('/API/IDP/connect/token', urllib.parse.urlencode({
            'grant_type': 'password', 'client_id': 'GrantValidatorClient',
            'username': args.user, 'password': password}).encode(), 'application/x-www-form-urlencoded')
        del password
        token = login['access_token']
        stage = 'event submission'
        if marker:
            with marker.open('x', encoding='utf-8') as stream:
                json.dump({'status': 'attempting', 'event': event}, stream, indent=2)
        status, response = request('/api/rest/v1/events', json.dumps(event).encode(), 'application/json')
        if status != 202:
            raise RuntimeError('Unexpected status; check Alarm Manager before retrying')
        if marker:
            marker.write_text(json.dumps({'status': 'accepted', 'event': event, 'response': response}, indent=2), encoding='utf-8')
        print('XProtect accepted the event (HTTP 202). Confirm the alarm in Smart Client Alarm Manager.')
        print('Tag:', event['tag'])
        if args.result:
            print('Event uses the original clip end time; adjust Alarm Manager time filters if necessary.')
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'{stage}: HTTP {exc.code}. No automatic retry; check user permissions and alarm configuration.') from None
    except OSError:
        raise RuntimeError(f'{stage}: connection or file error. Delivery may be uncertain; inspect Alarm Manager before retrying.') from None


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, KeyError) as exc:
        raise SystemExit(str(exc))
