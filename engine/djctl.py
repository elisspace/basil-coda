#!/usr/bin/env python3
"""Narrow local Pear Desktop control. Never exposes authentication values."""
import argparse
import json
import pathlib
import sys
import urllib.request
import urllib.error

# Mutable state and authentication are deliberately outside the source tree.
import os
import re
from portable_runtime import CONFIG
ROOT = CONFIG.state_dir
SOURCE = pathlib.Path(__file__).resolve().parent
BASE = CONFIG.rest_url


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url if req else '', code,
                                     'Player redirect refused', headers, fp)

class QueueReadbackError(ValueError):
    """Safe queue diagnostic, containing no server/authentication details."""


def request(method, path, payload=None, token=None):
    # Validate literal authority without URL-parser normalization of odd hosts.
    if not isinstance(BASE, str) or not re.fullmatch(r'http://127\.0\.0\.1:[0-9]{1,5}', BASE) or not 1 <= int(BASE.rsplit(':', 1)[1]) <= 65535:
        raise ValueError('Invalid loopback player endpoint')
    if not isinstance(path, str) or not re.fullmatch(r'/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+', path):
        raise ValueError('Invalid player request path')
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    # Never consult HTTP_PROXY or forward a bearer token through a redirect.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(req, timeout=15) as response:
        body = response.read()
        return json.loads(body) if body else None

def queue_capabilities(live=None):
    """Read-only snapshot contract, never an authorization token or repair."""
    live = live if isinstance(live, dict) else {}
    # These are supported experimental operations, not a live health probe or a
    # claim that server-backed queue persistence has been repaired. Each helper
    # retains its own OFF, generation, playback, screening and readback guards.
    return {'version': 1, 'release_mode': 'experimental', 'ready': True,
            'exact_append': True, 'refill': True, 'queue_edit': True,
            'queue_mutation_ready': True, 'automatic_refill_ready': True,
            'server_takeover': False, 'transport': True,
            'reason': 'Automatic DJ and queue controls are experimental; durable server-backed queue persistence is not guaranteed. No saved-playlist/library mutations or server takeover are supported.',
            'server_queues_enabled': live.get('serverQueuesEnabled')}


def require_queue_ready(live=None):
    result = queue_capabilities(live)
    if not result['ready']: raise QueueReadbackError(result['reason'])
    return result


def api(method, path, payload=None):
    # Keep the original ephemeral queue controls, never account/library edits.
    # Exact appends use the guarded renderer helper, not native POST queue.
    if method != 'GET' and (method, path) not in {
            *(('POST', name) for name in ('search', 'pause', 'play', 'next', 'previous', 'volume')),
            ('DELETE', 'queue'), ('PATCH', 'queue')} and not (
                method in ('DELETE', 'PATCH') and re.fullmatch(r'queue/[0-9]+', path)):
        raise QueueReadbackError('Unsupported queue/account write. No saved playlist/library mutations or server repair are supported.')
    client = json.loads((ROOT/'player-client.json').read_text())['client_id']
    if not isinstance(client, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,256}', client):
        raise ValueError('Invalid player client identifier')
    auth = request('POST', '/auth/' + client)
    if not isinstance(auth, dict) or not isinstance(auth.get('accessToken'), str):
        raise ValueError('Authentication failed')
    token = auth['accessToken']
    return request(method, '/api/v1/' + path, payload, token)

def wait_for(read, predicate, timeout=15):
    import time
    deadline=time.monotonic()+timeout
    while True:
        value=read()
        if predicate(value): return value
        if time.monotonic()>=deadline: raise ValueError('Player change was not confirmed before timeout')
        time.sleep(0.3)

def live_status():
    import subprocess
    return json.loads(subprocess.check_output(['node',str(SOURCE/'player_dom.mjs'),'status'],text=True,timeout=15))

def append_queue_snapshot():
    from dj_session import compact_queue
    raw = api('GET', 'queue')
    if not isinstance(raw, dict) or not isinstance(raw.get('items'), list):
        raise QueueReadbackError('Queue contains unknown rows; inspect queue, do not retry automatically. Any reservation is retained.')
    tracks = compact_queue(raw)
    if len(tracks) != len(raw['items']):
        raise QueueReadbackError('Queue contains unknown rows; inspect queue, do not retry automatically. Any reservation is retained.')
    return tracks


