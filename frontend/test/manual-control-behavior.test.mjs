import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import * as input from '../../autodrive_console/web/manual_control_input.js';

const source=readFileSync(new URL('../../autodrive_console/web/manual_control.js',import.meta.url),'utf8');
const normal={manual_ready:true,actual_source:'miniapp',runtime:'ready',can_begin_manual:true,
  session:{present:true,state:'active'},emergency_stop:{state:'normal'},
  car_state_sync:{control_source:'confirmed',emergency_stop:'confirmed'}};
function harness(){
  const nodes=new Map(),pending=[],timers=new Map();let nextTimer=0;
  const node=id=>{
    if(!nodes.has(id))nodes.set(id,{value:'0.2',min:'0.1',max:'1',dataset:{},classList:{remove(){},toggle(){}},
      setAttribute(){},removeAttribute(){}});
    return nodes.get(id);
  };
  const c=vm.createContext({...input,console,WeakMap,AbortController,Blob,
    document:{getElementById:node,querySelectorAll:()=>[]},
    navigator:{sendBeacon:(path,payload)=>pending.push({path,payload,beacon:true})},
    window:{localStorage:{getItem:()=>null},setInterval:(fn,ms)=>{const id=++nextTimer;timers.set(id,{fn,ms});return id;},
      clearInterval:id=>timers.delete(id),setTimeout:(fn,ms)=>{const id=++nextTimer;timers.set(id,{fn,ms,timeout:true});return id;},
      clearTimeout:id=>timers.delete(id)},
    requestVehicleControl:(path,payload,...options)=>new Promise((resolve,reject)=>pending.push({path,payload,options,resolve,reject})),
  });
  const start=source.indexOf('(() => {')+'(() => {'.length,end=source.indexOf('  $("enterManual").addEventListener');
  vm.runInContext(source.slice(start,end)+`;globalThis.audit={heartbeat,beginHold,render,refresh,stop,leavePageSafely,
    get:()=>({sessionId,heldVector,inputTimer,lastStatus}),setSession:id=>sessionId=id};`,c);
  c.audit.setSession('a');c.audit.render(structuredClone(normal));
  return {a:c.audit,pending,timers,node};
}
const flush=async()=>{for(let n=0;n<8;n++)await Promise.resolve();};
for(const kind of ['heartbeat','refresh'])test(`older ${kind} response cannot cancel a newer held direction`,async()=>{
  const h=harness();const older=h.a[kind]();h.a.beginHold('key:KeyI','forward');
  h.pending.find(p=>p.path.endsWith('/vector')).resolve(structuredClone(normal));await flush();
  const old=h.pending.find(p=>!p.path.endsWith('/vector'));
  old.resolve({...structuredClone(normal),manual_ready:false,emergency_stop:{state:'unknown'}});await older;
  assert.equal(h.a.get().heldVector.linearRatio,1);assert.notEqual(h.a.get().inputTimer,null);
});
test('a new unknown emergency response still clears held input',async()=>{
  const h=harness();h.a.beginHold('key:KeyI','forward');
  h.pending.at(-1).resolve(structuredClone(normal));await flush();
  const fresh=h.a.heartbeat();h.pending.at(-1).resolve({...structuredClone(normal),emergency_stop:{state:'unknown'}});await fresh;
  assert.equal(h.a.get().heldVector.linearRatio,0);assert.equal(h.a.get().inputTimer,null);
});
test('a current miniapp status can still adopt a missing local session',async()=>{
  const h=harness();h.a.setSession(null);const refreshed=h.a.refresh();
  h.pending.at(-1).resolve(structuredClone(normal));await refreshed;await flush();
  assert.equal(h.pending.filter(p=>p.path.endsWith('/enter')).length,1);
});
test('an older failed heartbeat cannot clear a newer successful input',async()=>{
  const h=harness();const old=h.a.heartbeat();h.a.beginHold('key:KeyI','forward');
  h.pending.at(-1).resolve(structuredClone(normal));await flush();
  const error=new Error('old transport failure');h.pending[0].reject(error);await old;
  assert.equal(h.a.get().heldVector.linearRatio,1);assert.notEqual(h.a.get().inputTimer,null);
});
test('held input keeps at most one motion request while HTTP is stalled',async()=>{
  const h=harness();h.a.beginHold('key:KeyI','forward');
  const tick=[...h.timers.values()].find(t=>t.ms===50).fn;
  for(let n=0;n<200;n++)tick();
  assert.equal(h.pending.filter(p=>p.path.endsWith('/vector')).length,1);
});
test('STOP bypasses stalled motion and never replays an old held vector',async()=>{
  const h=harness();h.a.beginHold('key:KeyI','forward');
  const tick=[...h.timers.values()].find(t=>t.ms===50).fn;for(let n=0;n<10;n++)tick();
  const stopped=h.a.stop();const zeros=h.pending.filter(p=>p.payload?.linear_ratio===0);
  assert.equal(zeros.length,1);assert.equal(h.pending.length,2);
  zeros[0].resolve(structuredClone(normal));await stopped;
  h.pending[0].resolve(structuredClone(normal));await flush();
  assert.equal(h.pending.length,2);assert.equal(h.a.get().heldVector.linearRatio,0);
});
test('invalid local session is cleared while aggregate status without an id is retained',async()=>{
  const h=harness();const first=h.a.refresh();h.pending.at(-1).resolve(structuredClone(normal));await first;
  assert.equal(h.a.get().sessionId,'a');
  const failed=h.a.heartbeat();const error=new Error('invalid session');error.status=409;
  error.vehicleState={...structuredClone(normal),manual_ready:false,session:{present:false,state:'none'}};
  h.pending.at(-1).reject(error);await failed;
  assert.equal(h.a.get().sessionId,null);assert.equal(h.node('enterManual').hidden,false);
});
test('leaving page releases only its own session and does so once',()=>{
  const h=harness();h.a.leavePageSafely();h.a.leavePageSafely();
  assert.equal(h.pending.filter(p=>p.beacon).length,1);
  assert.equal(h.pending[0].path,'/api/vehicle-control/release');
});
test('a newer GET cannot suppress the active motion timeout and priority STOP',async()=>{
  const h=harness();h.a.beginHold('key:KeyI','forward');const motion=h.pending.at(-1);
  const polled=h.a.refresh();h.pending.at(-1).resolve(structuredClone(normal));await polled;
  motion.reject(new Error('control timeout'));await flush();
  assert.equal(h.a.get().heldVector.linearRatio,0);
  assert.equal(h.pending.filter(p=>p.payload?.linear_ratio===0).length,1);
});
test('explicit invalid current session wins over a newer aggregate GET',async()=>{
  const h=harness();const old=h.a.heartbeat();const polled=h.a.refresh();
  h.pending.at(-1).resolve(structuredClone(normal));await polled;
  const error=new Error('invalid');error.sessionInvalid=true;
  error.vehicleState=structuredClone(normal);h.pending[0].reject(error);await old;
  assert.equal(h.a.get().sessionId,null);assert.equal(h.node('enterManual').hidden,false);
});
test('a new safety lock fences a delayed motion with one newer STOP',async()=>{
  const h=harness();h.a.beginHold('key:KeyI','forward');const motion=h.pending.at(-1);
  const polled=h.a.refresh();h.pending.at(-1).resolve({...structuredClone(normal),manual_ready:false,emergency_stop:{state:'unknown'}});await polled;
  const zero=h.pending.find(p=>p.payload?.linear_ratio===0);
  assert.ok(zero);assert.ok(zero.payload.input_sequence>motion.payload.input_sequence);
  zero.resolve({...structuredClone(normal),manual_ready:false,emergency_stop:{state:'unknown'}});await flush();
  h.a.render({...structuredClone(normal),manual_ready:false,emergency_stop:{state:'unknown'}});
  assert.equal(h.pending.filter(p=>p.payload?.linear_ratio===0).length,1);
  motion.resolve(structuredClone(normal));await flush();
  assert.equal(h.a.get().heldVector.linearRatio,0);
});
test('a current heartbeat failure fences movement started while it was pending',async()=>{
  const h=harness();const heartbeat=h.a.heartbeat();const old=h.pending.at(-1);
  h.a.beginHold('key:KeyI','forward');const motion=h.pending.at(-1);
  old.reject(new Error('connection lost'));await heartbeat;
  const zero=h.pending.find(p=>p.payload?.linear_ratio===0);
  assert.ok(zero);assert.ok(zero.payload.input_sequence>motion.payload.input_sequence);
  assert.equal(h.a.get().heldVector.linearRatio,0);
});
