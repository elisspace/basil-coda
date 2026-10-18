"""Portable bootstrap tests: subprocesses use empty HOME; no live integrations."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]


class PortableTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(('BASIL_', 'HERMES_'))}
        self.env.pop('PYTHONPATH', None)
        self.env.update(HOME=str(self.root), TMPDIR=str(self.root))
        self.clean_env = dict(self.env)
        self.env['PYTHONPATH'] = str(REPO)  # only import probes, never installed bootstrap

    def run_python(self, code, **env):
        return subprocess.run([sys.executable, '-c', code], env={**self.env, **env}, cwd=self.root,
                              text=True, capture_output=True, check=False)

    def test_default_paths_are_independent_of_original_account(self):
        result = self.run_python('import portable_config as p; c=p.load(); print(c.state_dir); print(c.profile_dir)')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [str(self.root / '.local/share/basil-coda/state'),
                                                     str(self.root / '.hermes/profiles/dj')])
        self.assertEqual(list(self.root.iterdir()), [])  # loading configuration is read-only

    def test_nonloopback_endpoints_rejected_before_network(self):
        for key, value in [('BASIL_REST_URL', 'http://example.com:26538'),
                           ('BASIL_CDP_URL', 'http://0.0.0.0:26539'),
                           ('BASIL_REST_URL', 'http://127.0.0.1:1/path'),
                           ('BASIL_REST_URL', 'http://user:secret@127.0.0.1:1')]:
            result = self.run_python('import portable_config as p; p.load()', **{key: value})
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('loopback', result.stderr)

    def test_installer_empty_home_and_readonly_doctor(self):
        prefix = self.root / 'prefix with spaces $cash%value'
        result = subprocess.run([sys.executable, str(REPO/'scripts/setup.py'), 'install', '--prefix', str(prefix)],
                                env=self.clean_env, cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((prefix/'share/basil-coda/server.py').is_file())
        self.assertFalse((self.root/'.hermes').exists())
        self.assertFalse((self.root/'.config/systemd').exists())
        self.assertFalse((prefix/'share/basil-coda/integrations').exists())
        service = (prefix/'share/basil-coda.service').read_text()
        self.assertIn('prefix with spaces $cash%%value/share/basil-coda\n', service)
        self.assertIn('prefix with spaces $cash%%value/bin/basil-coda" serve', service)
        self.assertIn('ExecStart=:', service)  # systemd suppresses environment substitution
        import shutil
        if shutil.which('systemd-analyze'):
            verify = subprocess.run(['systemd-analyze', 'verify', '--man=no', str(prefix/'share/basil-coda.service')],
                                    cwd=self.root, env=self.clean_env, capture_output=True, text=True)
            self.assertEqual(verify.returncode, 0, verify.stderr)
        before = sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))
        doctor = subprocess.run([str(prefix/'bin/basil-coda'), 'doctor'], env=self.clean_env, cwd=self.root, capture_output=True, text=True)
        self.assertEqual(doctor.returncode, 0, doctor.stderr)
        report = json.loads(doctor.stdout)
        self.assertTrue(report['installed'])
        self.assertFalse(report['configured'])
        self.assertEqual(report['login'], 'unverified')
        self.assertEqual(report['live_acceptance'], 'not performed')
        self.assertEqual(before, sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*')))
        again = subprocess.run([sys.executable, str(REPO/'scripts/setup.py'), 'install', '--prefix', str(prefix)],
                               env=self.clean_env, cwd=self.root, capture_output=True, text=True)
        self.assertNotEqual(again.returncode, 0)  # no overwrite of an existing install/config

    def test_backslash_prefix_is_rejected_before_installation(self):
        prefix = self.root / 'prefix\\q'
        result = subprocess.run([sys.executable, str(REPO/'scripts/setup.py'), 'install', '--prefix', str(prefix)],
                                env=self.clean_env, cwd=self.root, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unsupported', result.stderr.lower())
        self.assertFalse(prefix.exists())

    def test_runtime_payload_excludes_private_shaped_fake_files(self):
        import shutil
        staged = self.root/'source'
        shutil.copytree(REPO, staged, ignore=shutil.ignore_patterns('__pycache__'))
        private = ['engine/auth.json', 'engine/private.sqlite-wal', 'web/cookies.json', 'deploy/config.toml']
        for name in private:
            (staged/name).write_text('SYNTHETIC TEST MARKER, NOT A CREDENTIAL')
        prefix = self.root/'install'
        result = subprocess.run([sys.executable, str(staged/'scripts/setup.py'), 'install', '--prefix', str(prefix)],
                                cwd=self.root, env=self.clean_env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        installed = prefix/'share/basil-coda'
        for name in private:
            self.assertFalse((installed/name).exists(), name)
        for name in ['hermes', 'integrations', 'tests', 'engine/fixtures']:
            self.assertFalse((installed/name).exists(), name)
        self.assertTrue((installed/'THIRD_PARTY_NOTICES.md').is_file())

    def test_config_file_env_precedence_and_explicit_fake_player_argv(self):
        config = self.root/'public.toml'
        fake = self.root/'fake player; not a shell'
        fake.write_text('#!' + sys.executable + '\nimport json, sys\nprint(json.dumps(sys.argv[1:]))\n')
        fake.chmod(0o755)
        data = self.root/'dedicated player'
        config.write_text('[basil]\nhermes_profile = "curator"\nplayer_executable = '+json.dumps(str(fake))+
                          '\nplayer_data_dir = '+json.dumps(str(data))+'\ncdp_url = "http://127.0.0.1:22345"\n')
        probe = self.run_python('import portable_config as p; c=p.load(); print(c.hermes_profile)',
                                BASIL_CONFIG=str(config), BASIL_HERMES_PROFILE='override')
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertEqual(probe.stdout.strip(), 'override')
        result = subprocess.run([sys.executable, '-B', str(REPO/'basil.py'), 'player'],
                                cwd=self.root, env={**self.clean_env, 'BASIL_CONFIG': str(config)},
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), ['--user-data-dir='+str(data),
            '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=22345'])
        self.assertFalse(data.exists())  # fake executable only; no real player data created
        invalid = subprocess.run([sys.executable, '-B', str(REPO/'basil.py'), 'player', '--remote-debugging-address=0.0.0.0'],
                                 cwd=self.root, env={**self.clean_env, 'BASIL_CONFIG': str(config)},
                                 capture_output=True, text=True)
        self.assertNotEqual(invalid.returncode, 0)

    def test_clean_installed_http_and_fake_endpoint_probe(self):
        # These fake HTTP dependencies prove reachability plumbing, NOT login.
        import http.client
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import socket
        import threading
        import time
        calls = []

        class FakeDependency(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                calls.append(self.path)
                body = b'[]' if self.path == '/json/list' else b'{"fixture": "FAKE PEAR schema, no auth or player"}'
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        fake = ThreadingHTTPServer(('127.0.0.1', 0), FakeDependency)
        worker = threading.Thread(target=fake.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(fake.server_close)
        self.addCleanup(fake.shutdown)
        prefix = self.root/'isolated prefix'
        subprocess.run([sys.executable, str(REPO/'scripts/setup.py'), 'install', '--prefix', str(prefix)],
                       env=self.clean_env, cwd=self.root, check=True, capture_output=True)
        env = {**self.clean_env, 'BASIL_REST_URL': f'http://127.0.0.1:{fake.server_port}',
               'BASIL_CDP_URL': f'http://127.0.0.1:{fake.server_port}'}
        doctor = subprocess.run([str(prefix/'bin/basil-coda'), 'doctor', '--probe'],
                                env=env, cwd=self.root, capture_output=True, text=True, check=True)
        health = json.loads(doctor.stdout)
        self.assertEqual(health['read_only_probes'], {'pear_schema': 'reachable', 'cdp_targets': 'reachable'})
        self.assertFalse(health['configured'])
        self.assertEqual(health['login'], 'unverified')
        self.assertEqual(calls, ['/doc', '/json/list'])
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        process = subprocess.Popen([str(prefix/'bin/basil-coda'), 'serve', '--port', str(port)],
                                   env=env, cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            def request(path, host=None):
                connection = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
                connection.request('GET', path, headers={'Host': host or f'127.0.0.1:{port}'})
                response = connection.getresponse()
                result = response.status, response.read()
                connection.close()
                return result
            deadline = time.monotonic()+10
            while True:
                try:
                    status, body = request('/api/health')
                    break
                except OSError:
                    if process.poll() is not None or time.monotonic()>deadline:
                        self.fail('Installed server failed startup')
                    time.sleep(.05)
            self.assertEqual(status, 200)
            self.assertFalse(json.loads(body)['configured'])
            self.assertIn(b'Basil', request('/')[1])
            self.assertEqual(request('/', 'evil.example')[0], 403)
            status, body = request('/api/state')
            self.assertEqual(status, 502)
            self.assertIn(b'doctor', body)
            self.assertNotIn(b'Traceback', body)
            self.assertEqual(calls, ['/doc', '/json/list'])  # serving did not contact fake player
            self.assertFalse((self.root/'.hermes').exists())
            self.assertFalse((self.root/'.local/share/basil-coda/state/player-client.json').exists())
        finally:
            process.terminate()
            process.communicate(timeout=10)

    def test_server_configuration_is_applied_before_engine_import(self):
        custom = self.root / 'state elsewhere'
        result = self.run_python('import server; print(server.RUNTIME); print(server.djctl.ROOT); print(server.SKILL)',
                                 BASIL_STATE_DIR=str(custom), BASIL_HERMES_PROFILE='curator',
                                 BASIL_HERMES_HOME=str(self.root/'agent'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [str(custom), str(custom),
            str(self.root/'agent/profiles/curator/skills/youtube-music-dj/SKILL.md')])


if __name__ == '__main__':
    unittest.main()
