import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {requestJson} from '../../../autodrive_console/web/platform/http.js';

function browser({fetchImpl=async()=>({ok:true,status:200}), reportImpl=()=>Promise.resolve({ok:false,status:500}), now=()=>1000}={}) {
  const listeners=new Map(),reports=[];
  class XMLHttpRequest extends EventTarget {
    open(method,url){this.method=method;this.url=url;}
    finish(status,aborted=false){this.status=status;if(aborted)this.dispatchEvent(new Event('abort'));this.dispatchEvent(new Event('loadend'));}
  }
  const context=vm.createContext({URL,Promise,Map,Set,WeakSet,Date:{now},location:{origin:'http://console.test',href:'http://console.test/deployment.html?token=secret',pathname:'/deployment.html'},
    XMLHttpRequest,
    fetch(...args){if(args[0]==='/api/tool-logs/client-events'){reports.push(JSON.parse(args[1].body));return reportImpl(...args);}return fetchImpl(...args);},
    addEventListener(name,callback){const entries=listeners.get(name)||[];entries.push(callback);listeners.set(name,entries);},
  });
  context.window=context;
  const source=readFileSync(new URL('../../../autodrive_console/web/platform/client-diagnostics.js',import.meta.url),'utf8');
  const install=()=>vm.runInContext(source,context);
  install();
  return {context,reports,install,emit(name,event){for(const callback of listeners.get(name)||[])callback(event);},listeners};
}
const flush=()=>new Promise(resolve=>setImmediate(resolve));

test('early diagnostics install once and sanitize page errors without recursive reporting',async()=>{
  const app=browser();app.install();
  app.emit('error',{message:'failed https://user:pass@remote.test/a?token=secret#key authorization=secret {"password":"secret phrase"} /api/data?first=a&token=secret',filename:'http://console.test/app.js?secret=abc'});
  await flush();
  assert.equal(app.reports.length,1);
  assert.equal(app.reports[0].event,'browser_error');
  assert.equal(app.reports[0].page,'/deployment.html');
  assert.doesNotMatch(JSON.stringify(app.reports),/secret|user:pass|token=|#key/);
  assert.equal(app.listeners.get('error').length,1);
});

test('fetch keeps its response and original rejection while recording only first-party failures',async()=>{
  const response={ok:false,status:503};const failure=new TypeError('offline');
  const app=browser({fetchImpl:async url=>{if(url==='/api/offline')throw failure;return response;}});
  assert.equal(await app.context.fetch('/api/data?password=secret'),response);
  await assert.rejects(app.context.fetch('/api/offline'),error=>error===failure);
  await app.context.fetch('http://elsewhere.test/api/data');
  await flush();
  assert.equal(app.reports.length,2);
  assert.equal(app.reports[0].operation,'GET /api/data');
  assert.doesNotMatch(JSON.stringify(app.reports),/password|secret/);
});

test('expected aborts and diagnostics endpoints do not produce reports',async()=>{
  const app=browser({fetchImpl:async()=>{const error=new Error('cancel');error.name='AbortError';throw error;}});
  await assert.rejects(app.context.fetch('/api/data'));
  await assert.rejects(app.context.fetch('/api/observation/client-log'));
  app.emit('unhandledrejection',{reason:Object.assign(new Error('cancel'),{name:'AbortError'})});
  await flush();assert.equal(app.reports.length,0);
});

test('duplicate and total budgets are bounded',async()=>{
  let time=1000;const app=browser({now:()=>time});
  const report=message=>app.context.RYAletheiaDiagnostics.report({event:'operation_failed',level:'ERROR',message,operation:'map.cleanup'});
  for(let i=0;i<100;i++)report('same');
  await flush();assert.equal(app.reports.length,1);
  for(let i=0;i<200;i++){report('different '+i);await flush();}
  assert.equal(app.reports.length,60);
  time+=60001;report('same');await flush();assert.equal(app.reports.length,61);
});

test('diagnostics never accumulate work behind two pending writes',async()=>{
  const pending=[];const app=browser({reportImpl:()=>new Promise(resolve=>pending.push(resolve))});
  for(let i=0;i<100;i++)app.context.RYAletheiaDiagnostics.failure('map.cleanup','failure '+i);
  assert.equal(app.reports.length,2);
  pending.forEach(resolve=>resolve({ok:true,status:202}));await flush();
  assert.equal(app.reports.length,2,'dropped work is never queued or retried');
  app.context.RYAletheiaDiagnostics.failure('map.cleanup','new failure');
  assert.equal(app.reports.length,3);pending.at(-1)({ok:true,status:202});await flush();
});

test('legacy upload failures report without changing XHR or treating cancellation as failure',async()=>{
  const app=browser();
  const failed=new app.context.XMLHttpRequest();failed.open('POST','/api/upload?token=secret');failed.finish(500);
  const canceled=new app.context.XMLHttpRequest();canceled.open('POST','/api/upload');canceled.finish(0,true);
  await flush();assert.equal(app.reports.length,1);assert.equal(app.reports[0].operation,'POST /api/upload');
});

test('HTTP wrapper and global fetch deduplicate the same caught HTTP and transport failure',async()=>{
  const error=new TypeError('offline');
  const app=browser({fetchImpl:async url=>{if(url==='/api/offline')throw error;return {ok:false,status:500,json:async()=>({error:'private backend detail'})};}});
  const previous=globalThis.RYAletheiaDiagnostics;globalThis.RYAletheiaDiagnostics=app.context.RYAletheiaDiagnostics;
  try {
    await assert.rejects(requestJson('/api/data',{}, {fetchImpl:app.context.fetch}));
    await assert.rejects(requestJson('/api/offline',{}, {fetchImpl:app.context.fetch}));
    await flush();assert.equal(app.reports.length,2);
    assert.doesNotMatch(JSON.stringify(app.reports),/private backend detail/);
  }finally{globalThis.RYAletheiaDiagnostics=previous;}
});

test('malformed successful JSON reports a decode failure while preserving the existing empty fallback',async()=>{
  const app=browser();const previous=globalThis.RYAletheiaDiagnostics;globalThis.RYAletheiaDiagnostics=app.context.RYAletheiaDiagnostics;
  try {
    const payload=await requestJson('/api/data?token=secret',{}, {fetchImpl:async()=>({ok:true,status:200,json:async()=>{throw new SyntaxError('private response bytes');}})});
    assert.deepEqual(payload,{});await flush();assert.equal(app.reports.length,1);
    assert.equal(app.reports[0].operation,'request.json');assert.doesNotMatch(JSON.stringify(app.reports),/private|secret/);
  }finally{globalThis.RYAletheiaDiagnostics=previous;}
});

test('caught operation failure and resource errors are reported with bounded plain messages',async()=>{
  const app=browser();
  app.context.RYAletheiaDiagnostics.failure('map.export',new Error('x'.repeat(2000)));
  app.emit('error',{target:{tagName:'SCRIPT',src:'http://console.test/missing.js?token=secret'}});
  await flush();
  assert.equal(app.reports[0].event,'operation_failed');assert.ok(app.reports[0].message.length<=1200);
  assert.equal(app.reports[1].event,'resource_error');assert.doesNotMatch(JSON.stringify(app.reports),/token|secret/);
});
