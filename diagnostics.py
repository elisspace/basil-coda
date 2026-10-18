"""Read-only installation diagnostics; never authenticate or start a dependency."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
from portable_config import load


def executable(value):
    return bool(value and shutil.which(value))


def node_supported():
    try:
        version = subprocess.run(['node', '--version'], capture_output=True, text=True, timeout=5, check=False)
        return version.returncode == 0 and int(version.stdout.strip().lstrip('v').split('.')[0]) >= 22
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def report(config=None, probe=False):
    c = config or load()
    checks = {'python_3_11': sys.version_info >= (3, 11), 'node_22': node_supported(),
              'hermes_executable': executable(c.hermes_bin),
              'hermes_profile_config': (c.profile_dir/'config.yaml').is_file(),
              'dj_skill': c.skill.is_file(), 'player_executable': executable(c.player_executable),
              'player_client_file': (c.state_dir/'player-client.json').is_file()}
    result = {'ok': True, 'installed': (Path(__file__).parent/'server.py').is_file(),
              'configured': all(checks.values()), 'checks': checks,
              'login': 'unverified', 'live_acceptance': 'not performed',
              'release_mode': 'experimental', 'queue_mutation_ready': True,
              'automatic_refill_ready': True, 'automatic_dj_ready': False,
              'queue_note': 'Automatic DJ and queue editing are enabled experimentally; YouTube may override changes. See docs/queue-release.md.',
              'note': 'File/executable presence is not valid login, tool restriction, safe queue operation or audible playback. '
                      'Install/configure Pear and Hermes separately; explicitly launch and sign in. '
                      'No account, model, playback or service actions are performed by doctor.'}
    if probe:
        result['read_only_probes'] = {}
        # No proxy environment, redirects, authentication or credential-file reads.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        for name, url in [('pear_schema', c.rest_url+'/doc'), ('cdp_targets', c.cdp_url+'/json/list')]:
            try:
                with opener.open(url, timeout=2) as response:
                    response.read(1024)
                    result['read_only_probes'][name] = 'reachable' if response.status == 200 else 'unavailable'
            except Exception:
                result['read_only_probes'][name] = 'unavailable'
        result['note'] += ' Reachability is not authentication, a dedicated target, login or queue capability acceptance.'
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe', action='store_true', help='GET loopback schema/CDP only; no auth, model or mutations')
    args = parser.parse_args()
    print(json.dumps(report(probe=args.probe), indent=2))


if __name__ == '__main__':
    main()