APPEND_LIFETIME_MS = 8000


def append_requested(video_id, expected_ids, deadline_ms=None, replay_index=None):
    import subprocess
    import time
    if deadline_ms is None: deadline_ms = int(time.time()*1000) + APPEND_LIFETIME_MS
    require_queue_ready()
    require_playing = bool(os.environ.get('BASIL_REFILL_GENERATION'))
    try:
        output = subprocess.check_output(
            ['node', str(SOURCE/'player_dom.mjs'), 'append-requested', video_id, json.dumps(expected_ids), str(deadline_ms), str(require_playing).lower(), json.dumps(replay_index)],
            text=True, stderr=subprocess.DEVNULL, timeout=15)
        result = json.loads(output)
        if result.get('beforeIds') != expected_ids or result.get('afterIds') != expected_ids + [video_id]:
            raise ValueError('Exact append not confirmed')
        return result
    except (subprocess.SubprocessError, ValueError, OSError, AttributeError) as error:
        raise QueueReadbackError('Enqueue was not confirmed; reservation retained. Inspect queue; do not retry or clear automatically.') from error


def enqueue_album(browse_id):
    from albums import resolve_album, reserve_album
    from dj_session import control_lock, load, enabled, queue_mode, album_due, save, discovery_filters
    import subprocess, time
    generation = os.environ.get('BASIL_REFILL_GENERATION')
    # Album network resolution holds no control lock: OFF remains responsive.
    state = load()
    if not enabled(state): raise ValueError('DJ is OFF; album denied')
    require_queue_ready()
    original_generation = state.get('generation')
    filters = discovery_filters(state)
    if generation: admit_refill(generation)
    album = resolve_album(browse_id, screen=filters['exclude_library'])
    with control_lock(ROOT):
        state = load()
        if not enabled(state) or state.get('generation') != original_generation or discovery_filters(state) != filters:
            raise ValueError('Album cancelled: authorization changed')
        if queue_mode(state) != 'album': raise ValueError('Enable explicit album mode in the session brief first')
        if generation: state = admit_refill(generation)
        require_queue_ready()
        current = append_queue_snapshot()
        if live_status().get('paused') is not False or not album_due(state,api('GET','song'),api('GET','queue')):
            raise ValueError('Album denied: paused/unknown player or queue full or next album already pending')
        reserve_album(ROOT/'discovery.sqlite', album['tracks'], current, **filters)
        replay_index = None if filters['avoid_repeats'] else next(r['index'] for r in current if r.get('selected'))
        ids = [r['videoId'] for r in current]
        requested = [t['videoId'] for t in album['tracks']]
        deadline_ms = int(time.time()*1000)+APPEND_LIFETIME_MS
        state['append_deadline_ms'] = deadline_ms
        if generation: state['refill_remaining'] -= 1
        save(state)
        try:
            output = subprocess.check_output(['node',str(SOURCE/'player_dom.mjs'),'append-album',json.dumps(requested),json.dumps(ids),str(deadline_ms),'true',json.dumps(replay_index)],text=True,stderr=subprocess.DEVNULL,timeout=15)
            result = json.loads(output)
            if result.get('beforeIds') != ids or result.get('afterIds') != ids+requested:
                raise ValueError('Complete album dispatch not confirmed')
            def confirmed(rows):
                actual = [r['videoId'] for r in rows]
                if actual == ids+requested: return True
                if actual != ids: raise QueueReadbackError('Unexpected/partial album queue; reservations retained; inspect, never retry blindly')
                return False
            wait_for(append_queue_snapshot,confirmed)
            state['last_album'] = {'browseId':browse_id,'title':album['title'],'videoIds':requested,'start_index':len(ids)}
            policy = state.get('queue_guard', {})
            if policy.get('generation') == state.get('generation') and policy.get('verified_ids') == ids:
                # Only a proven append may advance the human-reviewed baseline.
                policy['verified_ids'] = ids+requested
            save(state)
            return {'confirmed':True,'album':album,'beforeIds':ids,'afterIds':ids+requested}
        except (subprocess.SubprocessError,ValueError,OSError) as error:
            raise QueueReadbackError('Complete album enqueue NOT confirmed; all reservations retained. Inspect exact queue; no automatic retry.') from error


