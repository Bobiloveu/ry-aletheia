import test from 'node:test';
import assert from 'node:assert/strict';
import {buildRouteGrid,findRoutePath,planRouteSegments} from '../../../autodrive_console/web/deployment/route-planner.js';

function fixture(width=80,height=60,resolution=.1) {
 const rgba=new Uint8ClampedArray(width*height*4);rgba.fill(255);
 const map={width,height,resolution_m:resolution,origin:[-2,-3,0]};
 return {width,height,rgba,map,black(x,y){rgba[(y*width+x)*4]=0;},world(x,y){return {x:map.origin[0]+(x+.5)*resolution,y:map.origin[1]+(height-y-.5)*resolution};}};
}
function collisionFree(grid,points) {
 for(let i=1;i<points.length;i++)for(let t=0;t<=1;t+=.02) {
  const p={x:points[i-1].x*(1-t)+points[i].x*t,y:points[i-1].y*(1-t)+points[i].y*t};
  assert.ok(grid.usable(p),`Collision at ${JSON.stringify(p)}`);
 }
}
test('preview detours around a wall instead of connecting task nodes through it',()=>{
 const f=fixture();for(let y=0;y<43;y++)f.black(39,y);
 const grid=buildRouteGrid({...f,radiusM:.18}),start=f.world(20,20),end=f.world(60,20);
 const path=findRoutePath(grid,start,end);
 assert.equal(path.status,'ready');assert.deepEqual(path.points[0],start);assert.deepEqual(path.points.at(-1),end);
 assert.ok(path.points.some(p=>p.y<f.world(39,43).y));collisionFree(grid,path.points);
});
test('a sealed wall and an undersized doorway produce no fabricated straight route',()=>{
 const f=fixture();for(let y=0;y<60;y++)if(y<28||y>31)f.black(39,y);
 const grid=buildRouteGrid({...f,radiusM:.28});
 assert.equal(findRoutePath(grid,f.world(20,30),f.world(60,30)).status,'blocked');
});
test('saved virtual walls constrain planning even over white pixels',()=>{
 const f=fixture(),a=f.world(39,0),b=f.world(39,59);
 const grid=buildRouteGrid({...f,radiusM:.1,virtualWalls:[{points:[a,b]}]});
 const result=findRoutePath(grid,f.world(20,30),f.world(60,30));
 assert.equal(result.status,'blocked');assert.deepEqual(result.points,[]);
});
test('clearance cost favors the center of a corridor and rounds bends safely',()=>{
 const f=fixture(100,90);
 for(let y=0;y<90;y++)for(let x=0;x<100;x++)if(!((x>=10&&x<=33&&y>=10&&y<=79)||(x>=10&&x<=89&&y>=10&&y<=33)))f.black(x,y);
 const grid=buildRouteGrid({...f,radiusM:.25});
 const path=findRoutePath(grid,f.world(21,72),f.world(82,21));
 assert.equal(path.status,'ready');collisionFree(grid,path.points);
 const corridor=path.points.filter(p=>p.y<f.world(21,40).y&&p.y>f.world(21,65).y);
 assert.ok(corridor.every(p=>Math.abs(p.x-f.world(21,50).x)<.35));
 assert.ok(path.points.length>6,'bend should have sampled round geometry');
});
test('mandatory visits and duplicate visits retain their exact position and execution order',()=>{
 const f=fixture(),grid=buildRouteGrid({...f,radiusM:.1});
 const anchors=[f.world(15,20),f.world(55,20),f.world(55,45),f.world(15,20)];
 const result=planRouteSegments(grid,[{leg:'outbound',points:anchors}]);
 assert.equal(result.failures.length,0);const points=result.segments[0].paths.flat();
 let index=0;for(const p of points)if(JSON.stringify(p)===JSON.stringify(anchors[index]))index++;
 assert.equal(index,anchors.length);
});
test('map origin rotation is respected and out-of-map anchors cannot snap elsewhere',()=>{
 const f=fixture();f.map.origin=[10,20,Math.PI/2];
 const grid=buildRouteGrid({...f,radiusM:.1});
 const a={x:7,y:22},b={x:6,y:25};
 const path=findRoutePath(grid,a,b);assert.equal(path.status,'ready');collisionFree(grid,path.points);
 assert.equal(findRoutePath(grid,{x:100,y:100},b).status,'blocked');
});
test('downsampling preserves single-pixel obstacles and transparent outside regions',()=>{
 const f=fixture(200,200);f.black(100,100);f.rgba[3]=0;
 const grid=buildRouteGrid({...f,radiusM:.1,maxCells:10000});
 assert.ok(grid.width*grid.height<=10000);
 assert.equal(grid.usable(f.world(100,100)),false);
 assert.equal(grid.usable(f.world(0,0)),false);
});
test('failed intermediate connections remain separate paths without jumping across obstacles',()=>{
 const f=fixture();for(let y=0;y<60;y++)f.black(39,y);
 const anchors=[f.world(10,20),f.world(20,20),f.world(60,20),f.world(65,25)];
 const result=planRouteSegments(buildRouteGrid({...f,radiusM:.1}),[{leg:'outbound',points:anchors}]);
 assert.equal(result.failures.length,1);assert.equal(result.segments[0].paths.length,2);
 assert.deepEqual(result.segments[0].paths[0].at(-1),anchors[1]);assert.deepEqual(result.segments[0].paths[1][0],anchors[2]);
});

