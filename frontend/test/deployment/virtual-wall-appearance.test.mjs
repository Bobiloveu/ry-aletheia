import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import {createMapEditHistory} from '../../../autodrive_console/web/deployment/map-edit-history.js';

const source=readFileSync(new URL('../../../autodrive_console/web/deployment.js',import.meta.url),'utf8');
function controller(name) {
  const start=source.indexOf(`function ${name}(`);
  assert.notEqual(start,-1,`${name} exists`);
  return source.slice(source.slice(start-6,start)==='async '?start-6:start,source.indexOf('\n}',start)+2);
}
function editor() {
  const nodes=new Map();
  const state={mapAppearance:'styled',activeTool:'pan',spacePanActive:false,eraserMode:'erase',selectedVirtualWall:null,virtualWallDrag:null,
    virtualWallDraft:null,polygonEraseDraft:[],pendingPolygonErase:null,eraserCommitPending:false,
    eraserStroke:null,placementHoverPoint:null,eraserHoverPoint:null,polygonVertexHover:-1,
    canvas:{style:{}},mapTools:{setActive(){}},COMPONENT_SPECS:{},draws:0,
    mapBeauty:{phase:'ready',cancel(){}},
    finishPolygonVertexDrag(){},scheduleMapDraw(){},drawMap(){state.draws++;},
    $(id){if(!nodes.has(id))nodes.set(id,{attributes:{},setAttribute(k,v){this.attributes[k]=v;},focus(){},classList:{toggle(){}}});return nodes.get(id);}};
  runInNewContext(`${controller('mapToolCursor')}\n${controller('setMapAppearance')}\n${controller('setTool')}`,state);
  return state;
}

test('virtual-wall tool opens raw view and beauty view exits hidden wall editing',()=>{
  const state=editor();
  state.setTool('virtual_wall');
  assert.equal(state.mapAppearance,'raw');
  assert.equal(state.activeTool,'virtual_wall');
  assert.equal(state.$('rawMapView').attributes['aria-pressed'],'true');
  assert.equal(state.$('styledMapView').attributes['aria-pressed'],'false');
  state.virtualWallDraft={points:[{x:0,y:0}]};
  state.selectedVirtualWall={id:'wall'};
  state.virtualWallDrag={wall:state.selectedVirtualWall};
  state.setMapAppearance('styled');
  assert.equal(state.mapAppearance,'styled');
  assert.equal(state.activeTool,'pan');
  assert.equal(state.virtualWallDraft,null);
  assert.equal(state.selectedVirtualWall,null);
  assert.equal(state.virtualWallDrag,null);
  assert.equal(state.$('styledMapView').attributes['aria-pressed'],'true');
  state.setTool('erase_brush');
  assert.equal(state.mapAppearance,'raw');
});

test('hidden virtual walls cannot intercept clicks in beauty view',()=>{
  const wall={id:'wall'};
  let hits=0;
  const state={activeMap:{},mapView:{},mapAppearance:'styled',canvasPointFromEvent:()=>({x:0,y:0}),
    virtualWallsForActiveMap:()=>[wall],wallHitTest:()=>{hits++;return 'segment-0';}};
  runInNewContext(controller('virtualWallAt'),state);
  assert.equal(state.virtualWallAt({}),null);
  assert.equal(hits,0);
  state.mapAppearance='raw';
  const picked=state.virtualWallAt({});
  assert.equal(picked.wall,wall);
  assert.equal(picked.hit,'segment-0');
  assert.equal(hits,1);
});

function wallRequests() {
  let finish,renders=0,confirmations=0;
  const wall={id:'wall-a',map_asset_id:'a',points:[{x:0,y:0},{x:1,y:0}]};
  const state={selectedProject:{id:'p',virtual_walls:[{...wall,points:[{x:0,y:0},{x:2,y:0}]}]},activeMap:{id:'a'},selectedVirtualWall:wall,mapAppearance:'raw',mapEditHistory:createMapEditHistory(),
    request:()=>new Promise(resolve=>{finish=resolve;}),window:{confirm(){confirmations++;return true;}},
    renderProject(project){renders++;state.selectedProject=project;},drawMap(){},note(){},keepMapAnnotationOpen(){},openProject(){throw Error('must not reopen a stale project');}};
  runInNewContext([controller('createVirtualWall'),controller('persistVirtualWall'),controller('deleteSelectedVirtualWall')].join('\n'),state);
  return {state,wall,respond(){finish({project:{id:'p',virtual_walls:[wall]},virtual_wall:wall});},renders:()=>renders,confirmations:()=>confirmations};
}

