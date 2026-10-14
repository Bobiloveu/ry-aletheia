import test from 'node:test';
import assert from 'node:assert/strict';

test('late trajectory upload cannot attach itself to a different project', async () => {
  const { createTrajectoryPreview } = await import('../../../autodrive_console/web/deployment/trajectory-preview.js');
  let resolve;
  const pending = new Promise(done => {resolve=done;});
  const changed = [];
  const controller = createTrajectoryPreview({fetchImpl:()=>pending, onChange:s=>changed.push(s)});
  controller.setScope('one','cloud');
  const upload = controller.upload(new Blob(['pcd']));
  controller.setScope('two','other');
  resolve(new Response(new Float32Array([1,2]), {headers:{'X-Point-Count':'1','X-Point-Format':'xy-v1','X-Point-Origin':'[0,0]'}}));
  await upload;
  assert.equal(changed.at(-1).trajectory,null);
  assert.equal(changed.at(-1).busy,false);
});

test('trajectory can be hidden and removed without any map mutation request', async () => {
  const { createTrajectoryPreview } = await import('../../../autodrive_console/web/deployment/trajectory-preview.js');
  const calls=[];
  let state;
  const controller = createTrajectoryPreview({fetchImpl:async(url,options)=>{
    calls.push([url,options.method]);
    return new Response(new Float32Array([1,2]), {headers:{'X-Point-Count':'1','X-Point-Format':'xy-v1','X-Point-Origin':'[10,20]'}});
  },onChange:s=>{state=s;}});
  controller.setScope('one','cloud');
  await controller.upload(new Blob(['pcd']));
  assert.equal(state.trajectory.points.length,2);
  controller.show(false);
  assert.equal(state.visible,false);
  controller.remove();
  assert.equal(state.trajectory,null);
  assert.deepEqual(calls,[['/api/deployments/one/map-projections/cloud/trajectory-preview.bin','POST']]);
});
