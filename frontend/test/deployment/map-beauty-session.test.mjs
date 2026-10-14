import test from 'node:test';
import assert from 'node:assert/strict';
import {createMapBeautySession} from '../../../autodrive_console/web/deployment/map-beauty-session.js';
function fixture(cacheOptions={}){
 const workers=[],states=[];
 const session=createMapBeautySession({...cacheOptions,document:{createElement(){throw Error('UI pixel readback');}},displayOptions:{bitmapFactory:async()=>({width:2,height:2}),workerFactory:()=>{const w={postMessage(data){this.input=data;},terminate(){this.stopped=true;}};workers.push(w);return w;}},onChange:s=>states.push(s)});
 const image={naturalWidth:2,naturalHeight:2}, options={resolution:.05,virtualWalls:[],passagePoints:[]};
 const sync=(extra={},edits=[])=>session.sync(image,{...options,...extra},edits);
 const ready=w=>w.onmessage({data:{result:{bitmap:{width:2,height:2,close(){this.closed=true;}},features:new Uint32Array(),shades:new Uint8Array(),stats:{}}}});
 return {session,workers,states,image,options,sync,ready};
}
test('opening and repeatedly editing raw maps never starts topology work',()=>{
 const f=fixture();f.sync();
 for(let x=0;x<100;x++)f.sync({virtualWalls:[{points:[{x,y:0},{x:1,y:1}]}]});
 assert.equal(f.workers.length,0);assert.equal(f.session.phase,'idle');
 assert.equal(f.session.display.getExportSurface(),null);
});
test('beautification requires explicit action and reuses the current completed result',async()=>{
 const f=fixture();f.sync();assert.equal(f.session.generate(),true);await Promise.resolve();
 assert.equal(f.workers.length,1);assert.equal(f.session.phase,'processing');
 f.session.generate();f.sync();assert.equal(f.workers.length,1);
 f.ready(f.workers[0]);assert.equal(f.session.phase,'ready');
 f.session.generate();assert.equal(f.workers.length,1);assert.ok(f.session.display.getExportSurface());
});
test('saved geometry or erasures cancel obsolete work and require manual regeneration',async()=>{
 const f=fixture();f.sync();f.session.generate();await Promise.resolve();const old=f.workers[0];
 const virtualWalls=[{points:[{x:0,y:0},{x:1,y:1}]}];
 f.sync({virtualWalls});assert.equal(old.stopped,true);assert.equal(f.session.phase,'dirty');
 f.ready(old);assert.equal(f.session.phase,'dirty');assert.equal(f.session.display.getExportSurface(),null);
 assert.equal(f.workers.length,1);
 f.session.generate();await Promise.resolve();f.ready(f.workers[1]);
 f.sync({virtualWalls},[{id:'erase',points:[{x:0,y:0}]}]);
 assert.equal(f.session.phase,'dirty');assert.equal(f.session.display.getExportSurface(),null);assert.equal(f.workers.length,2);
});
test('cancel, map switch, and pending edits cannot expose stale results',async()=>{
 const f=fixture();f.sync();assert.equal(f.session.generate({blocked:true}),false);assert.equal(f.workers.length,0);
 f.session.generate();await Promise.resolve();f.session.cancel();assert.equal(f.workers[0].stopped,true);assert.equal(f.session.phase,'dirty');
 f.session.sync({naturalWidth:2,naturalHeight:2},f.options,[]);assert.equal(f.session.phase,'idle');
 assert.equal(f.session.display.getExportSurface(),null);assert.equal(f.workers.length,1);
 f.session.sync(null,{},[]);assert.equal(f.session.generate(),false);
});
test('worker failure can be retried explicitly without requiring an edit',async()=>{
 const f=fixture();f.sync();f.session.generate();await Promise.resolve();
 f.workers[0].onmessage({data:{error:'failed'}});assert.equal(f.session.phase,'fallback');
 f.session.generate();await Promise.resolve();assert.equal(f.workers.length,2);assert.equal(f.session.phase,'processing');
});

