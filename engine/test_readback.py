import contextlib
import io
import json
import pathlib
import sqlite3
import tempfile
import unittest
from queue_test_support import QueuePrimitiveFixture
from unittest.mock import patch

import djctl
from djctl import wait_for

class EnqueueReadbackTests(QueuePrimitiveFixture):
    target = '5ycyIkcX7zU'

    def run_enqueue(self, queues, timeout=2):
        # Exercise the real CLI/reservation boundary with isolated metadata;
        # no real player or persistent discovery database is touched.
        calls = []
        replies = iter(queues)
        def api(method, path, payload=None):
            calls.append((method, path, payload))
            if method == 'GET' and path == 'queue':
                return {'items': [v if isinstance(v, dict) else {'playlistPanelVideoRenderer': {'videoId': v}}
                                  for v in next(replies)]}
        def append(video_id, expected_ids, deadline_ms):
            self.assertEqual(json.loads((root/'session.json').read_text())['append_deadline_ms'], deadline_ms)
            with contextlib.closing(sqlite3.connect(root/'discovery.sqlite')) as db:
                self.assertEqual(db.execute('SELECT video_id FROM discoveries').fetchall(), [(video_id,)])
            calls.append(('CDP', 'append-requested', {'videoId': video_id, 'expectedIds': expected_ids}))
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            with contextlib.closing(sqlite3.connect(root/'search-cache.sqlite')) as db, db:
                db.execute('CREATE TABLE tracks (video_id TEXT PRIMARY KEY,title TEXT,artist TEXT,library INTEGER,liked INTEGER)')
                db.execute('INSERT INTO tracks VALUES (?,?,?,?,?)', (self.target, 'Empty Pages', 'Traffic',0,0))
            from discovery import reserve as real_reserve
            with patch.object(djctl, 'ROOT', root), patch.object(djctl, 'api', side_effect=api), \
                 patch.object(djctl, 'append_requested', side_effect=append), \
                 patch('dj_session.load', return_value={'active': True, 'management_version': 2, 'generation': 'test'}), \
                 patch('dj_session.STATE', root/'session.json'), \
                 patch('discovery.reserve', wraps=real_reserve) as reserve, \
                 patch.object(djctl, 'wait_for', side_effect=lambda read, predicate: wait_for(read, predicate, timeout)), \
                 patch('sys.argv', ['djctl.py', 'enqueue', self.target]), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                try:
                    djctl.main()
                finally:
                    self.calls = calls
                    self.reservations = reserve.call_count
                    with contextlib.closing(sqlite3.connect(root/'discovery.sqlite')) as db:
                        self.retained_ids = [row[0] for row in db.execute('SELECT video_id FROM discoveries')]
                return json.loads(output.getvalue())

    def test_initial_enqueue_rejects_generated_queue_without_cleanup_or_retry(self):
        with self.assertRaisesRegex(ValueError, 'Initial queue.*unexpected.*not retry'):
            self.run_enqueue([[], [], [self.target, 'unrelated01', 'unrelated02']])
        writes = [c for c in self.calls if c[0] != 'GET']
        self.assertEqual(writes, [('CDP', 'append-requested', {'videoId': self.target, 'expectedIds': []})])
        self.assertEqual(self.reservations, 1)
        self.assertEqual(self.retained_ids, [self.target])

    def test_initial_enqueue_waits_for_requested_only_queue(self):
        result = self.run_enqueue([[], [], [self.target]])
        self.assertEqual([r['videoId'] for r in result], [self.target])
        self.assertEqual(sum(c[0] == 'CDP' for c in self.calls), 1)

    def test_refill_preserves_existing_queue_and_history(self):
        result = self.run_enqueue([['oldhistory1', 'oldcurrent1'], ['oldhistory1', 'oldcurrent1', self.target]])
        self.assertEqual([r['videoId'] for r in result], ['oldhistory1', 'oldcurrent1', self.target])
        self.assertEqual(sum(c[0] != 'GET' for c in self.calls), 1)

    def test_nonempty_enqueue_rejects_expansion(self):
        with self.assertRaisesRegex(djctl.QueueReadbackError, 'unexpected'):
            self.run_enqueue([['oldcurrent1'], ['oldcurrent1', self.target, 'unrelated01']])
        self.assertEqual(self.reservations, 1)
        self.assertEqual(sum(c[0] != 'GET' for c in self.calls), 1)

    def test_nonempty_enqueue_rejects_reordering(self):
        with self.assertRaisesRegex(djctl.QueueReadbackError, 'unexpected'):
            self.run_enqueue([['oldhistory1', 'oldcurrent1'], ['oldcurrent1', 'oldhistory1', self.target]])

    def test_unknown_readback_rows_are_not_silently_dropped(self):
        with self.assertRaisesRegex(djctl.QueueReadbackError, 'unknown'):
            self.run_enqueue([[], [self.target, {'unknownRenderer': {}}]])
        self.assertEqual(self.retained_ids, [self.target])

    def test_empty_readback_timeout_keeps_reservation_and_does_not_retry(self):
        with self.assertRaisesRegex(djctl.QueueReadbackError, 'Enqueue was not confirmed.*reservation retained.*not retry'):
            self.run_enqueue([[], []], timeout=0)
        self.assertEqual(self.reservations, 1)
        self.assertEqual(self.retained_ids, [self.target])
        self.assertEqual(sum(c[0] != 'GET' for c in self.calls), 1)

class AppendBridgeTests(QueuePrimitiveFixture):
    def test_fixed_named_helper_receives_only_exact_id_and_expected_order(self):
        target = '5ycyIkcX7zU'
        expected = ['U8Ie9J2Eo5Q']
        with patch('subprocess.check_output', return_value=json.dumps({'beforeIds': expected, 'afterIds': expected+[target]})) as run:
            djctl.append_requested(target, expected)
        self.assertEqual(run.call_count, 1)
        argv=run.call_args.args[0]
        self.assertEqual(argv[:5], ['node', str(djctl.SOURCE/'player_dom.mjs'), 'append-requested', target, json.dumps(expected)])
        self.assertGreater(int(argv[5]), 0)
        self.assertEqual(argv[6], 'false')
        self.assertNotIn('shell', run.call_args.kwargs)

    def test_ambiguous_helper_failure_is_redacted_and_not_retried(self):
        import subprocess
        for reply in ['{}', 'private backend details', json.dumps({'beforeIds': [], 'afterIds': ['unrequested']})]:
            with self.subTest(reply=reply), patch('subprocess.check_output', return_value=reply) as run:
                with self.assertRaisesRegex(djctl.QueueReadbackError, 'reservation retained.*not retry') as error:
                    djctl.append_requested('5ycyIkcX7zU', [])
                self.assertNotIn('private backend details', str(error.exception))
                self.assertEqual(run.call_count, 1)
        with patch('subprocess.check_output', side_effect=subprocess.TimeoutExpired('private backend details', 15)) as run:
            with self.assertRaisesRegex(djctl.QueueReadbackError, 'reservation retained.*not retry'):
                djctl.append_requested('5ycyIkcX7zU', [])
            self.assertEqual(run.call_count, 1)

class ReadbackTests(unittest.TestCase):
    def test_waits_for_async_queue_update_without_reissuing_write(self):
        replies=iter([[],[],[{'videoId':'confirmed'}]])
        result=wait_for(lambda:next(replies),lambda q:bool(q),timeout=2)
        self.assertEqual(result,[{'videoId':'confirmed'}])
    def test_unconfirmed_change_is_not_success(self):
        with self.assertRaises(ValueError):wait_for(lambda:[],bool,timeout=0)

if __name__=='__main__':unittest.main()
