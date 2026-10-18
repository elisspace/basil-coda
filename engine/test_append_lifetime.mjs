import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {appendRequested} from './queue_append.mjs';
const target='5ycyIkcX7zU', old='U8Ie9J2Eo5Q';
const item=videoId=>({playlistPanelVideoRenderer:{videoId}});
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
function pendingFixture() {
  let finish;
  const response=new Promise(resolve=>{finish=resolve;});
  let state={items:[{playlistPanelVideoRenderer:{videoId:old,selected:true}}],selectedItemIndex:0,repeatMode:'NONE',nextQueueItemId:2,shuffleEnabled:false};
  const writes=[], video={paused:false};
  const queue={queue:{serverQueuesEnabled:false,store:{store:{getState:()=>({queue:state})}}},dispatch:action=>{
    writes.push(action);state={...state,items:[...state.items,...action.payload.items]};
  }};
  const document={querySelector:selector=>selector==='#queue'?queue:selector==='video'?video:
    selector==='ytmusic-app'?{networkManager:{fetch:()=>response}}:null};
  return {document,video,writes,finish:()=>finish({queueDatas:[{content:item(target)}]}),ids:()=>state.items.map(x=>x.playlistPanelVideoRenderer.videoId)};
}
function run(f,deadlineMs=Date.now()+1000,requirePlaying=true) {
  // Execute the actual serialized CDP expression in its own renderer context.
  return vm.runInNewContext(`(${appendRequested.toString()})(document,${JSON.stringify(target)},[${JSON.stringify(old)}],${deadlineMs},${requirePlaying})`,
    {document:f.document,Date,setTimeout,clearTimeout});
}
test('client timeout leaves a real pending renderer fetch: late response cannot dispatch',async()=>{
  const f=pendingFixture();
  const pending=run(f,Date.now()+25);
  const result=pending.then(()=>({ok:true}),()=>({ok:false}));
  const client=await Promise.race([result,delay(60).then(()=>({timeout:true}))]);
  assert.equal(client.timeout,true); // Neither closing CDP nor fetch cancellation is assumed.
  f.finish();
  assert.equal((await result).ok,false);
  assert.deepEqual(f.writes,[]);assert.deepEqual(f.ids(),[old]);
});
for(const paused of [true,null,undefined]) test(`pause/unknown (${paused}) during pending fetch denies final admission`,async()=>{
  const f=pendingFixture();const pending=run(f);
  f.video.paused=paused;f.finish();
  await assert.rejects(pending,/refused/);
  assert.deepEqual(f.writes,[]);assert.deepEqual(f.ids(),[old]);
});
test('expired operation arriving after OFF cannot even fetch',async()=>{
  const f=pendingFixture();
  const pending=run(f,Date.now()-1);f.finish();
  await assert.rejects(pending,/refused/);
  assert.deepEqual(f.writes,[]);
});
test('shuffle enabled during async fetch prevents final ADD_ITEMS admission',async()=>{
  const f=pendingFixture();const pending=run(f);
  f.document.querySelector('#queue').queue.store.store.getState().queue.shuffleEnabled=true;
  f.finish();await assert.rejects(pending,/refused/);assert.deepEqual(f.writes,[]);
});
for(const shuffle of [true,null,undefined]) test(`shuffle unsafe/unknown (${shuffle}) refuses before fetch`,async()=>{
  const f=pendingFixture();
  f.document.querySelector('#queue').queue.store.store.getState().queue.shuffleEnabled=shuffle;
  const pending=run(f);f.finish();await assert.rejects(pending,/refused/);assert.deepEqual(f.writes,[]);
});
test('foreground exact append permits paused seed while still bounded',async()=>{
  const f=pendingFixture();f.video.paused=true;
  const pending=run(f,Date.now()+1000,false);f.finish();
  await pending;assert.deepEqual(f.ids(),[old,target]);
});
