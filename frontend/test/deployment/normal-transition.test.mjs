import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import test from "node:test";
import { runInNewContext } from "node:vm";
import {nextTransitionLabel,transitionDisplayLabel} from '../../../autodrive_console/web/deployment/transition-labels.js';

const script = readFileSync(new URL("../../../autodrive_console/web/deployment.js", import.meta.url), "utf8");
const html = readFileSync(new URL("../../../autodrive_console/web/deployment.html", import.meta.url), "utf8");

test("placing a new manual transition posts normal speed", async () => {
  const start = script.indexOf('if (placementKind === "transition") {');
  const end = script.indexOf('if (placementKind === "elevator") {', start);
  assert.ok(start >= 0 && end > start, "transition placement handler exists");
  const calls = [];
  const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
  const placeTransition = new AsyncFunction(
    "placementKind", "selectedProject", "activeMap", "point", "request",
    "renderProject", "taskTransitionRole", "note", "keepMapAnnotationOpen", "completeDeploymentEdit", "nextTransitionLabel",
    script.slice(start, end),
  );
  await placeTransition("transition", { id: "project-1" }, { id: "floor-1" }, { x: 2, y: 3 },
    async (url, options) => {
      calls.push({ url, options });
      return { project: {} };
    }, () => {}, () => "target", () => {}, () => true, () => {}, nextTransitionLabel);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "/api/deployments/project-1/waypoints");
  assert.equal(calls[0].options.method, "POST");
  assert.deepEqual(JSON.parse(calls[0].options.body), {
    map_id: "floor-1", kind: "transition", label: "过渡点 1", x: 2, y: 3, yaw: 0, speed_mode: "normal",
  });
});

test("transition speed picker exposes continuous passage and single-point stop separately", () => {
  const select = html.match(/<select id="waypointTransitionSpeed">([\s\S]*?)<\/select>/)?.[1];
  assert.ok(select, "transition speed picker exists");
  const options = [...select.matchAll(/<option value="([^"]+)">([^<]+)<\/option>/g)]
    .map((match) => [match[1], match[2]]);
  assert.deepEqual(options.slice(0, 2), [["normal", "常规通过"], ["single_point", "单点停靠"]]);
});

test("manual transition headings remain visible before a task role is assigned in raw and styled views", () => {
  const draw=script.match(/function drawWaypointSymbol\(point, px, py\) \{[\s\S]*?\n\}/)[0];
  for(const mapAppearance of ["raw","styled"]) {
    const rotations=[],tips=[],labels=[];
    const context={save(){},restore(){},beginPath(){},arc(){},fill(){},stroke(){},translate(){},rotate:r=>rotations.push(r),moveTo:(x,y)=>tips.push([x,y]),lineTo(){},closePath(){},setLineDash(){},fillText:text=>labels.push(text)};
    const state={context,mapAppearance,selectedWaypoint:null,selectedProject:{},transitionDisplayLabel,taskTransitionRole:()=>null,waypointHeadingDegrees:()=>90};
    runInNewContext(draw,state);
    state.drawWaypointSymbol({id:"door",kind:"transition",map_asset_id:"ferry",label:"门口",yaw:Math.PI/2},50,60);
    assert.deepEqual(rotations,[-Math.PI/2],mapAppearance);
    assert.ok(tips.some(([x,y])=>x===24&&y===0),"forward arrowhead is drawn");
    assert.match(labels[0],/90°/);
  }
});

test("a manual transition rotation handle is usable without a task role", () => {
  const hit=script.match(/function transitionRotateHandleAt\(event\) \{[\s\S]*?\n\}/)[0];
  const state={selectedWaypoint:{id:"door",kind:"transition",map_asset_id:"ferry"},activeMap:{id:"ferry"},taskTransitionRole:()=>null,canvasPointFromEvent:e=>e,transitionDirectionHandlePoint:()=>({x:32,y:0})};
  runInNewContext(hit,state);
  assert.equal(state.transitionRotateHandleAt({x:32,y:0}),true);
  assert.equal(state.transitionRotateHandleAt({x:60,y:0}),false);
  state.selectedWaypoint.generated_by="facility";
  assert.equal(state.transitionRotateHandleAt({x:32,y:0}),false);
});

