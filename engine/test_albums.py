"""Whole-album regressions; callers must isolate BASIL_STATE_DIR before import."""
import os
assert os.environ.get('BASIL_STATE_DIR'), 'Set isolated BASIL_STATE_DIR before importing tests'
import unittest
from queue_test_support import QueuePrimitiveFixture
from unittest.mock import patch
import dj_session

class AlbumBudgetTests(QueuePrimitiveFixture):
    def test_full_album_brief_has_one_album_budget_not_track_deficit(self):
        state={'brief':'Full albums Jack Johnson / Jimmy Buffett beach mood'}
        self.assertEqual(dj_session.refill_policy(state, 0), {'mode':'album','remaining':1})
    def test_album_mode_waits_until_pending_album_starts(self):
        state={'active':True,'management_version':2,'queue_mode':'album','last_album':{'videoIds':['b','c']}}
        queue={'items':[{'playlistPanelVideoRenderer':{'videoId':v,'selected':v=='a'}} for v in ('a','b','c')]}
        self.assertFalse(dj_session.should_refill(state, {'videoId':'a','isPaused':False},queue))
        queue['items'][0]['playlistPanelVideoRenderer']['selected']=False
        queue['items'][1]['playlistPanelVideoRenderer']['selected']=True
        self.assertTrue(dj_session.should_refill(state, {'videoId':'b','isPaused':False},queue))
    def test_worker_album_prompt_and_budget_have_no_eight_track_cap(self):
        import tempfile,pathlib,json
        state={'active':True,'management_version':2,'generation':'g','brief':'full albums beach Jack Johnson'}
        queue={'items':[{'playlistPanelVideoRenderer':{'videoId':'aaaaaaaaaaa','selected':True}}]}
        def api(method,path,payload=None):
            return {'videoId':'aaaaaaaaaaa','isPaused':False} if path=='song' else {'mode':'NONE'} if path=='repeat-mode' else queue
        with tempfile.TemporaryDirectory() as tmp,patch.object(dj_session,'ROOT',pathlib.Path(tmp)),patch.object(dj_session,'STATE',pathlib.Path(tmp)/'session.json'),patch.object(dj_session,'load',return_value=state),patch.object(dj_session,'save') as save,patch.object(dj_session,'api',side_effect=api),patch.object(dj_session,'live_status',return_value={'paused':False}),patch('subprocess.check_output',return_value=json.dumps({'autoplay':False})),patch.object(dj_session,'run_refill') as run,patch.object(dj_session.time,'sleep',side_effect=StopIteration):
            with self.assertRaises(StopIteration):dj_session.worker()
        self.assertEqual(state['refill_remaining'],1);self.assertEqual(state['refill_mode'],'album')
        self.assertIn('ONE COMPLETE ALBUM',run.call_args.args[0]);self.assertIn('album-enqueue',run.call_args.args[0])
        self.assertNotIn('at most 8 tracks',run.call_args.args[0])
    def test_track_mode_keeps_deficit(self):
        self.assertEqual(dj_session.refill_policy({'brief':'jazz deep cuts'}, 3), {'mode':'tracks','remaining':5})

class AlbumResolutionTests(unittest.TestCase):
    def test_real_official_album_resolves_every_track_in_order(self):
        import json, pathlib
        import albums
        raw=json.loads((pathlib.Path(__file__).parent/'fixtures/album_in_between_dreams.json').read_text())
        album=albums.parse_album(raw,'MPREb_7ZOwMFpCLco')
        self.assertEqual(album['title'],'In Between Dreams')
        self.assertEqual(len(album['tracks']),14)
        self.assertEqual([t['number'] for t in album['tracks']],list(range(1,15)))
        self.assertEqual(album['tracks'][0]['title'],'Better Together')
        self.assertEqual(album['tracks'][-1]['title'],'Constellations')
        raw['musicShelfRenderer']['contents'][0]['musicResponsiveListItemRenderer']['navigationEndpoint']['watchEndpoint']['playlistId']='OLAK5uy_other'
        # Different edition hidden under another official endpoint must fail.
        with self.assertRaisesRegex(ValueError,'edition'):albums.parse_album(raw,'MPREb_7ZOwMFpCLco')
    def test_missing_track_rejected_not_partial_album(self):
        import json, pathlib, albums
        raw=json.loads((pathlib.Path(__file__).parent/'fixtures/album_in_between_dreams.json').read_text())
        shelf=next(albums.find(raw,'musicShelfRenderer'))
        shelf['contents'].pop()
        with self.assertRaisesRegex(ValueError,'complete'):albums.parse_album(raw,'MPREb_7ZOwMFpCLco')
    def test_atomic_reservation_rejects_whole_album_if_last_tune_reserved(self):
        import albums, discovery, pathlib, tempfile
        tracks=[{'videoId':f'{i:011d}','title':f'Tune {i}','artist':'Artist','library':False,'liked':False} for i in range(14)]
        with tempfile.TemporaryDirectory() as tmp:
            path=pathlib.Path(tmp)/'discovery.sqlite'
            discovery.reserve(path,tracks[-1]['videoId'],tracks[-1]['title'],'Artist')
            with self.assertRaises(ValueError):albums.reserve_album(path,tracks,[])
            self.assertEqual(len(discovery.recent(path)),1)
    def test_unknown_membership_rejects_before_any_reservation(self):
        import albums, pathlib,tempfile
        tracks=[{'videoId':f'{i:011d}','title':f'Tune {i}','artist':'Artist','library':False,'liked':False} for i in range(14)]
        tracks[-1]['liked']=None
        with tempfile.TemporaryDirectory() as tmp:
            path=pathlib.Path(tmp)/'discovery.sqlite'
            with self.assertRaisesRegex(ValueError,'membership'):albums.reserve_album(path,tracks,[])
            self.assertFalse(path.exists())

