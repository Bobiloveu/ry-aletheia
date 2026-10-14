import test from 'node:test';
import assert from 'node:assert/strict';
import {buildMapContours,paintMapContours} from '../../../autodrive_console/web/deployment/map-architecture.js';

test('styled virtual walls retain open polyline segments in the architectural palette and correct map coordinates',async()=>{
  const {paintStyledVirtualWalls}=await import('../../../autodrive_console/web/deployment/map-architecture.js');
  const calls=[],ctx=Object.fromEntries(['save','restore','beginPath','rect','clip','moveTo','lineTo','stroke','closePath'].map(k=>[k,(...args)=>calls.push([k,...args])]));
  const map={id:'a',width:100,height:80,resolution_m:.05,origin:[-2,-1]};
  paintStyledVirtualWalls(ctx,{map,view:{x:10,y:20,scale:40},walls:[
    {map_asset_id:'a',points:[{x:-1,y:0},{x:0,y:0},{x:0,y:1}]},
    {map_asset_id:'b',points:[{x:-1,y:0},{x:1,y:0}]},
    {map_asset_id:'a',points:[{x:NaN,y:0},{x:0,y:0}]},
  ]});
  assert.equal(ctx.strokeStyle,'#8b99a7');assert.equal(ctx.lineWidth,2.4);
  assert.deepEqual(calls.filter(c=>c[0]==='moveTo'),[['moveTo',50,140]]);
  assert.deepEqual(calls.filter(c=>c[0]==='lineTo'),[['lineTo',90,140],['lineTo',90,100]]);
  assert.equal(calls.filter(c=>c[0]==='closePath').length,0,'an open virtual wall must never be closed implicitly');
  assert.deepEqual(calls.at(-1),['restore']);
});

function model(width,height,cells) {
  const floor=new Uint8Array(width*height);
  for(const [x,y] of cells)floor[y*width+x]=1;
  const before=floor.slice(),result=buildMapContours({floor,width,height,resolution:.05});
  assert.deepEqual(floor,before);
  return result;
}
test('rectangular passage becomes four vector corners, including map-edge boundaries',()=>{
  const cells=[];for(let y=0;y<3;y++)for(let x=0;x<4;x++)cells.push([x,y]);
  const r=model(6,5,cells);
  assert.deepEqual([...r.offsets],[0,4]);
  assert.deepEqual([...r.vertices],[0,0,4,0,4,3,0,3]);
});
test('courtyard holes and diagonal touching passages stay separate closed contours',()=>{
  const cells=[];for(let y=1;y<=5;y++)for(let x=1;x<=5;x++)if(x!==3||y!==3)cells.push([x,y]);
  const r=model(8,8,cells);
  assert.equal(r.offsets.length,3);
  const diagonal=model(3,3,[[0,0],[1,1]]);
  assert.deepEqual([...diagonal.offsets],[0,4,8]);
});
test('uniform unknown area has no invented rooms, outlines or features',()=>{
  const r=model(20,20,[]);assert.equal(r.vertices.length,0);assert.deepEqual([...r.offsets],[0]);
});
test('contour budget falls back completely, avoiding partial geometry on noisy large maps',()=>{
  const floor=Uint8Array.from({length:400},(_,i)=>(i%20+Math.floor(i/20))%2);
  const r=buildMapContours({floor,width:20,height:20,resolution:.05,maxVertices:8});
  assert.equal(r.limited,true);assert.equal(r.vertices.length,0);assert.deepEqual([...r.offsets],[0]);
});
test('contours paint with one consistent stroke and preserve caller canvas state',()=>{
  const r=model(3,3,[[1,1]]),calls=[];
  const ctx=Object.fromEntries(['save','restore','beginPath','closePath','stroke','moveTo','lineTo'].map(k=>[k,(...a)=>calls.push([k,...a])]));
  paintMapContours(ctx,r,{x:10,y:20,scale:2});
  assert.deepEqual(calls[0],['save']);assert.deepEqual(calls.at(-1),['restore']);
  assert.ok(calls.some(c=>c[0]==='moveTo'&&c[1]===12&&c[2]===22));
  assert.equal(calls.filter(c=>c[0]==='stroke').length,1);
});
test('magnified drawing skips offscreen edges without closing partial contours across the viewport',()=>{
  const calls=[],ctx=Object.fromEntries(['save','restore','beginPath','closePath','stroke','moveTo','lineTo'].map(k=>[k,(...a)=>calls.push([k,...a])]));
  paintMapContours(ctx,{resolution:.05,vertices:new Uint32Array([0,0,100,0,100,100,0,100,1000,1000,1010,1000,1010,1010,1000,1010]),offsets:new Uint32Array([0,4,8])},
    {x:-95,scale:1,viewport:{width:10,height:10}});
  assert.equal(calls.filter(c=>c[0]==='lineTo').length,2);
  assert.equal(calls.filter(c=>c[0]==='closePath').length,0);
});
test('random passage masks preserve exact signed contour area, including holes and touching corners',()=>{
  let seed=37;
  for(let n=0;n<200;n++) {
    const floor=Uint8Array.from({length:120},()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed%3===0?1:0;});
    const r=buildMapContours({floor,width:12,height:10,resolution:.05});let twiceArea=0;
    for(let p=1;p<r.offsets.length;p++)for(let i=r.offsets[p-1];i<r.offsets[p];i++) {
      const next=i+1===r.offsets[p]?r.offsets[p-1]:i+1;
      twiceArea+=r.vertices[i*2]*r.vertices[next*2+1]-r.vertices[next*2]*r.vertices[i*2+1];
    }
    assert.equal(twiceArea,2*floor.reduce((sum,value)=>sum+value,0));
  }
});
