"""Persistent conservative no-repeat history: IDs and normalized tune titles."""
import re
import sqlite3
import time
import unicodedata

def tune_key(title):
    title=unicodedata.normalize('NFKD',title).casefold()
    title=re.sub(r'\([^)]*\)|\[[^]]*\]',' ',title)
    title=re.sub(r'\s[-–—]\s.*(?:remaster|live|mono|stereo|version|take|mix).*$', '', title)
    title=''.join(c for c in title if not unicodedata.combining(c))
    key=re.sub(r'[^a-z0-9]+',' ',title).strip()
    if not key: raise ValueError('Empty tune identity')
    return key

def connect(path):
    db=sqlite3.connect(path,timeout=20)
    db.execute('CREATE TABLE IF NOT EXISTS discoveries (video_id TEXT PRIMARY KEY, tune TEXT UNIQUE NOT NULL, title TEXT NOT NULL, artist TEXT NOT NULL, reserved REAL NOT NULL)')
    return db

def attempt_key(current, requested):
    import hashlib, json
    # Position/context, not just video identity: blocks accidental/ambiguous retry
    # while permitting intentional replay once the exact queue has advanced.
    return hashlib.sha256(json.dumps([[r['videoId'] for r in current], requested], separators=(',', ':')).encode()).hexdigest()


def reserve_batch(path, tracks, avoid_repeats=True, attempt=None):
    db=connect(path)
    try:
        with db:
            db.execute('CREATE TABLE IF NOT EXISTS reservation_events (id INTEGER PRIMARY KEY, video_id TEXT NOT NULL, tune TEXT NOT NULL, title TEXT NOT NULL, artist TEXT NOT NULL, reserved REAL NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS append_attempts (intent TEXT PRIMARY KEY, reserved REAL NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS reservation_events_video ON reservation_events(video_id)')
            db.execute('CREATE INDEX IF NOT EXISTS reservation_events_tune ON reservation_events(tune)')
            # Acquire write lock before checking eligibility, so batches are atomic.
            db.execute('BEGIN IMMEDIATE')
            if attempt:
                if db.execute('SELECT 1 FROM append_attempts WHERE intent=?',(attempt,)).fetchone():
                    raise ValueError('Append retry denied: prior attempt retained; inspect exact queue, never retry blindly')
                db.execute('INSERT INTO append_attempts VALUES (?,?)',(attempt,time.time()))
            rows=[(t['videoId'],tune_key(t['title']),t['title'],t['artist'],time.time()) for t in tracks]
            if avoid_repeats:
                for video,tune,*_ in rows:
                    for table in ('discoveries','reservation_events'):
                        if db.execute(f'SELECT 1 FROM {table} WHERE video_id=? OR tune=?',(video,tune)).fetchone():
                            raise ValueError('Repeat blocked: this recording or tune is already in discovery history')
            # Preserve every original reservation byte-for-byte. The append-only
            # occurrence ledger also retains alternate IDs sharing a unique tune.
            db.executemany('INSERT OR IGNORE INTO discoveries VALUES (?,?,?,?,?)',rows)
            db.executemany('INSERT INTO reservation_events (video_id,tune,title,artist,reserved) VALUES (?,?,?,?,?)',rows)
    finally: db.close()


def reserve(path,video_id,title,artist,avoid_repeats=True,attempt=None):
    reserve_batch(path,[{'videoId':video_id,'title':title,'artist':artist}],avoid_repeats,attempt)


def eligible_queue(current, avoid_repeats):
    if avoid_repeats: return current
    selected=[i for i,r in enumerate(current) if r.get('selected')]
    if len(selected)!=1: raise ValueError('Queue selection unknown; replay denied')
    return current[selected[0]:]  # current and upcoming still cannot duplicate

def recent(path):
    db=connect(path)
    try:
        return [{'videoId':i,'title':t,'artist':a} for i,t,a in db.execute('SELECT video_id,title,artist FROM discoveries ORDER BY reserved DESC LIMIT 100')]
    finally:db.close()
