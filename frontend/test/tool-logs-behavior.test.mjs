import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';

const source=readFileSync(new URL('../../autodrive_console/web/tool-logs.js',import.meta.url),'utf8');
const settle=async()=>{for(let i=0;i<40;i++)await Promise.resolve();};
function harness() {
  const nodes=new Map(),requests=[],options={},timers=new Map(),intervals=new Map(),windowHandlers={};let timer=0;
  const element=()=>({textContent:'',value:'',disabled:false,hidden:false,open:false,dataset:{},handlers:{},
    classList:{toggle(){}},setAttribute(){},focus(){},
    addEventListener(name,callback){this.handlers[name]=callback;},
    showModal(){this.open=true;},close(){this.open=false;this.handlers.close?.();},
    get innerHTML(){return this._html??String(this.textContent).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');},
    set innerHTML(value){this._html=value;},
  });
  const get=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};
  const files=[{name:'video-runtime.log',label:'视频运行时',detail:'运行输出',kind:'current',file_id:'a'.repeat(24),can_clear:true,can_delete:false,size_bytes:2000000000,modified_at:1792000000},
    {name:'video-runtime.log.1',label:'视频运行时（历史）',detail:'运行输出',kind:'archive',file_id:'b'.repeat(24),can_clear:false,can_delete:true,size_bytes:1024,modified_at:1791900000}];
  const storage={total_size_bytes:2000001024,limit_bytes:268435456,policy:{retention_days:7,max_total_mib:256,max_file_mib:16},last_cleanup_at:null,last_error:null};
  const tabs=[{...element(),dataset:{scope:'all'}},{...element(),dataset:{scope:'errors'}}];
  const fileTabs=[{...element(),dataset:{fileScope:'current'}},{...element(),dataset:{fileScope:'archive'}}];
  const context=vm.createContext({document:{hidden:false,getElementById:get,createElement:element,addEventListener(){},
    querySelectorAll(selector){return selector==='.log-tab'?tabs:selector==='.file-tab'?fileTabs:[];}},
    window:{setTimeout(fn){const id=++timer;timers.set(id,fn);return id;},clearTimeout(id){timers.delete(id);},setInterval(fn){const id=++timer;intervals.set(id,fn);return id;},clearInterval(id){intervals.delete(id);},addEventListener(name,fn){windowHandlers[name]=fn;}},
    AbortController,formatFileSize:n=>`${n} bytes`,formatUnixSeconds:n=>String(n),
    requestJson:async(url,opts={})=>{
      requests.push({url,method:opts.method||'GET',body:opts.body?JSON.parse(opts.body):null,signal:opts.signal});
      if(opts.method&&opts.method!=='GET'){
        if(options.deferMutation)await new Promise(resolve=>options.finishMutation=resolve);
        if(options.failMutation)throw Error('日志文件已更新，请刷新后重试');
        return {freed_bytes:1024,removed_count:1,skipped_count:0,storage};
      }
      if(url==='/api/tool-logs/files'){
        if(options.abortFiles)await new Promise((resolve,reject)=>opts.signal.addEventListener('abort',()=>reject(Error('请求超时'))));
        if(options.deferFiles)await new Promise(resolve=>options.finishFiles=resolve);
        return {files,storage};
      }
      return {entries:[],scope:'all'};
    },
  });
  vm.runInContext(source.replace(/^import .*;\s*$/gm,''),context);
  const clickFile=kind=>get('diagnosticFileList').handlers.click({target:{closest:()=>({dataset:{logAction:kind,fileName:kind==='clear'?'video-runtime.log':'video-runtime.log.1'}})}});
  return {context,nodes,requests,options,files,storage,fileTabs,get,clickFile,timers,intervals,windowHandlers};
}

test('file management requires explicit confirmation and current/history actions stay distinct',async()=>{
  const e=harness();await settle();
  e.clickFile('clear');assert.equal(e.get('logActionDialog').open,true);
  assert.equal(e.requests.filter(r=>r.method==='POST').length,0);
  e.get('logCancelAction').handlers.click();assert.equal(e.get('logActionDialog').open,false);
  assert.equal(e.requests.filter(r=>r.method==='POST').length,0);
  e.clickFile('clear');await e.get('logConfirmAction').handlers.click();await settle();
  const clear=e.requests.find(r=>r.method==='POST');
  assert.equal(clear.url,'/api/tool-logs/files/video-runtime.log/clear');
  assert.equal(clear.body.file_id,'a'.repeat(24));assert.equal(clear.body.confirm,true);
  e.fileTabs[1].handlers.click();e.clickFile('delete');await e.get('logConfirmAction').handlers.click();await settle();
  assert.ok(e.requests.some(r=>r.method==='DELETE'&&r.url==='/api/tool-logs/files/video-runtime.log.1'));
});

