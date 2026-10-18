"""Experimental release surface with real admission and fixture player/helper I/O."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from test_server import server, raw_queue


class ReleaseSurfaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = server.Application(runtime=Path(self.tmp.name)/'state')

    def test_on_uses_original_manager_without_transport_or_append(self):
        with patch.object(server.djctl, 'api', side_effect=lambda method,path: {'videoId':'a'} if path=='song' else raw_queue()) as api, patch.object(server.djctl, 'live_status', return_value={'paused':True}), patch.object(self.app, 'helper') as helper, patch.object(server.dj_session, 'load', return_value={'active':True,'management_version':2}), patch.object(self.app, 'worker_running', return_value=True), patch.object(server.djctl, 'append_requested') as append:
            result=self.app.control({'action':'dj_on'})
        self.assertTrue(result['ok'])
        helper.assert_called_once_with('dj_session.py','start')
        self.assertTrue(all(call.args[0]=='GET' for call in api.call_args_list))
        append.assert_not_called()

    def test_remove_and_move_reach_guarded_mutation_with_exact_readback(self):
        for operation, body, expected, method in [
            ('remove',{'index':1,'videoId':'b'},('a','c'),'DELETE'),
            ('move',{'index':2,'videoId':'c','toIndex':1},('a','c','b'),'PATCH')]:
            reads=iter([raw_queue(), raw_queue(), raw_queue(expected)])
            writes=[]
            def api(verb,path,payload=None):
                if verb=='GET':return next(reads)
                writes.append((verb,path,payload))
            with self.subTest(operation=operation), patch.object(server.djctl,'api',side_effect=api):
                result=self.app.edit_queue(operation,body)
                self.assertEqual([row['videoId'] for row in result['queue']],list(expected))
                self.assertEqual(len(writes),1)
                self.assertEqual(writes[0][0],method)

    def test_snapshots_expose_experimental_availability_not_login(self):
        def api(method,path,payload=None):
            return {'state':42,'isMuted':False} if path=='volume' else ({'videoId':'a'} if path=='song' else raw_queue())
        with patch.object(server.djctl,'api',side_effect=api),patch.object(server.djctl,'live_status',return_value={'paused':True,'serverQueuesEnabled':True}),patch.object(server.dj_session,'load',return_value={'active':True,'management_version':2}),patch.object(self.app,'worker_running',return_value=True):
            state=self.app.state()
        capabilities=state['queue_capabilities']
        self.assertEqual(capabilities['release_mode'],'experimental')
        for key in ('ready','refill','queue_edit','exact_append','queue_mutation_ready','automatic_refill_ready'):
            self.assertTrue(capabilities[key],key)
        self.assertFalse(capabilities['server_takeover'])
        self.assertTrue(capabilities['server_queues_enabled'])
        self.assertTrue(state['session']['effective_active'])

    def test_capability_failure_is_not_bypassed(self):
        with patch.object(server.djctl,'queue_capabilities',return_value={'refill':False,'queue_edit':False,'reason':'Fixture unavailable'}),patch.object(server.djctl,'api') as api,patch.object(self.app,'helper') as helper:
            for operation in (lambda:self.app.control({'action':'dj_on'}),lambda:self.app.edit_queue('remove',{'index':1,'videoId':'b'})):
                with self.assertRaises(server.APIError) as caught:operation()
                self.assertEqual(caught.exception.status,409)
            api.assert_not_called();helper.assert_not_called()

    def test_uncertain_chat_still_blocks_on_and_queue_edits(self):
        self.app.chat_unsafe=True
        with patch.object(server.djctl,'api') as api,patch.object(self.app,'helper') as helper:
            for operation in (lambda:self.app.control({'action':'dj_on'}),lambda:self.app.edit_queue('remove',{'index':1,'videoId':'b'})):
                with self.assertRaises(server.APIError) as caught:operation()
                self.assertEqual(caught.exception.status,503)
            api.assert_not_called();helper.assert_not_called()

    def test_chat_restores_guarded_queue_policy_not_blanket_denial(self):
        prompt=self.app.chat_prompt()
        self.assertNotIn('restricted preview',prompt)
        self.assertNotIn('Do not enqueue',prompt)
        self.assertIn('Use guarded enqueue helpers',prompt)
        self.assertIn('Do not start playback or replace a queue without authorization',prompt)
        self.assertIn('saved playlists, library changes',prompt)
        self.assertIn('never to escape rejection',prompt)

    def test_readme_has_one_concise_experimental_disclaimer(self):
        readme=(server.REPO/'README.md').read_text()
        self.assertEqual(readme.count('Automatic DJing and queue editing are experimental; YouTube may override queue changes.'),1)
        self.assertEqual(readme.lower().count('experimental'),1)
        self.assertNotIn('restricted preview',readme)


if __name__=='__main__':unittest.main()
