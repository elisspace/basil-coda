"""Local SQLite only; never read or change the live player."""
from contextlib import closing
import sqlite3
from pathlib import Path
import tempfile
import threading
import unittest

from history import ListeningHistory, HistoryTracker


def song(video='a', title=None):
    return {'videoId': video, 'title': title or video, 'artist': 'Artist',
            'imageSrc': 'https://img.example/' + video}


def live(progress: float = 1, title='a', paused=False):
    return {'paused': paused, 'currentTime': progress, 'title': title}


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.history = ListeningHistory(self.root)

    def entries(self):
        return self.history.snapshot()['entries']

    def test_progress_confirmation_preserves_first_observed_timestamp(self):
        self.history.observe(song(), live(2), now=100)
        self.assertEqual(self.entries(), [])
        self.history.observe(song(), live(3), now=105)
        entry, = self.entries()
        self.assertEqual(entry['timestamp'], 100)
        self.assertEqual(entry['status'], 'played')
        self.assertEqual(entry['source'], 'observed-playback')
        self.assertEqual(entry['imageSrc'], 'https://img.example/a')
        self.history.observe(song(), live(4), now=110)
        self.assertEqual(self.entries(), [entry])

    def test_paused_stalled_zero_nonfinite_and_stale_metadata_not_listens(self):
        for snapshot in [live(2, paused=True), live(0), live(float('nan')),
                         live(float('inf')), live(True), live(2, title='other'),
                         {'currentTime': 2, 'title': 'a'},
                         dict(live(2), error='decode failed')]:
            self.history.observe(song(), snapshot, now=100)
        self.history.observe(song(), live(1), now=101)
        self.history.observe(song(), live(1), now=102)
        self.assertEqual(self.entries(), [])

    def test_restart_continuation_pause_and_seek_dedup_conservatively(self):
        self.history.observe(song(), live(10), now=100)
        self.history.observe(song(), live(11), now=101)
        self.history = ListeningHistory(self.root)
        self.history.observe(song(), live(12), now=102)
        self.history.observe(song(), live(12, paused=True), now=103)
        self.history.observe(song(), live(1), now=104)
        self.history.observe(song(), live(2), now=105)
        self.assertEqual(len(self.entries()), 1)

    def test_unconfirmed_restart_and_track_changes(self):
        self.history.observe(song(), live(1), now=100)
        self.history = ListeningHistory(self.root)
        self.history.observe(song(), live(2), now=101)
        self.history.observe(song('b'), live(1, 'b'), now=200)
        self.history.observe(song('b'), live(2, 'b'), now=201)
        self.history.observe(song(), live(1), now=300)
        self.history.observe(song(), live(2), now=301)
        rows = self.entries()
        self.assertEqual([r['timestamp'] for r in rows], [300, 200, 100])
        self.assertEqual([r['videoId'] for r in rows], ['a', 'b', 'a'])
        self.assertEqual(len({r['id'] for r in rows}), 3)

    def test_legacy_reservation_is_queued_and_database_unchanged(self):
        path = self.root / 'discovery.sqlite'
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE discoveries (video_id TEXT PRIMARY KEY, tune TEXT UNIQUE NOT NULL, title TEXT NOT NULL, artist TEXT NOT NULL, reserved REAL NOT NULL)')
            db.execute('INSERT INTO discoveries VALUES (?,?,?,?,?)', ('old', 'old', 'Old song', 'Old artist', 50.25))
        before = path.read_bytes()
        self.history.observe(song(), live(1), now=100)
        self.history.observe(song(), live(2), now=101)
        rows = self.entries()
        self.assertEqual([r['timestamp'] for r in rows], [100, 50.25])
        self.assertEqual(rows[1]['status'], 'queued')
        self.assertEqual(rows[1]['source'], 'discovery-reservation')
        self.assertEqual(before, path.read_bytes())
        self.assertIn('not completed', self.history.snapshot()['coverage'])
        self.assertIn('not full YouTube', self.history.snapshot()['coverage'])

    def test_missing_legacy_not_created_and_unknown_schema_reported(self):
        self.assertEqual(self.entries(), [])
        path = self.root / 'discovery.sqlite'
        self.assertFalse(path.exists())
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE discoveries (video_id TEXT)')
        self.assertEqual(self.entries(), [])
        self.assertIn('unavailable', self.history.snapshot()['coverage'])

    def test_legacy_unknown_dates_are_not_invented(self):
        with closing(sqlite3.connect(self.root / 'discovery.sqlite')) as db, db:
            db.execute('CREATE TABLE discoveries (video_id TEXT, title TEXT, artist TEXT, reserved REAL)')
            db.executemany('INSERT INTO discoveries VALUES (?,?,?,?)',
                           [('unknown', 'Unknown', 'Artist', None),
                            ('bad', 'Bad', 'Artist', 'yesterday')])
        result = self.history.snapshot()
        self.assertEqual(result['entries'], [])
        self.assertIn('unavailable', result['coverage'])

    def test_concurrent_observations_are_one_occurrence(self):
        self.history.observe(song(), live(1), now=100)
        workers = [threading.Thread(target=self.history.observe, args=(song(), live(2)), kwargs={'now': 101}) for _ in range(8)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        self.assertEqual(len(self.entries()), 1)

    def test_tracker_polls_without_browser_and_stops(self):
        observed = threading.Event()
        calls = []
        def read():
            calls.append(1)
            if len(calls) == 1:
                raise OSError('offline')
            if len(calls) >= 3:
                observed.set()
            return {'song': song(), 'live': live(len(calls))}
        tracker = HistoryTracker(self.history, read, interval=0.01)
        tracker.start()
        tracker.start()
        self.assertTrue(observed.wait(2))
        tracker.stop(timeout=2)
        self.assertFalse(tracker.running)
        self.assertEqual(len(self.entries()), 1)


if __name__ == '__main__':
    unittest.main()