test('a failed destructive request is reported and never automatically repeated',async()=>{
  const e=harness();await settle();e.options.failMutation=true;
  e.clickFile('clear');await e.get('logConfirmAction').handlers.click();await settle();
  assert.equal(e.requests.filter(r=>r.method==='POST').length,1);
  assert.match(e.get('logManagementMessage').textContent,/已更新/);
  assert.equal(e.get('logConfirmAction').disabled,false);
});

test('double confirmation cannot submit two mutations while the first is pending',async()=>{
  const e=harness();await settle();e.options.deferMutation=true;e.clickFile('clear');
  const pending=e.get('logConfirmAction').handlers.click();await settle();
  assert.equal(e.get('logConfirmAction').disabled,true);
  await e.get('logConfirmAction').handlers.click();
  assert.equal(e.requests.filter(r=>r.method==='POST').length,1);
  e.options.finishMutation();await pending;await settle();
  assert.equal(e.get('logConfirmAction').disabled,false);
});

test('refreshing sizes does not overwrite an unsaved retention edit',async()=>{
  const e=harness();await settle();e.get('retentionDays').value='30';e.get('retentionPolicyForm').handlers.input();
  await e.get('refreshLogs').handlers.click();await settle();
  assert.equal(e.get('retentionDays').value,'30');
  await e.get('retentionPolicyForm').handlers.submit({preventDefault(){}});await settle();
  const save=e.requests.find(r=>r.method==='PUT');
  assert.equal(save.url,'/api/tool-logs/retention');assert.equal(save.body.policy.retention_days,30);
});

test('file refreshes remain single-flight',async()=>{
  const e=harness();await settle();e.options.deferFiles=true;
  e.get('refreshLogs').handlers.click();e.get('refreshLogs').handlers.click();await settle();
  assert.equal(e.requests.filter(r=>r.url==='/api/tool-logs/files').length,2);
  e.options.finishFiles();await settle();
});

test('deleting all history requires its own confirmation and leaves current clear actions separate',async()=>{
  const e=harness();await settle();e.get('deleteLogHistory').handlers.click();
  assert.equal(e.requests.filter(r=>r.method==='POST').length,0);
  await e.get('logConfirmAction').handlers.click();await settle();
  const cleanup=e.requests.find(r=>r.method==='POST');
  assert.equal(cleanup.url,'/api/tool-logs/cleanup');assert.equal(cleanup.body.mode,'history');
});


test('a file-list deadline is visible and refresh can recover',async()=>{
  const e=harness();await settle();e.options.abortFiles=true;
  const pending=e.get('refreshLogs').handlers.click();await settle();
  for(const timeout of [...e.timers.values()])timeout();
  await pending;await settle();
  assert.match(e.get('logManagementMessage').textContent,/读取失败/);
  e.options.abortFiles=false;await e.get('refreshLogs').handlers.click();await settle();
  assert.match(e.get('logFileCount').textContent,/1 个当前/);
  assert.equal(e.get('logManagementMessage').textContent,'');
});

test('manual refresh during a mutation cannot reuse a pre-change file snapshot',async()=>{
  const e=harness();await settle();e.options.deferMutation=true;e.clickFile('clear');
  const pending=e.get('logConfirmAction').handlers.click();await settle();
  const before=e.requests.filter(r=>r.url==='/api/tool-logs/files').length;
  await e.get('refreshLogs').handlers.click();await settle();
  assert.equal(e.requests.filter(r=>r.url==='/api/tool-logs/files').length,before);
  e.options.finishMutation();await pending;await settle();
  assert.equal(e.requests.filter(r=>r.url==='/api/tool-logs/files').length,before+1);
});


test('restoring the page from browser back cache resumes refreshing',async()=>{
  const e=harness();await settle();
  e.windowHandlers.pagehide();assert.equal(e.intervals.size,0);
  const before=e.requests.filter(r=>r.url==='/api/tool-logs/files').length;
  e.windowHandlers.pageshow({persisted:true});await settle();
  assert.equal(e.intervals.size,1);
  assert.equal(e.requests.filter(r=>r.url==='/api/tool-logs/files').length,before+1);
});
