"""Isolated HTTP integration tests; no live player/model mutations."""
import http.client
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('basil_server', Path(__file__).resolve().parents[1] / 'server.py')
assert SPEC is not None and SPEC.loader is not None
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)


def raw_queue(ids=('a', 'b', 'c'), current=0):
    return {'items': [{'playlistPanelVideoRenderer': {'videoId': v, 'selected': i == current,
        'title': {'runs': [{'text': v}]}, 'thumbnail': {'thumbnails': [{'url': 'https://img.example/' + v}]}}}
        for i, v in enumerate(ids)]}


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        web = self.root / 'web'
        web.mkdir()
        (web / 'index.html').write_text('<h1>Basil</h1>')
        (self.root / 'secret.json').write_text('secret')
        (web / 'leak.css').symlink_to(self.root / 'secret.json')
        self.app = server.Application(runtime=self.root / 'runtime', web=web, persona=self.root / 'persona.md')
        self.httpd = server.make_server(port=0, app=self.app)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.host = '127.0.0.1:' + str(self.httpd.server_port)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.httpd.server_port, timeout=5)
        defaults = {'Host': self.host}
        if method == 'POST':
            defaults.update({'X-Basil-Request': '1', 'Content-Type': 'application/json', 'Origin': 'http://' + self.host})
        defaults.update(headers or {})
        conn.request(method, path, json.dumps(body) if body is not None else None, defaults)
        response = conn.getresponse()
        data = response.read()
        result = response.status, data, dict(response.getheaders())
        conn.close()
        return result

    def test_health_without_external_dependencies_is_not_live_acceptance(self):
        with patch.object(server.djctl, 'api') as api, patch.object(server.djctl, 'live_status') as live:
            status, data, _ = self.request('GET', '/api/health')
            self.assertEqual(status, 200)
            health = json.loads(data)
            self.assertTrue(health['installed'])
            self.assertEqual(health['login'], 'unverified')
            self.assertEqual(health['live_acceptance'], 'not performed')
            self.assertEqual(health['release_mode'], 'experimental')
            self.assertFalse(health['automatic_dj_ready'])
            self.assertTrue(health['queue_mutation_ready'])
            self.assertTrue(health['automatic_refill_ready'])
            api.assert_not_called()
            live.assert_not_called()

    def test_discovery_settings_persist_independently_without_player_calls(self):
        path=self.app.runtime/'session.json'
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({'active':False,'brief':'full albums beach','exclude_library':True,'generation':'keep','volume':'keep'}))
        with patch.object(server.djctl,'api') as api:
            status,data,_=self.request('GET','/api/settings')
            self.assertEqual(status,200)
            self.assertEqual(json.loads(data)['discovery_filters'],{'avoid_repeats':False,'exclude_library':False})
            status,data,_=self.request('POST','/api/settings',{'avoid_repeats':True})
            self.assertEqual(status,200)
            self.assertEqual(json.loads(data)['discovery_filters'],{'avoid_repeats':True,'exclude_library':False})
            self.assertEqual(self.request('POST','/api/settings',{'exclude_library':'false'})[0],400)
            self.assertEqual(self.request('POST','/api/settings',{'active':True})[0],400)
            state=json.loads(path.read_text());state['queue_mode']='tracks';path.write_text(json.dumps(state))
            settings=json.loads(self.request('GET','/api/settings')[1])
            self.assertEqual(settings['discovery_filters'],{'avoid_repeats':True,'exclude_library':True})
            self.assertEqual(state['generation'],'keep');self.assertFalse(state['active'])
            api.assert_not_called()

    def test_host_and_static_security(self):
        self.assertEqual(self.request('GET', '/')[0], 200)
        for host in ['evil.test', 'localhost', 'localhost:1', '127.0.0.1.evil:' + str(self.httpd.server_port)]:
            self.assertEqual(self.request('GET', '/', headers={'Host': host})[0], 403)
        for path in ['/../secret.json', '/%2e%2e/secret.json', '/leak.css', '/server.py', '/%252e%252e/secret.json']:
            self.assertEqual(self.request('GET', path)[0], 404)

    def test_all_methods_validate_host(self):
        for method in ('OPTIONS', 'PUT', 'DELETE', 'PATCH'):
            self.assertEqual(self.request(method, '/api/control', headers={'Host': 'evil.test'})[0], 403)

    def test_csrf_json_and_bound(self):
        for headers in [{'X-Basil-Request': ''}, {'Origin': 'http://evil.test'}, {'Content-Type': 'text/plain'}]:
            self.assertIn(self.request('POST', '/api/control', {'action': 'play'}, headers)[0], (403, 415))
        self.assertEqual(self.request('POST', '/api/chat', {'message': 'a' * 2001})[0], 400)
        self.assertEqual(self.request('POST', '/api/chat', {'message': 'a' * 20000})[0], 413)
        self.assertEqual(self.request('POST', '/api/control', {'action': 'shell'})[0], 400)

    def test_state_cache_and_real_art(self):
        def api(method, path, payload=None):
            return {'state': 42, 'isMuted': False} if path == 'volume' else ({'videoId': 'a', 'imageSrc': 'https://img.example/a'} if path == 'song' else raw_queue())
        with patch.object(server.djctl, 'api', side_effect=api), patch.object(server.djctl, 'live_status', return_value={'paused': False}) as live, patch.object(server.dj_session, 'load', return_value={'active': True}), patch.object(self.app, 'worker_running', return_value=True):
            for _ in range(2):
                status, data, _ = self.request('GET', '/api/state')
                state = json.loads(data)
                self.assertEqual(status, 200)
                self.assertEqual(state['queue'][1]['imageSrc'], 'https://img.example/b')
                self.assertEqual(state['song']['imageSrc'], 'https://img.example/a')
            self.assertEqual(live.call_count, 1)

    def test_queue_stale_current_and_played_rejected(self):
        with patch.object(server.djctl, 'api', return_value=raw_queue(current=1)) as api:
            for body in [{'videoId': 'bad', 'index': 2}, {'videoId': 'b', 'index': 1}, {'videoId': 'a', 'index': 0}]:
                self.assertEqual(self.request('POST', '/api/queue/remove', body)[0], 409)
            self.assertTrue(all(call.args[0] == 'GET' for call in api.call_args_list))

    def test_remove_polls_once_mutation(self):
        reads = iter([raw_queue(), raw_queue(), raw_queue(('a', 'c'))])
        writes = []
        def api(method, path, payload=None):
            if method == 'GET':
                return next(reads)
            writes.append((method, path, payload))
        with patch.object(server.djctl, 'api', side_effect=api):
            status, data, _ = self.request('POST', '/api/queue/remove', {'videoId': 'b', 'index': 1})
        self.assertEqual(status, 200, data)
        self.assertEqual(writes, [('DELETE', 'queue/1', None)])
        self.assertEqual([r['videoId'] for r in json.loads(data)['queue']], ['a', 'c'])

    def test_move_verified_order(self):
        reads = iter([raw_queue(), raw_queue(), raw_queue(('a', 'c', 'b'))])
        writes = []
        def api(method, path, payload=None):
            if method == 'GET':
                return next(reads)
            writes.append((method, path, payload))
        with patch.object(server.djctl, 'api', side_effect=api):
            status, data, _ = self.request('POST', '/api/queue/move', {'videoId': 'c', 'index': 2, 'toIndex': 1})
        self.assertEqual(status, 200, data)
        self.assertEqual(writes, [('PATCH', 'queue/2', {'toIndex': 1})])
        self.assertEqual([r['videoId'] for r in json.loads(data)['queue']], ['a', 'c', 'b'])

    def test_failed_readback_is_not_success_or_retried(self):
        self.app.readback_timeout = 0.01
        with patch.object(server.djctl, 'api', return_value=raw_queue()) as api:
            self.assertEqual(self.request('POST', '/api/queue/remove', {'videoId': 'b', 'index': 1})[0], 504)
        self.assertEqual(sum(c.args[0] == 'DELETE' for c in api.call_args_list), 1)

    def test_chat_one_worker_and_persistence(self):
        entered, release = threading.Event(), threading.Event()
        def reply(prompt):
            self.assertIn('youtube-music-dj', prompt)
            entered.set()
            release.wait(3)
            return 'A real mocked boundary reply.'
        with patch.object(self.app, 'run_chat', side_effect=reply):
            self.assertEqual(self.request('POST', '/api/chat', {'message': 'Suggest jazz'})[0], 202)
            self.assertTrue(entered.wait(2))
            self.assertEqual(self.request('POST', '/api/chat', {'message': 'Again'})[0], 409)
            self.assertTrue(json.loads(self.request('GET', '/api/chat')[1])['busy'])
            release.set()
            self.app.chat_thread.join(3)
        history = json.loads(self.request('GET', '/api/chat')[1])
        self.assertFalse(history['busy'])
        self.assertEqual([m['role'] for m in history['messages']], ['user', 'assistant'])
        self.assertTrue((self.app.runtime / 'web-chat.json').exists())
        restored = server.Application(runtime=self.app.runtime, web=self.app.web, persona=self.app.persona)
        self.assertEqual(restored.chat_snapshot()['messages'], history['messages'])

    def test_chat_policy_keeps_direction_ongoing_and_requires_saved_readback(self):
        self.app.messages = [{'role': 'user', 'content': 'Gentle full albums today'},
                             {'role': 'assistant', 'content': 'Saved'},
                             {'role': 'user', 'content': 'What is playing?'}]
        prompt = self.app.chat_prompt()
        for required in ('ongoing until explicitly replaced', 'even when worded "today"',
                         'dj_session direction --brief', '--queue-mode album|tracks',
                         'mirror preferences.md, and read back both',
                         'not an implicit reset of saved musical direction',
                         'never restore generic hits'):
            self.assertIn(required, prompt)

    def test_controls_fixed_helpers_and_verified_outcomes(self):
        with patch.object(self.app, 'helper') as helper, patch.object(server.djctl, 'live_status', return_value={'paused': True}):
            self.assertEqual(self.request('POST', '/api/control', {'action': 'pause'})[0], 200)
            helper.assert_called_once_with('djctl.py', 'pause')
        self.app.readback_timeout = 0.01
        with patch.object(self.app, 'helper'), patch.object(server.djctl, 'live_status', return_value={'paused': True}):
            self.assertEqual(self.request('POST', '/api/control', {'action': 'play'})[0], 504)
        with patch.object(self.app, 'helper') as helper, patch.object(server.djctl, 'live_status', return_value={'paused': True}), patch.object(self.app, 'worker_running', return_value=False), patch.object(server.dj_session, 'load', return_value={'active': False}):
            self.assertEqual(self.request('POST', '/api/control', {'action': 'stop'})[0], 200)
            self.assertEqual([c.args for c in helper.call_args_list], [('dj_session.py', 'stop'), ('djctl.py', 'pause')])
        with patch.object(self.app, 'helper'), patch.object(server.djctl, 'api', side_effect=[{'videoId': 'a'}, {'videoId': 'a'}, {'videoId': 'b'}]):
            self.app.readback_timeout = 1
            self.assertEqual(self.request('POST', '/api/control', {'action': 'next'})[0], 200)

    def test_management_toggle_separate_from_transport(self):
        for action, on in (('dj_on', True), ('dj_off', False)):
            with patch.object(self.app, 'helper') as helper, \
                 patch.object(self.app, 'worker_running', return_value=on), \
                 patch.object(server.dj_session, 'load', return_value={'active': on, 'management_version': 2}), \
                 patch.object(server.djctl, 'api', side_effect=lambda method, path: {'videoId': 'a'} if path == 'song' else raw_queue()), \
                 patch.object(server.djctl, 'live_status', return_value={'paused': True}), \
                 patch.object(server.djctl, 'append_requested') as append:
                status, data, _ = self.request('POST', '/api/control', {'action': action})
                self.assertEqual(status, 200, data)
                helper.assert_called_once_with('dj_session.py', 'start' if on else 'stop')
                append.assert_not_called()

    def test_management_on_unknown_queue_is_actionable_and_no_helper_runs(self):
        with patch.object(server.djctl, 'api', return_value={}), \
             patch.object(server.djctl, 'live_status', return_value={'paused': True}), \
             patch.object(self.app, 'helper') as helper:
            status, data, _ = self.request('POST', '/api/control', {'action': 'dj_on'})
            self.assertEqual(status, 409, data)
            helper.assert_not_called()

    def test_legacy_status_does_not_expose_expiry_or_on(self):
        with patch.object(server.djctl, 'api', side_effect=lambda method, path: {'state': 4, 'isMuted': False} if path == 'volume' else ({'videoId': 'a'} if path == 'song' else raw_queue())), \
             patch.object(server.djctl, 'live_status', return_value={'paused': True}), \
             patch.object(server.dj_session, 'load', return_value={'active': True, 'expires': 9999999999}), \
             patch.object(self.app, 'worker_running', return_value=False):
            status, data, _ = self.request('GET', '/api/state')
            self.assertEqual(status, 200)
            session = json.loads(data)['session']
            self.assertFalse(session['active'])
            self.assertNotIn('expires', session)

    def test_helper_argv_has_no_shell(self):
        with patch.object(server.subprocess, 'run') as run:
            self.app.helper('djctl.py', 'pause')
        self.assertEqual(run.call_args.args[0], [server.sys.executable, str(server.ENGINE / 'djctl.py'), 'pause'])
        self.assertNotIn('shell', run.call_args.kwargs)

    def test_queue_validation_and_busy(self):
        for body in [{'videoId': 'b', 'index': True}, {'videoId': 'b', 'index': -1}, {'videoId': 'b', 'index': '1'}]:
            self.assertEqual(self.request('POST', '/api/queue/remove', body)[0], 400)
        with patch.object(server.djctl, 'api', return_value=raw_queue()) as api:
            self.assertEqual(self.request('POST', '/api/queue/move', {'videoId': 'b', 'index': 1, 'toIndex': 0})[0], 409)
            self.assertFalse(any(c.args[0] != 'GET' for c in api.call_args_list))
        with self.app.mutation_lock:
            self.assertEqual(self.request('POST', '/api/control', {'action': 'play'})[0], 409)
            self.assertEqual(self.request('POST', '/api/queue/remove', {'videoId': 'b', 'index': 1})[0], 409)

    def test_chat_subprocess_argv_and_temporary_file_cleanup(self):
        self.app.runtime.mkdir()
        def launch(argv, **kwargs):
            self.assertEqual(argv[:11], ['hermes', '-p', 'dj', 'chat', '--oneshot', '-Q', '--max-turns', '40', '--run-budget', '300', '--query-file'])
            self.assertEqual(Path(argv[-1]).read_text(), 'Untrusted $(no shell)')
            self.assertTrue(kwargs['start_new_session'])
            self.assertNotIn('shell', kwargs)
            self.assertEqual(kwargs['cwd'], self.app.runtime)
            kwargs['stdout'].write(b'Actual provider output')
            from unittest.mock import Mock
            return Mock(returncode=0)
        with patch.object(server.subprocess, 'Popen', side_effect=launch):
            self.assertEqual(self.app.run_chat('Untrusted $(no shell)'), 'Actual provider output')
        self.assertEqual(list(self.app.runtime.glob('.basil-query-*')), [])

    def test_queue_recovery_has_room_to_finish_and_report(self):
        self.app.runtime.mkdir()
        def launch(argv, **kwargs):
            turns = int(argv[argv.index('--max-turns') + 1])
            budget = int(argv[argv.index('--run-budget') + 1])
            self.assertGreaterEqual(turns, 40, '18 turns exhausted during actual queue recovery')
            self.assertGreaterEqual(budget, 300)
            self.assertGreater(self.app.chat_timeout, budget)
            kwargs['stdout'].write(b'Verified recovery reply')
            from unittest.mock import Mock
            return Mock(returncode=0)
        with patch.object(server.subprocess, 'Popen', side_effect=launch):
            self.assertEqual(self.app.run_chat('Recover the interrupted classic rock request'), 'Verified recovery reply')

    def test_chat_timeout_kills_process_group_and_no_fake_reply(self):
        from unittest.mock import Mock
        self.app.runtime.mkdir()
        process = Mock(pid=98765, returncode=-9)
        process.wait.side_effect = [server.subprocess.TimeoutExpired('hermes', 180), 0]
        with patch.object(server.subprocess, 'Popen', return_value=process), patch.object(server.os, 'killpg') as kill:
            with self.assertRaises(server.APIError) as caught:
                self.app.run_chat('DJ request')
            self.assertEqual(caught.exception.status, 504)
            kill.assert_called_once_with(98765, server.signal.SIGKILL)
        self.assertEqual(list(self.app.runtime.glob('.basil-query-*')), [])
        with patch.object(self.app, 'run_chat', side_effect=server.APIError(502, 'Provider failed')):
            self.assertEqual(self.request('POST', '/api/chat', {'message': 'Jazz'})[0], 202)
            self.app.chat_thread.join(2)
        state = self.app.chat_snapshot()
        self.assertEqual(state['error'], 'Provider failed')
        self.assertEqual([m['role'] for m in state['messages']], ['user'])

    def test_pause_and_stop_cancel_running_chat_before_helpers(self):
        import subprocess
        import sys
        real_popen = subprocess.Popen
        for action in ('pause', 'stop', 'dj_off'):
            with self.subTest(action=action):
                launched = threading.Event()
                processes = []
                def launch(argv, **kwargs):
                    process = real_popen([sys.executable, '-c', 'import time; time.sleep(60)'], **kwargs)
                    processes.append(process)
                    launched.set()
                    return process
                def helper(name, command):
                    self.assertIsNotNone(processes[0].poll(), 'helper ran before chat exited')
                    self.assertEqual(self.request('POST', '/api/chat', {'message': 'race'})[0], 409)
                    self.assertEqual(self.request('POST', '/api/control', {'action': 'play'})[0], 409)
                    self.assertEqual(self.request('POST', '/api/queue/remove', {'index': 1, 'videoId': 'b'})[0], 409)
                with patch.object(server.subprocess, 'Popen', side_effect=launch), patch.object(self.app, 'helper', side_effect=helper) as helpers, patch.object(server.djctl, 'live_status', return_value={'paused': True}) as live, patch.object(self.app, 'worker_running', return_value=False), patch.object(server.dj_session, 'load', return_value={'active': False}):
                    try:
                        self.assertEqual(self.request('POST', '/api/chat', {'message': 'Jazz'})[0], 202)
                        self.assertTrue(launched.wait(2))
                        status, data, _ = self.request('POST', '/api/control', {'action': action})
                        self.assertEqual(status, 200, data)
                        self.assertEqual(live.called, action != 'dj_off')
                        self.assertEqual(helpers.call_count, 2 if action == 'stop' else 1)
                        self.app.chat_thread.join(2)
                        self.assertFalse(self.app.chat_thread.is_alive())
                        self.assertIn('cancel', self.app.chat_snapshot()['error'].lower())
                    finally:
                        for process in processes:
                            if process.poll() is None:
                                server.os.killpg(process.pid, server.signal.SIGKILL)
                            process.wait(timeout=2)
                        self.app.chat_thread.join(2)

    def test_priority_cancellation_prevents_pending_launch(self):
        entered, release = threading.Event(), threading.Event()
        def prompt():
            entered.set()
            release.wait(3)
            return 'pending request'
        responses = []
        control = None
        with patch.object(self.app, 'chat_prompt', side_effect=prompt), patch.object(server.subprocess, 'Popen') as launch, patch.object(self.app, 'helper') as helper, patch.object(server.djctl, 'live_status', return_value={'paused': True}):
            try:
                self.assertEqual(self.request('POST', '/api/chat', {'message': 'Jazz'})[0], 202)
                self.assertTrue(entered.wait(2))
                control = threading.Thread(target=lambda: responses.append(self.request('POST', '/api/control', {'action': 'pause'})[0]))
                control.start()
                # Wait for the cancellation signal, not a scheduling-dependent sleep.
                cancelled = getattr(self.app, 'chat_cancel', threading.Event())
                self.assertTrue(cancelled.wait(1), 'pause did not cancel pending chat')
                self.assertEqual(self.request('POST', '/api/chat', {'message': 'race'})[0], 409)
            finally:
                release.set()
                self.app.chat_thread.join(3)
                if control is not None:
                    control.join(3)
            self.assertEqual(responses, [200])
            launch.assert_not_called()
            helper.assert_called_once_with('djctl.py', 'pause')

    def test_unconfirmed_chat_kill_fails_closed(self):
        from unittest.mock import Mock
        for failure in (PermissionError('denied'), server.subprocess.TimeoutExpired('chat', 10)):
            with self.subTest(failure=type(failure).__name__):
                app = server.Application(runtime=self.root / 'quarantine', web=self.app.web)
                app.busy = True
                app.mutation_lock.acquire()
                app.chat_process = Mock(pid=98765)
                if isinstance(failure, PermissionError):
                    kill_effect = failure
                else:
                    kill_effect = None
                    app.chat_process.wait.side_effect = failure
                with patch.object(server.os, 'killpg', side_effect=kill_effect), patch.object(app, 'helper') as helper:
                    with self.assertRaises(server.APIError) as caught:
                        app.control({'action': 'stop'})
                    self.assertEqual(caught.exception.status, 503)
                    helper.assert_not_called()
                    # Even after worker cleanup releases its lock, uncertainty
                    # must not admit any further mutation or model process.
                    app.busy = False
                    app.mutation_lock.release()
                    for operation in (lambda: app.start_chat({'message': 'Jazz'}),
                                      lambda: app.control({'action': 'play'}),
                                      lambda: app.control({'action': 'pause'}),
                                      lambda: app.edit_queue('remove', {'index': 1, 'videoId': 'b'})):
                        with self.assertRaises(server.APIError) as blocked:
                            operation()
                        self.assertEqual(blocked.exception.status, 503)
                    helper.assert_not_called()

    def test_chat_cannot_enter_cancellation_lock_handoff_gap(self):
        entered, release = threading.Event(), threading.Event()
        handoff, resume = threading.Event(), threading.Event()
        real_lock = self.app.mutation_lock
        class HandoffLock:
            def acquire(inner, *args, **kwargs):
                if 'timeout' in kwargs:
                    handoff.set()
                    resume.wait(3)
                return real_lock.acquire(*args, **kwargs)
            def release(inner):
                real_lock.release()
        self.app.mutation_lock = HandoffLock()
        def prompt():
            entered.set()
            release.wait(3)
            return 'pending'
        result = []
        control = None
        with patch.object(self.app, 'chat_prompt', side_effect=prompt), patch.object(server.subprocess, 'Popen') as launch, patch.object(self.app, 'helper'), patch.object(server.djctl, 'live_status', return_value={'paused': True}):
            try:
                self.assertEqual(self.request('POST', '/api/chat', {'message': 'Jazz'})[0], 202)
                self.assertTrue(entered.wait(2))
                control = threading.Thread(target=lambda: result.append(self.request('POST', '/api/control', {'action': 'pause'})[0]))
                control.start()
                self.assertTrue(handoff.wait(2))
                release.set()
                self.app.chat_thread.join(2)
                self.assertFalse(self.app.busy)
                self.assertFalse(real_lock.locked())
                self.assertEqual(self.request('POST', '/api/chat', {'message': 'race'})[0], 409)
                self.assertEqual(self.request('POST', '/api/control', {'action': 'next'})[0], 409)
                self.assertEqual(self.request('POST', '/api/queue/remove', {'index': 1, 'videoId': 'b'})[0], 409)
            finally:
                release.set()
                resume.set()
                self.app.chat_thread.join(3)
                if control is not None:
                    control.join(3)
            self.assertEqual(result, [200])
            launch.assert_not_called()

    def test_backend_errors_are_redacted_not_fake_state(self):
        with patch.object(server.djctl, 'api', side_effect=RuntimeError('secret token value')):
            status, data, _ = self.request('GET', '/api/state')
        self.assertEqual(status, 502)
        self.assertNotIn(b'secret', data)
        self.assertFalse(json.loads(data)['ok'])

    def test_history_and_volume_routes(self):
        with patch.object(server.djctl, 'api', return_value={'state': 42, 'isMuted': False}) as api:
            status, data, _ = self.request('POST', '/api/volume', {'volume': 42})
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(data)['volume'], 42)
            self.assertEqual(api.call_args_list[0].args, ('POST', 'volume', {'volume': 42}))
            self.assertEqual(self.request('POST', '/api/volume', {'volume': True})[0], 400)
            self.assertEqual(self.request('POST', '/api/volume', {'volume': 42}, headers={'X-Basil-Request': '0'})[0], 403)
        status, data, _ = self.request('GET', '/api/history')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data)['entries'], [])
        self.assertIn('not full YouTube', json.loads(data)['coverage'])

    def test_concurrent_state_misses_share_cdp_read(self):
        def api(method, path, payload=None):
            return {'state': 42, 'isMuted': False} if path == 'volume' else ({'videoId': 'a'} if path == 'song' else raw_queue())
        with patch.object(server.djctl, 'api', side_effect=api), patch.object(server.djctl, 'live_status', return_value={'paused': False}) as live, patch.object(server.dj_session, 'load', return_value={'active': False}), patch.object(self.app, 'worker_running', return_value=False):
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=6) as pool:
                results = list(pool.map(lambda _: self.request('GET', '/api/state')[0], range(6)))
            self.assertEqual(results, [200] * 6)
            self.assertEqual(live.call_count, 1)


if __name__ == '__main__':
    unittest.main()
