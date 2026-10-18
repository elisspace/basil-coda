import test from 'node:test';
import assert from 'node:assert/strict';
import {appendRequested} from './queue_append.mjs';
import {appendAlbum} from './album_append.mjs';
const a='aaaaaaaaaaa', b='bbbbbbbbbbb', c='ccccccccccc';
function fixture(authority, mutate=()=>{}) {
 const row={playlistPanelVideoRenderer:{videoId:a,selected:true,navigationEndpoint:{watchEndpoint:{playlistId:'fixture-context'}}}};
 let state={items:[row],selectedItemIndex:0,shuffleEnabled:false,repeatMode:'NONE',queueContextParams:'fixture-context'};
 const fetches=[],writes=[];
 const queue={queue:{serverQueuesEnabled:authority,store:{store:{getState:()=>({queue:state})}}},dispatch(action){writes.push(action);state={...state,items:[...state.items,...action.payload.items]};}};
 const app={networkManager:{fetch:async(path,payload)=>{fetches.push({path,payload});mutate(state);return {queueDatas:[b,c].map(videoId=>({content:{playlistPanelVideoRenderer:{videoId}}})),commands:[{unsupported:'must never execute'}]};}}};
 return {document:{querySelector:s=>s==='#queue'?queue:s==='video'?{paused:false}:app},fetches,writes,state};
}
for(const album of [false,true]) {
 const run=f=>album?appendAlbum(f.document,[b,c],[a],Date.now()+8000):appendRequested(f.document,b,[a],Date.now()+8000);
 for(const authority of [true,false,null,undefined]) test(`${album?'album':'track'} experimental append preserves baseline with server metadata ${authority}`,async()=>{
  const f=fixture(authority);
  await run(f);
  assert.equal(f.fetches.length,1);
  assert.equal(f.fetches[0].path,'/music/get_queue');
  assert.equal(f.fetches[0].payload.queueContextParams,'fixture-context');
  assert.deepEqual(f.fetches[0].payload.videoIds,album?[b,c]:[b]);
  assert.equal(f.writes.length,1);
  assert.equal(f.writes[0].type,'ADD_ITEMS');
  assert.deepEqual(f.writes[0].payload.items.map(r=>r.playlistPanelVideoRenderer.videoId),album?[b,c]:[b]);
 });
 test(`${album?'album':'track'} shuffle still denied before request`,async()=>{
  const f=fixture(true);f.state.shuffleEnabled=true;
  await assert.rejects(run(f),/refused/);assert.equal(f.fetches.length,0);assert.equal(f.writes.length,0);
 });
 for(const change of ['shuffle','order']) test(`${album?'album':'track'} ${change} race still denied without dispatch`,async()=>{
  const f=fixture(true,state=>{
   if(change==='shuffle')state.shuffleEnabled=true;
   if(change==='order')state.items=[...state.items,{playlistPanelVideoRenderer:{videoId:c}}];
  });
  await assert.rejects(run(f),/refused/);assert.equal(f.fetches.length,1);assert.equal(f.writes.length,0);
 });
}
