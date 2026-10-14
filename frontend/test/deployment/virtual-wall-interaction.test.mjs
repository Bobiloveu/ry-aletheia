import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {snapWallPoint} from '../../../autodrive_console/web/deployment/virtual-walls.js';
import {createMapEditHistory} from '../../../autodrive_console/web/deployment/map-edit-history.js';
const source=readFileSync(new URL('../../../autodrive_console/web/deployment.js',import.meta.url),'utf8');
function controller(name){const start=source.indexOf(`function ${name}(`);assert.notEqual(start,-1,`${name} exists`);return source.slice(source.slice(start-6,start)==='async '?start-6:start,source.indexOf('\n}',start)+2);}
function drawing(){
  let pointerdown;const saved=[];
  const state={activeMap:{id:'a',origin:[0,0],height:10,width:10,resolution_m:1},mapView:{x:0,y:0,scale:10},
    activeTool:'virtual_wall',annotationSavePending:false,selectedProject:{id:'p'},spacePanActive:false,taskPreviewOpen:false,polygonVertexDrag:null,
    virtualWallPlacementPending:false,virtualWallDraft:null,selectedVirtualWall:null,virtualWallDrag:null,
    mapEditHistory:createMapEditHistory(),virtualWallsForActiveMap:()=>[{id:'old',map_asset_id:'a',points:[{x:1,y:2},{x:3,y:2}]}],
    snapWallPoint,worldPointFromEvent:e=>e.point,pointIsOnActiveMap:()=>true,
    $:()=>({focus(){}}),canvas:{style:{},addEventListener:(_name,handler)=>{pointerdown=handler;},setPointerCapture(){}},
    drawMap(){},note(){},closeComponentPopover(){},selectComponent(){},
    createVirtualWall:async points=>saved.push(structuredClone(points)),
    rotateHandleAt:()=>false,transitionRotateHandleAt:()=>false,resizeHandleAt:()=>false,componentAt:()=>null,waypointAt:()=>null,
    virtualWallAt:()=>({wall:{id:'old'},hit:'vertex:0'}),setTool:()=>{state.activeTool='pan';},
    selectVirtualWall:()=>{throw Error('drawing must not select an existing wall');}};
  const start=source.indexOf('canvas.addEventListener("pointerdown", async (event) => {');
  const end=source.indexOf('\ndocument.addEventListener("keydown"',start);
  // Keep the production event callback, so a wrong hit-test order fails here.
  const helper=source.includes('function drawVirtualWallFromEvent(')?controller('drawVirtualWallFromEvent'):'';
  runInNewContext(helper+'\n'+source.slice(start,end),state);
  return {state,saved,click:(point,detail=1)=>pointerdown({button:0,point,detail,pointerId:1})};
}

test('a new wall can start and end at saved endpoints without selecting or dragging the saved wall',async()=>{
  const f=drawing();await f.click({x:1.2,y:2.1});
  assert.equal(f.state.activeTool,'virtual_wall');assert.deepEqual(JSON.parse(JSON.stringify(f.state.virtualWallDraft.points)),[{x:1,y:2}]);
  await f.click({x:3.1,y:2.1});await f.click({x:3.1,y:2.1},2);
  assert.deepEqual(JSON.parse(JSON.stringify(f.saved)),[[{x:1,y:2},{x:3,y:2}]]);
});

test('clicking the same snapped point twice cannot add a zero length segment or save a one-point wall',async()=>{
  const f=drawing();await f.click({x:1,y:2});await f.click({x:1.1,y:2},2);
  assert.equal(f.saved.length,0);assert.equal(f.state.virtualWallDraft.points.length,1);
});

function undoEditor(){
 const history=createMapEditHistory(),calls=[];
 const state={selectedProject:{id:'p',virtual_walls:[],map_edits:[]},activeMap:{id:'a'},mapEditHistory:history,taskPreviewOpen:false,
   virtualWallDraft:null,polygonEraseDraft:[],pendingPolygonErase:null,eraserCommitPending:false,eraserStroke:null,
   virtualWallDrag:null,polygonVertexDrag:null,virtualWallPlacementPending:false,selectedVirtualWall:null,polygonVertexHover:-1,
   drawMap(){},note(){},finishPolygonVertexDrag(){},keepMapAnnotationOpen(){},
   renderProject(p){state.selectedProject=p;},
   request:async(url,options)=>{calls.push([url,options]);return {project:{id:'p',virtual_walls:[],map_edits:[]},virtual_wall:{id:'restored'}};},
   commitMapEdit:async payload=>calls.push(['erase',payload])};
 runInNewContext(controller('undoMapOperation'),state);
 return {state,history,calls};
}