def _main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['capabilities','status','queue','search','album-search','album-resolve','album-enqueue','enqueue','history','clear-queue','select','next','previous','pause','play','volume'])
    p.add_argument('value', nargs='?')
    args = p.parse_args()
    if args.command in ('search','album-search','album-resolve','album-enqueue','enqueue','volume','select') and args.value is None:
        p.error('This command requires a value')
    if args.command in ('enqueue','clear-queue','select'):
        from dj_session import load, enabled
        import time
        state=load()
        if not enabled(state): p.error('No active DJ session')
    if args.command == 'capabilities':
        try:
            observed=live_status()
        except Exception:
            observed={}
        result=queue_capabilities(observed)
    elif args.command == 'history':
        from discovery import recent
        result=recent(ROOT/'discovery.sqlite')
    elif args.command == 'clear-queue':
        api('DELETE','queue')
        from dj_session import compact_queue
        result=wait_for(lambda:compact_queue(api('GET','queue')),lambda q:not q)
    elif args.command == 'select':
        index=int(args.value)
        if index<0: p.error('Negative index')
        from dj_session import compact_queue
        tracks=compact_queue(api('GET','queue'))
        target=next((r for r in tracks if r['index']==index),None)
        if target is None: p.error('Queue index does not exist')
        api('PATCH','queue',{'index':index})
        result=wait_for(lambda:api('GET','song'),lambda s:isinstance(s,dict) and s.get('videoId')==target['videoId'])
    elif args.command == 'status':
        result={'api_snapshot':api('GET','song'),'live':live_status()}
    elif args.command == 'queue':
        from dj_session import compact_queue
        result = compact_queue(api('GET', 'queue'))
    elif args.command == 'album-search':
        from albums import search_albums
        result = search_albums(args.value)
    elif args.command == 'album-resolve':
        from albums import resolve_album
        from dj_session import load, discovery_filters
        result = resolve_album(args.value, screen=discovery_filters(load())['exclude_library'])
    elif args.command == 'album-enqueue':
        try: result = enqueue_album(args.value)
        except ValueError as error: raise QueueReadbackError(str(error)) from error
    elif args.command == 'search':
        raw = api('POST', 'search', {'query':args.value})
        from search_metadata import parse_search, cache_search
        result = parse_search(raw)
        cache_search(ROOT/'search-cache.sqlite', result)
    elif args.command == 'enqueue':
        import re
        if not re.fullmatch(r'[A-Za-z0-9_-]{11}', args.value): p.error('Expected an exact 11-character video ID')
        from dj_session import load, compact_queue, enabled, queue_mode, discovery_filters
        import time
        state = load()
        if not enabled(state):
            p.error('No active DJ session; enqueue denied')
        if queue_mode(state) == 'album': p.error('Single-track enqueue denied in album mode; use album-enqueue')
        from search_metadata import cached_track
        from discovery import reserve, eligible_queue, attempt_key
        track = cached_track(ROOT/'search-cache.sqlite', args.value)
        if not track: p.error('Search for this track first; metadata is required for repeat protection')
        filters = discovery_filters(state)
        if filters['exclude_library'] and (track[2] != 0 or track[3] != 0):
            p.error('Enqueue denied: library/liked membership is true or unknown; search for an explicitly screened track')
        require_queue_ready()
        current=append_queue_snapshot()
        from discovery import tune_key
        if any(r['videoId']==args.value or (filters['avoid_repeats'] and r.get('title') and tune_key(r['title'])==tune_key(track[0])) for r in eligible_queue(current,filters['avoid_repeats'])):
            p.error('Recording or tune is already in queue')
        reserve(ROOT/'discovery.sqlite',args.value,track[0],track[1],avoid_repeats=filters['avoid_repeats'],attempt=attempt_key(current,[args.value]))
        replay_index = None if filters['avoid_repeats'] else next(r['index'] for r in current if r.get('selected'))
        expected = [r['videoId'] for r in current] + [args.value]
        def confirmed_queue(queue):
            actual = [r['videoId'] for r in queue]
            if actual == expected: return True
            if actual != expected[:-1]:
                prefix = 'Initial queue' if not current else 'Queue'
                raise QueueReadbackError(prefix + ' contains unexpected tracks/order; reservation retained. Inspect queue; do not retry or clear automatically.')
            return False
        try:
            generation = os.environ.get('BASIL_REFILL_GENERATION')
            if generation:
                state = admit_refill(generation)
                from dj_session import save
                state['refill_remaining'] -= 1
                save(state)
            # Persist the bounded renderer lease under control_lock BEFORE CDP.
            # It survives a killed helper/model process; OFF must drain it.
            from dj_session import save
            deadline_ms = int(time.time()*1000) + APPEND_LIFETIME_MS
            state['append_deadline_ms'] = deadline_ms
            save(state)
            if replay_index is None: append_requested(args.value, expected[:-1], deadline_ms)
            else: append_requested(args.value, expected[:-1], deadline_ms, replay_index=replay_index)
            result = wait_for(append_queue_snapshot,confirmed_queue)
        except QueueReadbackError:
            raise
        except (ValueError, OSError, TimeoutError) as error:
            raise QueueReadbackError('Enqueue was not confirmed; reservation retained. Inspect queue; do not retry or clear automatically.') from error
    elif args.command == 'volume':
        volume = int(args.value)
        if not 0 <= volume <= 100: p.error('Volume must be 0–100')
        api('POST','volume',{'volume':volume})
        result = api('GET','volume')
    else:
        before=api('GET','song')
        api('POST', args.command)
        if args.command in ('pause','play'):
            result=wait_for(live_status,lambda s:s.get('paused') == (args.command=='pause'))
        else:
            result=wait_for(lambda:api('GET','song'),lambda s:isinstance(s,dict) and s.get('videoId')!=(before or {}).get('videoId'))
    print(json.dumps(result,ensure_ascii=False,indent=2))

