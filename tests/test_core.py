import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from roadwatch_store import Store
from roadwatch_check import interpret
from roadwatch_services import Services
from roadwatch_monitor import Monitor
from roadwatch_spatial import inside, validate_regions

CAM='3ccadc04-93aa-46ea-823a-6c0f3de83055'

def observation(second=0,disposition='candidate_obstruction',kind='vehicle'):
    start=dt.datetime(2026,10,22,14,0,tzinfo=dt.timezone.utc)+dt.timedelta(seconds=second)
    assessment={'assessment':'obstructed','road_context':'no_managed_closure_visible','obstruction_type':kind,
        'persists_within_clip':True,'traffic_effect':'stopping_behind','visibility':'adequate','evidence':'Stopped vehicle visible'}
    return {'summary_id':str(uuid.uuid4()),'camera_id':CAM,'start_utc':start.isoformat(),
        'end_utc':(start+dt.timedelta(seconds=15)).isoformat(),'disposition':disposition,
        'assessment':assessment,'raw_response':json.dumps(assessment),'latency_seconds':6}


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(self.temp.name)
        self.store.save_camera({'id':CAM,'name':'test','synthetic':True,'looping':True})
    def tearDown(self):
        self.temp.cleanup()
    def test_groups_distinct_observations_and_deduplicates(self):
        first=observation();iid=self.store.ingest(first)
        self.assertEqual(self.store.ingest(first),iid)
        self.assertEqual(self.store.ingest(observation(30)),iid)
        result=self.store.incident(iid)
        self.assertEqual(len(result['observations']),2)
        self.assertEqual(result['independent_observations'],2)
        self.assertEqual(result['observed_seconds'],30)
        self.assertFalse(result['persistence_verified'])
    def test_overlap_does_not_count_as_independent(self):
        iid=self.store.ingest(observation())
        self.store.ingest(observation(5))
        self.assertEqual(self.store.incident(iid)['independent_observations'],1)
    def test_closed_episode_does_not_reopen_and_clear_observation_does_not_close(self):
        iid=self.store.ingest(observation())
        self.assertIsNone(self.store.ingest(observation(20,'no_target_observed')))
        self.assertEqual(self.store.incident(iid)['status'],'new')
        with self.assertRaises(ValueError):
            self.store.update(iid,0,'cleared','clear',False)
        self.store.update(iid,0,'cleared','Verified in footage',True)
        next_id=self.store.ingest(observation(30))
        self.assertNotEqual(iid,next_id)
    def test_stale_updates_and_long_gaps(self):
        iid=self.store.ingest(observation())
        self.store.update(iid,0,'acknowledged','Reviewed')
        with self.assertRaises(ValueError):
            self.store.update(iid,0,'responding','Stale')
        self.assertNotEqual(self.store.ingest(observation(900)),iid)
    def test_budget_survives_restart(self):
        self.store.reserve(1)
        with self.assertRaises(ValueError):
            Store(self.temp.name).reserve(1)
    def test_delivery_claim_is_once_only(self):
        iid=self.store.ingest(observation())
        self.store.claim_delivery(iid,{'tag':'test'})
        with self.assertRaises(ValueError):
            self.store.claim_delivery(iid,{'tag':'test'})
        self.assertEqual(self.store.incident(iid)['delivery']['status'],'attempting')
    def test_legacy_delivery_prevents_resend(self):
        value=observation();path=Path(self.temp.name)/(value['summary_id']+'.json')
        path.write_text(json.dumps(value))
        path.with_name(value['summary_id']+'.event-submission.json').write_text(json.dumps({'status':'accepted'}))
        self.store.import_legacy();self.store.import_legacy()
        self.assertEqual(len(self.store.incidents()),1)
        self.assertEqual(self.store.incidents()[0]['delivery']['status'],'accepted')
    def test_uncertain_does_not_merge_with_candidate(self):
        first=self.store.ingest(observation())
        second=self.store.ingest(observation(20,'needs_review'))
        self.assertNotEqual(first,second)


