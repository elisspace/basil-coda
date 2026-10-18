"""Portable entrypoint boundaries: synthetic HOME/config only; no player I/O."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import djctl
import dj_session

ROOT = Path(__file__).resolve().parents[1]


class PortableBoundaryTests(unittest.TestCase):
    def probe(self, config='', overrides=None):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            cfg = home/'basil.toml'
            cfg.write_text(config)
            env = {k: v for k, v in os.environ.items() if not k.startswith(('BASIL_', 'HERMES_', 'PYTHONPATH'))}
            env.update(HOME=str(home), TMPDIR=str(home), BASIL_CONFIG=str(cfg))
            env.update(overrides or {})
            code = '''import socket,ssl,sys,json
socket.socket=lambda *a,**k: (_ for _ in ()).throw(AssertionError('network forbidden'))
sys.path.insert(0,sys.argv[1])
import djctl,dj_session
print(json.dumps({'root':str(djctl.ROOT),'base':djctl.BASE,'unit':dj_session.UNIT}))
'''
            result = subprocess.run([sys.executable, '-c', code, str(ROOT/'engine')], env=env, cwd=home, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout), home

    def test_standalone_defaults_external_state(self):
        result, home = self.probe()
        self.assertEqual(result['root'], str(home/'.local/share/basil-coda/state'))

    def test_standalone_toml_before_binding_and_env_precedence(self):
        result, _ = self.probe('[basil]\nstate_dir="/fixture/state"\nrest_url="http://127.0.0.1:32101"\nworker_unit="fixture-worker"\n')
        self.assertEqual(result, {'root':'/fixture/state', 'base':'http://127.0.0.1:32101', 'unit':'fixture-worker'})
        result, _ = self.probe('[basil]\nstate_dir="/fixture/state"\n', {'BASIL_STATE_DIR':'/fixture/env'})
        self.assertEqual(result['root'], '/fixture/env')

    def test_client_id_is_one_safe_url_component(self):
        for value in ['../escape', 'id?query', 'id#fragment', 'id/path', 'id%2fpath', '', None, ['id']]:
            with self.subTest(value=value), patch('pathlib.Path.read_text', return_value=json.dumps({'client_id':value})), patch.object(djctl, 'request') as request:
                with self.assertRaisesRegex(ValueError, 'client'):
                    djctl.api('GET', 'song')
                request.assert_not_called()

    def test_safe_client_ids_are_supported_without_inspecting_credentials(self):
        for client in ['fixture', 'basil-coda_client-01', '5d4b2995-73b8-4c4e-931e-7adaf0660000']:
            with self.subTest(client=client), patch('pathlib.Path.read_text', return_value=json.dumps({'client_id':client})), patch.object(djctl, 'request', side_effect=[{'accessToken':'fixture-token'},{}]) as request:
                djctl.api('GET','song')
                self.assertEqual(request.call_args_list[0].args, ('POST','/auth/'+client))

    def test_worker_argv_propagates_resolved_nonsecret_config(self):
        argv = dj_session.worker_command()
        self.assertIn(sys.executable, argv)
        self.assertNotIn('/usr/bin/python3', argv[:argv.index(sys.executable)])
        self.assertIn('--unit='+dj_session.CONFIG.worker_unit, argv)
        for key,value in vars(dj_session.CONFIG).items():
            self.assertIn('--setenv=BASIL_'+key.upper()+'='+str(value), argv)
        self.assertIn('--setenv=HERMES_HOME='+str(dj_session.CONFIG.hermes_home), argv)
        self.assertFalse(any('TOKEN' in arg or 'CLIENT_ID' in arg for arg in argv))

    def test_worker_clears_ambient_toml_and_uses_canonical_names(self):
        from dataclasses import replace
        config = replace(dj_session.CONFIG, hermes_bin='/fixture/bin/hermes', hermes_profile='portable_dj', worker_unit='portable-worker')
        with patch.object(dj_session, 'CONFIG', config), patch.object(dj_session, 'UNIT', config.worker_unit), patch.dict(os.environ, {'BASIL_CONFIG':'/missing/manager-config.toml','BASIL_HERMES':'obsolete','BASIL_PROFILE':'obsolete'}):
            argv = dj_session.worker_command()
        self.assertIn('--setenv=BASIL_CONFIG=', argv)
        self.assertIn('--setenv=BASIL_HERMES_BIN=/fixture/bin/hermes', argv)
        self.assertIn('--setenv=BASIL_HERMES_PROFILE=portable_dj', argv)
        self.assertIn('--unit=portable-worker', argv)
        self.assertNotIn('--setenv=BASIL_HERMES=obsolete', argv)
        self.assertNotIn('--setenv=BASIL_PROFILE=obsolete', argv)

    def test_rest_transport_disables_proxy_and_redirects(self):
        with patch('urllib.request.build_opener', wraps=__import__('urllib.request',fromlist=['build_opener']).build_opener) as build, patch('urllib.request.OpenerDirector.open', side_effect=RuntimeError('fixture transport')):
            with self.assertRaisesRegex(RuntimeError, 'fixture transport'):
                djctl.request('GET', '/api/v1/song', token='fixture-token')
            handlers = build.call_args.args
            self.assertTrue(any(isinstance(h, __import__('urllib.request',fromlist=['ProxyHandler']).ProxyHandler) and h.proxies == {} for h in handlers))
            redirect = next(h for h in handlers if isinstance(h, __import__('urllib.request',fromlist=['HTTPRedirectHandler']).HTTPRedirectHandler))
            with self.assertRaises(__import__('urllib.error',fromlist=['HTTPError']).HTTPError):
                redirect.redirect_request(None,None,302,'redirect',{},'http://example.invalid/')

    def test_request_rejects_nonlocal_base_and_unsafe_path_before_transport(self):
        for base in ['http://localhost:32101','http://127.0.0.1:32101@evil.invalid','http://127.0.0.1:32101/path','http://127.0.0.1:32101?x=1','https://127.0.0.1:32101']:
            with self.subTest(base=base), patch.object(djctl,'BASE',base), patch('urllib.request.build_opener') as opener:
                with self.assertRaises(ValueError): djctl.request('GET','/api/v1/song',token='fixture-token')
                opener.assert_not_called()
        for path in ['//evil.invalid/', '/api/v1/song?token=x', '/auth/../song', '/api/v1/song#fragment']:
            with self.subTest(path=path), patch('urllib.request.build_opener') as opener:
                with self.assertRaises(ValueError): djctl.request('GET',path)
                opener.assert_not_called()
