import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {appendRequested} from './queue_append.mjs';
const target='5ycyIkcX7zU', old='U8Ie9J2Eo5Q', other='HAYDqVSJO0Q';
const item=id=>({playlistPanelVideoRenderer:{videoId:id}});
const wrapped=id=>({playlistPanelVideoWrapperRenderer:{primaryRenderer:item(id)}});
function fixture(before, response, mutate) {
  let state={items:before.map((id,i)=>({playlistPanelVideoRenderer:{videoId:id,selected:i===0}})),selectedItemIndex:before.length?0:-1,nextQueueItemId:42,shuffleEnabled:false,repeatMode:'NONE'};
  const writes=[], fetches=[];
  const store={getState:()=>({queue:state})};
  const queue={queue:{serverQueuesEnabled:false,store:{store}}, dispatch:action=>{
    writes.push(action);
    state={...state,items:[...state.items.slice(0,action.payload.index),...action.payload.items,...state.items.slice(action.payload.index)]};
  }};
  const app={networkManager:{fetch:async(path,body)=>{
    fetches.push({path,body}); if(mutate) state={...state,items:[...state.items,item(other)]}; return response;
  }}};
  const document={querySelector:selector=>selector==='#queue'?queue:selector==='ytmusic-app'?app:null};
  return {document,writes,fetches,ids:()=>state.items.map(i=>(i.playlistPanelVideoRenderer||i.playlistPanelVideoWrapperRenderer.primaryRenderer.playlistPanelVideoRenderer).videoId)};
}
let append=(document,id,before)=>appendRequested(document,id,before,Date.now()+8000);
// Optional root-cause replay: actual installed Pear handler with a synthetic response fixture.
if(process.env.PEAR_BASELINE==='1') {
  const data=readFileSync(process.env.PEAR_ASAR || (()=>{throw Error('PEAR_BASELINE requires explicit PEAR_ASAR path');})());
  const header=JSON.parse(data.subarray(16,16+data.readUInt32LE(12)).toString());
  const entry=header.files.dist.files.renderer.files['youtube-music.iife.js'];
  const start=8+data.readUInt32LE(4)+Number(entry.offset);
  const source=data.subarray(start,start+entry.size).toString();
  const a=source.indexOf('window.ipcRenderer.on(`peard:add-to-queue`');
  const b=source.indexOf(',window.ipcRenderer.on(`peard:move-in-queue`',a);
  const handlerSource=source.slice(a,b);
  append=async(document,id)=>{
    let handler;
    vm.runInNewContext(handlerSource,{document,window:{ipcRenderer:{on:(_name,callback)=>{handler=callback;}}}});
    handler(null,id,'INSERT_AT_END');
    await new Promise(resolve=>setImmediate(resolve));
  };
}
for(const before of [[],[old]]) test(`requested only insertion into ${before.length?'nonempty':'empty'} queue`,async()=>{
  const f=fixture(before,{queueDatas:[{content:item(other)},{content:wrapped(target)},{content:item('U4zA0xnBEJU')}]});
  await append(f.document,target,before);
  assert.deepEqual(f.ids(),[...before,target]);
  assert.equal(f.writes.length,1);
  assert.equal(f.writes[0].payload.index,before.length);
  assert.equal(f.writes[0].payload.items.length,1);
  assert.equal(f.writes[0].payload.shouldAssignIds,true);
  assert.equal(f.fetches[0].path,'/music/get_queue');
  assert.deepEqual(f.fetches[0].body.videoIds,[target]);
});
if(process.env.PEAR_BASELINE!=='1') {
  for(const response of [{}, {queueDatas:[]}, {queueDatas:[{content:item(other)}]},
      {queueDatas:[{content:item(target)},{content:wrapped(target)}]}]) test('unknown/missing/duplicate requested response refuses mutation',async()=>{
    const f=fixture([old],response);
    await assert.rejects(append(f.document,target,[old]),/refused/);
    assert.equal(f.writes.length,0); assert.equal(f.fetches.length,1);
  });
  test('existing duplicate denied before fetch',async()=>{
    const f=fixture([target],{queueDatas:[{content:item(target)}]});
    await assert.rejects(append(f.document,target,[target]));
    assert.equal(f.writes.length,0); assert.equal(f.fetches.length,0);
  });
  test('stale expected order refuses before fetch',async()=>{
    const f=fixture([old,other],{});
    await assert.rejects(append(f.document,target,[other,old]));
    assert.equal(f.fetches.length,0);
  });
  test('queue race aborts without mutation or retry',async()=>{
    const f=fixture([old],{queueDatas:[{content:item(target)}]},true);
    await assert.rejects(append(f.document,target,[old]));
    assert.equal(f.writes.length,0); assert.equal(f.fetches.length,1);
  });
  test('post-dispatch expansion is ambiguous and never cleaned or retried',async()=>{
    const f=fixture([old],{queueDatas:[{content:item(target)}]});
    const queue=f.document.querySelector('#queue');
    const dispatch=queue.dispatch;
    queue.dispatch=action=>dispatch({...action,payload:{...action.payload,items:[...action.payload.items,item(other)]}});
    await assert.rejects(append(f.document,target,[old]));
    assert.equal(f.writes.length,1); assert.equal(f.fetches.length,1);
    assert.deepEqual(f.ids(),[old,target,other]);
  });
  test('unrecognizable existing row refuses before network fetch',async()=>{
    const f=fixture(['not-a-video-id'],{});
    await assert.rejects(append(f.document,target,[]));
    assert.equal(f.fetches.length,0); assert.equal(f.writes.length,0);
  });
  test('serialized fixed CDP function works without module globals',async()=>{
    const f=fixture([],{queueDatas:[{content:item(target)}]});
    const result=await vm.runInNewContext(`(${appendRequested.toString()})(document,${JSON.stringify(target)},[],Date.now()+8000)`,{document:f.document,Date,setTimeout,clearTimeout});
    assert.deepEqual(Array.from(result.afterIds),[target]);
  });
  test('invalid exact ID rejected before lookup',async()=>{
    await assert.rejects(append({querySelector:()=>assert.fail('must not read DOM')},'x;alert(1)',[]));
  });
}
