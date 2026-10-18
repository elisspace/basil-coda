// Minimal DOM boundary harness: no player, provider, or external dependencies.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
class Element {
  constructor() { this.tagName='DIV';this.value='';this.children=[];this.dataset={};this.style={};this.classList={add(){},remove(){}};this.listeners={};this._text='';this.hidden=false;this.scrollTop=0;this.scrollHeight=0;this.clientHeight=0; }
  set textContent(value) { this._text=String(value); }
  get textContent() { return this._text; }
  get firstChild() { return this.children[0] || this; }
  get firstElementChild() { return this.firstChild; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children=nodes.flatMap(n=>n.fragment?n.children:[n]); }
  setAttribute(k,v) { this[k]=v; }
  removeAttribute(k) { delete this[k]; }
  addEventListener(k,v) { this.listeners[k]=v; }
  focus() { document.activeElement=this; }
  scrollIntoView() {}
  closest(selector) { return selector.includes(this.tagName.toLowerCase()) ? this : null; }
  click() { if (!this.disabled) this.listeners.click?.({target:this}); }
  showModal() { this.open=true; element('shortcuts-close').focus(); }
  close() { this.open=false; this.listeners.close?.(); }
}
const elements=new Map();
const element=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
const queue=[{index:0,videoId:'past',title:'Already heard'},{index:1,videoId:'now',title:'Current',selected:true},{index:2,videoId:'next',title:'<script>not HTML</script>',artist:'Next artist'},{index:3,videoId:'last',title:'Last'}];
let chat={ok:true,messages:[],busy:false,error:'DJ request timed out; refresh player state before retrying.'};
let errorNotices=0;
const notice=element('notice-text');
Object.defineProperty(notice,'textContent',{get(){return this._text;},set(v){this._text=String(v);errorNotices++;}});
const timers=[];
const document={getElementById:element,createElement:()=>new Element(),createDocumentFragment:()=>Object.assign(new Element(),{fragment:true}),querySelectorAll:selector=>selector==='.queue-actions button'?element('queue').children.flatMap(row=>row.children[3]?.children||[]):[],listeners:{},addEventListener(k,v){this.listeners[k]=v;},activeElement:null,hidden:false};
const posts=[]; let capabilities={refill:true,queue_edit:true}; let managementOn=false; let volume=42; let historyError=false; let historyEntries=Array.from({length:150},(_,i)=>({id:String(i),timestamp:1700000000+i*86400,title:i%2?'Déjà Vu':'<script>not HTML</script>',artist:'Beyoncé',status:i%2?'played':'queued'}));
element('history-kind').value='all';
const context={document,location:{href:'http://127.0.0.1:8847/'},URL,AbortController,console,setTimeout(fn,delay){timers.push({fn,delay});return timers.length;},clearTimeout(){},fetch:async (path,options)=>{if(options.method==='POST'){posts.push({path,...options});if(path==='/api/volume')volume=JSON.parse(options.body).volume;if(path==='/api/control' && JSON.parse(options.body).action.startsWith('dj_'))managementOn=JSON.parse(options.body).action==='dj_on';}return {ok:true,json:async()=>path==='/api/chat'?chat:path==='/api/history'?(historyError?{ok:false,error:'Ledger offline'}:{ok:true,entries:historyEntries,coverage:'Fixture coverage'}):{ok:true,queue_capabilities:capabilities,volume:{volume},song:{title:'Real boundary data'},live:{paused:true},queue,session:{active:managementOn},worker_running:managementOn}};}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(new URL('../web/history-model.js',import.meta.url),'utf8'),context);
vm.runInContext(fs.readFileSync(new URL('../web/app.js',import.meta.url),'utf8'),context);
const flush=()=>new Promise(resolve=>setImmediate(resolve));
await flush();
assert.equal(element('dj-toggle').textContent, 'DJ OFF');
assert.equal(element('dj-toggle')['aria-pressed'], 'false');
assert.match(fs.readFileSync(new URL('../web/index.html', import.meta.url), 'utf8'), /id="dj-toggle"/);
element('dj-toggle').click(); await flush(); await flush();
assert.deepEqual(JSON.parse(posts.at(-1).body), {action:'dj_on'});
assert.equal(posts.at(-1).path, '/api/control');
assert.equal(element('play-text').textContent, 'Play', 'DJ ON must not resume paused playback');
assert.equal(element('dj-toggle').textContent, 'DJ ON');
assert.equal(element('dj-toggle')['aria-pressed'], 'true');
assert.match(element('session-status').textContent, /ON until OFF.*Paused: no refills/);
element('dj-toggle').click(); await flush(); await flush();
assert.deepEqual(JSON.parse(posts.at(-1).body), {action:'dj_off'});
assert.equal(element('dj-toggle').textContent, 'DJ OFF');
assert.equal(element('play-text').textContent, 'Play');
assert.equal(volume, 42);
assert.equal(posts.some(p=>p.path==='/api/control' && ['play','pause','stop'].includes(JSON.parse(p.body).action)), false);
assert.equal(element('notice').hidden,false);
assert.match(notice.textContent,/timed out.*refresh/);
assert.equal(element('queue-count').textContent,'(2)');
assert.equal(element('queue').children.length,2);
assert.equal(element('queue').children[0].children[2].children[0].textContent,'<script>not HTML</script>');
assert.equal(element('queue').children[0].children[3].children[0].dataset.boundary,'true');
assert.equal(element('queue').children[1].children[3].children[1].dataset.boundary,'true');
const queueButtons=document.querySelectorAll('.queue-actions button');
assert.deepEqual(queueButtons.map(button=>button.disabled),[true,false,false,false,true,false]);
queueButtons[1].click(); await flush(); await flush();
assert.equal(posts.at(-1).path,'/api/queue/move');
assert.deepEqual(JSON.parse(posts.at(-1).body),{videoId:'next',index:2,toIndex:3});
queueButtons[5].click(); await flush(); await flush();
assert.equal(posts.at(-1).path,'/api/queue/remove');
assert.deepEqual(JSON.parse(posts.at(-1).body),{videoId:'last',index:3});
const poll=timers.findLast(t=>t.delay===4000).fn;
await poll();await flush();
assert.equal(errorNotices,1,'An unchanged error must not reopen the notice on every poll');
chat={ok:true,messages:[{role:'assistant',content:'<img src=x onerror=alert(1)>'}],busy:false};
await poll();await flush();
assert.equal(element('chat-messages').children[0].children[1].textContent,'<img src=x onerror=alert(1)>');
chat={ok:true,messages:[],busy:false,error:'New request failed. Refresh player state before retrying.'};
await poll();await flush();
assert.equal(errorNotices,2);
assert.match(notice.textContent,/New request failed/);
element('notice').hidden=true;
element('message').value='Another request';
await element('chat-form').listeners.submit({preventDefault(){}});await flush();
assert.equal(errorNotices,3,'The same error must be shown again after a new accepted request');
assert.equal(element('notice').hidden,false);
element('notice').hidden=true;element('message').value='Third request';
await element('chat-form').listeners.submit({preventDefault(){}});await flush();
assert.equal(errorNotices,4,'Two accepted requests with identical failures must both notify');
assert.equal(element('notice').hidden,false);
await poll();await flush();assert.equal(errorNotices,4,'Polling still deduplicates the current request');
posts.length=0;
assert.equal(element('volume').value, '42');
assert.equal(element('volume').disabled, false);
element('volume').value='65'; element('volume').listeners.input();
assert.equal(posts.length,0,'Dragging volume must not write');
await element('volume').listeners.change(); await flush();
assert.equal(posts.length,1); assert.equal(JSON.parse(posts[0].body).volume,65);
assert.equal(posts[0].headers['X-Basil-Request'],'1');
element('mute').click(); await flush(); assert.equal(volume,0);
element('mute').click(); await flush(); assert.equal(volume,65);
const key=(key,target=new Element(),extra={})=>{let prevented=false;document.listeners.keydown({key,target,preventDefault(){prevented=true;},...extra});return prevented;};
const textarea=new Element();textarea.tagName='TEXTAREA';
const button=new Element();button.tagName='BUTTON';
const range=new Element();range.tagName='INPUT';
let before=posts.length;
for(const [k,target,extra] of [['n',textarea,{}],[' ',button,{}],['ArrowRight',range,{}],['n',new Element(),{ctrlKey:true}],['n',new Element(),{repeat:true}]])assert.equal(key(k,target,extra),false);
assert.equal(posts.length,before);
assert.equal(key('n'),true);await flush();assert.equal(posts.at(-1).path,'/api/control');assert.equal(JSON.parse(posts.at(-1).body).action,'next');
key('+');await flush();assert.equal(volume,70);
key('-');await flush();assert.equal(volume,65);
key(' ');await flush();assert.equal(JSON.parse(posts.at(-1).body).action,'play');
key('/');assert.equal(document.activeElement,element('history-search'));
key('h');assert.equal(document.activeElement,element('history-heading'));
key('?');assert.equal(element('shortcuts').open,true);
before=posts.length;key('n');await flush();assert.equal(posts.length,before);
assert.equal(key('Tab'),true);assert.equal(document.activeElement,element('shortcuts-close'));
key('Escape',textarea);assert.equal(element('shortcuts').open,false);
assert.equal(document.activeElement,element('history-heading'));
assert.equal(element('history-list').children.filter(e=>e.className==='history-item').length,60);
assert.match(element('history-coverage').textContent,/Fixture coverage/);
assert.match(element('history-coverage').textContent,/not proof/);
element('history-search').value='BEY deja'; element('history-search').listeners.input();
assert.match(element('history-status').textContent,/75/);
element('history-scrubber').value='1000';element('history-scrubber').listeners.input();
assert.match(element('history-page').textContent,/75–75 of 75/);
element('history-kind').value='queued';element('history-kind').listeners.change();
assert.match(element('history-status').textContent,/No records match/);
historyError=true;await element('history-refresh').listeners.click();assert.match(element('history-status').textContent,/Ledger offline/);
volume=null; await timers.findLast(t=>t.delay===2500).fn();await flush();assert.equal(element('volume').disabled,true);assert.equal(element('mute').disabled,true);
// Unavailable/missing capability envelopes must fail closed in the UI.
volume=42; capabilities={refill:false,queue_edit:false,reason:'Queue automation unavailable in fixture'};
await timers.findLast(t=>t.delay===2500).fn();await flush();
assert.equal(element('dj-toggle').disabled,true);
assert.equal(element('dj-toggle').textContent,'DJ unavailable');
assert.match(element('session-status').textContent,/unavailable in fixture/);
assert.equal(element('play-pause').disabled,false);
assert.equal(element('volume').disabled,false);
assert.ok(document.querySelectorAll('.queue-actions button').every(b=>b.disabled));
managementOn=true; await timers.findLast(t=>t.delay===2500).fn();await flush();
assert.equal(element('dj-toggle').disabled,false,'OFF must remain available for saved ON intent');
assert.equal(element('dj-toggle').textContent,'Stop manager');
element('dj-toggle').click();await flush();await flush();
assert.deepEqual(JSON.parse(posts.at(-1).body),{action:'dj_off'});
capabilities=undefined;await timers.findLast(t=>t.delay===2500).fn();await flush();
assert.equal(element('dj-toggle').disabled,true,'Missing capabilities cannot grant management');
console.log('PASS: volume readback/mute/commit, keyboard guards/modal/focus, bounded fuzzy history/time travel/error handling; async chat errors visible and deduplicated; queue future-only and bounded; metadata/replies literal text.');
