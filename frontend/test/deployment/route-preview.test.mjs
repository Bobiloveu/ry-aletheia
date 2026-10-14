import test from 'node:test';
import assert from 'node:assert/strict';
import {createRoutePreview} from '../../../autodrive_console/web/deployment/route-preview.js';
const wait=()=>new Promise(resolve=>setTimeout(resolve,5));
function setup(){const sent=[],worker={postMessage:r=>sent.push(r),terminate(){}};return {sent,worker,session:createRoutePreview({workerFactory:()=>worker,delay:0})};}
test('pan/view redraw reuses work and completed maps restore without a new request',async()=>{
 const {session,sent,worker}=setup();session.sync({key:'A'});await wait();
 session.sync({key:'A'});assert.equal(sent.length,1);
 worker.onmessage({data:{key:'A',result:{segments:[1]}}});
 session.sync({key:'B'});await wait();worker.onmessage({data:{key:'B',result:{segments:[2]}}});
 session.sync({key:'A'});await wait();assert.equal(sent.length,2);assert.deepEqual(session.state.result.segments,[1]);session.dispose();
});
test('rapid edits queue only the newest job and stale results cannot repaint another map',async()=>{
 const {session,sent,worker}=setup();session.sync({key:'A'});await wait();session.sync({key:'B'});session.sync({key:'C'});await wait();
 assert.equal(sent.length,1);worker.onmessage({data:{key:'A',result:{segments:['old']}}});
 assert.equal(session.state.phase,'processing');assert.equal(sent.at(-1).key,'C');
 worker.onmessage({data:{key:'C',result:{segments:['new']}}});assert.deepEqual(session.state.result.segments,['new']);session.dispose();
});
test('worker errors clear lines, and leaving the route view discards pending repaint',async()=>{
 const {session,sent,worker}=setup();session.sync({key:'A'});await wait();worker.onmessage({data:{key:'A',error:'blocked'}});
 assert.equal(session.state.phase,'error');assert.equal(session.state.result,null);
 session.sync({key:'B'});await wait();session.sync({key:'C'});session.sync(null);
 worker.onmessage({data:{key:'B',result:{segments:['old']}}});assert.equal(session.state.phase,'idle');assert.equal(sent.length,2);session.dispose();
});

test('caught route worker failures reach the tool diagnostic bridge',async()=>{
 const previous=globalThis.RYAletheiaDiagnostics,failures=[];
 globalThis.RYAletheiaDiagnostics={failure:(operation,error)=>failures.push({operation,error})};
 const {session,worker}=setup();
 try {
  session.sync({key:'A'});await wait();worker.onmessage({data:{key:'A',error:'worker could not decode map'}});
  assert.equal(failures.length,1);assert.equal(failures[0].operation,'deployment.route-preview');
  assert.equal(failures[0].error,'worker could not decode map');
 }finally{session.dispose();globalThis.RYAletheiaDiagnostics=previous;}
});