test('diagonal corners cannot be crossed between two blocked neighboring cells',()=>{
 const f=fixture(12,12);f.black(5,4);f.black(4,5);
 // Enclose the start so its only apparent escape would be a diagonal cut.
 for(let x=0;x<12;x++)f.black(x,3);
 for(let y=0;y<12;y++)f.black(3,y);
 const grid=buildRouteGrid({...f,radiusM:0});
 assert.equal(findRoutePath(grid,f.world(4,4),f.world(7,7)).status,'blocked');
});
test('thin maps still respect the preview cell limit and source boundaries',()=>{
 const f=fixture(5,1000);const grid=buildRouteGrid({...f,radiusM:0,maxCells:100});
 assert.ok(grid.width*grid.height<=100);
 assert.equal(grid.usable({x:f.map.origin[0]+.51,y:0}),false);
});

test('a long straight corridor stays compact instead of sampling dozens of collinear bends',()=>{
 const f=fixture(320,80),grid=buildRouteGrid({...f,radiusM:.2});
 const start=f.world(30,39),end=f.world(290,39),path=findRoutePath(grid,start,end);
 assert.equal(path.status,'ready');assert.deepEqual(path.points[0],start);assert.deepEqual(path.points.at(-1),end);
 collisionFree(grid,path.points);
 assert.ok(path.points.length<=8,`straight route has ${path.points.length} redundant vertices`);
});

test('pooled cells preserve every occupied pixel across uneven rows and thin source maps',()=>{
 for(const [width,height,maxCells] of [[13,17,30],[1,131,10],[131,1,10],[301,83,400]]){
  const f=fixture(width,height);
  for(let y=0;y<height;y++)for(let x=0;x<width;x++){
   const i=(y*width+x)*4;
   if((x*17+y*31)%19===0)f.rgba[i]=204;
   else if((x*7+y*3)%23===0)f.rgba[i+3]=127;
   else if((x+y)%5===0)f.rgba[i]=205;
  }
  const grid=buildRouteGrid({...f,radiusM:0,maxCells}),factor=Math.round(grid.resolution/f.map.resolution_m);
  for(let gy=0;gy<grid.height;gy++)for(let gx=0;gx<grid.width;gx++){
   let blocked=false;
   for(let y=gy*factor;y<Math.min(height,(gy+1)*factor);y++)for(let x=gx*factor;x<Math.min(width,(gx+1)*factor);x++){
    const i=(y*width+x)*4;blocked ||= f.rgba[i]<205||f.rgba[i+3]<128;
   }
   assert.equal(Number.isFinite(grid.cost[gy*grid.width+gx]),!blocked,`${width}x${height}, cell ${gx},${gy}`);
  }
 }
});

test('compressing a very long straight route bounds collision-check work per unit length',()=>{
 const f=fixture(10000,30,1),grid=buildRouteGrid({...f,radiusM:.34});
 const start=grid.world(10,15),end=grid.world(9989,15),index=grid.index;
 let samples=0;grid.index=p=>{samples++;return index(p);};
 const path=findRoutePath(grid,start,end);
 assert.equal(path.status,'ready');assert.deepEqual(path.points[0],start);assert.deepEqual(path.points.at(-1),end);
 assert.ok(samples<1000000,`straight-route validation used ${samples} samples`);
 assert.ok(path.points.length<2500,`straight route has ${path.points.length} redundant vertices`);
});