test('same-project wall responses refresh authoritative walls without replacing the newly selected map',async()=>{
  for(const operation of ['createVirtualWall','persistVirtualWall','deleteSelectedVirtualWall']) {
    const f=wallRequests(),pending=f.state[operation](operation==='createVirtualWall'?f.wall.points:f.wall);
    f.state.activeMap={id:'b'};const newSelection={id:'wall-b',map_asset_id:'b'};f.state.selectedVirtualWall=newSelection;
    f.respond();await pending;
    assert.equal(f.renders(),1,`${operation} must retain the saved project snapshot`);
    assert.equal(f.state.activeMap.id,'b');
    assert.deepEqual(f.state.selectedProject.virtual_walls,[f.wall]);
    assert.equal(f.state.selectedVirtualWall,newSelection);
  }
});

test('late wall responses cannot overwrite another project or steal another wall selection',async()=>{
  for(const operation of ['createVirtualWall','persistVirtualWall','deleteSelectedVirtualWall']) {
    for(const switchProject of [false,true]) {
      const f=wallRequests(),pending=f.state[operation](operation==='createVirtualWall'?f.wall.points:f.wall);
      const selection={id:'other-wall',map_asset_id:'a'};f.state.selectedVirtualWall=selection;
      if(switchProject)f.state.selectedProject={id:'other-project'};
      f.respond();await pending;
      assert.equal(f.state.selectedVirtualWall,selection,`${operation} must preserve the current selection`);
      assert.equal(f.renders(),switchProject?0:1);
    }
  }
});

test('saving a wall after returning to beauty view does not restore an invisible editing selection',async()=>{
  for(const operation of ['createVirtualWall','persistVirtualWall']) {
    const f=wallRequests(),pending=f.state[operation](operation==='createVirtualWall'?f.wall.points:f.wall);
    f.state.mapAppearance='styled';f.state.selectedVirtualWall=null;f.respond();await pending;
    assert.equal(f.renders(),1);assert.equal(f.state.selectedVirtualWall,null);
  }
  const f=wallRequests();f.state.mapAppearance='styled';
  const pending=f.state.deleteSelectedVirtualWall();
  assert.equal(f.confirmations(),0,'beauty view cannot delete a stale wall selection');
  await pending;
});

test('failed wall saves refresh data without reopening a stale project or clearing a newer selection',async()=>{
  for(const change of ['none','map','selection','project']) {
    const f=wallRequests();let finishReload;const notes=[];
    f.state.note=(...args)=>notes.push(args);
    f.state.request=(_url,options)=>options
      ? Promise.reject(Error('save failed'))
      : new Promise(resolve=>{finishReload=resolve;});
    const pending=f.state.persistVirtualWall(f.wall);
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(typeof finishReload,'function','failure requests authoritative project data');
    const selection={id:'new-wall',map_asset_id:change==='map'?'b':'a'};
    if(change==='map')f.state.activeMap={id:'b'};
    if(change==='project')f.state.selectedProject={id:'other-project'};
    if(change!=='none')f.state.selectedVirtualWall=selection;
    finishReload({project:{id:'p',virtual_walls:[f.wall]}});await pending;
    assert.equal(f.renders(),change==='project'?0:1);
    assert.equal(f.state.selectedVirtualWall,change==='none'?null:selection);
    assert.equal(notes.length,change==='map'||change==='project'?0:1);
  }
});

test('selecting a wall without moving it neither saves geometry nor occupies undo history',async()=>{
 const f=wallRequests();f.state.selectedProject.virtual_walls=[f.wall];
 let saves=0;f.state.request=async()=>{saves++;};
 await f.state.persistVirtualWall(f.wall);
 assert.equal(saves,0);assert.equal(f.state.mapEditHistory.peek('p','a'),null);
});

test('entering finished beauty view exits raw erasing tools',()=>{
 for(const tool of ['erase_brush','erase_polygon']) {
  const state=editor();state.mapAppearance='raw';state.activeTool=tool;
  state.setMapAppearance('styled');assert.equal(state.activeTool,'pan');assert.equal(state.mapAppearance,'styled');
 }
});
