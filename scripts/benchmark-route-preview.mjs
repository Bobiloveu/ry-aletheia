// Run with the locked Node runtime; uses synthetic pixels, never site files.
// pixi run --frozen --no-install node scripts/benchmark-route-preview.mjs
import assert from 'node:assert/strict';
import {buildRouteGrid,planRouteSegments} from '../autodrive_console/web/deployment/route-planner.js';

const width=3200,height=2200,rgba=new Uint8ClampedArray(width*height*4);
rgba.fill(255);
const map={width,height,resolution_m:.05,origin:[0,0,0]};
for(let y=0;y<height;y++)for(let x=0;x<width;x++) {
  if(x<20||y<20||x>=width-20||y>=height-20)rgba[(y*width+x)*4]=0;
}
const visits=Array.from({length:32},(_,i)=>({x:5+(i%8)*18,y:5+Math.floor(i/8)*25}));
const segments=[{leg:'outbound',points:visits},{leg:'return',points:visits.slice().reverse()}];
const started=performance.now();
const grid=buildRouteGrid({rgba,width,height,map,radiusM:.34});
const built=performance.now(),cache=new Map();
const result=planRouteSegments(grid,segments,cache),planned=performance.now();
for(let i=0;i<20;i++)planRouteSegments(grid,segments,cache);
const cached=performance.now();

assert.equal(result.failures.length,0);
assert.ok(grid.cost.length<=900000);
for(const segment of result.segments) {
  let visited=0;
  for(const path of segment.paths) {
    for(const p of path) {
      if(p.x===segment.anchors[visited]?.x&&p.y===segment.anchors[visited]?.y)visited++;
    }
    for(let i=1;i<path.length;i++) {
      const a=path[i-1],b=path[i],samples=Math.max(1,Math.ceil(Math.hypot(b.x-a.x,b.y-a.y)/(grid.resolution*.25)));
      for(let k=0;k<=samples;k++)assert.ok(grid.usable({x:a.x+(b.x-a.x)*k/samples,y:a.y+(b.y-a.y)*k/samples}));
    }
  }
  assert.equal(visited,segment.anchors.length);
}
const rounded=value=>Math.round(value*1000)/1000;
console.log(JSON.stringify({
  sourcePixels:width*height,gridCells:grid.cost.length,visits:visits.length,
  gridMs:rounded(built-started),planMs:rounded(planned-built),
  cachedMsPerRequest:rounded((cached-planned)/20),
  vertices:result.segments.flatMap(s=>s.paths.flat()).length,
  failures:result.failures.length,
  heapMiB:rounded(process.memoryUsage().heapUsed/1048576),
  arrayBuffersMiB:rounded(process.memoryUsage().arrayBuffers/1048576),
},null,2));
