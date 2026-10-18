"""Optional read-only household adapter diagnostic; not a real Signal delivery test.

Run from an operator-configured installation only. Synthetic boundary checks do
not prove that native gateway routing or actual senders are authorized.
"""
import importlib.util
import json
from pathlib import Path
import sys


def main():
    spec = importlib.util.spec_from_file_location('household_dj_probe', Path(__file__).with_name('__init__.py'))
    assert spec is not None and spec.loader is not None
    plugin = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(plugin)
    known = plugin.partners()
    if not plugin.GROUP or not known:
        print('Household adapter not configured: set BASIL_SIGNAL_GROUP and its matching protected identity binding.', file=sys.stderr)
        return 1
    for identity in known:
        source = {'platform': 'signal', 'profile': 'together', 'chat_id': plugin.GROUP, 'user_id': identity}
        assert plugin.allowed('together', source)
    source = {'platform': 'signal', 'profile': 'together', 'chat_id': plugin.GROUP, 'user_id': 'unrecognized-fixture-sender'}
    assert not plugin.allowed('together', source)
    result = plugin.dispatch({'action': 'status'})
    print(json.dumps({'binding_checks': 'passed', 'read_only_status_ok': bool(result.get('ok')), 'real_signal_delivery_tested': False}))
    return 0 if result.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())
