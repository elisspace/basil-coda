"""Experimental controls use original guarded paths, never live I/O."""
import os
assert os.environ.get('BASIL_STATE_DIR')
import contextlib
import io
import json
import unittest
from unittest.mock import patch
import djctl
import dj_session as session


class ReleaseSafetyTests(unittest.TestCase):
    def test_raw_api_denies_account_and_native_append_writes_before_auth(self):
        for method, path in [('POST', 'queue'), ('POST', 'shuffle'), ('POST', 'like'),
                             ('POST', 'playlist/edit'), ('DELETE', 'library'),
                             ('PATCH', 'queue/not-an-index')]:
            with self.subTest(path=path), patch.object(djctl, 'request') as request:
                with self.assertRaisesRegex(ValueError, 'Unsupported'):
                    djctl.api(method, path, {})
                request.assert_not_called()

    def test_supported_rest_controls_use_original_paths(self):
        operations = [('POST', p) for p in ('pause', 'play', 'next', 'previous', 'volume', 'search')]
        operations += [('DELETE', 'queue'), ('PATCH', 'queue'),
                       ('DELETE', 'queue/1'), ('PATCH', 'queue/2')]
        for method, path in operations:
            with self.subTest(path=path), patch.object(djctl, 'request', side_effect=[{'accessToken': 'fixture'}, {'ok': True}]) as request, \
                 patch('pathlib.Path.read_text', return_value='{"client_id":"fixture"}'):
                self.assertEqual(djctl.api(method, path, {}), {'ok': True})
                self.assertEqual(request.call_count, 2)

    def test_experimental_capabilities_are_not_a_durable_adapter_claim(self):
        for live in ({}, {'serverQueuesEnabled': True}, {'serverQueuesEnabled': False}):
            result = djctl.queue_capabilities(live)
            self.assertEqual(result['release_mode'], 'experimental')
            for key in ('ready', 'queue_edit', 'exact_append', 'refill', 'queue_mutation_ready', 'automatic_refill_ready', 'transport'):
                self.assertTrue(result[key], key)
            self.assertFalse(result['server_takeover'])
            self.assertIn('not guaranteed', result['reason'])
            self.assertEqual(result['server_queues_enabled'], live.get('serverQueuesEnabled'))
            self.assertEqual(djctl.require_queue_ready(live), result)

    def test_status_exposes_enabled_controls_but_preserves_off(self):
        for active in (True, False):
            with patch.object(session, 'load', return_value={'active': active, 'management_version': 2}):
                result = session.status()
            self.assertTrue(result['queue_capabilities']['ready'])
            self.assertEqual(result['effective_active'], active)
            self.assertEqual(result['refill_ready'], active)

    def test_background_transport_and_destructive_controls_stay_denied(self):
        for command in ('clear-queue', 'select', 'play', 'next', 'volume'):
            with self.subTest(command=command), patch.dict(os.environ, {'BASIL_REFILL_GENERATION': 'g'}), \
                 patch('sys.argv', ['djctl.py', command, '0']), patch.object(djctl, '_main') as effect:
                with self.assertRaisesRegex(ValueError, 'Background DJ'):
                    djctl.main()
                effect.assert_not_called()

    def test_background_search_and_append_require_current_generation(self):
        for command in ('search', 'enqueue', 'album-search', 'album-resolve', 'album-enqueue'):
            with self.subTest(command=command), patch.dict(os.environ, {'BASIL_REFILL_GENERATION': 'old'}), \
                 patch('sys.argv', ['djctl.py', command, 'aaaaaaaaaaa']), \
                 patch.object(session, 'load', return_value={'active': True, 'management_version': 2, 'generation': 'new'}), \
                 patch.object(session, 'control_lock'), patch.object(djctl, '_main') as effect, patch.object(djctl, 'api') as api:
                with self.assertRaisesRegex(ValueError, 'authorization changed'):
                    djctl.main()
                effect.assert_not_called()
                api.assert_not_called()

    def test_foreground_queue_controls_require_on_and_reach_existing_paths(self):
        for command in ('clear-queue', 'select', 'enqueue'):
            for active in (False, True):
                with self.subTest(command=command, active=active), patch.dict(os.environ, {}, clear=True), \
                     patch('sys.argv', ['djctl.py', command, '0']), patch.object(session, 'control_lock'), \
                     patch.object(session, 'load', return_value={'active': active, 'management_version': 2}), \
                     patch.object(djctl, '_main') as effect:
                    if active:
                        djctl.main()
                        effect.assert_called_once()
                    else:
                        with self.assertRaisesRegex(ValueError, 'OFF'):
                            djctl.main()
                        effect.assert_not_called()

    def test_foreground_clear_and_select_execute_and_read_back(self):
        queue = {'items': [{'playlistPanelVideoRenderer': {'videoId': 'aaaaaaaaaaa', 'selected': True}}]}
        cases = [
            ('clear-queue', ['0'], [None, {'items': []}], ('DELETE', 'queue')),
            ('select', ['0'], [queue, None, {'videoId': 'aaaaaaaaaaa'}], ('PATCH', 'queue', {'index': 0})),
        ]
        for command, args, responses, write in cases:
            with self.subTest(command=command), patch.dict(os.environ, {}, clear=True), \
                 patch('sys.argv', ['djctl.py', command, *args]), patch.object(session, 'control_lock'), \
                 patch.object(session, 'load', return_value={'active': True, 'management_version': 2}), \
                 patch.object(djctl, 'api', side_effect=responses) as api, contextlib.redirect_stdout(io.StringIO()):
                djctl.main()
                api.assert_any_call(*write)
                self.assertEqual(api.call_args.args[0], 'GET')

    def test_capabilities_cli_offline_is_read_only_and_experimental(self):
        with patch('sys.argv', ['djctl.py', 'capabilities']), patch.object(djctl, 'live_status', side_effect=OSError('offline')), \
             patch.object(djctl, 'api') as api, patch.object(session, 'save') as save, contextlib.redirect_stdout(io.StringIO()) as output:
            djctl.main()
        result = json.loads(output.getvalue())
        self.assertTrue(result['ready'])
        self.assertEqual(result['release_mode'], 'experimental')
        api.assert_not_called()
        save.assert_not_called()

    def test_start_restores_portable_worker_without_player_mutation(self):
        saved = []
        with patch('sys.argv', ['dj_session.py', 'start', '--brief', 'fixture']), patch.object(session, 'control_lock'), \
             patch.object(session, 'load', return_value={'active': False}), patch.object(session, 'save', side_effect=lambda s: saved.append(s.copy())), \
             patch.object(session, 'live_status') as live, patch.object(session.subprocess, 'run') as service, contextlib.redirect_stdout(io.StringIO()):
            session.main()
        live.assert_not_called()
        service.assert_called_once_with(session.worker_command(), check=True)
        self.assertTrue(saved[-1]['active'])
        self.assertEqual(saved[-1]['management_version'], 2)


if __name__ == '__main__':
    unittest.main()
