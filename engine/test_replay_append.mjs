import test from 'node:test';
import assert from 'node:assert/strict';
import {appendAlbum} from './album_append.mjs';
import {appendRequested} from './queue_append.mjs';
const a='aaaaaaaaaaa', b='bbbbbbbbbbb', c='ccccccccccc';
function fixture(delay=()=>{}) {
 let state={items:[a,b].map((videoId,i)=>({playlistPanelVideoRenderer:{videoId,selected:i===1}})),selectedItemIndex:1,repeatMode:'NONE',shuffleEnabled:false,nextQueueItemId:2};
 let writes=0;
 const queue={queue:{serverQueuesEnabled:false,store:{store:{getState:()=>({queue:state})}}},dispatch(action){writes++;state={...state,items:[...state.items,...action.payload.items]};}};
 const app={networkManager:{fetch:async()=>{delay(state);return {queueDatas:[a,c].map(videoId=>({content:{playlistPanelVideoRenderer:{videoId}}}))};}}};
 return {document:{querySelector:s=>s==='#queue'?queue:s==='video'?{paused:false}:app},writes:()=>writes};
}
for(const album of [false,true]) {
 const append=(f,index)=>album?appendAlbum(f.document,[a,c],[a,b],Date.now()+8000,true,index):appendRequested(f.document,a,[a,b],Date.now()+8000,true,index);
 test(`${album?'album':'track'} replay of played ID preserves exact order`,async()=>{
  const f=fixture();assert.deepEqual((await append(f,1)).afterIds,album?[a,b,a,c]:[a,b,a]);assert.equal(f.writes(),1);
 });
 test(`${album?'album':'track'} default still rejects played ID`,async()=>{const f=fixture();await assert.rejects(append(f,undefined));assert.equal(f.writes(),0)});
 test(`${album?'album':'track'} wrong selection and transition cancel replay`,async()=>{
  let f=fixture();await assert.rejects(append(f,0));assert.equal(f.writes(),0);
  f=fixture(state=>{state.selectedItemIndex=0});await assert.rejects(append(f,1));assert.equal(f.writes(),0);
 });
}
