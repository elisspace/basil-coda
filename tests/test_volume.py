"""Volume API seam tests with mocks only; no live mutations."""
from contextlib import contextmanager
import unittest
from unittest.mock import Mock, call

from volume import read_volume, set_volume


class APIError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class App:
    def __init__(self):
        self.locked = False
        self.acquire_mutation = Mock()
        self.mutation_lock = Mock()
        self.invalidate = Mock()
        self.player_lock = self.lock()

    @contextmanager
    def lock(self):
        self.locked = True
        try:
            yield
        finally:
            self.locked = False

    def poll(self, read, predicate):
        for _ in range(3):
            result = read()
            if predicate(result):
                return result
        raise APIError(504, 'unconfirmed')


class VolumeTests(unittest.TestCase):
    def test_actual_pear_state_schema_normalized(self):
        api = Mock(return_value={'state': 42.0, 'isMuted': False})
        self.assertEqual(read_volume(api, APIError), {'volume': 42})
        api.assert_called_once_with('GET', 'volume')

    def test_invalid_player_values_not_fabricated(self):
        for raw in [None, {}, {'state': True}, {'state': -1}, {'state': 101},
                    {'state': float('nan')}, {'state': 4.5}, {'state': '40'}]:
            with self.subTest(raw=raw), self.assertRaises(APIError) as error:
                read_volume(Mock(return_value=raw), APIError)
            self.assertEqual(error.exception.status, 502)

    def test_invalid_input_never_acquires_or_calls_api(self):
        app, api = App(), Mock()
        for value in [True, False, None, '42', 42.0, -1, 101, {}, []]:
            with self.subTest(value=value), self.assertRaises(APIError) as error:
                set_volume(app, {'volume': value}, api, APIError)
            self.assertEqual(error.exception.status, 400)
        app.acquire_mutation.assert_not_called()
        api.assert_not_called()

    def test_boundaries_polled_readback_single_write_and_locks(self):
        for value in [0, 42, 100]:
            app = App()
            reads = iter([{'state': 10, 'isMuted': False}, {'state': value, 'isMuted': False}])
            def backend(method, path, payload=None):
                self.assertTrue(app.locked)
                app.acquire_mutation.assert_called_once_with()
                return next(reads) if method == 'GET' else None
            api = Mock(side_effect=backend)
            self.assertEqual(set_volume(app, {'volume': value}, api, APIError), {'ok': True, 'volume': value})
            self.assertEqual(api.call_args_list, [call('POST', 'volume', {'volume': value}), call('GET', 'volume'), call('GET', 'volume')])
            app.invalidate.assert_called_once_with()
            app.mutation_lock.release.assert_called_once_with()

    def test_unconfirmed_and_write_failure_release_without_retry(self):
        for fail_write in [False, True]:
            app = App()
            def backend(method, path, payload=None):
                if method == 'POST' and fail_write:
                    raise OSError('offline')
                return {'state': 9}
            api = Mock(side_effect=backend)
            with self.assertRaises((APIError, OSError)):
                set_volume(app, {'volume': 42}, api, APIError)
            self.assertEqual(sum(c.args[0] == 'POST' for c in api.call_args_list), 1)
            app.invalidate.assert_called_once_with()
            app.mutation_lock.release.assert_called_once_with()

    def test_busy_does_not_mutate_or_release_unowned_lock(self):
        app, api = App(), Mock()
        app.acquire_mutation.side_effect = APIError(409, 'busy')
        with self.assertRaises(APIError):
            set_volume(app, {'volume': 42}, api, APIError)
        api.assert_not_called()
        app.mutation_lock.release.assert_not_called()


if __name__ == '__main__':
    unittest.main()
