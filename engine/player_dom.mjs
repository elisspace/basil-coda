// Narrow DOM bridge to this dedicated player only; never reads credentials.
import {appendRequested} from './queue_append.mjs';
import {appendAlbum} from './album_append.mjs';
import {maintainQueueGuard} from './queue_guard.mjs';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {get} from 'node:http';
const command=process.argv[2]||'status';

if(!['status','discovery-mode','append-requested','append-album','album-browse','queue-guard'].includes(command)) throw new Error('Unsupported command');
let videoId, expectedIds, deadlineMs, requirePlaying, replayIndex = null;
if(command==='album-browse') {
  if(process.argv.length!==4 || !/^MPREb_[A-Za-z0-9_-]{1,100}$/.test(process.argv[3]||'')) throw new Error('Expected official album browse ID');
} else if(command==='append-requested'||command==='append-album') {
  videoId=command==='append-album'?JSON.parse(process.argv[3]):process.argv[3];
  if(command==='append-album' ? !Array.isArray(videoId)||videoId.length<2||videoId.length>100||!videoId.every(id=>/^[A-Za-z0-9_-]{11}$/.test(id)) : !/^[A-Za-z0-9_-]{11}$/.test(videoId||'')) throw new Error('Expected exact video IDs');
  if(![7,8].includes(process.argv.length)) throw new Error('Expected bounded append admission');
  if(process.argv.length===8) replayIndex=JSON.parse(process.argv[7]);
  if(replayIndex!==null && (!Number.isInteger(replayIndex)||replayIndex<0)) throw new Error('Expected explicit replay selection');
  deadlineMs=Number(process.argv[5]);
  if(!Number.isSafeInteger(deadlineMs)||deadlineMs<=Date.now()||deadlineMs>Date.now()+8000) throw new Error('Append admission expired or invalid');
  if(!['true','false'].includes(process.argv[6])) throw new Error('Expected explicit playback policy');
  requirePlaying=process.argv[6]==='true';
  expectedIds=JSON.parse(process.argv[4]||'null');
  if(!Array.isArray(expectedIds)||!expectedIds.every(id=>typeof id==='string'&&/^[A-Za-z0-9_-]{11}$/.test(id))) throw new Error('Expected exact queue IDs');
} else if(command==='queue-guard') {
  if(process.argv.length!==6 || !/^[A-Za-z0-9_-]{1,128}$/.test(process.argv[3]||'')) throw new Error('Expected guard generation');
  expectedIds=JSON.parse(process.argv[4]||'null');
  deadlineMs=Number(process.argv[5]);
  if(!Array.isArray(expectedIds)||expectedIds.length>512||!expectedIds.every(id=>typeof id==='string'&&/^[A-Za-z0-9_-]{11}$/.test(id))) throw new Error('Expected exact bounded queue IDs');
  if(!Number.isSafeInteger(deadlineMs)||deadlineMs<=Date.now()||deadlineMs>Date.now()+8000) throw new Error('Guard admission expired or invalid');
} else if(process.argv.length>3) throw new Error('Unexpected arguments');
// Share the exact Python TOML/env resolver, including standalone invocations.
// This bridge only reads nonsecret configuration; it never opens a player.
const config=JSON.parse(execFileSync('python3',[fileURLToPath(new URL('./portable_runtime.py',import.meta.url))],{encoding:'utf8',timeout:5000}));
for(const [key,value] of Object.entries(config)) process.env['BASIL_'+key.toUpperCase()]=value;
process.env.HERMES_HOME=config.hermes_home;
const endpoint=/^http:\/\/127\.0\.0\.1:([0-9]{1,5})$/.exec(config.cdp_url);
if(!endpoint||Number(endpoint[1])<1||Number(endpoint[1])>65535) throw new Error('Unexpected player endpoint');
// node:http never consults environment proxies or follows redirects. A fresh
// direct connection avoids global fetch dispatchers and proxy-enabled agents.
const pages=await new Promise((resolve,reject)=>{
  const request=get(config.cdp_url+'/json/list',{agent:false,timeout:5000},response=>{
    if(response.statusCode!==200){response.resume();reject(new Error('Player discovery HTTP status refused'));return}
    let body='';
    response.on('data',chunk=>{body+=chunk;if(body.length>1024*1024){request.destroy();reject(new Error('Player discovery response too large'))}});
    response.on('error',()=>reject(new Error('Player discovery unavailable')));
    response.on('end',()=>{try{resolve(JSON.parse(body))}catch{reject(new Error('Player discovery invalid'))}});
  });
  request.on('timeout',()=>{request.destroy();reject(new Error('Player discovery timed out'))});
  request.on('error',()=>reject(new Error('Player discovery unavailable')));
});
if(!Array.isArray(pages)) throw new Error('Player discovery invalid');
const musicPages=pages.filter(p=>p.type==='page'&&p.url.startsWith('https://music.youtube.com/'));
if(musicPages.length!==1) throw new Error('Dedicated player unavailable or ambiguous');
const target=musicPages[0];
const socketMatch=typeof target.webSocketDebuggerUrl==='string'&&/^ws:\/\/127\.0\.0\.1:([0-9]{1,5})\/devtools\/(?:page|browser)\/[A-Za-z0-9_-]+$/.exec(target.webSocketDebuggerUrl);
if(!socketMatch||Number(socketMatch[1])!==Number(endpoint[1])) throw new Error('Unexpected player endpoint');
const socketUrl=new URL(target.webSocketDebuggerUrl);
const ws=new WebSocket(socketUrl.href);
const timer=setTimeout(()=>{console.error('Player DOM timed out');process.exit(1)},10000);
const expression=command==='album-browse'
  ? `(async()=>{const app=document.querySelector('ytmusic-app');if(typeof app?.networkManager?.fetch!=='function') throw Error('Album resolver unavailable');return await app.networkManager.fetch('/browse',{browseId:${JSON.stringify(process.argv[3])}});})()`
  : command==='append-album' ? `(${appendAlbum.toString()})(document,${JSON.stringify(videoId)},${JSON.stringify(expectedIds)},${deadlineMs},${requirePlaying},${JSON.stringify(replayIndex)})`
  : command==='append-requested'
  ? `(${appendRequested.toString()})(document,${JSON.stringify(videoId)},${JSON.stringify(expectedIds)},${deadlineMs},${requirePlaying},${JSON.stringify(replayIndex)})`
  : command==='queue-guard' ? `(${maintainQueueGuard.toString()})(document,${JSON.stringify(process.argv[3])},${JSON.stringify(expectedIds)},${deadlineMs})`
  : `(()=>{const toggle=document.querySelector('tp-yt-paper-toggle-button#automix');${command==='discovery-mode'?"if(toggle?.checked) toggle.click();":''}const v=document.querySelector('video');const q=document.querySelector('#queue')?.queue;const state=q?.store?.store?.getState()?.queue;return {autoplay:toggle?Boolean(toggle.checked):null,shuffle:state?.shuffleEnabled??null,repeat:state?.repeatMode??null,serverQueuesEnabled:q?.serverQueuesEnabled??null,selectedItemIndex:state?.selectedItemIndex??null,paused:v?.paused??null,volume:v?.volume??null,muted:v?.muted??null,currentTime:v?.currentTime??null,duration:v?.duration??null,readyState:v?.readyState??null,error:v?.error?.message??null,title:document.querySelector('ytmusic-player-bar .title')?.textContent?.trim()??null};})()`;
ws.onopen=()=>ws.send(JSON.stringify({id:1,method:'Runtime.evaluate',params:{expression,returnByValue:true,awaitPromise:true}}));
ws.onerror=()=>{clearTimeout(timer);console.error('Player DOM connection failed');process.exit(1)};
ws.onmessage=e=>{const d=JSON.parse(e.data);if(d.id!==1)return;clearTimeout(timer);if(d.result?.exceptionDetails||d.error){console.error('Player DOM evaluation failed');process.exitCode=1}else{console.log(JSON.stringify(d.result.result.value,null,2))}ws.close()};
