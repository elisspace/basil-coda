"""Discovery controls: isolated ledger and real admission regressions."""
import os
assert os.environ.get('BASIL_STATE_DIR')
import pathlib, tempfile, unittest, sqlite3
from unittest.mock import patch
from queue_test_support import QueuePrimitiveFixture
import dj_session, albums, discovery

class DiscoveryFilterTests(QueuePrimitiveFixture):
    def test_mode_defaults_ignore_obsolete_album_library_flag(self):
        self.assertEqual(dj_session.discovery_filters({'queue_mode':'album','exclude_library':True}),
                         {'avoid_repeats':False,'exclude_library':False})
        self.assertEqual(dj_session.discovery_filters({'queue_mode':'tracks'}),
                         {'avoid_repeats':True,'exclude_library':True})
    def test_independent_explicit_overrides_survive_mode_change(self):
        state={'queue_mode':'album','discovery_filters':{'avoid_repeats':True,'exclude_library':False}}
        self.assertEqual(dj_session.discovery_filters(state),state['discovery_filters'])
        state['queue_mode']='tracks'
        self.assertEqual(dj_session.discovery_filters(state),state['discovery_filters'])
    def test_repeat_album_keeps_prior_reservations_and_records_occurrences(self):
        tracks=[{'videoId':f'{i:011d}','title':f'Tune {i}','artist':'Artist','library':True,'liked':None} for i in range(2)]
        current=[{**tracks[0],'selected':False},{'videoId':'zzzzzzzzzzz','selected':True}]
        with tempfile.TemporaryDirectory() as tmp:
            path=pathlib.Path(tmp)/'ledger.sqlite'
            discovery.reserve(path,tracks[0]['videoId'],tracks[0]['title'],'Artist')
            db=sqlite3.connect(path)
            before=db.execute('SELECT * FROM discoveries').fetchall()
            event_count=db.execute('SELECT COUNT(*) FROM reservation_events').fetchone()[0]
            db.close()
            albums.reserve_album(path,tracks,current,avoid_repeats=False,exclude_library=False)
            db=sqlite3.connect(path)
            self.assertEqual(db.execute('SELECT * FROM discoveries WHERE video_id=?',(tracks[0]['videoId'],)).fetchall(),before)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM reservation_events').fetchone()[0],event_count+2)
            with self.assertRaisesRegex(ValueError,'retry'):
                albums.reserve_album(path,tracks,current,avoid_repeats=False,exclude_library=False)
            db.close()
    def test_upcoming_duplicates_remain_denied_when_repeats_off(self):
        tracks=[{'videoId':f'{i:011d}','title':f'Tune {i}','artist':'Artist'} for i in range(2)]
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'queue'):
                albums.reserve_album(pathlib.Path(tmp)/'ledger.sqlite',tracks,[{'videoId':'zzzzzzzzzzz','selected':True},tracks[0]],avoid_repeats=False,exclude_library=False)
    def test_filters_cli_persists_overrides_and_drains_old_renderer(self):
        import sys,json,io,contextlib
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp)
            with patch.object(dj_session,'ROOT',root),patch.object(dj_session,'STATE',root/'session.json'):
                dj_session.save({'active':False,'queue_mode':'album','generation':'keep','append_deadline_ms':104000})
                def drain(seconds):
                    self.assertAlmostEqual(seconds,4.05)
                    self.assertNotIn('discovery_filters',dj_session.load())
                with patch.object(sys,'argv',['dj_session.py','filters','--avoid-repeats','on']),patch.object(dj_session.time,'time',return_value=100),patch.object(dj_session.time,'sleep',side_effect=drain) as wait,contextlib.redirect_stdout(io.StringIO()) as output:
                    dj_session.main()
                wait.assert_called_once()
                self.assertEqual(json.loads(output.getvalue()),{'avoid_repeats':True,'exclude_library':False})
                state=dj_session.load();self.assertFalse(state['active']);self.assertEqual(state['generation'],'keep')
                state['queue_mode']='tracks';dj_session.save(state)
                self.assertEqual(dj_session.discovery_filters(dj_session.load()),{'avoid_repeats':True,'exclude_library':True})

    def test_album_filters_are_independent_and_atomic(self):
        for repeat in (False,True):
            for library in (False,True):
                with self.subTest(repeat=repeat,library=library),tempfile.TemporaryDirectory() as tmp:
                    path=pathlib.Path(tmp)/'ledger.sqlite'
                    tracks=[{'videoId':f'{i:011d}','title':f'Tune {i}','artist':'Artist','library':True,'liked':None} for i in range(2)]
                    discovery.reserve(path,tracks[0]['videoId'],tracks[0]['title'],'Artist')
                    current=[{'videoId':'zzzzzzzzzzz','selected':True}]
                    if repeat or library:
                        with self.assertRaises(ValueError):albums.reserve_album(path,tracks,current,avoid_repeats=repeat,exclude_library=library)
                        db=sqlite3.connect(path);self.assertEqual(db.execute('SELECT COUNT(*) FROM discoveries').fetchone()[0],1);db.close()
                    else:
                        albums.reserve_album(path,tracks,current,avoid_repeats=False,exclude_library=False)
    def test_strict_track_rejects_queued_cover_before_reservation(self):
        import djctl,sys
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp)
            with patch.object(dj_session,'ROOT',root),patch.object(dj_session,'STATE',root/'session.json'),patch.object(djctl,'ROOT',root):
                dj_session.save({'active':True,'management_version':2,'generation':'g'})
                with patch('search_metadata.cached_track',return_value=('Known Tune (Remastered)','Other',0,0)),patch.object(djctl,'append_queue_snapshot',return_value=[{'videoId':'bbbbbbbbbbb','title':'Known Tune','selected':True,'index':0}]),patch.object(djctl,'append_requested') as append,patch.object(sys,'argv',['djctl.py','enqueue','aaaaaaaaaaa']):
                    with self.assertRaises(SystemExit):djctl.main()
                    append.assert_not_called()
                    self.assertFalse((root/'discovery.sqlite').exists())

    def test_track_replay_uses_real_cli_and_preserves_duplicate_order(self):
        import djctl,sys,json,io,contextlib
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);state={'active':True,'management_version':2,'generation':'g','discovery_filters':{'avoid_repeats':False,'exclude_library':False}}
            current=[{'videoId':'aaaaaaaaaaa','index':0,'selected':False},{'videoId':'bbbbbbbbbbb','index':1,'selected':True}]
            with patch.object(dj_session,'ROOT',root),patch.object(dj_session,'STATE',root/'session.json'),patch.object(djctl,'ROOT',root):
                dj_session.save(state)
                discovery.reserve(root/'discovery.sqlite','aaaaaaaaaaa','Played','Artist')
                with patch('search_metadata.cached_track',return_value=('Played','Artist',True,None)),patch.object(djctl,'append_queue_snapshot',side_effect=[current,current+[{'videoId':'aaaaaaaaaaa'}]]),patch.object(djctl,'append_requested',return_value={}) as append,patch.object(sys,'argv',['djctl.py','enqueue','aaaaaaaaaaa']),contextlib.redirect_stdout(io.StringIO()) as output:
                    djctl.main()
                self.assertEqual([r['videoId'] for r in json.loads(output.getvalue())],['aaaaaaaaaaa','bbbbbbbbbbb','aaaaaaaaaaa'])
                self.assertEqual(append.call_args.kwargs['replay_index'],1)
    def test_filter_change_cancels_album_resolution_before_reservations(self):
        import djctl
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp)
            with patch.object(dj_session,'ROOT',root),patch.object(dj_session,'STATE',root/'session.json'),patch.object(djctl,'ROOT',root):
                dj_session.save({'active':True,'management_version':2,'queue_mode':'album','generation':'g'})
                def resolve(_,screen):
                    self.assertFalse(screen)
                    state=dj_session.load();state['discovery_filters']={'avoid_repeats':True};dj_session.save(state)
                    return {'tracks':[]}
                with patch('albums.resolve_album',side_effect=resolve),patch.object(djctl,'api') as api:
                    with self.assertRaisesRegex(ValueError,'authorization'):djctl.enqueue_album('MPREb_fixture')
                    api.assert_not_called()
                    self.assertFalse((root/'discovery.sqlite').exists())
    def test_pending_replay_album_uses_position_not_repeated_video_identity(self):
        state={'queue_mode':'album','last_album':{'videoIds':['a','b'],'start_index':2}}
        queue={'items':[{'playlistPanelVideoRenderer':{'videoId':v,'selected':i==0}} for i,v in enumerate(['a','z','a','b'])]}
        self.assertFalse(dj_session.album_due(state,{'videoId':'a'},queue))
    def test_background_cannot_change_filters_and_policy_change_denies_admission(self):
        import djctl,sys,json
        state={'active':True,'management_version':2,'generation':'g','queue_mode':'album'}
        with patch.dict(os.environ,{'BASIL_REFILL_GENERATION':'g','BASIL_REFILL_FILTERS':json.dumps({'avoid_repeats':True,'exclude_library':True})}),patch.object(sys,'argv',['dj_session.py','filters','--avoid-repeats','off']):
            with self.assertRaisesRegex(ValueError,'cannot change'):dj_session.main()
            with patch.object(dj_session,'load',return_value=state),patch.object(djctl,'api') as api:
                with self.assertRaisesRegex(ValueError,'controls changed'):djctl.admit_refill('g')
                api.assert_not_called()

    def test_strict_filter_sees_bypassed_alternate_recording(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=pathlib.Path(tmp)/'ledger.sqlite'
            discovery.reserve(path,'aaaaaaaaaaa','Tune','Artist')
            discovery.reserve(path,'bbbbbbbbbbb','Tune','Other',avoid_repeats=False)
            with self.assertRaises(ValueError):
                discovery.reserve(path,'bbbbbbbbbbb','Renamed','Other')

if __name__=='__main__':unittest.main()
