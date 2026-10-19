import importlib.util
import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('household_dj',pathlib.Path(__file__).with_name('__init__.py'))
assert spec is not None and spec.loader is not None
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class BoundaryTests(unittest.TestCase):
    def setUp(self):
        binding = patch.object(m, 'GROUP', 'group:fixture-household')
        binding.start()
        self.addCleanup(binding.stop)

    @patch.object(m, 'partners', return_value={'fixture-user'})
    def test_unconfigured_group_never_admits_even_matching_empty_chat(self, _partners):
        with patch.object(m, 'GROUP', ''):
            self.assertFalse(m.allowed('together', {'platform':'signal','profile':'together','chat_id':'','user_id':'fixture-user'}))

    def test_missing_binding_fails_closed(self):
        with patch.object(pathlib.Path, 'read_text', side_effect=FileNotFoundError):
            self.assertEqual(m.partners(), set())

    @patch.object(m, "partners", return_value={"member-one","member-two"})
    def test_both_members_same_group_and_wrong_context_denied(self, _partners):
        for user in ('member-one','member-two'):
            self.assertTrue(m.allowed('together',{'platform':'signal','profile':'together','chat_id':m.GROUP,'user_id':user}))
        for changes in ({'chat_id':'another-group'},{'platform':'cli'},{'profile':'default'}):
            source=dict(platform='signal',profile='together',chat_id=m.GROUP);source.update(changes)
            self.assertFalse(m.allowed('together',source))
    def test_unknown_action_and_extra_fields_never_execute(self):
        with patch.object(m,'run') as run:
            for args in ({'action':'shell'},{'action':'status','command':'whoami'},{'action':'skip','brief':'bad'},{'action':'feedback','brief':''}):
                result=m.dispatch(args)
                self.assertFalse(result['ok'])
            run.assert_not_called()
    def test_start_enables_management_without_play_or_timed_hours(self):
        def run(script, *args):
            return {'active': False} if script == 'dj_session.py' and args == ('status',) else [{'videoId':'a'}]
        with patch.object(m, 'run', side_effect=run) as helper, \
             patch.object(m, 'management', side_effect=[False, True]):
            self.assertTrue(m.dispatch({'action':'start','brief':'Hits'})['ok'])
        calls = [c.args for c in helper.call_args_list]
        self.assertIn(('dj_session.py','start','--brief','Hits'), calls)
        self.assertNotIn(('djctl.py','play'), calls)
        self.assertTrue(all('--hours' not in call for call in calls))

    def test_start_empty_queue_has_no_other_effects(self):
        with patch.object(m,'run',return_value=[]) as helper,patch.object(m,'management') as management,patch.object(m,'update_brief') as update:
            result=m.dispatch({'action':'start','brief':'New direction'})
        self.assertFalse(result['ok'])
        helper.assert_called_once_with('djctl.py','queue')
        management.assert_not_called();update.assert_not_called()

    def test_start_existing_manager_preserves_queue_and_audio(self):
        with patch.object(m,'run',return_value=[{'videoId':'a'}]) as helper,patch.object(m,'management',return_value=True),patch.object(m,'update_brief',return_value={'active':True,'queued_tracks_unchanged':True}) as update:
            result=m.dispatch({'action':'start','brief':'New direction'})
        self.assertTrue(result['ok'])
        self.assertTrue(result['result']['playback_unchanged'])
        helper.assert_called_once_with('djctl.py','queue')
        update.assert_called_once_with('New direction')

    def test_helper_whitelist_rejects_state_or_arbitrary_code(self):
        with patch.object(m.subprocess,'run') as runner:
            for script in ('../djctl.py','arbitrary.py','player-client.json'):
                with self.assertRaises(ValueError):m.run(script,'status')
            runner.assert_not_called()

    def test_helper_code_is_separate_from_private_state(self):
        with patch.object(m.subprocess, 'run') as runner:
            runner.return_value.returncode = 0
            runner.return_value.stdout = '{}'
            m.run('djctl.py', 'status')
        command = runner.call_args.args[0]
        self.assertEqual(pathlib.Path(command[1]).parent, m.ENGINE)
        self.assertNotEqual(m.ENGINE, m.WORK)
        self.assertEqual(runner.call_args.kwargs['cwd'], m.WORK)

    def test_fixed_skip_argv(self):
        with patch.object(m,'run',return_value={'title':'verified'}) as run:
            self.assertTrue(m.dispatch({'action':'skip'})['ok'])
            run.assert_called_once_with('djctl.py','next')

    def test_feedback_updates_standing_format_and_revokes_old_work_without_on(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root/'session.json').write_text(json.dumps({
                'active': False, 'brief': 'Old hits', 'queue_mode': 'tracks',
                'generation': 'old', 'refill_remaining': 4, 'custom': 'keep'}))
            with patch.object(m, 'WORK', root), patch.dict(os.environ, {'BASIL_STATE_DIR': str(root)}):
                result = m.dispatch({'action': 'feedback', 'brief': 'Full albums of beach folk today'})
            self.assertTrue(result['ok'])
            state = json.loads((root/'session.json').read_text())
            self.assertEqual(state['brief'], 'Full albums of beach folk today')
            self.assertEqual(state['queue_mode'], 'album')
            self.assertEqual(state['refill_mode'], 'album')
            self.assertNotEqual(state['generation'], 'old')
            self.assertEqual(state['refill_remaining'], 0)
            self.assertFalse(state['active'])
            self.assertEqual(state['custom'], 'keep')

    def test_feedback_reports_legacy_raw_active_as_effectively_off(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            (root/'session.json').write_text(json.dumps({
                'active': True, 'management_version': 1, 'brief': 'Old mood',
                'generation': 'old', 'queue_mode': 'tracks'}))
            with patch.object(m, 'WORK', root), patch.dict(os.environ, {'BASIL_STATE_DIR': str(root)}):
                result = m.dispatch({'action': 'feedback', 'brief': 'Quiet folk today'})
            self.assertTrue(result['ok'])
            self.assertFalse(result['result']['active'])
            state = json.loads((root/'session.json').read_text())
            self.assertEqual(state['management_version'], 1, 'Feedback must not arm legacy management')

if __name__=='__main__':unittest.main()
