import contextlib
import io
import json
import pathlib
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import djctl


def menu(library=False, liked=False):
    return {'menuRenderer': {'items': [
        {'toggleMenuServiceItemRenderer': {'defaultText': {'runs': [{'text': 'Save to library'}]}, 'isToggled': library}},
        {'menuServiceItemRenderer': {'text': {'runs': [{'text': 'Remove from liked songs' if liked else 'Add to liked songs'}]},
            'serviceEndpoint': {'likeEndpoint': {'status': 'INDIFFERENT' if liked else 'LIKE'}},
            'defaultLikeStatus': 'LIKE' if not liked else 'INDIFFERENT'}}]}}


from queue_test_support import QueuePrimitiveFixture

class MembershipTests(QueuePrimitiveFixture):
    def search(self, raw):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            with patch.object(djctl, 'ROOT', root), patch.object(djctl, 'api', return_value=raw), \
                 patch('sys.argv', ['djctl.py', 'search', 'explicit hand picked hit']), contextlib.redirect_stdout(io.StringIO()) as output:
                djctl.main()
            return json.loads(output.getvalue())

    def test_card_liked_and_library_flags(self):
        result = self.search({'musicCardShelfRenderer': {'onTap': {'watchEndpoint': {'videoId': 'LS_20S2J8SQ'}},
            'title': {'runs': [{'text': 'War On Drugs'}]}, 'menu': menu(True, True)}})
        self.assertIs(result[0].get('liked'), True)
        self.assertIs(result[0].get('library'), True)

    def test_responsive_requested_hit_explicit_nonmember(self):
        result = self.search({'musicResponsiveListItemRenderer': {'playlistItemData': {'videoId': '5ycyIkcX7zU'},
            'menu': menu(False, False)}})
        self.assertIs(result[0].get('liked'), False)
        self.assertIs(result[0].get('library'), False)

    def test_missing_is_unknown(self):
        result = self.search({'musicCardShelfRenderer': {'onTap': {'watchEndpoint': {'videoId': '5ycyIkcX7zU'}}}})
        self.assertIsNone(result[0].get('liked'))
        self.assertIsNone(result[0].get('library'))

    def test_toggle_liked_endpoint(self):
        result = self.search({'musicCardShelfRenderer': {'onTap': {'watchEndpoint': {'videoId': '5ycyIkcX7zU'}},
            'menu': {'toggleMenuServiceItemRenderer': {'defaultText': {'runs': [{'text': 'Remove from liked songs'}]},
                'defaultServiceEndpoint': {'likeEndpoint': {'status': 'INDIFFERENT'}}}}}})
        self.assertIs(result[0].get('liked'), True)

    def test_safe_legacy_cache_migration_keeps_metadata_and_unknown_flags(self):
        from search_metadata import cached_track
        with tempfile.TemporaryDirectory() as temp:
            path = pathlib.Path(temp)/'cache.sqlite'
            with contextlib.closing(sqlite3.connect(path)) as db, db:
                db.execute('CREATE TABLE tracks (video_id TEXT PRIMARY KEY,title TEXT,artist TEXT)')
                db.execute('INSERT INTO tracks VALUES (?,?,?)', ('5ycyIkcX7zU', 'Hit', 'Artist'))
            self.assertEqual(cached_track(path, '5ycyIkcX7zU'), ('Hit', 'Artist', None, None))
            self.assertEqual(cached_track(path, '5ycyIkcX7zU'), ('Hit', 'Artist', None, None))

    def test_new_unknown_evidence_does_not_keep_stale_nonmembership(self):
        from search_metadata import cache_search, cached_track
        with tempfile.TemporaryDirectory() as temp:
            path = pathlib.Path(temp)/'cache.sqlite'
            cache_search(path, [{'videoId': '5ycyIkcX7zU', 'labels': ['Hit', 'Artist'], 'library': False, 'liked': False}])
            cache_search(path, [{'videoId': '5ycyIkcX7zU', 'labels': [], 'library': None, 'liked': None}])
            self.assertEqual(cached_track(path, '5ycyIkcX7zU'), ('Hit', 'Artist', None, None))

    def test_verified_nonmember_is_allowed_with_reservation_before_append(self):
        from search_metadata import cache_search
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            cache_search(root/'search-cache.sqlite', [{'videoId': '5ycyIkcX7zU', 'labels': ['Hit', 'Artist'], 'library': False, 'liked': False}])
            calls = []
            replies = iter([{'items': []}, {'items': [{'playlistPanelVideoRenderer': {'videoId': '5ycyIkcX7zU'}}]}])
            def api(method, path, payload=None):
                self.assertEqual((method, path), ('GET', 'queue'))
                return next(replies)
            def append(video_id, expected, deadline_ms):
                with contextlib.closing(sqlite3.connect(root/'discovery.sqlite')) as db:
                    self.assertEqual(db.execute('SELECT video_id FROM discoveries').fetchall(), [(video_id,)])
                calls.append((video_id, expected))
            with patch.object(djctl, 'ROOT', root), patch.object(djctl, 'api', side_effect=api), \
                 patch.object(djctl, 'append_requested', side_effect=append), \
                 patch('dj_session.load', return_value={'active': True, 'management_version': 2, 'generation': 'test', 'exclude_library': True}), \
                 patch('dj_session.STATE', root/'session.json'), \
                 patch('sys.argv', ['djctl.py', 'enqueue', '5ycyIkcX7zU']), contextlib.redirect_stdout(io.StringIO()):
                djctl.main()
            self.assertEqual(calls, [('5ycyIkcX7zU', [])])

    def test_exclusion_denies_before_reservation_or_any_player_access(self):
        for library, liked in [(1, 0), (0, 1), (None, 0), (0, None), (None, None)]:
            with self.subTest(library=library, liked=liked), tempfile.TemporaryDirectory() as temp:
                root = pathlib.Path(temp)
                with contextlib.closing(sqlite3.connect(root/'search-cache.sqlite')) as db, db:
                    db.execute('CREATE TABLE tracks (video_id TEXT PRIMARY KEY,title TEXT,artist TEXT,library INTEGER,liked INTEGER)')
                    db.execute('INSERT INTO tracks VALUES (?,?,?,?,?)', ('5ycyIkcX7zU', 'Hit', 'Artist', library, liked))
                with patch.object(djctl, 'ROOT', root), patch.object(djctl, 'api') as api, \
                     patch('discovery.reserve') as reserve, \
                     patch('dj_session.load', return_value={'active': True, 'management_version': 2, 'generation': 'test', 'exclude_library': True}), \
                 patch('dj_session.STATE', root/'session.json'), \
                     patch('sys.argv', ['djctl.py', 'enqueue', '5ycyIkcX7zU']), contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        djctl.main()
                    reserve.assert_not_called()
                    api.assert_not_called()

if __name__ == '__main__': unittest.main()