test('undo removes unfinished wall points first and never sends a saved-wall delete for a draft',async()=>{
 const f=undoEditor();f.history.push('p','a',{kind:'wall-create',wallId:'old',label:'新增虚拟墙'});
 f.state.virtualWallDraft={points:[{x:1,y:2},{x:3,y:4}]};
 await f.state.undoMapOperation();assert.equal(f.state.virtualWallDraft.points.length,1);assert.equal(f.calls.length,0);
 await f.state.undoMapOperation();assert.equal(f.state.virtualWallDraft,null);assert.equal(f.calls.length,0);
 await f.state.undoMapOperation();assert.equal(f.calls[0][1].method,'DELETE');assert.match(f.calls[0][0],/virtual-walls\/old$/);assert.equal(f.history.peek('p','a'),null);
});

test('undo restores moved/deleted walls through existing APIs and remaps IDs for earlier undo entries',async()=>{
 const f=undoEditor();f.history.push('p','a',{kind:'wall-create',wallId:'old'});
 f.history.push('p','a',{kind:'wall-delete',wallId:'old',before:{points:[{x:1,y:2},{x:3,y:4}]}});
 await f.state.undoMapOperation();assert.deepEqual(JSON.parse(f.calls[0][1].body),{map_id:'a',points:[{x:1,y:2},{x:3,y:4}]});
 assert.equal(f.history.peek('p','a').wallId,'restored');
 f.history.push('p','a',{kind:'wall-update',wallId:'restored',before:{points:[{x:2,y:2},{x:4,y:4}]}});
 await f.state.undoMapOperation();assert.match(f.calls[1][0],/virtual-walls\/restored$/);assert.deepEqual(JSON.parse(f.calls[1][1].body),{points:[{x:2,y:2},{x:4,y:4}]});
});

test('failed undo retains its entry for retry and ignores late results from other projects',async()=>{
 const f=undoEditor();f.history.push('p','a',{kind:'wall-create',wallId:'old'});
 f.state.request=async()=>{throw Error('offline');};await f.state.undoMapOperation();assert.equal(f.history.peek('p','a').wallId,'old');assert.equal(f.history.busy('p','a'),false);
 let finish;f.state.request=()=>new Promise(resolve=>{finish=resolve;});
 const pending=f.state.undoMapOperation();await f.state.undoMapOperation();
 f.state.selectedProject={id:'q'};finish({project:{id:'p'}});await pending;
 assert.equal(f.state.selectedProject.id,'q');assert.equal(f.history.peek('p','a'),null);
});

test('erase undo follows saved order and does not remove history before Backend confirms',async()=>{
 const f=undoEditor();f.history.push('p','a',{kind:'erase-add',editId:'e',label:'擦除'});
 f.state.selectedProject.map_edits=[{id:'e',map_asset_id:'a'}];
 await f.state.undoMapOperation();assert.match(f.calls[0][0],/map-edits$/);assert.deepEqual(JSON.parse(f.calls[0][1].body),{map_id:'a',action:'undo'});
 assert.equal(f.history.peek('p','a'),null);
});

test('selected raw virtual walls show highlight and vertex handles while beauty keeps its architectural style',()=>{
 const calls=[],context=new Proxy({},{get:(_,k)=>(...args)=>calls.push([k,...args]),set:(_,k,v)=>{calls.push([k,v]);return true;}});
 const wall={id:'selected',points:[{x:1,y:2},{x:3,y:2}]};
 const state={activeMap:{},mapAppearance:'raw',virtualWallDrag:null,selectedVirtualWall:wall,virtualWallDraft:null,context,
   virtualWallsForActiveMap:()=>[wall],wallsForDisplay:w=>w,worldCanvasPoint:p=>p,paintStyledVirtualWalls:()=>calls.push(['beauty'])};
 runInNewContext(controller('drawVirtualWalls'),state);state.drawVirtualWalls();
 assert.ok(calls.some(c=>c[0]==='strokeStyle'&&c[1]==='#007aff'));
 assert.equal(calls.filter(c=>c[0]==='arc').length,2);
 calls.length=0;state.mapAppearance='styled';state.mapView={};state.drawVirtualWalls();assert.deepEqual(calls,[['beauty']]);
});

test('selecting another component clears the old wall selection but clearing components does not clear a wall just selected',()=>{
 const component={id:'component',attributes:{}};
 const state={selectedProject:{components:[component]},selectedVirtualWall:{id:'wall'},selectedComponent:null,drawMap(){},renderComponentAttributes(){},$:()=>({})};
 runInNewContext(controller('selectComponent'),state);
 state.selectComponent(null);assert.equal(state.selectedVirtualWall.id,'wall');
 state.selectComponent(component);assert.equal(state.selectedVirtualWall,null);
});
