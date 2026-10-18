"""Real pending renderer promise + actual OFF lease barrier, no API/CDP/model."""
import json
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import dj_session

RENDERER = r'''
import {appendRequested} from './queue_append.mjs';
let finish;
const response=new Promise(resolve=>{finish=resolve;});
const item=videoId=>({playlistPanelVideoRenderer:{videoId}});
const writes=[];let state={items:[{playlistPanelVideoRenderer:{videoId:'U8Ie9J2Eo5Q',selected:true}}],selectedItemIndex:0,repeatMode:'NONE',shuffleEnabled:false,nextQueueItemId:1};
const queue={queue:{serverQueuesEnabled:false,store:{store:{getState:()=>({queue:state})}}},dispatch:action=>{
 writes.push(action);state={...state,items:[...state.items,...action.payload.items]};
}};
const video={paused:false};
const document={querySelector:s=>s==='#queue'?queue:s==='video'?video:s==='ytmusic-app'?{networkManager:{fetch:()=>response}}:null};
const pending=appendRequested(document,'5ycyIkcX7zU',['U8Ie9J2Eo5Q'],Number(process.argv[1]),true);
const result=pending.then(()=>true,()=>false);
console.log('pending');
process.stdin.once('data',async data=>{
 const mode=data.toString().trim();if(mode==='paused')video.paused=true;if(mode==='unknown')video.paused=null;
 finish({queueDatas:[{content:item('5ycyIkcX7zU')}]});
 console.log(JSON.stringify({ok:await result,writes:writes.length,ids:state.items.map(i=>i.playlistPanelVideoRenderer.videoId)}));
});
'''

class AppendOffTests(unittest.TestCase):
    def test_off_drains_orphaned_renderer_before_return_even_if_helper_died(self):
        for mode in ('playing', 'paused', 'unknown'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root=pathlib.Path(directory)
                deadline=int(time.time()*1000)+500
                state={'active':True,'management_version':2,'generation':'fixture','append_deadline_ms':deadline}
                (root/'session.json').write_text(json.dumps(state))
                renderer=subprocess.Popen(['node','--input-type=module','-e',RENDERER,str(deadline)],
                    cwd=pathlib.Path(__file__).parent,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                assert renderer.stdin is not None and renderer.stdout is not None and renderer.stderr is not None
                try:
                    self.assertEqual(renderer.stdout.readline().strip(),'pending')
                    # Helper is already dead/released its lock; renderer is not.
                    with patch.object(dj_session,'ROOT',root), patch.object(dj_session,'STATE',root/'session.json'), patch.object(sys,'argv',['dj_session.py','stop']), \
                         patch.object(dj_session.subprocess,'run',return_value=subprocess.CompletedProcess([],0)):
                        dj_session.main()
                    off_returned=time.time()*1000
                    output,errors=renderer.communicate(mode+'\n',timeout=3)
                    self.assertEqual(renderer.returncode,0,errors)
                    result=json.loads(output)
                    self.assertFalse(result['ok'])
                    self.assertEqual(result['writes'],0)
                    self.assertEqual(result['ids'],['U8Ie9J2Eo5Q'])
                    self.assertGreaterEqual(off_returned,deadline)
                    self.assertFalse(json.loads((root/'session.json').read_text())['active'])
                finally:
                    if renderer.poll() is None: renderer.kill();renderer.wait()
                    renderer.stdin.close();renderer.stdout.close();renderer.stderr.close()

if __name__=='__main__': unittest.main()
