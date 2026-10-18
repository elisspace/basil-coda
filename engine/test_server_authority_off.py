"""OFF admission characterization: isolated state, no real CDP/API/model/service."""
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch
import dj_session
import djctl

class ServerAuthorityOffTests(unittest.TestCase):
    def test_off_blocks_model_launch_before_player_or_network_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            with patch.object(dj_session, 'ROOT', root), patch.object(dj_session, 'STATE', root/'session.json'), \
                 patch.object(dj_session, 'api') as api, patch.object(dj_session, 'live_status') as live, \
                 patch.object(dj_session.subprocess, 'Popen') as paid:
                dj_session.save({'active':False,'management_version':2,'generation':'g'})
                dj_session.run_refill('fixture only', {'active':True,'management_version':2,'generation':'g'})
                paid.assert_not_called()
                api.assert_not_called()
                live.assert_not_called()

    def test_off_blocks_background_search_and_queue_write_before_network(self):
        for command in ('search', 'enqueue', 'clear-queue', 'select'):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as directory:
                root = pathlib.Path(directory)
                with patch.object(dj_session,'ROOT',root), patch.object(dj_session,'STATE',root/'session.json'), \
                     patch.object(djctl,'ROOT',root), patch.dict(os.environ,{'BASIL_REFILL_GENERATION':'g'}), \
                     patch('sys.argv',['djctl.py',command,'00000000002']), \
                     patch.object(djctl,'api') as network, patch.object(djctl,'append_requested') as append, \
                     patch.object(djctl,'_main') as effect:
                    dj_session.save({'active':False,'management_version':2,'generation':'g'})
                    with self.assertRaises(ValueError): djctl.main()
                    network.assert_not_called()
                    append.assert_not_called()
                    effect.assert_not_called()

if __name__ == '__main__': unittest.main()
