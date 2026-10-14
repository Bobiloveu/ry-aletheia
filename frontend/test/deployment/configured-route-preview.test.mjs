import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import * as compiler from '../../../autodrive_console/web/deployment/task-compiler-preview.js';
import {previewRouteSegments} from '../../../autodrive_console/web/deployment/execution-chain-view.js';
import {taskLineRouteSegments} from '../../../autodrive_console/web/deployment/task-lines.js';
import {createRoutePreview} from '../../../autodrive_console/web/deployment/route-preview.js';

const line={id:'line',name:'配送',start_component_id:'start',steps:[{kind:'transition',id:'door'},{kind:'component',id:'home',action:{purpose:'delivery',cargo_id:1,operation:'open'}}]};
const project={id:'p',task_mode:'single',active_task_line_id:'line',task_lines:[line],task_compiler:{identity:{community:'测试',last_preview_input_sha256:'valid'}},components:[
  {id:'start',kind:'start',map_asset_id:'hall',x:0,y:0},{id:'home',kind:'target',map_asset_id:'floor',x:4,y:4},
],waypoints:[{id:'door',kind:'transition',map_asset_id:'hall',x:2,y:0}],map_assets:[{id:'hall'},{id:'floor'}]};
const wp=(waypoint_id,x,y)=>({waypoint_id,pose:{position:{x,y}}});
const preview={status:'ready',task_mode:'single',input_sha256:'valid',artifacts:[{path:'tasks/line.json'}],manifest:{task_mode:'single',active_task_line:line,subtask_map_asset_ids:['hall','floor','hall']},task_json:{subtasks:[
  {subtask_name:'outbound_hall',waypoints:[wp('start',0,0),wp('door',2,0),wp('lift',0,3)]},
  {subtask_name:'outbound_floor',waypoints:[wp('home',4,4)]},
  {subtask_name:'return_hall',waypoints:[wp('arrive',0,3),wp('complete',0,0)]},
]}};
const source=readFileSync(new URL('../../../autodrive_console/web/deployment.js',import.meta.url),'utf8');
function fn(name){const start=source.indexOf(`function ${name}(`);return start<0?'':source.slice(start,source.indexOf('\n}',start)+2);}
const plain=value=>JSON.parse(JSON.stringify(value));
function canvas({dirty=false,busy=false,draft=line,cached=preview,inline=null}={}) {
  const state={selectedProject:project,activeMap:{id:'hall'},taskPreviewOpen:false,taskCompilerPreview:cached,taskCompilerProjectId:'p',
    taskLinesUI:{dirty,busy,draft},taskLineCompileBlocked:()=>dirty||busy,document:{body:{dataset:{deploymentStage:'localization'}}},
    deploymentProjectGeneration:1,deploymentStageEditGeneration:1,taskLinePreviewGeneration:1,
    reusableTaskPreview:compiler.reusableTaskPreview,previewIncludesTaskLine:compiler.previewIncludesTaskLine,selectTaskLinePreview:compiler.selectTaskLinePreview,taskPreviewLineId:'all',previewRouteSegments,taskLineRouteSegments,
    taskLineMapPreview:{stateFor:()=>inline?{phase:'ready',preview:inline}:{phase:'idle',preview:null}},
  };
  runInNewContext(fn('taskLineMapPreviewContext')+'\n'+fn('configuredTaskLineMapPreview')+'\n'+fn('currentMapRouteSegments'),state);
  return state;
}
test('saved configuration and final preview use the same full lift and return segments',()=>{
  const state=canvas(),configured=plain(state.currentMapRouteSegments());
  assert.deepEqual(configured.map(s=>[s.leg,s.points]),[
    ['outbound',[{x:0,y:0},{x:2,y:0},{x:0,y:3}]],['return',[{x:0,y:3},{x:0,y:0}]],
  ]);
  state.taskPreviewOpen=true;
  assert.deepEqual(plain(state.currentMapRouteSegments()),configured);
});
test('configuration uses inline compiled output before the export overlay has been opened',()=>{
  const state=canvas({cached:null,inline:preview});
  assert.equal(state.currentMapRouteSegments().length,2);
  assert.equal(state.currentMapRouteSegments()[0].points.at(-1).y,3);
});
for(const change of [{dirty:true},{busy:true},{draft:{...line,id:'other'}},{cached:{...preview,input_sha256:'stale'}}]) {
  test(`configuration never overlays obsolete compiled output: ${JSON.stringify(change)}`,()=>{
    const state=canvas(change),segments=state.currentMapRouteSegments();
    assert.deepEqual(plain(segments.map(s=>[s.leg,s.points])),[
      ['outbound',[{x:0,y:0},{x:2,y:0}]],['return',[{x:2,y:0},{x:0,y:0}]],
    ]);
  });
}

