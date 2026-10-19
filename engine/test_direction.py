"""Standing direction regressions; callers must isolate HOME/state before imports."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
from subprocess import run as run_python
from unittest.mock import Mock, patch

from queue_test_support import QueuePrimitiveFixture
import dj_session as dj
from test_management import queue


class DirectionTests(QueuePrimitiveFixture):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.root = pathlib.Path(directory)
        self.enterContext(patch.object(dj, 'ROOT', self.root))
        self.enterContext(patch.object(dj, 'STATE', self.root/'session.json'))
        self.services = self.enterContext(patch.object(dj.subprocess, 'run', return_value=Mock(returncode=0)))
        self.enterContext(patch.object(dj, 'require_queue_ready'))
        self.player = self.enterContext(patch.object(dj, 'api', side_effect=AssertionError('No player mutation/read expected')))

    def command(self, *args):
        with patch('sys.argv', ['dj_session.py', *args]):
            dj.main()

    def test_off_on_preserves_explicit_format_not_in_brief(self):
        self.command('start', '--brief', 'Beach folk today', '--queue-mode', 'album')
        self.command('stop')
        self.command('start')
        state = dj.load()
        self.assertEqual(state['brief'], 'Beach folk today')
        self.assertEqual(state['queue_mode'], 'album')
        self.assertEqual(state['refill_mode'], 'album')
        self.player.assert_not_called()

    def test_start_with_explicit_replacement_while_on_is_not_ignored(self):
        self.command('start', '--brief', 'Old jazz', '--queue-mode', 'album')
        old = dj.load()
        self.command('start', '--brief', 'Ambient today', '--queue-mode', 'tracks')
        state = dj.load()
        self.assertEqual(state['brief'], 'Ambient today')
        self.assertEqual(state['queue_mode'], 'tracks')
        self.assertNotEqual(state['generation'], old['generation'])
        self.assertTrue(dj.enabled(state))
        self.assertEqual(self.services.call_count, 1, 'Do not launch a second singleton')

    def test_direction_while_off_persists_and_explicit_format_replaces(self):
        dj.save({'active': False, 'brief': 'Old hits', 'queue_mode': 'tracks',
                 'discovery_filters': {'avoid_repeats': False}, 'custom': 'keep'})
        self.command('direction', '--brief', 'Full albums of beach folk today')
        first = dj.load()
        self.assertFalse(first['active'])
        self.assertEqual(first['queue_mode'], 'album')
        self.command('direction', '--brief', 'Gentle acoustic mood today')
        self.assertEqual(dj.load()['queue_mode'], 'album', 'Unspecified format is not a reset')
        self.command('direction', '--brief', 'Ambient track mix')
        self.assertEqual(dj.load()['queue_mode'], 'tracks')
        self.assertEqual(dj.load()['custom'], 'keep')
        self.assertEqual(dj.load()['discovery_filters'], {'avoid_repeats': False})
        self.services.assert_not_called()
        self.player.assert_not_called()

    def test_replacement_revokes_old_refill_and_worker_uses_latest_without_restart(self):
        dj.save({'active': True, 'management_version': 2, 'generation': 'old',
                 'brief': 'Old hits', 'queue_mode': 'tracks', 'refill_remaining': 7})
        old = dj.load()
        self.command('direction', '--brief', 'Full albums of beach folk today')
        self.assertFalse(dj.same_generation(old))
        self.assertEqual(dj.load()['refill_remaining'], 0)
        prompts = []
        checks = 0
        def api(method, path):
            nonlocal checks
            if path == 'song':
                checks += 1
                if checks == 1:
                    self.command('direction', '--brief', 'Full albums of ambient today')
                return {'videoId': '0'}
            return {'mode': 'NONE'} if path == 'repeat-mode' else queue(2)
        with patch.object(dj, 'api', side_effect=api), \
             patch.object(dj, 'live_status', return_value={'paused': False}), \
             patch.object(dj, 'queue_capabilities', return_value={'ready': True}), \
             patch.object(dj.subprocess, 'check_output', return_value=json.dumps({'autoplay': False})), \
             patch.object(dj, 'run_refill', side_effect=lambda prompt, state: prompts.append(prompt)), \
             patch.object(dj.time, 'sleep', side_effect=StopIteration):
            with self.assertRaises(StopIteration):
                dj.worker()
        self.assertEqual(len(prompts), 1)
        self.assertIn('Full albums of ambient today', prompts[0])
        self.assertIn('until explicitly replaced', prompts[0])
        self.assertNotIn('Old hits', prompts[0])
        self.services.assert_not_called()

    def test_restart_import_reads_saved_direction_not_defaults(self):
        self.command('start', '--brief', 'Full albums of folk today')
        # A fresh interpreter reads only isolated state. Status is local-only.
        result = run_python([sys.executable, dj.__file__, 'status'], cwd=self.root,
                            env=dict(os.environ, BASIL_STATE_DIR=str(self.root)),
                            capture_output=True, text=True, check=True)
        state = json.loads(result.stdout)
        self.assertEqual(state['brief'], 'Full albums of folk today')
        self.assertEqual(state['queue_mode'], 'album')
        self.assertTrue(dj.should_refill(state, {'videoId': '0', 'isPaused': False}, queue(2), now=10**12))

    def test_direction_drains_old_admission_and_is_idempotent(self):
        dj.save({'active': True, 'management_version': 2, 'generation': 'old',
                 'brief': 'Old mood', 'append_deadline_ms': 104000})
        with patch.object(dj.time, 'time', return_value=100), patch.object(dj.time, 'sleep') as sleep:
            self.command('direction', '--brief', 'Quiet folk today')
        sleep.assert_called_once_with(4.05)
        first = dj.load()
        with patch.object(dj, 'drain_append') as drain:
            self.command('direction', '--brief', 'Quiet folk today')
        self.assertEqual(dj.load()['generation'], first['generation'])
        drain.assert_not_called()
        with patch.dict(os.environ, {'BASIL_REFILL_GENERATION': first['generation']}):
            with self.assertRaisesRegex(ValueError, 'Background refill cannot change'):
                self.command('direction', '--brief', 'Generic hits')
        self.assertEqual(dj.load()['brief'], 'Quiet folk today')

    def test_direction_change_cancels_and_reaps_inflight_refill(self):
        dj.save({'active': True, 'management_version': 2, 'generation': 'old',
                 'brief': 'Old mood', 'refill_remaining': 4})
        old = dj.load()
        child = Mock(pid=98765, returncode=0)
        def wait(timeout):
            if timeout == 1:
                self.command('direction', '--brief', 'Full albums of ambient today')
                raise subprocess.TimeoutExpired('fixture-model', timeout)
        child.wait.side_effect = wait
        with patch.object(dj, 'api', side_effect=lambda method, path: {'videoId': '0'} if path == 'song' else queue(2)), \
             patch.object(dj, 'live_status', return_value={'paused': False}), \
             patch.object(dj.subprocess, 'Popen', return_value=child), \
             patch.object(dj.os, 'killpg') as kill:
            dj.run_refill('fixture boundary only; no model', old)
        kill.assert_called_once_with(child.pid, dj.signal.SIGKILL)
        self.assertEqual([call.kwargs['timeout'] for call in child.wait.call_args_list], [1, 10])
        self.assertEqual(dj.load()['brief'], 'Full albums of ambient today')
