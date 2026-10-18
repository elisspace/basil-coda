"""Local observed-playback history, separate from no-repeat reservations.

A listen here means *observed advancing playback*, not completion or audible
output. Same-track rewinds are deliberately not counted as new occurrences:
without a stable player session ID a seek and a replay cannot be distinguished.
The persistent cursor also avoids inventing another occurrence after restart.
"""
import json
import math
from pathlib import Path
import sqlite3
import threading
import time
from typing import TypeGuard


COVERAGE = (
    'Local observed playback since this tracker was installed, not completed '
    'listens and not full YouTube account history. Played timestamps are the '
    'first positive-progress observation, confirmed by a later advancing sample. '
    'Queued timestamps are legacy discovery reservations, not proof of playback '
    'or a successful enqueue. Same-track replays and playback while this web '
    'service is stopped may be missing; restart deduplication is conservative.'
)


def _number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class ListeningHistory:
    """Use an external runtime directory. Never opens discovery.sqlite writable."""

    def __init__(self, runtime):
        self.runtime = Path(runtime)
        self.path = self.runtime / 'listening-history.sqlite'
        self.legacy_path = self.runtime / 'discovery.sqlite'
        self.lock = threading.RLock()

    def _connect(self):
        self.runtime.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=5)
        db.execute('CREATE TABLE IF NOT EXISTS listens ('
                   'id INTEGER PRIMARY KEY, video_id TEXT NOT NULL, '
                   'title TEXT NOT NULL, artist TEXT NOT NULL, image_src TEXT, '
                   'observed REAL NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS cursor ('
                   'id INTEGER PRIMARY KEY CHECK (id=1), state TEXT NOT NULL)')
        return db

    def observe(self, song, live, *, now=None):
        """Record only matching metadata and increasing live video time.

        Two fresh advancing samples are required. Paused, zero-progress and
        stale REST snapshots never create listens or reset an existing session.
        A changed track's zero-time sample can establish a new session cursor,
        but it is not evidence of playback and has no listening timestamp.
        """
        if not isinstance(song, dict) or not isinstance(live, dict):
            return
        video_id, title = song.get('videoId'), song.get('title')
        progress = live.get('currentTime')
        if (not isinstance(video_id, str) or not video_id or
                not isinstance(title, str) or not title.strip() or
                not isinstance(live.get('title'), str) or
                live['title'].strip() != title.strip() or
                live.get('paused') is not False or live.get('error') or
                not _number(progress) or progress < 0):
            return
        ready = live.get('readyState')
        if ready is not None and (not _number(ready) or ready < 2):
            return
        now = time.time() if now is None else now
        if not _number(now) or now <= 0:
            return
        with self.lock:
            db = self._connect()
            try:
                with db:
                    db.execute('BEGIN IMMEDIATE')
                    row = db.execute('SELECT state FROM cursor WHERE id=1').fetchone()
                    state = json.loads(row[0]) if row else None
                    if state is None or state['videoId'] != video_id:
                        state = {'videoId': video_id, 'progress': progress,
                                 'first': now if progress > 0 else None,
                                 'recorded': False}
                    elif not state['recorded'] and progress > 0:
                        if state['first'] is None:
                            state['first'] = now
                        elif progress > state['progress']:
                            image = song.get('imageSrc')
                            artist = song.get('artist')
                            db.execute('INSERT INTO listens (video_id,title,artist,image_src,observed) VALUES (?,?,?,?,?)',
                                       (video_id, title, artist if isinstance(artist, str) else '',
                                        image if isinstance(image, str) else None, state['first']))
                            state['recorded'] = True
                    state['progress'] = progress
                    db.execute('INSERT OR REPLACE INTO cursor VALUES (1,?)', (json.dumps(state),))
            finally:
                db.close()

    def _legacy_entries(self):
        if not self.legacy_path.exists():
            return [], False
        db = None
        try:
            # Do not call discovery.connect: that helper creates/migrates tables.
            db = sqlite3.connect(self.legacy_path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
            columns = {row[1] for row in db.execute('PRAGMA table_info(discoveries)')}
            if not {'video_id', 'title', 'artist', 'reserved'}.issubset(columns):
                return [], True
            entries = []
            unavailable = False
            for video_id, title, artist, reserved in db.execute(
                    'SELECT video_id,title,artist,reserved FROM discoveries'):
                if not _number(reserved) or reserved <= 0:
                    unavailable = True
                    continue  # Unknown dates cannot honestly be placed on a timeline.
                entries.append({'id': 'queued:' + str(video_id), 'videoId': video_id,
                                'title': title, 'artist': artist, 'timestamp': reserved,
                                'status': 'queued', 'source': 'discovery-reservation'})
            return entries, unavailable
        except sqlite3.Error:
            return [], True
        finally:
            if db is not None:
                db.close()

    def snapshot(self):
        with self.lock:
            entries = []
            if self.path.exists():
                db = sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
                try:
                    for row in db.execute('SELECT id,video_id,title,artist,image_src,observed FROM listens'):
                        entry = {'id': 'played:' + str(row[0]), 'videoId': row[1],
                                 'title': row[2], 'artist': row[3], 'timestamp': row[5],
                                 'status': 'played', 'source': 'observed-playback'}
                        if row[4]:
                            entry['imageSrc'] = row[4]
                        entries.append(entry)
                finally:
                    db.close()
            legacy, unavailable = self._legacy_entries()
            entries.extend(legacy)
            entries.sort(key=lambda entry: (entry['timestamp'], entry['id']), reverse=True)
            coverage = COVERAGE + (' Legacy reservation history is unavailable.' if unavailable else '')
            return {'ok': True, 'entries': entries, 'coverage': coverage}


class HistoryTracker:
    """One serial read-only poller; pass Application.state to share its cache.

    Instantiate without starting in Application.__init__; start/stop only for the
    running HTTP service. The callback must have bounded I/O timeouts. stop()
    waits for the in-flight read (and raises if its explicit deadline expires).
    """

    def __init__(self, history, read_state, interval=5):
        if not _number(interval) or interval <= 0:
            raise ValueError('Polling interval must be positive and finite')
        self.history, self.read_state, self.interval = history, read_state, interval
        self._stop = threading.Event()
        self._thread = None
        self._lifecycle = threading.Lock()
        self.last_error = None

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        with self._lifecycle:
            if self.running:
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name='basil-history', daemon=True)
            self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                state = self.read_state()
                self.history.observe(state.get('song'), state.get('live'))
                self.last_error = None
            except Exception:
                # Avoid leaking authentication, paths, or untrusted backend errors.
                self.last_error = 'Playback observation temporarily unavailable.'
            if self._stop.wait(self.interval):
                break

    def stop(self, timeout=120):
        with self._lifecycle:
            self._stop.set()
            if self._thread is not None:
                self._thread.join(timeout)
                if self._thread.is_alive():
                    raise RuntimeError('History polling has not stopped within its deadline')
                self._thread = None
