"""ON/OFF regressions. All player/model boundaries are isolated."""
import json
import pathlib
import tempfile
import unittest
from queue_test_support import QueuePrimitiveFixture
from unittest.mock import patch, Mock
import dj_session as dj


def queue(n, selected=0):
    return {'items': [{'playlistPanelVideoRenderer': {'videoId': str(i), 'selected': i == selected}}
                      for i in range(n)]}


ON = {'active': True, 'management_version': 2, 'generation': 'test', 'brief': 'Hits 60s–00s; 12–20% Vietnamese'}


class ManagementTests(QueuePrimitiveFixture):
    def test_on_without_expiry_refills_four_upcoming_not_five(self):
        song = {'videoId': '1', 'isPaused': False}
        self.assertTrue(dj.should_refill(ON, song, queue(6, 1), 100))
        self.assertFalse(dj.should_refill(ON, song, queue(7, 1), 100))

    def test_legacy_active_never_arms_and_unknown_queue_fails_closed(self):
        song = {'videoId': '0', 'isPaused': False}
        for state in ({'active': True}, {'active': True, 'expires': 9999999999}, dict(ON, active=False)):
            self.assertFalse(dj.should_refill(state, song, queue(2), 100))
        for q in ({}, {'items': [{}]}, queue(2, -1), {'items': queue(2)['items'] + [{}]}):
            self.assertFalse(dj.should_refill(ON, song, q, 100))
        self.assertFalse(dj.should_refill(ON, dict(song, isPaused=True), queue(2), 100))

    def test_worker_full_queue_and_pause_make_only_local_reads(self):
        for paused, n in ((False, 6), (True, 2)):
            with tempfile.TemporaryDirectory() as tmp, patch.object(dj, 'ROOT', pathlib.Path(tmp)), \
                 patch.object(dj, 'load', return_value=dict(ON)), \
                 patch.object(dj, 'save'), \
                 patch.object(dj, 'api', side_effect=lambda method, path: {'videoId': '0'} if path == 'song' else queue(n)), \
                 patch.object(dj, 'live_status', return_value={'paused': paused}), \
                 patch.object(dj, 'run_refill') as refill, \
                 patch.object(dj.time, 'sleep', side_effect=StopIteration) as sleep:
                with self.assertRaises(StopIteration): dj.worker()
                refill.assert_not_called()
                sleep.assert_called_once_with(300)

    def test_worker_deficit_and_next_attempt_are_bounded(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(dj, 'ROOT', pathlib.Path(tmp)), \
             patch.object(dj, 'load', return_value=dict(ON)), patch.object(dj, 'save'), \
             patch.object(dj, 'api', side_effect=lambda method, path: {'videoId': '0'} if path == 'song' else ({'mode': 'NONE'} if path == 'repeat-mode' else queue(5))), \
             patch.object(dj, 'live_status', return_value={'paused': False}), \
             patch.object(dj.subprocess, 'check_output', return_value=json.dumps({'autoplay': False})), \
             patch.object(dj, 'run_refill') as refill, \
             patch.object(dj.time, 'sleep', side_effect=StopIteration) as sleep:
            with self.assertRaises(StopIteration): dj.worker()
            prompt = refill.call_args.args[0]
            self.assertIn('at most 4 tracks', prompt)
            self.assertIn('8 upcoming', prompt)
            sleep.assert_called_once_with(300)

    def test_background_append_denied_after_off_pause_target_or_new_generation(self):
        import djctl
        import os
        for state, paused, n in ((dict(ON, active=False), False, 2), (ON, True, 2),
                                 (ON, False, 9), (dict(ON, generation='new'), False, 2)):
            with tempfile.TemporaryDirectory() as tmp, patch.object(djctl, 'ROOT', pathlib.Path(tmp)), \
                 patch.object(dj, 'load', return_value=dict(state, expires=float('inf'))), \
                 patch.object(djctl, 'wait_for', return_value=[]), \
                 patch.dict(os.environ, {'BASIL_REFILL_GENERATION': 'test'}), \
                 patch.object(djctl, 'live_status', return_value={'paused': paused}), \
                 patch.object(djctl, 'api', side_effect=lambda method, path: {'videoId': '0'} if path == 'song' else queue(n)), \
                 patch('search_metadata.cached_track', return_value=('Title', 'Artist', 0, 0)), \
                 patch.object(djctl, 'append_requested') as append, patch('discovery.reserve') as reserve, \
                 patch('sys.argv', ['djctl.py', 'enqueue', '5ycyIkcX7zU']):
                with self.assertRaises((SystemExit, ValueError)): djctl.main()
                reserve.assert_not_called()
                append.assert_not_called()

    def test_final_append_rereads_pause_and_keeps_committed_reservation(self):
        import djctl
        import os
        import sqlite3
        with tempfile.TemporaryDirectory() as tmp, patch.object(djctl, 'ROOT', pathlib.Path(tmp)), \
             patch.object(dj, 'load', return_value=dict(ON, refill_remaining=1)), \
             patch.dict(os.environ, {'BASIL_REFILL_GENERATION': 'test'}), \
             patch.object(djctl, 'live_status', side_effect=[{'paused':False}, {'paused':True}]), \
             patch.object(djctl, 'api', side_effect=lambda method, path: {'videoId': '0'} if path == 'song' else queue(2)), \
             patch('search_metadata.cached_track', return_value=('Title', 'Artist', 0, 0)), \
             patch.object(djctl, 'append_requested') as append, \
             patch('sys.argv', ['djctl.py', 'enqueue', '5ycyIkcX7zU']):
            with self.assertRaises(djctl.QueueReadbackError): djctl.main()
            append.assert_not_called()
            import contextlib
            with contextlib.closing(sqlite3.connect(pathlib.Path(tmp)/'discovery.sqlite')) as db:
                self.assertEqual(db.execute('SELECT video_id FROM discoveries').fetchall(), [('5ycyIkcX7zU',)])

    def test_attempt_budget_denies_extra_tracks_even_as_queue_consumes(self):
        import djctl
        with patch.object(dj, 'load', return_value=dict(ON, refill_remaining=0)), \
             patch.object(djctl, 'live_status', return_value={'paused':False}), \
             patch.object(djctl, 'api', side_effect=lambda method, path: {'videoId':'0'} if path=='song' else queue(2)):
            with self.assertRaisesRegex(ValueError, 'budget exhausted'): djctl.admit_refill('test')

    def test_only_one_worker_can_own_lock(self):
        import fcntl
        with tempfile.TemporaryDirectory() as tmp, patch.object(dj, 'ROOT', pathlib.Path(tmp)), \
             patch.object(dj, 'load') as load:
            with (pathlib.Path(tmp)/'worker.lock').open('w') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaises(BlockingIOError): dj.worker()
            load.assert_not_called()

    def test_refill_failures_wait_300_then_stop_with_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(dj, 'ROOT', pathlib.Path(tmp)), \
             patch.object(dj, 'STATE', pathlib.Path(tmp)/'session.json'), \
             patch.object(dj, 'api', side_effect=lambda method, path: {'videoId':'0'} if path=='song' else ({'mode':'NONE'} if path=='repeat-mode' else queue(2))), \
             patch.object(dj, 'live_status', return_value={'paused':False}), \
             patch.object(dj.subprocess, 'check_output', return_value=json.dumps({'autoplay':False})), \
             patch.object(dj, 'run_refill', side_effect=RuntimeError('Fixture model failure')) as refill, \
             patch.object(dj.time, 'sleep') as sleep:
            dj.save(dict(ON))
            dj.worker()
            self.assertEqual(refill.call_count, 3)
            self.assertEqual([c.args for c in sleep.call_args_list], [(300,), (300,)])
            self.assertFalse(dj.enabled(dj.load()))
            self.assertIn('Fixture model failure', dj.load()['error'])

    def test_refill_launch_rereads_pause_and_watermark(self):
        for paused, n in ((True, 2), (False, 6)):
            with tempfile.TemporaryDirectory() as tmp, patch.object(dj, 'ROOT', pathlib.Path(tmp)), \
                 patch.object(dj, 'load', return_value=dict(ON)), \
                 patch.object(dj, 'api', side_effect=lambda method, path: {'videoId':'0'} if path=='song' else queue(n)), \
                 patch.object(dj, 'live_status', return_value={'paused':paused}), \
                 patch.object(dj.subprocess, 'Popen', return_value=Mock(pid=98765, returncode=0)) as launch, \
                 patch.object(dj.os, 'killpg'):
                dj.run_refill('Do not invoke AI if queue filled or playback paused during preparation', ON)
                self.assertEqual(launch.call_count, 0)

    def test_owned_refill_child_is_killed_and_reaped_on_off(self):
        import subprocess
        import sys
        real_popen = subprocess.Popen
        children = []
        def launch(argv, **kwargs):
            self.assertEqual(argv[argv.index('--max-turns')+1], '40')
            self.assertEqual(argv[argv.index('--run-budget')+1], '300')
            self.assertEqual(kwargs['env']['BASIL_REFILL_GENERATION'], 'test')
            self.assertTrue(kwargs['start_new_session'])
            child = real_popen([sys.executable, '-c', 'import time; time.sleep(60)'], **kwargs)
            children.append(child)
            return child
        for cause in ('off', 'pause'):
            states = [dict(ON), dict(ON, active=cause != 'off')]
            live = [{'paused':False}, {'paused':cause == 'pause'}]
            with tempfile.TemporaryDirectory() as tmp, patch.object(dj, 'ROOT', pathlib.Path(tmp)), \
                 patch.object(dj, 'load', side_effect=states), \
                 patch.object(dj, 'api', side_effect=lambda method, path: {'videoId':'0'} if path=='song' else queue(2)), \
                 patch.object(dj, 'live_status', side_effect=live), \
                 patch.object(dj.subprocess, 'Popen', side_effect=launch):
                dj.run_refill('isolated fixture, not a model request', ON)
        self.assertEqual(len(children), 2)
        for child in children:
            self.assertIsNotNone(child.poll())
            self.assertEqual(child.returncode, -9)

    def test_start_is_idempotent_and_stop_does_not_touch_player(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(dj, 'ROOT', pathlib.Path(tmp)), \
             patch.object(dj, 'STATE', pathlib.Path(tmp)/'session.json'), \
             patch.object(dj.subprocess, 'run', return_value=Mock(returncode=0)) as run, patch.object(dj, 'api') as api:
            with patch('sys.argv', ['dj_session.py', 'start', '--brief', 'Hits']): dj.main()
            first = dj.load()
            self.assertTrue(dj.enabled(first))
            self.assertNotIn('expires', first)
            with patch('sys.argv', ['dj_session.py', 'start']): dj.main()
            self.assertEqual(dj.load()['generation'], first['generation'])
            self.assertEqual(run.call_count, 1)
            for _ in range(2):
                with patch('sys.argv', ['dj_session.py', 'stop']): dj.main()
            self.assertFalse(dj.enabled(dj.load()))
            api.assert_not_called()


if __name__ == '__main__': unittest.main()