test("manual transition pose controls are available before task-line configuration", () => {
  const open=script.match(/function openWaypointPopover\(waypoint, event\) \{[\s\S]*?\n\}/)[0];
  const elements=new Map();
  const get=id=>{if(!elements.has(id))elements.set(id,{classList:{toggle(name,hidden){this.hidden=hidden;},remove(){}},getBoundingClientRect:()=>({left:0,top:0}),style:{},offsetWidth:200,offsetHeight:150,clientWidth:800,clientHeight:600});return elements.get(id);};
  const state={$:get,selectedProject:{},transitionDisplayLabel,taskTransitionRole:()=>null,syncTransitionYawControl(){},note(){},closeComponentPopover(){},drawMap(){}};
  runInNewContext(open,state);
  state.openWaypointPopover({id:"door",kind:"transition",map_asset_id:"ferry",x:0,y:0},{clientX:10,clientY:10});
  for(const id of ["transitionNameControl","transitionYawControl","transitionSpeedControl","saveWaypointTransitionSpeed"])
    assert.equal(get(id).classList.hidden,false,id);
});

test('transition settings save a descriptive name with speed and heading, and reject a blank name',async()=>{
  const body=script.match(/\$\("saveWaypointTransitionSpeed"\)\.addEventListener\("click", async \(\) => \{([\s\S]*?)\n\}\);/)[1];
  const elements={waypointTransitionName:{value:'  4号门  回入口  '},waypointTransitionSpeed:{value:'normal'},waypointTransitionYaw:{value:'90'}};
  const saved=[],notes=[];
  const state={$:id=>elements[id],selectedProject:{id:'p'},selectedWaypoint:{id:'door',kind:'transition'},annotationSavePending:false,
    saveMapAnnotation:async(point,collection,data)=>{saved.push({point,collection,data});return {...point,...data};},
    note:(...args)=>notes.push(args),closeWaypointPopover(){}};
  runInNewContext(`async function save(){${body}\n}`,state);
  await state.save();
  assert.equal(saved.length,1);
  assert.equal(saved[0].collection,'waypoints');
  assert.equal(saved[0].data.label,'4号门 回入口');
  assert.equal(saved[0].data.speed_mode,'normal');
  assert.equal(saved[0].data.yaw,Math.PI/2);
  elements.waypointTransitionName.value='   ';
  await state.save();
  assert.equal(saved.length,1,'invalid name must not reach the backend');
  assert.equal(notes.at(-1)[0],'waypointPopoverStatus');
});

test('editing a duplicate maximum-length name retains the valid stored name instead of its display suffix',()=>{
  const open=script.match(/function openWaypointPopover\(waypoint, event\) \{[\s\S]*?\n\}/)[0];
  const label='门'.repeat(80),waypoints=['a','b'].map(id=>({id,label,kind:'transition',map_asset_id:'hall',x:0,y:0}));
  const elements=new Map();
  const get=id=>{if(!elements.has(id))elements.set(id,{classList:{toggle(){},remove(){}},getBoundingClientRect:()=>({left:0,top:0}),style:{},offsetWidth:200,offsetHeight:150,clientWidth:800,clientHeight:600});return elements.get(id);};
  const state={$:get,selectedProject:{waypoints},transitionDisplayLabel,taskTransitionRole:()=>null,syncTransitionYawControl(){},note(){},closeComponentPopover(){},drawMap(){}};
  runInNewContext(open,state);
  state.openWaypointPopover(waypoints[0],{clientX:10,clientY:10});
  assert.equal(get('waypointPopoverTitle').textContent,`${label}（1）`);
  assert.equal(get('waypointTransitionName').value,label);
});
