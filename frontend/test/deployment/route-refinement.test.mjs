import test from 'node:test';
import assert from 'node:assert/strict';
import {buildRouteGrid,planRouteSegments} from '../../../autodrive_console/web/deployment/route-planner.js';
import {buildLocalRouteGrid} from '../../../autodrive_console/web/deployment/route-refinement.js';

function fixture() {
  const width=120,height=100,rgba=new Uint8ClampedArray(width*height*4);rgba.fill(255);
  const map={width,height,resolution_m:.05,origin:[0,0,0]};
  for(let y=0;y<height;y++)rgba[(y*width+10)*4]=0;
  return {width,height,rgba,map};
}

test('a valid exact start near a wall keeps its first connection after coarse pooling rejects it',()=>{
  const data=fixture(),coarse=buildRouteGrid({...data,radiusM:.34,maxCells:750});
  const start={x:.925,y:2.525},end={x:3.025,y:2.525},segments=[{leg:'outbound',points:[start,end]}],cache=new Map();
  const fine=buildLocalRouteGrid({...data,radiusM:.34},start,end);
  assert.equal(coarse.usable(start),false);
  assert.equal(fine.usable(start),true);
  assert.equal(planRouteSegments(coarse,segments,cache).failures.length,1);
  const result=planRouteSegments(coarse,segments,cache,{refineGrid:()=>fine});
  assert.equal(result.failures.length,0);
  assert.deepEqual(result.segments[0].paths[0][0],start);
  assert.deepEqual(result.segments[0].paths[0].at(-1),end);
  for(const p of result.segments[0].paths.flat())assert.ok(fine.usable(p));
  const cached=planRouteSegments(coarse,segments,cache);
  assert.deepEqual(cached,result);
});

test('local refinement preserves rotated coordinates, virtual walls and a truly obstructed start',()=>{
  const data=fixture();data.map.origin=[10,-4,Math.PI/2];
  const world=(x,y)=>({x:10-y,y:-4+x});
  const start=world(.925,2.525),end=world(3.025,2.525);
  const clear=buildLocalRouteGrid({...data,radiusM:.34},start,end);
  assert.equal(planRouteSegments(clear,[{points:[start,end]}]).failures.length,0);
  const wall={points:[world(2,0),world(2,5)]};
  const blocked=buildLocalRouteGrid({...data,radiusM:.34,virtualWalls:[wall]},start,end);
  assert.equal(planRouteSegments(blocked,[{points:[start,end]}]).failures.length,1);
  const nearWall=world(.575,2.525);
  assert.equal(clear.usable(nearWall),false,'refinement cannot move an obstructed anchor into free space');
});

test('local windows respect their cell budget and reject out-of-map endpoints',()=>{
  const data=fixture(),start={x:.925,y:2.525},end={x:3.025,y:2.525};
  assert.equal(buildLocalRouteGrid({...data,radiusM:.34},start,end,{maxCells:100}),null);
  assert.equal(buildLocalRouteGrid({...data,radiusM:.34},{x:-1,y:2},end),null);
  const local=buildLocalRouteGrid({...data,radiusM:.34},start,end);
  assert.equal(local.resolution,data.map.resolution_m);
  assert.ok(local.cost.length<=900000);
});