def admit_refill(generation):
    from dj_session import load, enabled, upcoming_count, REFILL_TARGET
    state = load()
    from dj_session import discovery_filters
    admitted_filters = os.environ.get('BASIL_REFILL_FILTERS')
    if admitted_filters and json.loads(admitted_filters) != discovery_filters(state):
        raise ValueError('Discovery controls changed; refill cancelled')
    if not enabled(state) or state.get('generation') != generation:
        raise ValueError('Refill authorization changed; operation denied')
    require_queue_ready()
    live = live_status()
    song = api('GET', 'song')
    count = upcoming_count(song, api('GET', 'queue'))
    if live.get('paused') is not False or count is None:
        raise ValueError('Refill denied: playback paused or queue unknown; inspect dedicated player')
    from dj_session import queue_mode
    mode = queue_mode(state)
    if state.get('refill_mode', 'tracks') != mode: raise ValueError('Refill mode changed; operation denied')
    from dj_session import album_due
    if mode == 'album' and not album_due(state,song,api('GET','queue')): raise ValueError('Next album pending or queue full; operation denied')
    if mode == 'tracks' and count >= REFILL_TARGET: raise ValueError('Refill target reached; operation denied')
    if state.get('refill_remaining', 0) <= 0: raise ValueError('Refill attempt budget exhausted')
    return state


def main():
    from dj_session import control_lock, load, enabled
    command = sys.argv[1] if len(sys.argv) > 1 else ''
    generation = os.environ.get('BASIL_REFILL_GENERATION')

    if generation and command not in ('capabilities', 'status', 'queue', 'history', 'search', 'enqueue', 'album-search', 'album-resolve', 'album-enqueue'):
        raise ValueError('Background DJ cannot control transport or clear/select queue')
    if generation and command in ('album-search', 'album-resolve', 'album-enqueue'):
        admit_refill(generation)
        return _main()
    if command not in ('enqueue', 'clear-queue', 'select') and not (generation and command == 'search'):
        return _main()
    with control_lock(ROOT):
        state = load()
        if not enabled(state): raise ValueError('DJ is OFF; operation denied')
        if generation: admit_refill(generation)
        return _main()


if __name__ == '__main__':
    try: main()
    except QueueReadbackError as e:
        print(f'Player operation failed: {e}',file=sys.stderr)
        sys.exit(1)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError) as e:
        print(f'Player operation failed: {type(e).__name__}. Check the dedicated player and sign-in; do not assume success.',file=sys.stderr)
        sys.exit(1)