test('controller blocks generation for every active geometry gesture and save',async()=>{
 const {readFileSync}=await import('node:fs'),{runInNewContext}=await import('node:vm');
 const source=readFileSync(new URL('../../../autodrive_console/web/deployment.js',import.meta.url),'utf8');
 const fn=source.match(/function mapBeautyEditing\(\) \{[\s\S]*?\n\}/)[0];
 const fields=['virtualWallDraft','virtualWallDrag','eraserStroke','eraserCommitPending','pendingPolygonErase','polygonVertexDrag','virtualWallPlacementPending','componentDrag','componentResize','componentRotate','waypointRotate','componentPlacementPending','annotationSavePending','annotationDeleteInFlight'];
 for(const field of fields) {
  const state=Object.fromEntries(fields.map(f=>[f,null]));
  Object.assign(state,{polygonEraseDraft:[],selectedProject:{id:'p'},activeMap:{id:'m'},mapEditHistory:{busy:()=>false}});
  state[field]=field==='virtualWallDraft'?{points:[{}]}:{};
  runInNewContext(fn,state);
  assert.equal(state.mapBeautyEditing(),true,field);
 }
});
test('raw preparation keeps large source uploads out of the fallback canvas path',async()=>{
 const {readFileSync}=await import('node:fs'),{runInNewContext}=await import('node:vm');
 const source=readFileSync(new URL('../../../autodrive_console/web/deployment.js',import.meta.url),'utf8');
 const fn=source.match(/function drawMapBase\(options\) \{[\s\S]*?\n\}/)?.[0];assert.ok(fn);
 let draws=0;
 const state={mapAppearance:'raw',rawMapPhase:'raw-processing',rawMapDisplay:{drawRaw:()=>{draws++;return true;}},mapDisplay:{draw(){throw Error('unexpected beauty');}}};
 runInNewContext(fn,state);assert.equal(state.drawMapBase({}),true);assert.equal(draws,0);
 state.rawMapPhase='raw-ready';assert.equal(state.drawMapBase({}),true);assert.equal(draws,1);
});
test('failed local component movement cannot become a protection anchor after switching maps',async()=>{
 const {readFileSync}=await import('node:fs'),{runInNewContext}=await import('node:vm');
 const {mapProtectionRegions}=await import('../../../autodrive_console/web/deployment/map-display.js');
 const source=readFileSync(new URL('../../../autodrive_console/web/deployment.js',import.meta.url),'utf8');
 const fn=source.match(/function refreshDisplayProtection\([^)]*\) \{[\s\S]*?\n\}/)[0];
 const map={id:'a',resolution_m:.05,origin:[0,0],height:100};
 const project={components:[{map_asset_id:'a',x:1,y:1}],waypoints:[]};
 const state={activeMap:map,selectedProject:project,displayProtection:[],displayProtectionSource:null,displayProtectionAnchors:[],mapProtectionRegions};
 runInNewContext(fn,state);state.refreshDisplayProtection(project);assert.equal(state.displayProtection[0].x,20);
 project.components[0].x=2;state.activeMap={...map,id:'b'};state.refreshDisplayProtection();
 state.activeMap=map;state.refreshDisplayProtection();assert.equal(state.displayProtection[0].x,20);
 state.refreshDisplayProtection(structuredClone(project));assert.equal(state.displayProtection[0].x,40);
});

