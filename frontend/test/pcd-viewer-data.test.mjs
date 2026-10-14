import assert from 'node:assert/strict';
import test from 'node:test';
import { decodePointPreview, readViewerLocation, readEmbeddedBand } from '../src/pcdViewerData.js';

const headers = (patch = {}) => new Headers({
  'X-Point-Count': '2', 'X-Source-Point-Count': '12', 'X-Finite-Point-Count': '11',
  'X-Point-Origin': '[1000000,2000000,3]',
  'X-Point-Bounds': '[[999999,1000001],[1999999,2000001],[2,4]]', ...patch,
});
const bytes = () => new Float32Array([-1, -1, -1, 1, 1, 1]).buffer;

test('embedded height updates accept only a valid band from the same-origin parent', () => {
  const parent = {};
  const event = { source: parent, origin: 'http://localhost', data: { type: 'aletheia-pcd-band', band: [-1, 2] } };
  assert.deepEqual(readEmbeddedBand(event, 'http://localhost', parent), [-1, 2]);
  for (const patch of [{ source: {} }, { origin: 'http://elsewhere' }, { data: null },
    ...[[2,1], [1,1], [NaN,2], ['1',2], [1,2,3]].map(band => ({ data: { type: 'aletheia-pcd-band', band } }))]) {
    assert.equal(readEmbeddedBand({ ...event, ...patch }, 'http://localhost', parent), null);
  }
});

test('source viewer preserves relative coordinates and original-coordinate bounds', () => {
  const data = decodePointPreview(bytes(), headers());
  assert.deepEqual(Array.from(data.positions), [-1,-1,-1,1,1,1]);
  assert.deepEqual(data.origin, [1000000,2000000,3]);
  assert.deepEqual(data.localBounds, [[-1,1],[-1,1],[-1,1]]);
  assert.equal(data.sampleCount, 2);
  assert.equal(data.pointCount, 12);
  assert.equal(data.finiteCount, 11);
});
test('source viewer rejects oversized, truncated and nonfinite packets', () => {
  assert.throws(() => decodePointPreview(bytes(), headers({'X-Point-Count':'100001'})));
  assert.throws(() => decodePointPreview(bytes().slice(0,12), headers()));
  assert.throws(() => decodePointPreview(new Float32Array([NaN,0,0,1,1,1]).buffer, headers()));
  assert.throws(() => decodePointPreview(bytes(), headers({'X-Point-Origin':'[0,1]'})));
  assert.throws(() => decodePointPreview(bytes(), headers({'X-Point-Bounds':'[[2,1],[0,1],[0,1]]'})));
  assert.throws(() => decodePointPreview(bytes(), headers({'X-Finite-Point-Count':'1'})));
});
test('source viewer constrains project/session query and accepts optional finite height band', () => {
  const projection = `projection-${'a'.repeat(32)}`;
  const data = readViewerLocation(`?project=site-foo&projection=${projection}&z_min=-1&z_max=2.5`);
  assert.equal(data.url, `/api/deployments/site-foo/map-projections/${projection}/source-detail.bin`);
  assert.deepEqual(data.band, [-1,2.5]);
  assert.throws(() => readViewerLocation(`?project=../../etc&projection=${projection}`));
  assert.throws(() => readViewerLocation('?project=site-foo&projection=wrong'));
  assert.equal(readViewerLocation(`?project=site-foo&projection=${projection}&z_min=NaN&z_max=2`).band, null);
});

test('height slice overlay clips extreme finite inputs to source extent without changing selected range', async () => {
  const { clipDisplayBand } = await import('../src/pcdViewerData.js');
  assert.deepEqual(clipDisplayBand([-1e300,1e300],[-2,3]), [-2,3]);
  assert.equal(clipDisplayBand([100,200],[-2,3]), null);
  assert.equal(clipDisplayBand(null,[-2,3]), null);
});

test('dense wire decodes original RGBA and intensity without confusing them with XYZ', () => {
  const wire=new ArrayBuffer(40),v=new DataView(wire);
  [[-1,0,1,10,20,30,255,12],[1,0,-1,90,80,70,255,30]].forEach((p,i)=>{
    p.slice(0,3).forEach((x,j)=>v.setFloat32(i*20+j*4,x,true));
    p.slice(3,7).forEach((x,j)=>v.setUint8(i*20+12+j,x));v.setFloat32(i*20+16,p[7],true);
  });
  const h=headers({'X-Finite-Point-Count':'2','X-Point-Format':'xyz-rgba-intensity-v1','X-Point-Attributes':JSON.stringify({rgb:true,intensity:true,intensity_range:[12,30],display_bounds:[[999999,1000001],[1999999,2000001],[2,4]]})});
  const d=decodePointPreview(wire,h);
  assert.deepEqual([...d.colors],[10,20,30,255,90,80,70,255]);
  assert.deepEqual([...d.intensities],[12,30]);assert.equal(d.defaultColorMode,'rgb');
  assert.throws(()=>decodePointPreview(wire.slice(0,39),h));
});

test('dense wire supports absent colors and rejects malformed display metadata', () => {
  const h=headers({'X-Finite-Point-Count':'2','X-Point-Format':'xyz-rgba-intensity-v1','X-Point-Attributes':JSON.stringify({rgb:false,intensity:false,intensity_range:null,display_bounds:[[999999,1000001],[1999999,2000001],[2,4]]})});
  const wire=new ArrayBuffer(40),v=new DataView(wire);v.setFloat32(16,NaN,true);v.setFloat32(36,NaN,true);
  const d=decodePointPreview(wire,h);assert.equal(d.defaultColorMode,'height');
  h.set('X-Point-Attributes','{}');assert.throws(()=>decodePointPreview(wire,h));
});


test('full detail accepts more than two million points and refuses silently sampled dense caches', () => {
  const count = 2_000_003;
  const wire = new ArrayBuffer(count * 20);
  const h = headers({'X-Point-Count':String(count),'X-Source-Point-Count':String(count),
    'X-Finite-Point-Count':String(count),'X-Point-Format':'xyz-rgba-intensity-v1',
    'X-Point-Attributes':JSON.stringify({rgb:false,intensity:false,intensity_range:null,
      display_bounds:[[999999,1000001],[1999999,2000001],[2,4]]})});
  const data = decodePointPreview(wire,h);
  assert.equal(data.positions.length, 6_000_009);
  assert.equal(data.sampleCount, count);
  h.set('X-Source-Point-Count',String(count+1));
  h.set('X-Finite-Point-Count',String(count+1));
  assert.throws(() => decodePointPreview(wire,h));
});