class SafetyTests(unittest.TestCase):
    def test_rebuild_retires_old_camera_and_invalidates_regions(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder)
            store.save_camera({'id':CAM,'name':'same_camera','synthetic':False,'looping':True,'region_reviewed':True})
            iid=store.ingest(observation())
            new_id=str(uuid.uuid4())
            xp,gateway=Mock(),Mock()
            xp.call.side_effect=[(200,{'array':[{'id':new_id,'name':'same_camera'}]}),(200,{'array':[]})]
            gateway.call.return_value=(200,None)
            with patch('roadwatch_services.Client',side_effect=[xp,gateway]):
                Services(store).connect('test','fake','fake')
            self.assertEqual([c['id'] for c in store.cameras()],[new_id])
            self.assertFalse(store.cameras()[0]['region_reviewed'])
            self.assertEqual(store.incident(iid)['camera_name'],'same_camera')
    def test_response_conflicts_and_invalid_output(self):
        self.assertEqual(interpret('Weather is clear')['disposition'],'needs_review')
        value=observation()['assessment'];value.update(road_context='managed_roadworks',traffic_effect='managed_merge')
        self.assertEqual(interpret(json.dumps(value))['disposition'],'needs_review')
        value.update(road_context='no_managed_closure_visible',traffic_effect='stopping_behind',persists_within_clip=False)
        self.assertEqual(interpret(json.dumps(value))['disposition'],'needs_review')
    def test_geometry(self):
        regions={'open_lane':[[0,0],[1,0],[1,1],[0,1]],'work_area':[[0,0],[.2,0],[.2,.2],[0,.2]]}
        validate_regions(regions)
        self.assertTrue(inside([.5,.5],regions['open_lane']))
        self.assertFalse(inside([.5,.5],regions['work_area']))
        with self.assertRaises(ValueError):
            validate_regions({'open_lane':[[0,0],[1,1],[0,1],[1,0]],'work_area':regions['work_area']})
    def test_synthetic_auto_delivery_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder);store.save_camera({'id':CAM,'name':'loop','synthetic':True})
            services=Services(store);services.connected=True
            with self.assertRaises(ValueError):
                Monitor(services).start({'camera_ids':[CAM],'auto_send':True})
    def test_quota_reserve_blocks_before_submission(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder);store.save_camera({'id':CAM,'name':'test'})
            services=Services(store);services.connected=True;services.credentials={'gateway_password':'fake'}
            with patch.object(services,'quota',return_value={'used':450,'limit':500}),patch('roadwatch_services.assess') as request:
                with self.assertRaises(ValueError):
                    services.check(CAM)
                request.assert_not_called()
    def test_upstream_event_contract_and_duplicate_block(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder);iid=store.ingest(observation());store.set_setting('event_type','99f5b1e9-0895-48c6-89ff-cc22713e08c1')
            services=Services(store);services.connected=True;services.credentials={'user':'test','password':'fake'}
            services.xp=Mock();services.xp.call.return_value=(202,{'data':{'id':'event'}})
            services.send(iid)
            args=services.xp.call.call_args.args
            self.assertEqual(args[0:2],('POST','/api/rest/v1/events'))
            self.assertEqual(args[2]['source'],'cameras/'+CAM)
            self.assertEqual(args[2]['datatype'],'analytics')
            with self.assertRaises(ValueError):
                services.send(iid)
            self.assertEqual(services.xp.call.call_count,1)
    def test_ambiguous_delivery_remains_claimed(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder);iid=store.ingest(observation());store.set_setting('event_type','99f5b1e9-0895-48c6-89ff-cc22713e08c1')
            services=Services(store);services.connected=True;services.credentials={'user':'test','password':'fake'}
            services.xp=Mock();services.xp.call.side_effect=RuntimeError('Uncertain upstream outcome')
            with self.assertRaises(RuntimeError):
                services.send(iid)
            with self.assertRaises(ValueError):
                services.send(iid)
            self.assertEqual(Store(folder).incident(iid)['delivery']['status'],'attempting')
    def test_bookmark_uses_exact_observation_interval(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder);value=observation();iid=store.ingest(value)
            services=Services(store);services.connected=True;services.credentials={'user':'test','password':'fake'}
            services.xp=Mock();services.xp.call.return_value=(200,{'array':[]})
            services.bookmark(iid)
            args=services.xp.call.call_args.args
            self.assertEqual(args[1],'/api/rest/v1/bookmarks')
            self.assertEqual(args[2]['timeBegin'],value['start_utc'])
            self.assertEqual(args[2]['devicePath'],{'type':'cameras','id':CAM})
    def test_monitor_stops_at_session_cap(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder);store.save_camera({'id':CAM,'name':'test'})
            services=Services(store);services.connected=True
            with patch.object(services,'check',return_value={'incident_id':None}) as check:
                monitor=Monitor(services)
                # Wake the scheduler's inter-check wait without real delays.
                with patch.object(monitor.stop_event,'wait',return_value=False):
                    monitor.start({'camera_ids':[CAM],'max_requests':2,'minutes':1,'interval':30})
                    monitor.thread.join(3)
                self.assertFalse(monitor.thread.is_alive())
                self.assertEqual(check.call_count,2)
                self.assertEqual(monitor.snapshot()['status'],'completed')
    def test_stop_allows_inflight_to_finish_without_new_request(self):
        import threading
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder);store.save_camera({'id':CAM,'name':'test'})
            services=Services(store);services.connected=True
            entered,release=threading.Event(),threading.Event()
            def check(_):
                entered.set();release.wait(2);return {'incident_id':None}
            with patch.object(services,'check',side_effect=check) as request:
                monitor=Monitor(services);monitor.start({'camera_ids':[CAM]})
                self.assertTrue(entered.wait(2));monitor.stop();release.set();monitor.thread.join(3)
                self.assertEqual(request.call_count,1)
                self.assertEqual(monitor.snapshot()['status'],'stopped')


if __name__=='__main__':
    unittest.main()
