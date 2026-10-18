import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync, writeFileSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';

const helper=fileURLToPath(new URL('./player_dom.mjs',import.meta.url));
function run({base='http://127.0.0.1:32102',socket='ws://127.0.0.1:32102/devtools/page/fixture',envBase,statusCode=200,args=['status']}={}) {
  const home=mkdtempSync(join(tmpdir(),'basil-node-boundary-'));
  try {
    writeFileSync(join(home,'config.toml'),`[basil]\ncdp_url=${JSON.stringify(base)}\n`);
    const preload=join(home,'fixture.mjs');
    writeFileSync(preload,`
      import net from 'node:net'; import http from 'node:http'; import https from 'node:https';
      import {EventEmitter} from 'node:events'; import {syncBuiltinESMExports} from 'node:module';
      net.Socket.prototype.connect=()=>{throw Error('network forbidden')};
      http.request=https.request=()=>{throw Error('network forbidden')};
      globalThis.fetch=()=>{throw Error('proxy-prone global fetch forbidden')};
      http.get=(url,options,callback)=>{
        if(url!==${JSON.stringify((envBase||base)+'/json/list')}) throw Error('wrong configured CDP base');
        if(options?.agent!==false) throw Error('proxy-prone agent not blocked');
        const req=new EventEmitter();req.destroy=()=>{};
        queueMicrotask(()=>{
          const response=new EventEmitter();response.statusCode=${statusCode};response.resume=()=>{};
          callback(response);
          response.emit('data',Buffer.from(JSON.stringify([{type:'page',url:'https://music.youtube.com/',webSocketDebuggerUrl:${JSON.stringify(socket)}}])));
          response.emit('end');
        });
        return req;
      };
      syncBuiltinESMExports();
      globalThis.WebSocket=class {
        constructor(url){if(url!==${JSON.stringify(socket)}) throw Error('wrong socket');queueMicrotask(()=>this.onopen())}
        send(){this.onmessage({data:JSON.stringify({id:1,result:{result:{value:{paused:true}}}})})}
        close(){}
      };
    `);
    const env=Object.fromEntries(Object.entries(process.env).filter(([key])=>!key.startsWith('BASIL_')&&!key.startsWith('HERMES_')&&key!=='PYTHONPATH'));
    Object.assign(env,{HOME:home,TMPDIR:home,BASIL_STATE_DIR:join(home,'state'),BASIL_CONFIG:join(home,'config.toml')});
    if(envBase) env.BASIL_CDP_URL=envBase;
    return spawnSync(process.execPath,['--import',preload,helper,...args],{env,cwd:home,encoding:'utf8',timeout:10000});
  } finally {rmSync(home,{recursive:true,force:true})}
}

test('standalone DOM helper loads TOML with env precedence; fetch refuses redirects',()=>{
  for(const options of [{},{envBase:'http://127.0.0.1:32103',socket:'ws://127.0.0.1:32103/devtools/page/fixture'}]) {
    const result=run(options);
    assert.equal(result.status,0,result.stderr);
    assert.deepEqual(JSON.parse(result.stdout),{paused:true});
  }
});

test('experimental queue bridge commands reach configured fixture CDP without hidden opt-in',()=>{
  for(const command of ['append-requested','append-album','discovery-mode','queue-guard']) {
    const deadline=String(Date.now()+8000);
    const args=command==='append-requested'?[command,'aaaaaaaaaaa','[]',deadline,'true']:
      command==='append-album'?[command,'["aaaaaaaaaaa","bbbbbbbbbbb"]','[]',deadline,'true']:
      command==='queue-guard'?[command,'fixture','[]',deadline]:[command];
    const result=run({args});
    assert.equal(result.status,0,result.stderr);
    assert.deepEqual(JSON.parse(result.stdout),{paused:true});
  }
});

test('DOM refuses redirects rather than following Location',()=>{
  const result=run({statusCode:302});
  assert.notEqual(result.status,0);
  assert.match(result.stderr,/Player discovery HTTP status refused/);
});

test('DOM rejects nonliteral/nonlocal/credential/query/path CDP URLs before fetch',()=>{
  for(const base of ['http://localhost:32102','http://2130706433:32102','http://127.0.0.1:32102@evil.invalid','http://127.0.0.1:32102/path','http://127.0.0.1:32102?x=1','http://127.0.0.1:0','http://127.0.0.1:65536']) {
    const result=run({base});
    assert.notEqual(result.status,0);
    assert.doesNotMatch(result.stderr,/wrong configured CDP base/);
  }
});

test('DOM debugger URL must be same literal loopback port with no auth/query',()=>{
  for(const socket of ['ws://localhost:32102/devtools/page/x','ws://2130706433:32102/devtools/page/x','ws://127.0.0.1:32103/devtools/page/x','ws://user:password@127.0.0.1:32102/devtools/page/x','wss://127.0.0.1:32102/devtools/page/x','ws://127.0.0.1:32102/devtools/page/x?token=x','ws://127.0.0.1:32102/devtools/page/x#fragment']) {
    const result=run({socket});
    assert.notEqual(result.status,0);
    assert.match(result.stderr,/Unexpected player endpoint/);
  }
});
