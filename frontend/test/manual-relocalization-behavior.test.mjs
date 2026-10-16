import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
const source = readFileSync(new URL('../src/liveObservation.js', import.meta.url), 'utf8');
function harness(request = async () => ({})) {
  let now = 100;
  const c = vm.createContext({ request, $:()=>undefined, relocalizationHandoffTimer:undefined, performance: {now: () => now},
    LIVE_POSE_FALLBACK_MS: 450, window: {confirm:()=>true,clearTimeout(){}, setTimeout(fn,ms){if(ms===150)fn();return 1;}},
    relocalizationStatus: {phase:'idle', can_begin:true}, relocalizationPreview:undefined,
    relocalizationPanelOpen:true,relocalizationEditing:false,relocalizationDraftRevision:0,relocalizationSubmittedRevision:0,
    relocalizationPreviewMapId:undefined,relocalizationWorkflowPending:false,
    relocalizationSubmissionUncertain:false,relocalizationOutcomePending:false,relocalizationRequestId:undefined,
    relocalizationMapUnconfirmed:false,tfVehiclePose:undefined,renderedVehiclePose:undefined,latestLiveMotion:undefined,
    refreshActiveMapFromServer(){},
    mobileConsoleEnabled:()=>false,
    mapInfo:undefined,
    relocalizationPreviewAnchor:undefined, rawVehiclePose: {x:10.01,y:20.02,yaw:.03,receivedAt:100},
    relocalizationDrag:undefined, relocalizationActionPending:false, relocalizationActionNotice:'',
    relocalizationPlacing:false,
    relocalizationPlacementOriginal:undefined,
    relocalizationActionEpoch:0, relocalizationPollPending:false, relocalizationAwaitingPose:false,
    activeMapRequestEpoch:0,requestedActiveMapId:undefined,
    relocalizationWaitingForMap:false,relocalizationTargetMapId:undefined,displayedMapId:'aaaaaaaaaaaaaaaa',
    relocalizationHandoffAt:0, relocalizationLayerBarrier:0n, lastPoseTimestamp:100n,
    relocalizationConfigPicker: {setEditable(){},reset(){},payload:pose=>({...pose}),summary:()=> '沿用当前配置',ready:()=>true}, mapView:{}, lastMapLayout:{},
    overviewUntilMovement:false, scheduleMapDraw(){}, renderCostmap(){},
    scheduleRelocalizationCloudRender(){}, renderRelocalizationControls(){},
    freezeMapViewportForRelocalization(){}, stopRelocalizationDrag(){},
    invalidateMapScopedCloud(){}, vehiclePoseInMap:()=>({position:{x:10,y:20},yaw:0}),
    normalizeAngle:(v)=>Math.atan2(Math.sin(v),Math.cos(v)),
  });
  const a=source.indexOf('function relocalizationCandidateFromLivePose()');
  const b=source.indexOf('function manualRelocalizationCopy(',a);
  const d=source.indexOf('function setRelocalizationMapVisibility(');
  const e=source.indexOf('function setupRelocalizationControl(',d);
  vm.runInContext(source.slice(a,b)+source.slice(d,e),c);
  c.scheduleRelocalizationCloudRender=()=>{};
  return c;
}
const deferred = () => {let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
const active={phase:'calibrating',can_apply:true,can_cancel:true};
test('find vehicle entry remains visible while parked after a runtime validation failure',()=>{
  const c=harness();gestures(c,0,15);
  const nodes={};
  c.$=id=>nodes[id]??=( {dataset:{},classList:{toggle(){}},setAttribute(){}} );
  c.setText=(id,value)=>c.$(id).textContent=value;
  const a=source.indexOf('function manualRelocalizationCopy('),b=source.indexOf('function setRelocalizationMapVisibility(',a);
  vm.runInContext(source.slice(a,b),c);c.renderMapOperationStatus=()=>{};
  c.relocalizationStatus={phase:'failed',can_begin:true,can_recover_navigation:true,
    detail:'当前定位版本尚未核验沿用配置能力'};
  c.renderRelocalizationControls();
  assert.equal(nodes.relocalizationPlace.hidden,false);
  assert.equal(nodes.relocalizationPlace.textContent,'一键找回车体');
  assert.equal(nodes.relocalizationPlace.disabled,false);
  c.relocalizationStatus=active;c.renderRelocalizationControls();
  assert.equal(nodes.relocalizationPlace.disabled,false);
});
test('initial candidate uses the raw map pose rather than the displayed deadband pose',()=>{
  const c=harness();const pose=c.relocalizationCandidateFromLivePose();
  assert.equal(pose.x,10.01);assert.equal(pose.yaw,.03);
});
test('missing or stale live pose does not block an operator supplied target',()=>{
  const c=harness();c.applyRelocalizationStatus(active);c.rawVehiclePose=undefined;
  assert.equal(c.canEditRelocalization(),true);
  c.setRelocalizationPreview({x:3,y:4,yaw:1});
  assert.equal(c.hasFiniteRelocalizationCandidate(c.relocalizationPreview),true);
  c.relocalizationStatus={phase:'calling_service',can_apply:false};
  assert.equal(c.canEditRelocalization(),true);
});
test('every action is single flight, including begin',async()=>{
  const pending=deferred();let calls=0;const c=harness(()=>{calls++;return pending.promise;});
  const first=c.postRelocalizationAction('/begin');
  const second=c.postRelocalizationAction('/begin');
  assert.equal(calls,1);pending.resolve(active);await Promise.all([first,second]);
  assert.equal(c.relocalizationStatus.phase,'calibrating');
});
test('a pre-action GET cannot overwrite a newer action response',async()=>{
  const pending=deferred();const c=harness((path,options)=>options?Promise.resolve(active):pending.promise);
  const poll=c.refreshRelocalizationStatus();await c.postRelocalizationAction('/begin');
  pending.resolve({phase:'idle',can_begin:true});await poll;
  assert.equal(c.relocalizationStatus.phase,'calibrating');
});
test('status polls are single flight and skipped while an action is pending',async()=>{
  const pending=deferred();let calls=0;const c=harness(()=>{calls++;return pending.promise;});
  const first=c.refreshRelocalizationStatus();const second=c.refreshRelocalizationStatus();
  assert.equal(calls,1);pending.resolve(active);await Promise.all([first,second]);
  c.relocalizationActionPending=true;await c.refreshRelocalizationStatus();assert.equal(calls,1);
});
test('submission preserves the chosen target until a new real pose can take over',async()=>{
  const pending=deferred();const c=harness(()=>pending.promise);
  c.applyRelocalizationStatus(active);c.setRelocalizationPreview({x:50,y:-20,yaw:1.2});
  const post=c.postRelocalizationAction('/apply',{x:50,y:-20,yaw:1.2});
  pending.resolve({phase:'switching_to_navigation'});await post;
  assert.equal(c.relocalizationPreview.x,50);assert.equal(c.relocalizationAwaitingPose,true);
  c.applyRelocalizationStatus({phase:'idle',can_begin:true});assert.equal(c.relocalizationPreview.x,50);
});
test('latest live pose anchors cloud transform without changing the operator target',()=>{
  const c=harness();c.setRelocalizationPreview({x:50,y:-20,yaw:Math.PI/2});
  c.rawVehiclePose={x:12,y:22,yaw:0,receivedAt:100};
  const p=c.transformRelocalizationPoint({x:13,y:22,yaw:0});
  assert.ok(Math.abs(p.x-50)<1e-10);assert.ok(Math.abs(p.y+19)<1e-10);
  assert.equal(c.relocalizationPreview.x,50);
});

function gestures(c, rotation, pixelsPerMeter) {
  const listeners={};const captured=new Set();
  const interaction={style:{},parentElement:{getBoundingClientRect:()=>({width:800,height:600}),addEventListener:(name,fn)=>listeners[name]=fn},
    getBoundingClientRect:()=>({left:80,top:120}),
    addEventListener:(name,fn)=>listeners[name]=fn, hasPointerCapture:id=>captured.has(id),
    setPointerCapture:id=>captured.add(id),releasePointerCapture:id=>captured.delete(id),
    classList:{add(){},remove(){},toggle(){}}};
  Object.assign(c,{$:()=>interaction, ResizeObserver:class{observe(){}},
    mapViewport:{width:800,height:600},pixiApp:undefined,mapInteractionTimer:undefined,
    mapInteractionActive:false,cloudRasterPending:false,closeMapMarkerMenu(){},
    MIN_PIXELS_PER_METER:1,MAX_PIXELS_PER_METER:100,
    vehicleModel:{},projectVehicleFootprint:()=>({width:12,length:18}),
    mapInfo:{origin:{x:-30,y:-20},width:2000,height:1000,resolution:.05},
    currentMapLayout:()=>({vehicle:{position:{x:10,y:20},yaw:.03},rotation,pixelsPerMeter,
      center:{x:10,y:20},viewportWidth:800,viewportHeight:600,ratio:.05*pixelsPerMeter,
      left:400+(-30-10)*pixelsPerMeter,top:300-(-20+50-20)*pixelsPerMeter})});
  let a=source.indexOf('function viewportPointForMapPosition('),b=source.indexOf('function mapMarkerAtViewportPoint(',a);
  vm.runInContext(source.slice(a,b),c);
  a=source.indexOf('function setupMapInteraction()');b=source.indexOf('function normalizeAngle(',a);
  vm.runInContext(source.slice(a,b),c);c.setupMapInteraction();
  return (name,point,button=0,extra={})=>listeners[name]({pointerId:1,pointerType:'mouse',button,
    clientX:point.x+80,clientY:point.y+120,deltaY:100,preventDefault(){},stopPropagation(){},...extra});
}
function panelControls(c) {
  const nodes = {};
  const documentListeners = {};
  for (const id of ['relocalizationControl', 'relocalizationToggle', 'relocalizationPanel']) {
    nodes[id] = { hidden: id === 'relocalizationPanel', listeners: {},
      addEventListener(name, fn) { this.listeners[name] = fn; }, setAttribute() {}, focus() {} };
  }
  const lookup = c.$;
  c.$ = id => nodes[id] || lookup(id);
  c.relocalizationPanelOpen = false;
  c.document = { addEventListener(name, fn) { documentListeners[name] = fn; } };
  c.MAP_OVERLAY_OPEN_EVENT = 'map-overlay-open';
  c.announceMapOverlayOpen = () => {};
  c.createRelocalizationConfigPicker = () => c.relocalizationConfigPicker;
  c.relocalizationConfigPicker.close = () => {};
  c.window.setInterval = () => 1;
  c.RELOCALIZATION_STATUS_REFRESH_MS = 1000;
  const a = source.indexOf('function setupRelocalizationControl()');
  const b = source.indexOf('function closeMapMarkerMenu()', a);
  vm.runInContext(source.slice(a, b), c);
  c.setupRelocalizationControl();
  return { toggle: () => nodes.relocalizationToggle.listeners.click(), nodes, documentListeners };
}
test('vehicle move and rotation require opening the manual relocalization panel', () => {
  const c = harness(); const event = gestures(c, 0, 15); const panel = panelControls(c);
  const point = { x: 400, y: 300 };
  assert.equal(c.canEditRelocalization(), false);
  for (const button of [0, 2]) {
    event('pointerdown', point, button);
    assert.equal(c.relocalizationDrag, undefined);
    assert.equal(c.relocalizationPreview, undefined);
    event('pointerup', point, button);
  }
  panel.toggle();
  assert.equal(panel.nodes.relocalizationPanel.hidden, false);
  assert.equal(c.canEditRelocalization(), true);
  for (const phase of ['idle', 'calibrating', 'failed', 'unavailable', 'calling_service', 'switching_to_miniapp', 'switching_to_navigation']) {
    c.applyRelocalizationStatus({ phase });
    event('pointerdown', point);
    assert.equal(c.relocalizationDrag?.mode, 'move', phase);
    event('pointerup', point);
    event('pointerdown', point, 2);
    assert.equal(c.relocalizationDrag?.mode, 'rotate', phase);
    event('pointerup', point, 2);
  }
});
test('closing the manual panel ends a drag and blocks editing until reopened', () => {
  const c = harness(); const event = gestures(c, 0, 15); const panel = panelControls(c);
  panel.toggle(); event('pointerdown', { x: 400, y: 300 });
  assert.ok(c.relocalizationDrag);
  const original = { ...c.relocalizationPreview };
  panel.toggle();
  assert.equal(c.relocalizationDrag, undefined);
  assert.equal(c.canEditRelocalization(), false);
  event('pointermove', { x: 450, y: 320 });
  assert.deepEqual({ ...c.relocalizationPreview }, original);
  panel.toggle(); event('pointerdown', { x: 400, y: 300 });
  assert.equal(c.relocalizationDrag?.mode, 'move');
});
test('opening another map overlay cancels vehicle placement and locks the closed manual panel', () => {
  const c = harness(); const event = gestures(c, 0, 15); const panel = panelControls(c);
  panel.toggle();
  const original = { ...c.relocalizationPreview };
  c.setRelocalizationPlacement(true);
  event('pointermove', { x: 500, y: 400 });
  panel.documentListeners['map-overlay-open']({ detail: 'markers' });
  assert.equal(panel.nodes.relocalizationPanel.hidden, true);
  assert.equal(c.relocalizationPlacing, false);
  assert.equal(c.canEditRelocalization(), false);
  assert.deepEqual({ ...c.relocalizationPreview }, original);
});
test('Escape in another overlay cannot discard the closed manual panel preview or configuration', () => {
  const c = harness(); gestures(c, 0, 15); const panel = panelControls(c);
  panel.toggle(); c.editRelocalizationPreview({ x: 7, y: 8, yaw: 1 });
  let resets = 0; c.relocalizationConfigPicker.reset = () => { resets++; };
  panel.documentListeners['map-overlay-open']({ detail: 'markers' });
  panel.documentListeners.keydown({ key: 'Escape' });
  assert.deepEqual({ ...c.relocalizationPreview }, { x: 7, y: 8, yaw: 1 });
  assert.equal(resets, 0);
  panel.toggle(); panel.documentListeners.keydown({ key: 'Escape' });
  assert.equal(c.relocalizationPreview, undefined);
  assert.equal(resets, 1);
});
test('scrolling the localization configuration panel must not zoom the map or consume its wheel',()=>{
  const c=harness();const event=gestures(c,0,15);c.mapView.pixelsPerMeter=15;
  event('wheel',{x:450,y:350},0,{target:{closest:()=>({})},
    preventDefault(){assert.fail('panel scrolling was intercepted by the map');}});
  assert.equal(c.mapView.pixelsPerMeter,15);
});
for (const rotation of [0,.7,-1.3]) {
  test(`place a missing vehicle and drag heading in map coordinates, rotation ${rotation}`,()=>{
    const c=harness();const event=gestures(c,rotation,15);
    c.rawVehiclePose=undefined;c.applyRelocalizationStatus(active);
    c.relocalizationPlacing=true;
    const start=c.viewportPointForMapPosition({x:7,y:8},c.currentMapLayout());
    event('pointerdown',start);
    assert.ok(Math.abs(c.relocalizationPreview.x-7)<1e-9);
    assert.ok(Math.abs(c.relocalizationPreview.y-8)<1e-9);
    event('pointermove',c.viewportPointForMapPosition({x:7,y:10},c.currentMapLayout()));
    assert.ok(Math.abs(c.relocalizationPreview.yaw-Math.PI/2)<1e-9);
    event('pointerup',start);assert.equal(c.relocalizationPlacing,false);
    assert.equal(c.relocalizationActionPending,false);
  });
}
test('an off-map live pose starts placement with the map overview, without chasing the outlier',()=>{
  const c=harness();gestures(c,0,15);
  c.rawVehiclePose={x:9000,y:-9000,yaw:1,receivedAt:100};
  c.applyRelocalizationStatus(active);
  assert.equal(c.relocalizationPreview,undefined);
  assert.equal(c.relocalizationPlacing,true);
  assert.equal(c.mapView.followVehicle,false);
  assert.equal(c.mapView.center.x,20);assert.equal(c.mapView.center.y,5);
  c.applyRelocalizationStatus(active);assert.equal(c.relocalizationPreview,undefined);
});
test('zooming during placement keeps the map independent of the lost live vehicle',()=>{
  const c=harness();const event=gestures(c,0,15);
  c.rawVehiclePose=undefined;c.applyRelocalizationStatus(active);
  event('wheel',{x:400,y:300});
  assert.equal(c.mapView.followVehicle,false);
  assert.equal(c.mapView.center.x,10);assert.equal(c.mapView.center.y,20);
});
test('placement stays local and editable while requests are pending or parking has failed',()=>{
  const c=harness();const event=gestures(c,0,15);
  c.rawVehiclePose=undefined;c.applyRelocalizationStatus(active);
  c.relocalizationActionPending=true;
  event('pointerdown',{x:350,y:350});assert.ok(c.relocalizationPreview);
  event('pointerup',{x:350,y:350});
  c.relocalizationActionPending=false;c.applyRelocalizationStatus({phase:'failed'});
  event('pointerdown',{x:350,y:350});assert.ok(c.relocalizationPreview);
});
test('one-click recovery follows the mouse and cancelling restores the previous candidate',()=>{
  const c=harness();const event=gestures(c,0,15);c.applyRelocalizationStatus(active);
  const original={...c.relocalizationPreview};c.setRelocalizationPlacement(true);
  event('pointermove',c.viewportPointForMapPosition({x:7,y:8},c.currentMapLayout()));
  assert.ok(Math.abs(c.relocalizationPreview.x-7)<1e-9);
  assert.ok(Math.abs(c.relocalizationPreview.y-8)<1e-9);
  c.setRelocalizationPlacement(false);
  assert.equal(c.relocalizationPreview.x,original.x);
  assert.equal(c.relocalizationPreview.yaw,original.yaw);
});
test('interrupted placement restores the previous target instead of committing the hover preview',()=>{
  const c=harness();const event=gestures(c,0,15);c.applyRelocalizationStatus(active);
  const original={...c.relocalizationPreview};c.setRelocalizationPlacement(true);
  const point=c.viewportPointForMapPosition({x:7,y:8},c.currentMapLayout());
  event('pointerdown',point);event('pointercancel',point);
  assert.equal(c.relocalizationPlacing,false);
  assert.equal(c.relocalizationPreview.x,original.x);
});
test('an explicit grab of the resumed real vehicle seeds a new local preview',()=>{
  const c=harness();const event=gestures(c,0,15);
  c.rawVehiclePose=undefined;c.applyRelocalizationStatus(active);
  c.relocalizationPlacing=false;
  c.rawVehiclePose={x:10,y:20,yaw:0,receivedAt:100};
  assert.doesNotThrow(()=>event('pointerdown',{x:400,y:300}));
  assert.equal(c.relocalizationDrag.mode,'move');assert.ok(c.relocalizationPreview);
});

test('a touch grab of the vehicle drags the local preview rather than panning the map',()=>{
  const c=harness();const event=gestures(c,0,15);
  c.beginLocalRelocalizationPreview();
  event('pointerdown',{x:400,y:300},0,{pointerType:'touch'});
  assert.equal(c.relocalizationDrag?.mode,'move');
  const x=c.relocalizationPreview.x;
  event('pointermove',{x:430,y:300},0,{pointerType:'touch'});
  assert.ok(Math.abs(c.relocalizationPreview.x-x-2)<1e-8);
  event('pointerup',{x:430,y:300},0,{pointerType:'touch'});
  assert.equal(c.relocalizationDrag,undefined);
});
for (const scale of [.5, 8, 40, 80]) {
  test(`dragging and rotating a relocation preview preserves the real metric footprint at ${scale}px/m`,()=>{
    const c=harness();gestures(c,.7,scale);
    c.vehicleModel={length_m:1.2,width_m:.75};
    const element={style:{},hidden:true,setAttribute(){}};
    c.$=()=>element;
    const a=source.indexOf('function syncVehicleLayer('),b=source.indexOf('function vehiclePoseInMap(',a);
    vm.runInContext(source.slice(a,b),c);
    c.syncVehicleLayer({position:{x:10,y:20},yaw:0},c.currentMapLayout());
    const initial={width:element.style.width,height:element.style.height};
    for (const pose of [{x:7,y:8,yaw:0},{x:-4,y:12,yaw:1.7},{x:18,y:-3,yaw:-2.1}]) {
      c.editRelocalizationPreview(pose);
      c.syncVehicleLayer(c.previewVehiclePose(undefined),c.currentMapLayout());
      assert.equal(element.style.width,initial.width);
      assert.equal(element.style.height,initial.height);
      assert.ok(Math.abs(parseFloat(element.style.height)-1.2*scale)<1e-10);
      assert.ok(Math.abs(parseFloat(element.style.width)-.75*scale)<1e-10);
      assert.equal(element.hidden,false);
    }
  });
}
test('a metric-sized preview remains draggable from its larger invisible hit area on an overview',()=>{
  const c=harness();const event=gestures(c,0,.5);
  c.setRelocalizationPreview({x:10,y:20,yaw:0});
  // The visible footprint is under one pixel; a grab 20px away still works.
  event('pointerdown',{x:420,y:300});
  assert.equal(c.relocalizationDrag?.mode,'move');
  event('pointermove',{x:430,y:300});event('pointerup',{x:430,y:300});
  assert.ok(Math.abs(c.relocalizationPreview.x-30)<1e-8);
});
for (const [rotation,scale] of [[0,15],[.7,45],[-1.3,8]]) {
  test(`grab offset survives nonzero origin, rotation ${rotation} and zoom ${scale}`,()=>{
    const c=harness();c.applyRelocalizationStatus(active);
    c.setRelocalizationPreview({x:10,y:20,yaw:.4});
    const event=gestures(c,rotation,scale);
    const start=c.viewportPointForMapPosition({x:10.1,y:20.1},c.currentMapLayout());
    event('pointerdown',start);event('pointermove',start);
    assert.ok(Math.abs(c.relocalizationPreview.x-10)<1e-9);
    assert.ok(Math.abs(c.relocalizationPreview.y-20)<1e-9);
    const end=c.viewportPointForMapPosition({x:11.1,y:19.6},c.currentMapLayout());
    event('pointermove',end);
    assert.ok(Math.abs(c.relocalizationPreview.x-11)<1e-9);
    assert.ok(Math.abs(c.relocalizationPreview.y-19.5)<1e-9);
    const committedX=c.relocalizationPreview.x;
    c.relocalizationActionPending=true;
    event('pointermove',start);assert.ok(Math.abs(c.relocalizationPreview.x-10)<1e-9);
  });
}
test('right drag adds relative yaw and a failed parking poll preserves the operator target',()=>{
  const c=harness();c.applyRelocalizationStatus(active);c.setRelocalizationPreview({x:10,y:20,yaw:2.9});
  const event=gestures(c,.7,45);
  const start=c.viewportPointForMapPosition({x:10.2,y:20},c.currentMapLayout());
  event('pointerdown',start,2);event('pointermove',start,2);
  assert.ok(Math.abs(c.relocalizationPreview.yaw-2.9)<1e-9);
  event('pointermove',c.viewportPointForMapPosition({x:10,y:20.2},c.currentMapLayout()),2);
  assert.ok(Math.abs(c.relocalizationPreview.yaw-Math.atan2(Math.sin(2.9+Math.PI/2),Math.cos(2.9+Math.PI/2)))<1e-9);
  c.applyRelocalizationStatus({phase:'failed'});
  assert.ok(c.relocalizationPreview);assert.equal(c.canEditRelocalization(),true);
});
test('fresh handoff uses actual pose and resets all velocity estimates without inventing target feedback',()=>{
  const c=harness();let clears=0;
  Object.assign(c,{lastPoseTimestamp:200n, relocalizationAwaitingPose:true,
    relocalizationPreview:{x:50,y:60,yaw:1},latestLiveMotion:{position:{x:10,y:20},yaw:0,measuredAt:99},
    renderedVehiclePose:{position:{x:10,y:20}},tfVehiclePose:{position:{x:10,y:20}},
    livePoseUpdatedAt:0,vehicleUpdatedAt:0,livePoseSourceAgeMs:0,
    clientPerformance:{poseApplied:0},yawOf:o=>o.yaw,
    STATIC_POSE_POSITION_HOLD_M:.03,STATIC_POSE_YAW_HOLD_RAD:.02,MAX_VEHICLE_PREDICTION_MS:300,
    MAX_VEHICLE_YAW_RATE_RADPS:3,positionCostmapSprite(){},leaveOverviewAfterMovement(){},
    updateDiagnostics(){},requestFollowAnimation(){},requestVehicleAnimation(){},
    invalidateMapScopedCloud:()=>clears++});
  const a=source.indexOf('function estimateLiveMotion('),b=source.indexOf('function telemetryHeader(',a);
  vm.runInContext(source.slice(a,b),c);
  c.updateLivePose({pose:{position:{x:49.8,y:60.1},orientation:{yaw:.98}}});
  assert.equal(c.relocalizationPreview,undefined);assert.equal(c.relocalizationAwaitingPose,false);
  assert.equal(c.tfVehiclePose.position.x,49.8);assert.equal(c.tfVehiclePose.yaw,.98);
  assert.equal(c.tfVehiclePose.velocity.x,0);assert.equal(c.tfVehiclePose.yawRate,0);
  assert.equal(c.renderedVehiclePose,undefined);assert.equal(c.relocalizationLayerBarrier,200n);
  assert.equal(clears,1);
});
test('uncertain HTTP failure retains local editing while submission waits for a fresh result',async()=>{
  const c=harness(async()=>{throw Error('connection lost');});c.applyRelocalizationStatus(active);
  await c.postRelocalizationAction('/apply',{x:1,y:2,yaw:0});
  assert.equal(c.canEditRelocalization(),true);
  assert.equal(c.relocalizationActionNotice,'connection lost');
});

for(const phase of ['idle','normal','warning','error','failed','unavailable','unknown','relocalizing','initializing','calibrating','calling_service','switching_to_miniapp','switching_to_navigation']) {
  test(`opening manual relocation allows vehicle dragging without any service call in ${phase}`,()=>{
    let calls=0;const c=harness(()=>calls++);const event=gestures(c,0,15);
    c.relocalizationStatus={phase,can_apply:false};
    c.relocalizationActionPending=phase==='calling_service';
    c.beginLocalRelocalizationPreview();
    event('pointerdown',{x:400,y:300});event('pointermove',{x:460,y:300});event('pointerup',{x:460,y:300});
    assert.ok(c.relocalizationPreview);
    assert.ok(Math.abs(c.relocalizationPreview.x-14.01)<1e-9);
    assert.equal(calls,0);
    const x=c.relocalizationPreview.x;c.applyRelocalizationStatus({phase,can_apply:false});
    assert.equal(c.relocalizationPreview.x,x);
  });
}
test('cancelling the preview sends neither parking nor navigation requests',()=>{
  let calls=0;const c=harness(()=>calls++);gestures(c,0,15);
  c.setRelocalizationPreview({x:7,y:8,yaw:1});
  c.discardRelocalizationPreview();assert.equal(c.relocalizationPreview,undefined);
  assert.equal(calls,0);
});
test('a failed cross-map initialization releases local editing once the confirmed target bitmap is visible',()=>{
  const c=harness();c.relocalizationWaitingForMap=true;c.displayedMapId='2222222222222222';
  c.updateRelocalizationMapTarget({phase:'failed',target_map_id:'2222222222222222'});
  assert.equal(c.relocalizationWaitingForMap,false);assert.equal(c.canEditRelocalization(),true);
});
test('a handoff timer for the old submitted revision cannot erase a newer local target',async()=>{
  const c=harness(async()=>({phase:'switching_to_navigation'}));let timer;
  c.window.setTimeout=fn=>{timer=fn;return 1;};
  c.applyRelocalizationStatus(active);c.setRelocalizationPreview({x:1,y:2,yaw:0});
  await c.postRelocalizationAction('/apply',{x:1,y:2,yaw:0});
  c.editRelocalizationPreview({x:7,y:8,yaw:1});timer();
  assert.equal(c.relocalizationPreview.x,7);assert.equal(c.relocalizationPreview.yaw,1);
});
test('success without a fresh pose resets the one-time configuration when handing off the submitted preview',async()=>{
  const c=harness(async()=>({phase:'switching_to_navigation'}));let timer;let resets=0;
  c.window.setTimeout=fn=>{timer=fn;return 1;};c.relocalizationConfigPicker.reset=()=>resets++;
  c.editRelocalizationPreview({x:1,y:2,yaw:0});
  await c.postRelocalizationAction('/apply',{x:1,y:2,yaw:0});timer();
  assert.equal(c.relocalizationPreview,undefined);assert.equal(resets,1);
});
test('starting Find immediately after success survives the previous handoff timer before any pointermove',async()=>{
  const c=harness(async()=>({phase:'switching_to_navigation'}));let timer;
  c.window.setTimeout=fn=>{timer=fn;return 1;};
  c.editRelocalizationPreview({x:1,y:2,yaw:0});
  await c.postRelocalizationAction('/apply',{x:1,y:2,yaw:0});
  c.setRelocalizationPlacement(true);timer();
  assert.equal(c.relocalizationPlacing,true);
  assert.equal(c.relocalizationPreview.x,1);
});
test('a lost request is resolved without replay before permitting another explicit Confirm',async()=>{
  const calls=[];const c=harness(async(path,options)=>{
    calls.push([path,options&&JSON.parse(options.body)]);
    if(path.endsWith('/resolve'))return {operation_id:'lost',operation_outcome:'not_admitted'};
    return {operation_id:'lost',operation_outcome:'unknown'};
  });
  gestures(c,0,15);c.editRelocalizationPreview({x:7,y:8,yaw:1});
  c.relocalizationRequestId='lost';c.relocalizationOutcomePending=true;c.relocalizationSubmissionUncertain=true;
  await c.refreshRelocalizationStatus();
  assert.equal(calls[0][0],'/api/observation/relocalization?request_id=lost');
  assert.equal(calls[1][0],'/api/observation/relocalization/resolve');
  assert.equal(calls[1][1].request_id,'lost');
  assert.equal(c.relocalizationOutcomePending,false);
  assert.equal(c.canSubmitRelocalization(),true);assert.equal(c.relocalizationPreview.x,7);
  assert.ok(!calls.some(([path])=>path.endsWith('/apply')));
});
test('one Confirm performs parking and then submits the immutable chosen pose and source map',async()=>{
  const calls=[];
  const c=harness(async(path,options)=>{
    calls.push([path,options&&JSON.parse(options.body)]);
    if(path.endsWith('/begin'))return {...active,source_map_id:'a'.repeat(16)};
    if(path.endsWith('/apply'))return {phase:'switching_to_navigation'};
    return {phase:'idle',can_begin:true};
  });
  gestures(c,0,15);c.editRelocalizationPreview({x:7,y:8,yaw:1});
  c.window.confirm=()=>assert.fail('the Confirm button must start the operation without another modal');
  await c.submitRelocalizationPreview();
  assert.deepEqual(calls.map(([path])=>path),[
    '/api/observation/relocalization','/api/observation/relocalization/begin','/api/observation/relocalization/apply']);
  assert.equal(calls[2][1].x,7);assert.equal(calls[2][1].source_map_id,'a'.repeat(16));
  assert.ok(calls[2][1].request_id);
});
test('an edit during automatic parking remains local and does not alter the confirmed request',async()=>{
  const parked=deferred();let applied;
  const c=harness(async(path,options)=>{
    if(path.endsWith('/begin'))return parked.promise;
    if(path.endsWith('/apply')){applied=JSON.parse(options.body);return {phase:'switching_to_navigation'};}
    return {phase:'idle',can_begin:true};
  });
  gestures(c,0,15);c.editRelocalizationPreview({x:7,y:8,yaw:1});
  const submit=c.submitRelocalizationPreview();await new Promise(resolve=>setImmediate(resolve));
  c.editRelocalizationPreview({x:17,y:18,yaw:2});parked.resolve(active);await submit;
  assert.equal(applied.x,7);assert.equal(c.relocalizationPreview.x,17);
});
test('parking failure never submits a service request and preserves the draggable target',async()=>{
  const calls=[];const c=harness(async path=>{
    calls.push(path);return path.endsWith('/begin')?{phase:'failed',detail:'停车未确认'}:{phase:'idle',can_begin:true};
  });
  gestures(c,0,15);c.editRelocalizationPreview({x:7,y:8,yaw:1});
  await c.submitRelocalizationPreview();
  assert.ok(!calls.some(path=>path.endsWith('/apply')));
  assert.equal(c.relocalizationPreview.x,7);assert.equal(c.canEditRelocalization(),true);
});
test('a map change while parking rejects the old confirmed coordinates before apply',async()=>{
  const calls=[];let c;c=harness(async path=>{
    calls.push(path);
    if(path.endsWith('/begin')){c.displayedMapId='b'.repeat(16);return active;}
    return {phase:'idle',can_begin:true};
  });
  gestures(c,0,15);c.editRelocalizationPreview({x:7,y:8,yaw:1});
  await c.submitRelocalizationPreview();assert.ok(!calls.some(path=>path.endsWith('/apply')));
});
test('a lost successful HTTP response is resolved by its operation ID without replaying the mutation',async()=>{
  let posts=0;const c=harness(async(path,options)=>{
    if(options){posts++;throw Error('response lost');}
    return {phase:'idle',operation_id:'manual-lost',operation_outcome:'succeeded'};
  });
  gestures(c,0,15);c.editRelocalizationPreview({x:7,y:8,yaw:1});
  await c.postRelocalizationAction('/apply',{x:7,y:8,yaw:1,request_id:'manual-lost'});
  assert.equal(c.relocalizationSubmissionUncertain,true);
  c.editRelocalizationPreview({x:17,y:18,yaw:2});
  await c.refreshRelocalizationStatus();
  assert.equal(posts,1);assert.equal(c.relocalizationOutcomePending,false);
  assert.equal(c.relocalizationPreview.x,17);assert.equal(c.canEditRelocalization(),true);
});
test('an unrelated idle status cannot falsely resolve an unknown submitted operation',async()=>{
  const c=harness(async(path,options)=>{
    if(options)throw Error('response lost');
    return {phase:'idle',operation_id:'another-request',operation_outcome:'succeeded'};
  });
  gestures(c,0,15);c.editRelocalizationPreview({x:7,y:8,yaw:1});
  await c.postRelocalizationAction('/apply',{x:7,y:8,yaw:1,request_id:'manual-unknown'});
  await c.refreshRelocalizationStatus();
  assert.equal(c.relocalizationOutcomePending,true);assert.equal(c.canSubmitRelocalization(),false);
  assert.equal(c.canEditRelocalization(),true);
});
test('an unconfirmed partial map failure restores local editing but fences live telemetry',()=>{
  const c=harness();gestures(c,0,15);c.relocalizationWaitingForMap=true;
  c.applyRelocalizationStatus({phase:'failed',detail:'地图切换未确认',can_begin:true});
  assert.equal(c.relocalizationWaitingForMap,false);assert.equal(c.relocalizationMapUnconfirmed,true);
  assert.equal(c.canEditRelocalization(),true);assert.equal(c.rawVehiclePose,undefined);
});

test('manual cross-map request discards old telemetry until both services finish', async()=>{
  const pending=deferred();const c=harness(()=>pending.promise);let poses=0;
  Object.assign(c,{ArrayBuffer,DataView,TELEMETRY_HEADER_BYTES:20,TELEMETRY_MAGIC:'ALTM',
    TELEMETRY_POSE:2,TELEMETRY_CLOUD:1,TELEMETRY_COSTMAP:3,POINT_LIMIT:1024,
    COSTMAP_MAX_CELLS:1024,COSTMAP_META_BYTES:20,Date,
    updateLivePose:()=>poses++,cloud:undefined,costmap:undefined});
  const a=source.indexOf('function telemetryHeader('),b=source.indexOf('function scheduleLatestCloudPacket(',a);
  vm.runInContext(source.slice(a,b),c);
  function packet(kind){
    const size=kind===2?32:kind===1?28:41;
    const data=new ArrayBuffer(size),v=new DataView(data);
    for(let i=0;i<4;i++)v.setUint8(i,'ALTM'.charCodeAt(i));
    v.setUint8(4,1);v.setUint8(5,kind);v.setBigUint64(10,200n);v.setUint16(18,1);
    return data;
  }
  c.applyRelocalizationStatus(active);
  const post=c.postRelocalizationAction('/apply',{x:50,y:60,yaw:0,config_path:'/opt/ry/config/localization/P1.yaml'});
  assert.equal(c.relocalizationSwitchingMap,true);
  c.updateTelemetryPose(packet(2));c.updateTelemetryCloud(packet(1));c.updateTelemetryCostmap(packet(3));
  assert.equal(poses,0);assert.equal(c.cloud,undefined);assert.equal(c.costmap,undefined);
  c.displayedMapId='1234567890abcdef';
  pending.resolve({phase:'switching_to_navigation',target_map_id:'1234567890abcdef'});await post;
  assert.equal(c.relocalizationSwitchingMap,false);
  c.updateTelemetryPose(packet(2));assert.equal(poses,1);
});

test('successful RPC keeps telemetry fenced until the target bitmap is actually displayed',async()=>{
  const c=harness(async()=>({phase:'switching_to_navigation',target_map_id:'1234567890abcdef'}));
  let requests=0;c.refreshActiveMap=()=>requests++;
  c.applyRelocalizationStatus(active);
  await c.postRelocalizationAction('/apply',{x:1,y:2,yaw:0,config_path:'/opt/ry/config/localization/P1.yaml'});
  assert.equal(c.relocalizationActionPending,false);
  assert.equal(c.relocalizationWaitingForMap,true);
  assert.equal(c.relocalizationAwaitingPose,true);
  assert.equal(requests,1);
  c.displayedMapId='1111111111111111';c.updateRelocalizationMapTarget(c.relocalizationStatus);
  assert.equal(c.relocalizationWaitingForMap,true);
  c.displayedMapId='1234567890abcdef';c.updateRelocalizationMapTarget(c.relocalizationStatus);
  assert.equal(c.relocalizationWaitingForMap,false);
});

test('a pre-switch map metadata response cannot replace the selected target',async()=>{
  const old=deferred();const target=deferred();const loads=[];
  const c=harness(url=>url.includes('1111111111111111')?old.promise:target.promise);
  Object.assign(c,{loadedMapId:undefined,requestedActiveMapId:undefined,
    relocalizationTargetMapAcknowledged:false,virtualWalls:[],mapMarkers:[],
    clearLiveWallCompensation(){},closeMapMarkerMenu(){},closeMapMarkerForm(){},
    renderNavigationRoute(){},renderMapMarkers(){},loadCachedMap:(id)=>loads.push(id),
    updateDiagnostics(){},reportObservationOnce(){}});
  const a=source.indexOf('async function refreshActiveMap(observation,'),b=source.indexOf('function liveWallSignature(',a);
  vm.runInContext(source.slice(a,b),c);
  const first=c.refreshActiveMap({active_map_id:'1111111111111111'});
  c.activeMapRequestEpoch++;c.requestedActiveMapId=undefined;
  c.relocalizationTargetMapId='2222222222222222';c.relocalizationWaitingForMap=true;
  const second=c.refreshActiveMap({active_map_id:'2222222222222222'},true);
  target.resolve({map:{},virtual_walls:[]});await second;
  old.resolve({map:{},virtual_walls:[]});await first;
  assert.deepEqual(loads,['2222222222222222']);
});
test('bitmap failure releases its request marker so target loading can retry',()=>{
  const c=harness();let image;
  Object.assign(c,{loadedMapId:undefined,requestedActiveMapId:'2222222222222222',
    Image:class{constructor(){image=this;}},setText(){},reportObservationOnce(){}});
  const a=source.indexOf('function loadCachedMap('),b=source.indexOf('function closeTelemetryConnections(',a);
  vm.runInContext(source.slice(a,b),c);
  c.loadCachedMap('2222222222222222',{width:10,height:10,resolution:.05,origin:[0,0]});
  image.onerror();assert.equal(c.loadedMapId,undefined);assert.equal(c.requestedActiveMapId,undefined);
});