test('completed beauty survives map switching and new Image objects without another worker',async()=>{
 const f=fixture();const a={id:'p/a',source:'sha-a'},b={id:'p/b',source:'sha-b'};
 f.session.sync(f.image,f.options,[],a);f.session.generate();await Promise.resolve();f.ready(f.workers[0]);
 const surface=f.session.display.getExportSurface();
 f.session.sync(null);f.session.sync({naturalWidth:2,naturalHeight:2},f.options,[],b);
 assert.equal(f.session.phase,'idle');assert.equal(f.session.display.getExportSurface(),null);
 f.session.sync(null);f.session.sync({naturalWidth:2,naturalHeight:2},f.options,[],a);
 assert.equal(f.session.phase,'ready');assert.equal(f.session.display.getExportSurface(),surface);assert.equal(surface.closed,undefined);
 f.session.generate();assert.equal(f.workers.length,1);
 assert.equal(f.states.at(-1).restored,true);
 const drawn=[],context={canvas:{width:2,height:2},drawImage:bitmap=>drawn.push(bitmap),save(){},restore(){},beginPath(){},rect(){},clip(){}};
 assert.equal(f.session.display.draw({context,image:{naturalWidth:2,naturalHeight:2},activeMap:{width:2,height:2,resolution_m:.05},view:{x:0,y:0,scale:20},canvasBox:{width:2,height:2},prepare:false}),true);
 assert.equal(drawn[0],surface);
});
test('ordinary annotation protection changes neither invalidate ready beauty nor cancel processing',async()=>{
 const f=fixture();f.sync();f.session.generate();await Promise.resolve();
 f.sync({protectedPoints:[{x:1,y:1,radius:8}]});assert.equal(f.session.phase,'processing');assert.notEqual(f.workers[0].stopped,true);
 f.ready(f.workers[0]);const surface=f.session.display.getExportSurface();
 f.sync({protectedPoints:[{x:2,y:3,radius:8}]});assert.equal(f.session.phase,'ready');assert.equal(f.session.display.getExportSurface(),surface);
 assert.equal(f.workers.length,1);
});
test('adding, moving and deleting start markers preserves completed beauty across map switches',async()=>{
 const {mapClosureGeometry}=await import('../../../autodrive_console/web/deployment/map-display.js');
 const f=fixture(),identity={id:'p/a',source:'v1'};
 const map={id:'a',origin:[0,0],resolution_m:.05,height:2};
 const options=waypoints=>({...f.options,...mapClosureGeometry(map,[],waypoints)});
 f.session.sync(f.image,options([]),[],identity);f.session.generate();await Promise.resolve();f.ready(f.workers[0]);
 const surface=f.session.display.getExportSurface();
 for(const waypoints of [
  [{map_asset_id:'a',kind:'start',x:.025,y:.025}],
  [{map_asset_id:'a',kind:'start',x:.075,y:.075,yaw:1}],
  [],
 ]) {
  f.session.sync(f.image,options(waypoints),[],identity);
  assert.equal(f.session.phase,'ready');assert.equal(f.session.display.getExportSurface(),surface);
  f.session.sync(f.image,f.options,[],{id:'p/b'});
  f.session.sync({...f.image},options(waypoints),[],identity);
  assert.equal(f.session.phase,'ready');assert.equal(f.session.display.getExportSurface(),surface);
 }
 assert.equal(f.workers.length,1);assert.notEqual(surface.closed,true);
});
test('start edits keep in-flight beauty and become seeds for the next geometry regeneration',async()=>{
 const f=fixture();f.sync();f.session.generate();await Promise.resolve();const old=f.workers[0];
 f.sync({passagePoints:[{x:1,y:1}]});
 assert.equal(f.session.phase,'processing');assert.notEqual(old.stopped,true);
 f.ready(old);assert.equal(f.session.phase,'ready');
 const virtualWalls=[{points:[{x:0,y:0},{x:1,y:1}]}];
 f.sync({virtualWalls,passagePoints:[{x:1,y:0}]});assert.equal(f.session.phase,'dirty');
 assert.equal(f.workers.length,1);
 f.session.generate();await Promise.resolve();
 assert.deepEqual(f.workers[1].input.passagePoints,[{x:1,y:0}]);
 f.ready(f.workers[1]);assert.equal(f.session.phase,'ready');
});
test('only the changed map invalidates; source changes and relevant protection remain inputs',async()=>{
 const f=fixture(),a={id:'p/a',source:'v1'},b={id:'p/b',source:'v1'};
 f.session.sync(f.image,f.options,[],a);f.session.generate();await Promise.resolve();f.ready(f.workers[0]);const surfaceA=f.session.display.getExportSurface();
 f.session.sync(f.image,f.options,[],b);f.session.generate();await Promise.resolve();f.ready(f.workers[1]);
 f.session.sync(f.image,{...f.options,virtualWalls:[{points:[{x:0,y:0},{x:1,y:1}]}]},[],b);
 assert.equal(f.session.phase,'dirty');assert.equal(f.session.display.getExportSurface(),null);
 f.session.sync(f.image,f.options,[],a);assert.equal(f.session.display.getExportSurface(),surfaceA);
 f.session.sync(f.image,f.options,[],{...a,source:'v2'});assert.equal(f.session.phase,'dirty');assert.equal(surfaceA.closed,true);
 f.session.generate();await Promise.resolve();f.ready(f.workers[2]);
 f.session.sync(f.image,{...f.options,removeIsolated:true,protectedPoints:[{x:0,y:0,radius:1}]},[],a);assert.equal(f.session.phase,'dirty');
});
test('an unfinished worker is canceled on switch and cannot overwrite another map cache',async()=>{
 const f=fixture(),a={id:'p/a'},b={id:'p/b'};
 f.session.sync(f.image,f.options,[],a);f.session.generate();await Promise.resolve();const old=f.workers[0];
 f.session.sync(f.image,f.options,[],b);assert.equal(old.stopped,true);assert.equal(f.session.phase,'idle');
 f.ready(old);assert.equal(f.session.phase,'idle');assert.equal(f.session.display.getExportSurface(),null);
 f.session.sync(f.image,f.options,[],a);assert.equal(f.session.phase,'dirty');
});
test('map cache releases the least recently used inactive bitmap at its capacity',async()=>{
 let worker;const states=[];
 const session=createMapBeautySession({document:{},maxEntries:2,maxBytes:1000,displayOptions:{bitmapFactory:async()=>({width:2,height:2}),workerFactory:()=>worker={postMessage(){},terminate(){}}},onChange:s=>states.push(s)});
 const image={naturalWidth:2,naturalHeight:2},options={resolution:.05};const surfaces=[];
 for(const id of ['a','b','c']) {
  session.sync(image,options,[],{id});session.generate();await Promise.resolve();
  const bitmap={width:2,height:2,close(){this.closed=true;}};surfaces.push(bitmap);
  worker.onmessage({data:{result:{bitmap,features:new Uint32Array(),shades:new Uint8Array()}}});
 }
 assert.equal(surfaces[0].closed,true);assert.notEqual(surfaces[1].closed,true);assert.notEqual(surfaces[2].closed,true);
 session.sync(image,options,[],{id:'b'});assert.equal(session.phase,'ready');assert.equal(session.display.getExportSurface(),surfaces[1]);
 session.dispose();assert.equal(surfaces[1].closed,true);assert.equal(surfaces[2].closed,true);
});
test('cache identity depends on the project and source map rather than component edits or labels',async()=>{
 const {mapBeautyIdentity}=await import('../../../autodrive_console/web/deployment/map-beauty-session.js');
 const map={id:'a',width:2,height:2,resolution_m:.05,origin:[0,0,0],files:{image:'maps/a/map.pgm'},sha256:{'map.pgm':'v1'}};
 const original=mapBeautyIdentity('p',map);
 assert.deepEqual(mapBeautyIdentity('p',{...map,label:'new name'}),original);
 assert.notDeepEqual(mapBeautyIdentity('q',map),original);
 assert.notDeepEqual(mapBeautyIdentity('p',{...map,sha256:{'map.pgm':'v2'}}),original);
});
test('component gestures do not cancel topology work; wall and erase gestures do',async()=>{
 const {readFileSync}=await import('node:fs'),{runInNewContext}=await import('node:vm');
 const source=readFileSync(new URL('../../../autodrive_console/web/deployment.js',import.meta.url),'utf8');
 const fn=source.match(/function mapBeautyTopologyEditing\(\) \{[\s\S]*?\n\}/)?.[0];assert.ok(fn);
 const state={virtualWallDraft:null,virtualWallDrag:null,polygonEraseDraft:[],eraserStroke:null,eraserCommitPending:false,pendingPolygonErase:null,polygonVertexDrag:null,virtualWallPlacementPending:false,componentDrag:{},componentPlacementPending:true,selectedProject:{id:'p'},activeMap:{id:'a'},mapEditHistory:{busy:()=>false}};
 runInNewContext(fn,state);assert.equal(state.mapBeautyTopologyEditing(),false);
 state.virtualWallDrag={};assert.equal(state.mapBeautyTopologyEditing(),true);
 state.virtualWallDrag=null;state.eraserStroke={};assert.equal(state.mapBeautyTopologyEditing(),true);
});
test('ready beauty can be shown immediately while the raw bitmap is preparing',async()=>{
 const {readFileSync}=await import('node:fs'),{runInNewContext}=await import('node:vm');
 const source=readFileSync(new URL('../../../autodrive_console/web/deployment.js',import.meta.url),'utf8');
 const body=source.match(/\$\("styledMapView"\)\.addEventListener\("click", \(\) => \{([\s\S]*?)\n\}\);/)[1];
 let appearance=null;
 const state={syncMapBeauty(){},rawMapPhase:'raw-processing',mapBeautyEditing:()=>false,mapBeauty:{phase:'ready'},note(){throw Error('cached view must not be blocked');},setMapAppearance:next=>appearance=next};
 runInNewContext(`function click(){${body}\n}`,state);state.click();assert.equal(appearance,'styled');
});
test('showing cached beauty does not prepare the raw map until it is requested',async()=>{
 const {readFileSync}=await import('node:fs'),{runInNewContext}=await import('node:vm');
 const source=readFileSync(new URL('../../../autodrive_console/web/deployment.js',import.meta.url),'utf8');
 const fn=source.match(/function prepareRawMap\(\) \{[\s\S]*?\n\}/)?.[0];assert.ok(fn);
 const calls=[],image={};const state={activeMap:{},mapImage:image,mapAppearance:'styled',rawMapDisplay:{setImage:(...args)=>calls.push(args)}};
 runInNewContext(fn,state);state.prepareRawMap();assert.equal(calls.length,0);
 state.mapAppearance='raw';state.prepareRawMap();assert.equal(calls.length,1);assert.equal(calls[0][0],image);
});

test('cache byte budget evicts inactive surfaces while preserving an oversized active map',async()=>{
 const f=fixture({maxBytes:1});
 f.session.sync(f.image,f.options,[],{id:'a'});f.session.generate();await Promise.resolve();f.ready(f.workers[0]);
 const a=f.session.display.getExportSurface();assert.ok(a);assert.notEqual(a.closed,true);
 f.session.sync(f.image,f.options,[],{id:'b'});assert.equal(a.closed,true);
 f.session.generate();await Promise.resolve();f.ready(f.workers[1]);assert.ok(f.session.display.getExportSurface());
 f.session.sync(f.image,f.options,[],{id:'a'});assert.equal(f.session.phase,'idle');assert.equal(f.session.display.getExportSurface(),null);
});
