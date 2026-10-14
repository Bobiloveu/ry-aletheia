import test from 'node:test';
import assert from 'node:assert/strict';
import * as taskLines from '../../../autodrive_console/web/deployment/task-lines.js';
import {previewRouteSegments} from '../../../autodrive_console/web/deployment/execution-chain-view.js';
import {buildRouteGrid,planRouteSegments} from '../../../autodrive_console/web/deployment/route-planner.js';
import {passageIntersection} from '../../../autodrive_console/web/deployment/route-passages.js';

const passage={id:'passage',kind:'narrow_passage',map_asset_id:'a',x:0,y:0,yaw:0,attributes:{width_m:2,height_m:4}};
const project={components:[{id:'start',kind:'start',map_asset_id:'a',x:0,y:-4},passage,
  {id:'target',kind:'target',map_asset_id:'a',x:-4,y:4}]};
const line={start_component_id:'start',steps:[{kind:'component',id:'passage'},{kind:'component',id:'target'}]};

test('draft route visits both passage ends before turning toward the next target',()=>{
  const before=JSON.stringify(project);
  assert.equal(typeof taskLines.taskLineRouteSegments,'function');
  const [segment]=taskLines.taskLineRouteSegments(project,line,'a');
  assert.deepEqual(segment.points,[{x:0,y:-4},{x:0,y:-2},{x:0,y:2},{x:-4,y:4}]);
  assert.deepEqual(segment.straightPairs,[1]);
  assert.equal(JSON.stringify(project),before);
});

test('wide rotated passages traverse their long axis and reverse ends on a repeated visit',()=>{
  const p={components:[{id:'start',kind:'start',map_asset_id:'a',x:10,y:15},
    {...passage,x:10,y:10,yaw:Math.PI/2,attributes:{width_m:6,height_m:2}},
    {id:'target',kind:'target',map_asset_id:'a',x:10,y:5}]};
  assert.equal(typeof taskLines.taskLineRouteSegments,'function');
  const [segment]=taskLines.taskLineRouteSegments(p,{start_component_id:'start',steps:[
    {kind:'component',id:'passage'},{kind:'component',id:'target'},{kind:'component',id:'passage'}]},'a');
  const want=[[10,15],[10,13],[10,7],[10,5],[10,7],[10,13]];
  segment.points.forEach((point,i)=>assert.ok(Math.hypot(point.x-want[i][0],point.y-want[i][1])<1e-8));
  assert.equal(segment.points.length,6);
  assert.deepEqual(segment.straightPairs,[1,4]);
});

test('compiled outbound and return preserve the server poses and mark both passage traversals',()=>{
  const wp=(x,y)=>({pose:{position:{x,y}}});
  const preview={manifest:{subtask_map_asset_ids:['a','a']},task_json:{subtasks:[
    {subtask_name:'outbound_1',waypoints:[wp(0,-4),wp(0,-2),wp(0,2),wp(-4,4)]},
    {subtask_name:'return_2',waypoints:[wp(0,2),wp(0,-2),wp(0,-4)]},
  ]}};
  const before=JSON.stringify(preview),segments=previewRouteSegments(preview,project,'a');
  assert.deepEqual(segments.map(s=>s.straightPairs),[[1],[1]]);
  assert.deepEqual(segments[0].points,[{x:0,y:-4},{x:0,y:-2},{x:0,y:2},{x:-4,y:4}]);
  const planned=planRouteSegments(buildRouteGrid({...gridFixture(),radiusM:0}),segments);
  assert.deepEqual(planned.failures,[]);
  assert.deepEqual(planned.segments[1].paths[0],planned.segments[0].paths[0].slice().reverse());
  assert.equal(JSON.stringify(preview),before);
});

function gridFixture(){
  const width=90,height=90,rgba=new Uint8ClampedArray(width*height*4);rgba.fill(255);
  return {width,height,rgba,map:{resolution_m:.1,origin:[-4.5,-4.5,0]},
    black(x,y){rgba[(y*width+x)*4]=0;}};
}

test('passage axis stays straight even when an unconstrained route prefers higher clearance',()=>{
  const f=gridFixture();for(let y=25;y<65;y++)f.black(46,y);
  const grid=buildRouteGrid({...f,radiusM:0}),points=[{x:0,y:-2},{x:0,y:2}],cache=new Map();
  const unconstrained=planRouteSegments(grid,[{points}],cache);
  assert.equal(unconstrained.failures.length,0);
  assert.ok(unconstrained.segments[0].paths[0].some(p=>Math.abs(p.x)>.2));
  const result=planRouteSegments(grid,[{points,straightPairs:[0]}],cache);
  assert.equal(result.failures.length,0);
  assert.deepEqual(result.segments[0].paths,[points]);
  const returned=planRouteSegments(grid,[{points:points.slice().reverse(),straightPairs:[0]}],cache);
  assert.deepEqual(returned.segments[0].paths,[points.slice().reverse()]);
});

