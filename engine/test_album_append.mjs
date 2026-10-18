import test from 'node:test';
import assert from 'node:assert/strict';
import {appendAlbum} from './album_append.mjs';
const a='aaaaaaaaaaa', b='bbbbbbbbbbb', c='ccccccccccc';
function fixture(response, delayed) {
 let state={items:[{playlistPanelVideoRenderer:{videoId:a,selected:true}}],selectedItemIndex:0,repeatMode:'NONE',shuffleEnabled:false,nextQueueItemId:1};
 let writes=0; const video={paused:false};
 const queue={queue:{serverQueuesEnabled:false,store:{store:{getState:()=>({queue:state})}}},dispatch(action){writes++;state={...state,items:[...state.items,...action.payload.items]};}};
 const app={networkManager:{fetch:async()=>{if(delayed) await delayed(video);return {queueDatas:response.map(id=>({content:{playlistPanelVideoRenderer:{videoId:id}}}))};}}};
 return {document:{querySelector:s=>s==='#queue'?queue:s==='video'?video:app},ids:()=>state.items.map(x=>x.playlistPanelVideoRenderer.videoId),writes:()=>writes};
}
test('complete ordered album uses single dispatch, filters suggestions and server reorder',async()=>{
 const f=fixture([c,a,b]);const r=await appendAlbum(f.document,[b,c],[a],Date.now()+8000,true);
 assert.deepEqual(r.afterIds,[a,b,c]);assert.equal(f.writes(),1);
});
test('missing last song rejects whole album without any dispatch',async()=>{
 const f=fixture([b]);await assert.rejects(appendAlbum(f.document,[b,c],[a],Date.now()+8000,true));assert.equal(f.writes(),0);
});
test('pause during fetch cancels whole album',async()=>{
 const f=fixture([b,c],async v=>{v.paused=true});await assert.rejects(appendAlbum(f.document,[b,c],[a],Date.now()+8000,true));assert.equal(f.writes(),0);
});
test('lease expiry after fetch prevents late append',async()=>{
 const f=fixture([b,c],async()=>{await new Promise(r=>setTimeout(r,25))});await assert.rejects(appendAlbum(f.document,[b,c],[a],Date.now()+10,true));assert.equal(f.writes(),0);
});
