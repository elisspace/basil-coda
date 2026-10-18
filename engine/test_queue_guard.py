import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch
import dj_session
import djctl
import queue_guard

ID1='00000000001';ID2='00000000002';ID3='00000000003'
def row(video,selected=False):return {'videoId':video,'selected':selected}
from queue_test_support import QueuePrimitiveFixture
class GuardTests(QueuePrimitiveFixture):
 def setUp(self):
  super().setUp()
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=pathlib.Path(self.tmp.name)
  for module,name,value in [(dj_session,'ROOT',self.root),(dj_session,'STATE',self.root/'session.json'),(djctl,'ROOT',self.root)]:
   p=patch.object(module,name,value);p.start();self.addCleanup(p.stop)
  self.state={'active':True,'management_version':2,'generation':'test','queue_guard':{'version':1,'generation':'test','verified_ids':[ID1,ID2]}}
  dj_session.save(self.state)
 def test_off_never_submits_renderer(self):
  self.state['active']=False;dj_session.save(self.state)
  with patch('queue_guard.subprocess.check_output') as run:
   self.assertEqual(queue_guard.check()['skipped'],'OFF');run.assert_not_called()
 def test_off_lock_serializes_with_guard_and_revokes_next_check(self):
  import threading
  entered=threading.Event();release=threading.Event();off_done=threading.Event();errors=[]
  result={'generation':'test','beforeIds':[ID1,ID2],'afterIds':[ID1,ID2],'removedIds':[],'observations':[]}
  def renderer(*args,**kwargs):
   entered.set()
   if not release.wait(2):raise RuntimeError('fixture timeout')
   return json.dumps(result)
  def maintenance():
   try:queue_guard.check()
   except Exception as e:errors.append(e)
  def off():
   with dj_session.control_lock():
    state=dj_session.load();state['active']=False;dj_session.save(state)
   off_done.set()
  with patch('queue_guard.live_status',return_value={'paused':False}),patch('queue_guard.append_queue_snapshot',return_value=[row(ID1,True),row(ID2)]),patch('queue_guard.subprocess.check_output',side_effect=renderer) as run:
   t=threading.Thread(target=maintenance);t.start();self.assertTrue(entered.wait(2))
   o=threading.Thread(target=off);o.start();self.assertFalse(off_done.wait(0.02))
   release.set();t.join(2);o.join(2);self.assertTrue(off_done.is_set());self.assertFalse(errors)
   self.assertEqual(queue_guard.check()['skipped'],'OFF');self.assertEqual(run.call_count,1)
 def test_pause_never_submits_renderer(self):
  with patch('queue_guard.live_status',return_value={'paused':True}),patch('queue_guard.subprocess.check_output') as run:
   self.assertEqual(queue_guard.check()['skipped'],'paused/unknown');run.assert_not_called()
 def test_generation_mismatch_never_submits_renderer(self):
  self.state['generation']='new';dj_session.save(self.state)
  with patch('queue_guard.subprocess.check_output') as run:
   self.assertEqual(queue_guard.check()['skipped'],'not armed for this generation');run.assert_not_called()
 def test_clean_readback_persisted_and_lease_saved_before_submission(self):
  before=[row(ID1,True),row(ID2),row(ID3)];after=before[:2]
  result={'generation':'test','beforeIds':[ID1,ID2,ID3],'afterIds':[ID1,ID2],'removedIds':[ID3],'observations':[]}
  def execute(argv,**kwargs):
   self.assertEqual(argv[2],'queue-guard');self.assertGreater(dj_session.load()['append_deadline_ms'],0)
   return json.dumps(result)
  with patch('queue_guard.live_status',return_value={'paused':False}),patch('queue_guard.append_queue_snapshot',side_effect=[before,after]),patch('queue_guard.subprocess.check_output',side_effect=execute):
   self.assertEqual(queue_guard.check()['removedIds'],[ID3])
  self.assertEqual(dj_session.load()['queue_guard']['verified_ids'],[ID1,ID2])
 def test_unknown_server_replacement_preserved_and_flagged(self):
  now=[row(ID1,True),row(ID3)]
  result={'generation':'test','beforeIds':[ID1,ID3],'afterIds':[ID1,ID3],'removedIds':[],'observations':[],'blocked':'server authority'}
  with patch('queue_guard.live_status',return_value={'paused':False}),patch('queue_guard.append_queue_snapshot',side_effect=[now,now]),patch('queue_guard.subprocess.check_output',return_value=json.dumps(result)):
   self.assertIn('unexplained',queue_guard.check()['warning'])
 def test_worker_guard_warning_blocks_model_even_on_low_queue(self):
  raw={'items':[{'playlistPanelVideoRenderer':{'videoId':ID1,'selected':True}}]}
  with patch.object(dj_session,'api',side_effect=lambda method,path: {'videoId':ID1} if path=='song' else {'mode':'NONE'} if path=='repeat-mode' else raw), \
       patch.object(dj_session,'live_status',return_value={'paused':False}), \
       patch.object(queue_guard,'check',return_value={'warning':'unexplained replacement'}) as guard, \
       patch.object(dj_session.subprocess,'check_output',return_value=json.dumps({'autoplay':False})), \
       patch.object(dj_session,'run_refill') as refill, \
       patch.object(dj_session.time,'sleep',side_effect=StopIteration):
   with self.assertRaises(StopIteration):dj_session.worker()
   guard.assert_called_once();refill.assert_not_called()
   self.assertEqual(dj_session.load()['queue_guard_warning'],'unexplained replacement')
 def test_invalid_renderer_readback_does_not_advance_verified_baseline(self):
  result={'generation':'test','beforeIds':[ID1,ID2],'afterIds':[ID1],'removedIds':[ID2],'observations':[]}
  with patch('queue_guard.live_status',return_value={'paused':False}),patch('queue_guard.append_queue_snapshot',return_value=[row(ID1,True),row(ID2)]),patch('queue_guard.subprocess.check_output',return_value=json.dumps(result)):
   with self.assertRaises(ValueError):queue_guard.check()
  self.assertEqual(dj_session.load()['queue_guard']['verified_ids'],[ID1,ID2])
if __name__=='__main__':unittest.main()
