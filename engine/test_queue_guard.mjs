import test from 'node:test';
import assert from 'node:assert/strict';
import {maintainQueueGuard} from './queue_guard.mjs';
const id=n=>String(n).padStart(11,'0');
function fixture() {
 const video={paused:false,currentTime:42,volume:0.4};
 const row=(n,selected=false)=>({playlistPanelVideoRenderer:{videoId:id(n),selected}});
 const state={queue:{items:[row(1,true),row(2)],automixItems:[],nextQueueItemId:3,shuffleEnabled:false,repeatMode:'NONE'}};
 // Action semantics extracted from live music_polymer_inlined_html.js:
 // ADD_AUTOMIX_ITEMS changes preview, SHIFT_AUTOPLAY_ITEMS appends playable rows,
 // RESET_SHUFFLE_ITEMS replaces playable queue from server response.
 const store={getState:()=>state,dispatch(action){
  if(action.type==='ADD_AUTOMIX_ITEMS')state.queue={...state.queue,automixItems:action.payload.automixItems};
  if(action.type==='SHIFT_AUTOPLAY_ITEMS')state.queue={...state.queue,items:[...state.queue.items,...action.payload],automixItems:state.queue.automixItems.filter(x=>!action.payload.includes(x))};
  if(action.type==='ADD_ITEMS')state.queue={...state.queue,items:[...state.queue.items,...action.payload.items]};
  if(action.type==='REMOVE_ITEM')state.queue={...state.queue,items:state.queue.items.filter((_,i)=>i!==action.payload)};
  if(action.type==='RESET_SHUFFLE_ITEMS')state.queue={...state.queue,items:action.payload.queueItems};
 }};
 const queue={queue:{store:{store}}};
 const document={querySelector:s=>s==='#queue'?queue:s==='video'?video:null};
 const promote=(...numbers)=>{const items=numbers.map(n=>row(n));store.dispatch({type:'ADD_AUTOMIX_ITEMS',payload:{automixItems:items}});store.dispatch({type:'SHIFT_AUTOPLAY_ITEMS',payload:items});};
 queue.queue.serverQueuesEnabled=false;
 return {document,video,state,store,row,promote,queue,call:(expected=[id(1),id(2)],generation='g')=>maintainQueueGuard(document,generation,expected,Date.now()+8000)};
}
test('observed autoplay promotion cleaned without touching selection, time, volume or order',()=>{
 const f=fixture();f.call();f.promote(3,4);
 const result=f.call([id(1),id(2),id(3),id(4)]);
 assert.deepEqual(result.removedIds,[id(3),id(4)]);
 assert.deepEqual(f.state.queue.items.map(x=>x.playlistPanelVideoRenderer.videoId),[id(1),id(2)]);
 assert.deepEqual(f.video,{paused:false,currentTime:42,volume:0.4});
 assert.equal(f.state.queue.items[0].playlistPanelVideoRenderer.selected,true);
});
test('manual additions and preexisting unknown/reserved rows are never deleted',()=>{
 const f=fixture();f.call();f.store.dispatch({type:'ADD_ITEMS',payload:{items:[f.row(3),f.row(4)]}});
 assert.deepEqual(f.call([id(1),id(2),id(3),id(4)]).removedIds,[]);
});
test('preview alone is not enqueue proof; direct promotion without preview is unknown',()=>{
 const f=fixture();f.call();f.store.dispatch({type:'ADD_AUTOMIX_ITEMS',payload:{automixItems:[f.row(3)]}});
 assert.deepEqual(f.call().removedIds,[]);
 f.store.dispatch({type:'SHIFT_AUTOPLAY_ITEMS',payload:[f.row(4)]});
 assert.deepEqual(f.call([id(1),id(2),id(4)]).removedIds,[]);
});
test('selected recommendation is preserved, upcoming tagged recommendations removed',()=>{
 const f=fixture();f.call();f.promote(3,4);
 f.state.queue.items[0].playlistPanelVideoRenderer.selected=false;
 f.state.queue.items[2].playlistPanelVideoRenderer.selected=true;
 assert.deepEqual(f.call([id(1),id(2),id(3),id(4)]).removedIds,[id(4)]);
});
test('pause and expired lease do not mutate queue',()=>{
 const f=fixture();f.call();f.promote(3);f.video.paused=true;
 assert.throws(()=>f.call([id(1),id(2),id(3)]));f.video.paused=false;
 assert.throws(()=>maintainQueueGuard(f.document,'g',[id(1),id(2),id(3)],Date.now()-1));
 assert.equal(f.state.queue.items.length,3);
});
test('generation change discards evidence; stale expected snapshot refuses cleanup',()=>{
 const f=fixture();f.call();f.promote(3);assert.throws(()=>f.call());
 assert.deepEqual(f.call([id(1),id(2),id(3)],'other').removedIds,[]);
});
test('cloned rows are not ownership proof',()=>{
 const f=fixture();f.call();f.promote(3);f.state.queue.items=f.state.queue.items.map(x=>structuredClone(x));
 assert.deepEqual(f.call([id(1),id(2),id(3)]).removedIds,[]);
});
test('shuffle server replacement is recorded as unproven, never cleaned automatically',()=>{
 const f=fixture();f.call();f.promote(3);
 f.store.dispatch({type:'RESET_SHUFFLE_ITEMS',payload:{queueItems:[f.row(1,true),f.row(8),f.row(9)]}});
 const r=f.call([id(1),id(8),id(9)]);assert.deepEqual(r.removedIds,[]);
 assert.equal(r.observations.at(-1).type,'RESET_SHUFFLE_ITEMS');assert.equal(r.observations.at(-1).proven,false);
});
test('server queue authority, shuffle and unknown repeat prevent unsafe local cleanup',()=>{
 for(const unsafe of ['server','unknownServer','shuffle','repeat']) {
  const f=fixture();f.call();f.promote(3);
  if(unsafe==='server')f.queue.queue.serverQueuesEnabled=true;
  if(unsafe==='unknownServer')delete f.queue.queue.serverQueuesEnabled;
  if(unsafe==='shuffle')f.state.queue.shuffleEnabled=true;
  if(unsafe==='repeat')f.state.queue.repeatMode=null;
  const r=f.call([id(1),id(2),id(3)]);
  assert.deepEqual(r.removedIds,[]);assert.ok(r.blocked);assert.equal(f.state.queue.items.length,3);
 }
});
test('manual addition interleaved after recommendations is preserved',()=>{
 const f=fixture();f.call();f.promote(3);f.store.dispatch({type:'ADD_ITEMS',payload:{items:[f.row(4)]}});
 const r=f.call([id(1),id(2),id(3),id(4)]);assert.deepEqual(r.afterIds,[id(1),id(2),id(4)]);
});
