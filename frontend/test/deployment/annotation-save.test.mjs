import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";

const source = readFileSync(new URL("../../../autodrive_console/web/deployment.js", import.meta.url), "utf8");
const functionSource = name => {
  const start=source.indexOf(`function ${name}(`);
  return start < 0 ? "" : source.slice(source.slice(start-6,start)==="async "?start-6:start,source.indexOf("\n}",start)+2);
};
function editor(mode="waypointRotate") {
  let resolve,reject;
  const item={id:"marker",map_asset_id:"a",kind:mode==="waypointRotate"?"transition":"target",x:1,y:2,yaw:0,attributes:{width_m:1,height_m:1}};
  const collection=mode==="waypointRotate"?"waypoints":"components";
  const elements=new Map();
  const state={selectedProject:{id:"p",components:[],waypoints:[],[collection]:[item]},activeMap:{id:"a"},deploymentProjectGeneration:1,
    selectedComponent:collection==="components"?item:null,selectedWaypoint:collection==="waypoints"?item:null,
    componentRotate:null,componentResize:null,componentDrag:null,waypointRotate:null,annotationGesture:null,annotationSavePending:false,
    polygonVertexDrag:null,eraserStroke:null,virtualWallDrag:null,drag:null,activeTool:"pan",spacePanActive:false,pendingWaypointYaw:null,pendingComponentYaw:null,pendingComponentSizeReadout:null,
    canvas:{style:{},setPointerCapture(){}},document:{querySelectorAll:()=>[]},
    worldCanvasPoint:()=>({x:0,y:0}),canvasPointFromEvent:()=>({x:10,y:0}),
    $(id){if(!elements.has(id))elements.set(id,{value:id==="waypointTransitionSpeed"?"normal":"90"});return elements.get(id);},
    request:()=>new Promise((yes,no)=>{resolve=yes;reject=no;}),renders:0,notes:[],
    renderProject(p){state.renders++;state.selectedProject=p;},selectComponent(item){state.selectedComponent=item;},syncTransitionYawControl(){},drawMap(){},updateMapBeautyControls(){},
    isMapAnnotationWorkspaceActive:()=>true,keepMapAnnotationOpen:()=>true,completeDeploymentEdit(){},note:(...args)=>state.notes.push(args),closeWaypointPopover(){},
    rotateHandleAt:()=>mode==="componentRotate",transitionRotateHandleAt:()=>mode==="waypointRotate",resizeHandleAt:()=>mode==="componentResize",componentAt:()=>mode==="componentDrag"?item:null,waypointAt:()=>null,
  };
  const downStart=source.indexOf('  if (rotateHandleAt(event)) {');
  const downEnd=source.indexOf('  // Existing markers always win over virtual-wall',downStart);
  const upStart=source.indexOf('canvas.addEventListener("pointerup", async (event) => {');
  const upEnd=source.indexOf('\n});',upStart);
  const upBody=source.slice(upStart+'canvas.addEventListener("pointerup", async (event) => {'.length,upEnd);
  const cancelBody=source.match(/for \(const eventName of \["pointercancel", "lostpointercapture"\]\) \{\n  canvas.addEventListener\(eventName, \(event\) => \{([\s\S]*?)\n  \}\);/)?.[1];
  const fields=["saveComponent","saveWaypointTransitionSpeed"].map(id=> {
    const body=source.match(new RegExp('\\$\\("'+id+'"\\)\\.addEventListener\\("click", async \\(\\) => \\{([\\s\\S]*?)\\n\\}\\);'))?.[1];
    assert.ok(body,id);return `async function ${id}(){${body}\n}`;
  });
  runInNewContext([functionSource("mapToolCursor"),functionSource("beginAnnotationGesture"),functionSource("cancelAnnotationGesture"),functionSource("saveMapAnnotation"),`function down(event){${source.slice(downStart,downEnd)}\n}`,`function cancel(event){${cancelBody}\n}`,`async function up(event){${upBody}\n}`,...fields].join("\n"),state);
  return {state,item,collection,start(){state.down({pointerId:1});item.yaw=1.57;item.x=9;item.attributes={width_m:3,height_m:4};return state.up({pointerId:1});},fail(){reject(Error("save failed"));},respond(){const saved={...item},project={id:"p",components:[],waypoints:[],[collection]:[saved]};
    for(const [key,selection] of [["components",state.selectedComponent],["waypoints",state.selectedWaypoint]]) {
      if(selection && selection.id!==item.id)project[key].push(structuredClone(selection));
    }
    resolve({project,waypoint:saved,component:saved});}};
}

for(const mode of ["waypointRotate","componentRotate","componentResize","componentDrag"]) {
  test(`${mode}: failed save restores the original geometry`,async()=>{
    const f=editor(mode),pending=f.start();f.fail();await pending;
    assert.equal(f.item.x,1);assert.equal(f.item.yaw,0);assert.equal(f.item.attributes.width_m,1);
    assert.equal(f.state.annotationSavePending,false);
  });
  test(`${mode}: late saves cannot restore an old project, including leaving and returning`,async()=>{
    for(const sameId of [false,true]) {
      const f=editor(mode),pending=f.start();const replacement={id:sameId?"p":"other",components:[],waypoints:[]};
      f.state.selectedProject=replacement;f.state.deploymentProjectGeneration+=2;f.respond();await pending;
      assert.equal(f.state.selectedProject,replacement);assert.equal(f.state.renders,0);
    }
  });
  test(`${mode}: changing maps preserves the new selection`,async()=>{
    const f=editor(mode),pending=f.start();f.state.activeMap={id:"b"};const other={id:"other",map_asset_id:"b"};
    f.state.selectedComponent=other;f.state.selectedWaypoint=other;f.respond();await pending;
    assert.equal(f.state.renders,1);assert.equal(f.state.activeMap.id,"b");
    assert.equal(f.state.selectedComponent.id,other.id);assert.equal(f.state.selectedWaypoint.id,other.id);
    assert.equal(f.state.selectedComponent,f.state.selectedProject.components.find(item=>item.id===other.id));
    assert.equal(f.state.selectedWaypoint,f.state.selectedProject.waypoints.find(item=>item.id===other.id));
    assert.equal(f.state.notes.length,0);
  });
}
for(const mode of ["waypointRotate","componentRotate"]) {
  test(`${mode}: selecting a different marker while saving does not steal its selection`,async()=>{
    const f=editor(mode),pending=f.start(),other={id:"other",map_asset_id:"a"};
    f.state.selectedComponent=other;f.state.selectedWaypoint=other;f.respond();await pending;
    assert.equal(f.state.selectedComponent.id,other.id);assert.equal(f.state.selectedWaypoint.id,other.id);
    assert.equal(f.state.selectedComponent,f.state.selectedProject.components.find(item=>item.id===other.id));
    assert.equal(f.state.selectedWaypoint,f.state.selectedProject.waypoints.find(item=>item.id===other.id));
  });
}
for(const [handler,mode] of [["saveComponent","componentRotate"],["saveWaypointTransitionSpeed","waypointRotate"]]) {
  test(`${handler}: stale property saves cannot restore the previous project`,async()=>{
    const f=editor(mode),pending=f.state[handler]();const replacement={id:"other"};f.state.selectedProject=replacement;f.state.deploymentProjectGeneration++;
    f.respond();await pending;assert.equal(f.state.selectedProject,replacement);assert.equal(f.state.renders,0);
  });
}

test("gesture saves retain the annotation workspace captured before workflow refresh",async()=>{
  const f=editor("componentRotate");let editing=true,completed=false,kept=false;
  f.state.isMapAnnotationWorkspaceActive=()=>editing;
  f.state.renderProject=p=>{f.state.selectedProject=p;editing=false;};
  f.state.keepMapAnnotationOpen=(_message,{force=false}={})=>{kept=force||editing;return kept;};
  f.state.completeDeploymentEdit=()=>{completed=true;};
  const pending=f.start();f.respond();await pending;
  assert.equal(kept,true);assert.equal(completed,false);
});

for(const mode of ["waypointRotate","componentRotate","componentResize","componentDrag"]) {
  test(`${mode}: losing pointer capture restores the unfinished gesture`,()=>{
    const f=editor(mode);f.state.down({pointerId:1});f.item.yaw=1.57;f.item.x=9;
    f.state.cancel({pointerId:2});assert.equal(f.item.yaw,1.57,"another pointer cannot cancel this gesture");
    f.state.cancel({pointerId:1});assert.equal(f.item.yaw,0);assert.equal(f.item.x,1);assert.equal(f.state[mode],null);
    assert.equal(f.state.annotationGesture,null);
  });
}
test("normal pointer release does not cancel a save already in progress",async()=>{
  const f=editor(),pending=f.start();f.state.cancel({pointerId:1});f.respond();await pending;
  assert.equal(f.state.selectedProject.waypoints[0].yaw,1.57);
});