class AlbumEnqueueTests(QueuePrimitiveFixture):
    def setUp(self):
        super().setUp()
        import pathlib,tempfile,djctl
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=pathlib.Path(self.tmp.name)
        for module,name,value in [(dj_session,'ROOT',self.root),(dj_session,'STATE',self.root/'session.json'),(djctl,'ROOT',self.root)]:
            p=patch.object(module,name,value);p.start();self.addCleanup(p.stop)
        self.state={'active':True,'management_version':2,'generation':'g','queue_mode':'album','refill_mode':'album','refill_remaining':1}
        dj_session.save(self.state)
        self.tracks=[{'number':i+1,'videoId':f'{i:011d}','title':f'Tune {i}','artist':'Artist','library':False,'liked':False} for i in range(14)]
        self.album={'title':'Album','tracks':self.tracks}
        self.current=[{'videoId':'zzzzzzzzzzz','title':'Old song','artist':'Other','index':0,'selected':True}]
    def test_fourteen_track_album_spends_one_album_budget_and_confirms_complete_order(self):
        import djctl, json, discovery
        ids=[r['videoId'] for r in self.current]; requested=[t['videoId'] for t in self.tracks]
        def dispatch(argv,**kw):
            self.assertEqual(argv[2],'append-album');self.assertEqual(json.loads(argv[3]),requested)
            self.assertEqual(len(discovery.recent(self.root/'discovery.sqlite')),14)
            self.assertEqual(dj_session.load()['refill_remaining'],0)
            return json.dumps({'beforeIds':ids,'afterIds':ids+requested})
        with patch.dict(os.environ,{'BASIL_REFILL_GENERATION':'g'}), patch('albums.resolve_album',return_value=self.album), patch.object(djctl,'append_queue_snapshot',side_effect=[self.current,self.current+self.tracks]), patch.object(djctl,'api',return_value={}), patch.object(djctl,'live_status',return_value={'paused':False}), patch.object(dj_session,'upcoming_count',return_value=0),patch.object(dj_session,'album_due',return_value=True), patch('subprocess.check_output',side_effect=dispatch):
            result=djctl.enqueue_album('MPREb_fixture')
        self.assertTrue(result['confirmed']);self.assertEqual(result['afterIds'],ids+requested)
    def test_off_during_resolution_cancels_before_reservation_and_dispatch(self):
        import djctl
        def resolve(_, **kwargs):
            state=dj_session.load();state['active']=False;dj_session.save(state);return self.album
        with patch('albums.resolve_album',side_effect=resolve), patch.object(djctl,'api') as api, patch('subprocess.check_output') as dispatch:
            with self.assertRaisesRegex(ValueError,'authorization'):djctl.enqueue_album('MPREb_fixture')
        dispatch.assert_not_called();api.assert_not_called();self.assertFalse((self.root/'discovery.sqlite').exists())
    def test_pause_after_resolution_denies_whole_album(self):
        import djctl
        with patch('albums.resolve_album',return_value=self.album), patch.object(djctl,'append_queue_snapshot',return_value=self.current), patch.object(djctl,'api',return_value={}),patch.object(djctl,'live_status',return_value={'paused':True}),patch.object(dj_session,'upcoming_count',return_value=0),patch.object(dj_session,'album_due',return_value=True),patch('subprocess.check_output') as dispatch:
            with self.assertRaisesRegex(ValueError,'paused'):djctl.enqueue_album('MPREb_fixture')
        dispatch.assert_not_called();self.assertFalse((self.root/'discovery.sqlite').exists())
    def test_partial_renderer_success_is_failure_and_retains_all_reservations(self):
        import djctl,json,discovery
        with patch('albums.resolve_album',return_value=self.album),patch.object(djctl,'append_queue_snapshot',return_value=self.current),patch.object(djctl,'api',return_value={}),patch.object(djctl,'live_status',return_value={'paused':False}),patch.object(dj_session,'upcoming_count',return_value=0),patch.object(dj_session,'album_due',return_value=True),patch('subprocess.check_output',return_value=json.dumps({'beforeIds':['zzzzzzzzzzz'],'afterIds':['zzzzzzzzzzz','00000000000']})) as dispatch:
            with self.assertRaises(djctl.QueueReadbackError):djctl.enqueue_album('MPREb_fixture')
        self.assertEqual(dispatch.call_count,1);self.assertEqual(len(discovery.recent(self.root/'discovery.sqlite')),14)

if __name__=='__main__': unittest.main()
