"""Real Chromium smoke test; entirely local mock API, never contacts a player.
Run: python3 tests/test_frontend_browser.py
For visual inspection: python3 tests/test_frontend_browser.py --serve-only
"""
import functools
import http.server
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]


class Fixture(http.server.SimpleHTTPRequestHandler):
    volume = 42
    posts = []
    history_mode = 'full'
    state_mode = 'full'
    management_on = False
    filters = {'avoid_repeats':False,'exclude_library':False}

    def log_message(self, format, *args):
        pass

    def send_json(self, value):
        data = json.dumps(value).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == '/api/state':
            if Fixture.state_mode == 'offline':
                return self.send_json({'ok': False, 'error': 'Mock disconnected'})
            return self.send_json({'ok': True, 'queue_capabilities': {'refill': True, 'queue_edit': True}, 'song': {'title': 'Tezeta', 'artist': 'Mulatu Astatke'}, 'live': {'paused': True, 'currentTime': 20, 'duration': 240}, 'volume': {'volume': Fixture.volume}, 'queue': [], 'session': {'active': Fixture.management_on, 'queue_mode':'album','effective_discovery_filters':Fixture.filters}, 'worker_running': Fixture.management_on})
        if self.path == '/api/chat':
            return self.send_json({'ok': True, 'messages': [], 'busy': False})
        if self.path == '/api/history':
            if Fixture.history_mode == 'error':
                return self.send_json({'ok': False, 'error': 'Mock ledger unavailable'})
            entries = [] if Fixture.history_mode == 'empty' else [{'id': str(i), 'videoId': 'fixture', 'title': 'Déjà Vu' if i % 2 else '<script>literal</script>', 'artist': 'Beyoncé', 'timestamp': 1700000000 + i * 3600, 'status': 'played' if i % 2 else 'queued', 'source': 'mock'} for i in range(5001)]
            return self.send_json({'ok': True, 'entries': entries, 'coverage': 'Isolated fixture: observed starts and legacy reservations.'})
        if self.path == '/__fixture':
            return self.send_json({'posts': Fixture.posts, 'volume': Fixture.volume})
        if self.path == '/browser-checks.js':
            content = (ROOT / 'tests' / 'frontend_browser_checks.js').read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/javascript')
            self.end_headers()
            self.wfile.write(content)
            return
        if self.path == '/test':
            content = (ROOT / 'web' / 'index.html').read_text().replace('</head>', '<script src="/browser-checks.js" defer></script></head>')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(content.encode())
            return
        return super().do_GET()

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path == '/__fixture':
            Fixture.history_mode = body.get('history', Fixture.history_mode)
            Fixture.state_mode = body.get('state', Fixture.state_mode)
            if 'volume' in body:
                Fixture.volume = body['volume']
            return self.send_json({'ok': True})
        if self.path not in ['/api/volume', '/api/control', '/api/chat','/api/settings']:
            self.send_error(404)
            return
        if self.headers.get('X-Basil-Request') != '1':
            self.send_error(403)
            return
        Fixture.posts.append({'path': self.path, 'body': body})
        if self.path == '/api/settings':
            Fixture.filters.update(body)
        if self.path == '/api/volume':
            Fixture.volume = body['volume']
        if self.path == '/api/control' and body.get('action') in ('dj_on', 'dj_off'):
            Fixture.management_on = body['action'] == 'dj_on'
        self.send_json({'ok': True})


def main():
    handler = functools.partial(Fixture, directory=str(ROOT / 'web'))
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    url = f'http://127.0.0.1:{server.server_port}'
    if '--serve-only' in sys.argv:
        print(url, flush=True)
        server.serve_forever()
        return
    browser = shutil.which('chromium') or shutil.which('google-chrome')
    if not browser:
        raise SystemExit('Chromium not installed; browser verification NOT run')
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix='basil-browser-test-') as profile:
            result = subprocess.run([browser, '--headless', '--disable-gpu', '--no-sandbox', '--disable-background-networking', '--disable-dev-shm-usage', f'--user-data-dir={profile}', '--virtual-time-budget=20000', '--dump-dom', url + '/test'], capture_output=True, text=True, timeout=60)
        marker = '<pre id="browser-test-result">'
        report = result.stdout.split(marker)[-1].split('</pre>')[0] if marker in result.stdout else 'No test report: ' + result.stderr[-3000:]
        print(report)
        if not report.startswith('PASS:') or result.returncode:
            raise SystemExit(1)
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
