import test from 'node:test';
import assert from 'node:assert/strict';

test('fitting thin walls retains every occupied cell instead of nearest-neighbor sampling', async () => {
  const { rasterizeObstacles } = await import('../../../autodrive_console/web/deployment/raster-preview.js');
  // Four isolated wall cells all fall between the nearest-neighbor sample sites.
  const mask = rasterizeObstacles(new Uint32Array([11, 15, 51, 55]), 10,
    {width:5,height:5,x:0,y:0,scale:.5}, .5);
  assert.deepEqual([...mask.entries()].filter(([,v])=>v).map(([i])=>i), [0,2,10,12]);
});

test('preview radius changes only display coverage; pan, clipping and zoom share the image transform', async () => {
  const { rasterizeObstacles, trajectoryTransform } = await import('../../../autodrive_console/web/deployment/raster-preview.js');
  const cells = new Uint32Array([11]);
  const view = {width:8,height:8,x:2,y:1,scale:1};
  const small = rasterizeObstacles(cells,10,view,.5);
  const large = rasterizeObstacles(cells,10,view,1.5);
  assert.ok(large.reduce((a,b)=>a+b)>small.reduce((a,b)=>a+b));
  assert.deepEqual([...cells],[11]);
  const t = trajectoryTransform([10,20], {origin:[10,20,0],resolution_m:.05,height:10},view);
  assert.deepEqual([t.x+.025*t.scale,t.y-.025*t.scale,t.x+.075*t.scale,t.y-.075*t.scale], [2.5,10.5,3.5,9.5]);
});

test('offscreen obstacles never wrap into an unrelated scanline', async () => {
  const { rasterizeObstacles } = await import('../../../autodrive_console/web/deployment/raster-preview.js');
  for (const x of [-20,20]) {
    const mask = rasterizeObstacles(new Uint32Array([11]),10,{width:8,height:8,x,y:1,scale:1},.5);
    assert.equal(mask.reduce((a,b)=>a+b),0);
  }
});

test('trajectory decoder rejects truncated, wrong-format and nonfinite data', async () => {
  const { decodeTrajectory } = await import('../../../autodrive_console/web/deployment/raster-preview.js');
  const headers = new Headers({'X-Point-Count':'1','X-Point-Format':'xy-v1','X-Point-Origin':'[0,0]'});
  assert.throws(()=>decodeTrajectory(new ArrayBuffer(4),headers));
  assert.throws(()=>decodeTrajectory(new Float32Array([NaN,0]).buffer,headers));
  headers.set('X-Point-Format','xyz');
  assert.throws(()=>decodeTrajectory(new ArrayBuffer(8),headers));
});
