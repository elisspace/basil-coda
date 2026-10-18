import unittest
from queue_test_support import QueuePrimitiveFixture
import tempfile
import pathlib
import json
from unittest.mock import patch, Mock
import dj_session
from dj_session import should_refill, compact_queue

class SessionSafety(QueuePrimitiveFixture):
    def test_stopped_expired_paused_unknown_never_refill(self):
        q={'items':[{'playlistPanelVideoRenderer':{'videoId':'a','selected':True}}]}
        song={'videoId':'a','isPaused':False}
        self.assertFalse(should_refill({'active':False,'expires':200},song,q,100))
        self.assertFalse(should_refill({'active':True,'expires':90},song,q,100))
        self.assertFalse(should_refill({'active':True,'management_version':2,'generation':'test'},dict(song,isPaused=True),q,100))
        self.assertFalse(should_refill({'active':True,'management_version':2,'generation':'test'},song,{},100))
    def test_actual_worker_refill_has_budget_and_enforces_current_brief(self):
        state={'active':True,'management_version':2,'generation':'test','brief':'Hits 1960s–2000s; 12–20% Vietnamese','exclude_library':True}
        queue={'items':[{'playlistPanelVideoRenderer':{'videoId':'a','selected':True}}]}
        def api(method,path,payload=None):
            return {'videoId':'a','isPaused':False} if path=='song' else ({'mode':'NONE'} if path=='repeat-mode' else queue)
        with tempfile.TemporaryDirectory() as tmp, patch.object(dj_session,'ROOT',pathlib.Path(tmp)), \
             patch.object(dj_session,'load',return_value=state), patch.object(dj_session,'save'), patch.object(dj_session,'live_status',return_value={'paused':False}), patch.object(dj_session,'api',side_effect=api), \
             patch.object(dj_session.subprocess,'check_output',return_value=json.dumps({'autoplay':False,'paused':False}).encode()), \
             patch.object(dj_session,'run_refill') as run, \
             patch.object(dj_session.time,'sleep',side_effect=StopIteration):
            with self.assertRaises(StopIteration): dj_session.worker()
        prompt=run.call_args.args[0]
        self.assertIn('Vietnamese',prompt)
        self.assertIn('library',prompt)
        self.assertIn('existing named helpers',prompt)
        self.assertIn(str(dj_session.CONFIG.skill),prompt)
        self.assertIn(str(pathlib.Path(tmp)/'session.json'),prompt)

    def test_wrapped_queue_and_low_watermark(self):
        items=[{'playlistPanelVideoWrapperRenderer':{'primaryRenderer':{'playlistPanelVideoRenderer':{'videoId':str(i),'selected':i==1}}}} for i in range(7)]
        q={'items':items};session={'active':True,'management_version':2,'generation':'test'}
        self.assertEqual(len(compact_queue(q)),7)
        self.assertFalse(should_refill(session,{'videoId':'1','isPaused':False},q,100))
        items[1]['playlistPanelVideoWrapperRenderer']['primaryRenderer']['playlistPanelVideoRenderer']['selected']=False
        items[5]['playlistPanelVideoWrapperRenderer']['primaryRenderer']['playlistPanelVideoRenderer']['selected']=True
        self.assertTrue(should_refill(session,{'videoId':'5','isPaused':False},q,100))

if __name__=='__main__': unittest.main()