const owner=(overrides={})=>({project,projectGeneration:1,editGeneration:1,lineGeneration:1,lineId:'line',...overrides});
function requester() {
  assert.equal(typeof compiler.createTaskLineMapPreview,'function');
  const calls=[],states=[];
  const controller=compiler.createTaskLineMapPreview({request:(url,options)=>new Promise((resolve,reject)=>calls.push({url,options,resolve,reject})),onChange:state=>states.push(state)});
  return {controller,calls,states};
}
const settle=()=>new Promise(resolve=>setImmediate(resolve));
for(const phase of ['error','ready']) {
  test(`inline compilation refreshes its ${phase} hint when route geometry is unchanged`,async()=>{
    const hint={hidden:false,textContent:'',classList:{toggle(name,value){this[name]=value;}}};
    let compilation={phase:'processing',preview:null},workerRequest;
    const worker={postMessage(value){workerRequest=value;},terminate(){}};
    const segments=[{leg:'outbound',points:[{x:0,y:0},{x:1,y:0}]}];
    const state={taskPreviewOpen:false,taskLinesUI:{dirty:false,busy:false,draft:line},selectedProject:project,
      activeMap:{id:'hall'},mapImage:{naturalWidth:100,src:'map'},document:{body:{dataset:{deploymentStage:'localization'}}},
      configuredTaskLineMapPreview:()=>compilation.preview,taskLineMapPreview:{stateFor:()=>compilation},
      taskLineMapPreviewContext:()=>({}),syncTaskLineMapPreview(){},currentMapRouteSegments:()=>segments,
      routeVehicleWidth:0.68,mapBeautyIdentity:()=>'',virtualWallsForActiveMap:()=>[],paintRoutePreview(){},
      context:{},worldCanvasPoint:p=>p,$:()=>hint};
    state.routePreview=createRoutePreview({delay:0,workerFactory:()=>worker,onChange(){state.updateRoutePreviewHint();}});
    try {
      runInNewContext(fn('updateRoutePreviewHint')+'\n'+fn('drawMapRoutes'),state);
      state.drawMapRoutes();
      await new Promise(resolve=>setTimeout(resolve,10));
      worker.onmessage({data:{key:workerRequest.key,result:{segments,failures:[]}}});
      assert.match(hint.textContent,/正在校验完整/);
      compilation=phase==='error'?{phase,preview:null,error:'缺少共享电梯'}:{phase,preview};
      state.drawMapRoutes();
      assert.match(hint.textContent,phase==='error'?/缺少共享电梯/:/完整路线与最终实验预览一致/);
      assert.doesNotMatch(hint.textContent,/正在校验完整/);
      assert.equal(hint.classList['is-error'],phase==='error');
    } finally {state.routePreview.dispose();}
  });
}
test('inline full route uses the controlled preview API and reuses unchanged input across maps',async()=>{
  const f=requester(),context=owner();f.controller.sync(context);
  assert.equal(f.calls[0].url,'/api/deployments/p/task-compiler/preview');
  assert.deepEqual(f.calls[0].options,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  f.calls[0].resolve({preview});await settle();
  assert.equal(f.controller.stateFor(context).preview,preview);
  f.controller.sync({...context});assert.equal(f.calls.length,1);
});
for(const change of [{project:{...project,id:'other'}},{projectGeneration:2},{editGeneration:2},{lineGeneration:2},null]) {
  test(`inline full route ignores stale reply and only requests the latest owner: ${JSON.stringify(change)}`,async()=>{
    const f=requester(),initial=owner(),latest=change?owner(change):null;
    f.controller.sync(initial);f.controller.sync(latest);assert.equal(f.calls.length,1);
    f.calls[0].resolve({preview});await settle();
    assert.notEqual(f.controller.stateFor(latest).phase,'ready');
    assert.equal(f.calls.length,latest?2:1);
  });
}
test('inline compile errors do not loop and a changed draft can request a new full route',async()=>{
  const f=requester(),context=owner();f.controller.sync(context);f.calls[0].reject(Error('缺少共享电梯'));await settle();
  assert.equal(f.controller.stateFor(context).phase,'error');
  assert.match(f.controller.stateFor(context).error,/共享电梯/);
  f.controller.sync({...context});assert.equal(f.calls.length,1);
  f.controller.sync(owner({lineGeneration:2}));assert.equal(f.calls.length,2);
});
for(const bad of [{...preview,task_mode:'multi'},{...preview,manifest:{...preview.manifest,active_task_line:{...line,id:'other'}}},{status:'blocked',errors:['缺少地图']}]) {
  test('inline route rejects a response for an incompatible mode, line or failed compilation',async()=>{
    const f=requester(),context=owner();f.controller.sync(context);f.calls[0].resolve({preview:bad});await settle();
    assert.equal(f.controller.stateFor(context).phase,'error');assert.equal(f.controller.stateFor(context).preview,null);
  });
}