test('a blocked passage axis reports failure rather than drawing a side detour',()=>{
  const f=gridFixture();f.black(45,45);
  const grid=buildRouteGrid({...f,radiusM:0}),points=[{x:0,y:-2},{x:0,y:2}];
  assert.equal(planRouteSegments(grid,[{points}]).failures.length,0);
  const result=planRouteSegments(grid,[{points,straightPairs:[0]}]);
  assert.equal(result.failures.length,1);
  assert.deepEqual(result.segments[0].paths,[]);
});

test('a route through an unselected passage also visits its ends and turns outside',()=>{
  const f=gridFixture(),grid=buildRouteGrid({...f,radiusM:0});
  const wp=(x,y)=>({pose:{position:{x,y}}});
  const preview={manifest:{subtask_map_asset_ids:['a']},task_json:{subtasks:[
    {subtask_name:'outbound_1',waypoints:[wp(0,-3.5),wp(-3,1.9)]},
  ]}};
  const result=planRouteSegments(grid,previewRouteSegments(preview,project,'a'));
  assert.equal(result.failures.length,0);
  const points=result.segments[0].paths[0];
  const entry=points.findIndex(p=>Math.hypot(p.x,p.y+2)<1e-8);
  assert.ok(entry>=0,'route must reach the entrance end');
  assert.deepEqual(points[entry+1],{x:0,y:2});
  for(const point of [...points.slice(0,entry),...points.slice(entry+2)])
    assert.ok(!(Math.abs(point.x)<.9&&Math.abs(point.y)<1.9),'turn is inside passage');
});

test('rotated passage exterior curves cannot clip a side between raster cell centers',()=>{
  const f=gridFixture();f.width=f.height=100;f.map.origin=[-5,-5,0];
  f.rgba=new Uint8ClampedArray(100*100*4);f.rgba.fill(255);
  const component={...passage,x:.023,y:.037,yaw:.71,attributes:{width_m:1.2,height_m:4}};
  const p={components:[component]},wp=(x,y)=>({pose:{position:{x,y}}});
  const preview={manifest:{subtask_map_asset_ids:['a']},task_json:{subtasks:[{subtask_name:'outbound',waypoints:[
    wp(1.978501313,-2.238085628),wp(1.326667542,-1.479723752),wp(-1.280667542,1.553723752),wp(-2.252085628,-1.918501313),
  ]}]}};
  const segments=previewRouteSegments(preview,p,'a'),geometry=segments[0].passages[0];
  const result=planRouteSegments(buildRouteGrid({...f,radiusM:0}),segments);
  assert.equal(result.failures.length,0);
  let axes=0;
  const points=result.segments[0].paths[0];
  for(let i=1;i<points.length;i++) {
    const [a,b]=[points[i-1],points[i]];
    if(Math.hypot(a.x-geometry.ends[0].x,a.y-geometry.ends[0].y)<1e-6&&Math.hypot(b.x-geometry.ends[1].x,b.y-geometry.ends[1].y)<1e-6){axes++;continue;}
    assert.equal(passageIntersection(a,b,geometry),null,'exterior chord enters passage');
  }
  assert.equal(axes,1);
});

test('automatic passage direction follows the reachable crossing instead of the closest end',()=>{
  const f=gridFixture();f.width=f.height=100;f.map.origin=[-5,-5,0];
  f.rgba=new Uint8ClampedArray(100*100*4);f.rgba.fill(255);
  const grid=buildRouteGrid({...f,radiusM:.1,virtualWalls:[
    {start:{x:-5,y:0},end:{x:-1,y:0}},{start:{x:1,y:0},end:{x:5,y:2}},
  ]});
  const wp=(x,y)=>({pose:{position:{x,y}}});
  const preview={manifest:{subtask_map_asset_ids:['a']},task_json:{subtasks:[
    {subtask_name:'outbound',waypoints:[wp(3,.5),wp(3,3)]},
  ]}};
  const result=planRouteSegments(grid,previewRouteSegments(preview,project,'a'));
  assert.equal(result.failures.length,0);
  const points=result.segments[0].paths[0],entry=points.findIndex(p=>p.x===0&&p.y===-2);
  assert.ok(entry>=0);assert.deepEqual(points[entry+1],{x:0,y:2});
});

test('a map gap cannot choose passage direction using coordinates from the preceding map',()=>{
  const p={components:[{id:'start',kind:'start',map_asset_id:'a',x:0,y:10},
    {id:'other',kind:'target',map_asset_id:'b',x:0,y:0},passage]};
  const segments=taskLines.taskLineRouteSegments(p,{start_component_id:'start',steps:[
    {kind:'component',id:'other'},{kind:'component',id:'passage'},
  ]},'a');
  assert.equal(segments.length,4);
  assert.deepEqual(segments[1].points,[{x:0,y:-2},{x:0,y:2}]);
  assert.deepEqual(segments[2].points,[{x:0,y:2},{x:0,y:-2}]);
  assert.deepEqual(segments[3].points,[{x:0,y:10}]);
});
