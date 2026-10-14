import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import * as view from '../../../autodrive_console/web/deployment/execution-chain-view.js';
import {selectTaskLinePreview} from '../../../autodrive_console/web/deployment/task-compiler-preview.js';

const project={map_assets:[{id:'hall',label:'一层大厅'},{id:'floor',label:'用户楼层'}],components:[
  {id:'start',kind:'start',label:'仓库',map_asset_id:'hall'},
  {id:'market',kind:'target',label:'超市',map_asset_id:'hall'},
  {id:'home',kind:'target',label:'1509',map_asset_id:'floor'},
]};
const wp=(id,x,y)=>({waypoint_id:id,pose:{position:{x,y}}});
const preview={status:'ready',manifest:{subtask_map_asset_ids:['hall','floor','floor','hall'],
  active_task_line:{name:'配送',start_component_id:'start',steps:[{kind:'component',id:'market',action:{purpose:'pickup',cargo_id:1,operation:'open'}},{kind:'component',id:'home',action:{purpose:'delivery',cargo_id:1,operation:'unload'}}]},
  waypoint_trace:[
    ['start','hall','outbound','仓库','anchor','start'],['pickup','hall','outbound','超市','target','market'],
    ['delivery','floor','outbound','1509','target','home'],
    ['lift_call','floor','return','楼层电梯呼梯点','entry','lift-floor'],['lift_center','floor','return','楼层电梯中心','exit','lift-floor'],
    ['hall_lift','hall','return','大厅电梯中心','entry','lift-hall'],['complete','hall','return','仓库','anchor','start'],
  ].map(([waypoint_id,map_asset_id,leg,label,role,source_id])=>({waypoint_id,map_asset_id,leg,label,role,source_id}))},
  task_json:{subtasks:[
    {subtask_name:'outbound_market',waypoints:[wp('start',0,0),wp('pickup',9,0)]},
    {subtask_name:'outbound_delivery',waypoints:[wp('delivery',4,4)]},
    {subtask_name:'return_floor',waypoints:[wp('lift_call',2,2),wp('lift_center',0,0)]},
    {subtask_name:'return_hall',waypoints:[wp('hall_lift',1,0),wp('complete',0,0)]},
  ]}};

test('actual return list follows compiled trace and map order without replaying outbound pickup',()=>{
  assert.equal(typeof view.previewTaskItems,'function');
  const returned=view.previewTaskItems(preview,project,'return');
  assert.deepEqual(returned.map(item=>[item.title,item.mapAssetId]),[
    ['楼层电梯呼梯点','floor'],['楼层电梯中心','floor'],['大厅电梯中心','hall'],['仓库','hall'],
  ]);
  assert.match(returned[0].detail,/用户楼层.*返程.*进入/);
  const outbound=view.previewTaskItems(preview,project,'outbound');
  assert.deepEqual(outbound.map(item=>item.title),['起点 · 仓库','超市','1509']);
  assert.match(outbound[1].detail,/取货.*开仓/);
  assert.deepEqual(view.previewTaskItems(preview,project,'all'),[...outbound,...returned]);
});

function facilityPreview() {
  const data=structuredClone(preview);
  const added=[
    ['approach','hall','电梯','elevator_approach','lift-hall','single_point'],
    ['wait','hall','电梯','elevator_wait','lift-hall','single_point'],
    ['ride','hall','电梯','elevator_center','lift-hall','normal'],
    ['arrive','floor','电梯','elevator_arrival','lift-floor','backward'],
    ['passage-in','floor','窄通道','entry','passage','single_point'],
    ['passage-out','floor','窄通道','exit','passage','narrow_point'],
  ];
  const trace=added.map(([waypoint_id,map_asset_id,label,role,source_id])=>({waypoint_id,map_asset_id,leg:'outbound',label,role,source_id}));
  const nodes=added.map(([id,,,,,speed_mode],i)=>({...wp(id,i+1,i+1),speed_mode}));
  data.manifest.waypoint_trace.splice(2,0,...trace);
  data.task_json.subtasks[0].waypoints.push(...nodes.slice(0,3));
  data.task_json.subtasks[1].waypoints.unshift(...nodes.slice(3));
  return data;
}

test('outbound itinerary lists every compiled lift and passage node before delivery',()=>{
  const data=facilityPreview(),before=structuredClone(data);
  const rows=view.previewTaskItems(data,project,'outbound');
  assert.deepEqual(rows.map(item=>item.title),['起点 · 仓库','超市','电梯','电梯','电梯','电梯','窄通道','窄通道','1509']);
  assert.deepEqual(rows.map(item=>item.mapAssetId),['hall','hall','hall','hall','hall','floor','floor','floor','floor']);
  assert.match(rows[2].detail,/去程.*电梯门前/);
  assert.match(rows[3].detail,/去程.*候梯.*呼梯/);
  assert.match(rows[4].detail,/去程.*电梯中心.*乘梯/);
  assert.match(rows[5].detail,/去程.*出梯.*关门/);
  assert.match(rows[6].detail,/去程.*进入.*单点停靠/);
  assert.match(rows[7].detail,/去程.*离开.*窄通道/);
  assert.match(rows[1].detail,/取货.*上仓 1.*开仓/);
  assert.match(rows[8].detail,/送货.*上仓 1.*自动卸货/);
  assert.equal(view.previewTaskItems(data,project,'all').length,13);
  assert.equal(view.previewTaskItems(data,project,'return').length,4);
  assert.deepEqual(data,before);
});

test('automatic facility traversals are not collapsed when the same source is crossed twice',()=>{
  const data=facilityPreview();
  const extra=data.manifest.waypoint_trace.slice(6,8).map(node=>({...node,waypoint_id:node.waypoint_id+'-again'}));
  data.manifest.waypoint_trace.splice(8,0,...extra);
  data.task_json.subtasks[1].waypoints.splice(3,0,...extra.map(node=>wp(node.waypoint_id,3,3)));
  assert.deepEqual(view.previewTaskItems(data,project,'outbound').filter(row=>row.title==='窄通道').map(row=>/进入/.test(row.detail)?'entry':'exit'),['entry','exit','entry','exit']);
});

test('repeated target visits keep each visit action while automatic nodes remain in order',()=>{
  const data=facilityPreview();
  data.manifest.active_task_line.steps.splice(1,0,{kind:'component',id:'market',action:{purpose:'pickup',cargo_id:2,operation:'close'}});
  data.manifest.waypoint_trace.splice(2,0,{waypoint_id:'pickup-again',map_asset_id:'hall',leg:'outbound',label:'超市',role:'target',source_id:'market'});
  data.task_json.subtasks[0].waypoints.splice(2,0,wp('pickup-again',9,0));
  const rows=view.previewTaskItems(data,project,'outbound');
  assert.equal(rows.length,10);
  assert.match(rows[1].detail,/取货.*上仓 1.*开仓/);
  assert.match(rows[2].detail,/取货.*下仓 2.*关仓/);
  assert.match(rows[3].detail,/电梯门前/);
});

test('compiled nodes without a valid trace still remain complete instead of falling back to business-only visits',()=>{
  const data=facilityPreview();delete data.manifest.waypoint_trace;
  const rows=view.previewTaskItems(data,project,'outbound');
  assert.equal(rows.length,9);
  assert.deepEqual(rows.map(row=>row.mapAssetId),['hall','hall','hall','hall','hall','floor','floor','floor','floor']);
});

test('outbound elevator exit speed is not mislabeled as the return leg',()=>{
  const arrival=view.previewTaskItems(facilityPreview(),project,'outbound')[5];
  assert.match(arrival.detail,/去程.*出梯.*出梯速度/);
  assert.doesNotMatch(arrival.detail,/返程/);
});

test('legacy return list uses actual return subtasks and server maps, never reversed business steps',()=>{
  assert.equal(typeof view.previewTaskItems,'function');
  const legacy=structuredClone(preview);delete legacy.manifest.waypoint_trace;
  const returned=view.previewTaskItems(legacy,project,'return');
  assert.equal(returned.length,4);
  assert.deepEqual(returned.map(item=>item.mapAssetId),['floor','floor','hall','hall']);
  assert.ok(returned.every(item=>item.leg==='return'));
  assert.ok(returned.every(item=>!item.title.includes('超市')));
  legacy.task_json.subtasks=legacy.task_json.subtasks.slice(0,2);
  legacy.manifest.subtask_map_asset_ids=['hall','floor'];
  assert.deepEqual(view.previewTaskItems(legacy,project,'return'),[]);
});

test('trace owns direction and map attribution, with no line across map changes',()=>{
  const traced=structuredClone(preview);
  // Trace remains authoritative even when a cached runtime name uses an older prefix.
  traced.task_json.subtasks[2].subtask_name='old_floor';
  traced.manifest.subtask_map_asset_ids=['hall','floor','hall','hall'];
  const floor=view.previewRouteSegments(traced,project,'floor');
  assert.deepEqual(floor.map(({leg,points})=>[leg,points]),[
    ['outbound',[{x:4,y:4}]],['return',[{x:4,y:4},{x:2,y:2},{x:0,y:0}]],
  ]);
  const hall=view.previewRouteSegments(traced,project,'hall');
  assert.deepEqual(hall.map(({leg,points})=>[leg,points]),[
    ['outbound',[{x:0,y:0},{x:9,y:0}]],['return',[{x:1,y:0},{x:0,y:0}]],
  ]);
});

test('all/outbound/return filters leave full planner inputs unchanged',()=>{
  assert.equal(typeof view.filterPreviewLeg,'function');
  const segments=view.previewRouteSegments(preview,project,'floor'),before=structuredClone(segments);
  assert.deepEqual(view.filterPreviewLeg(segments,'all'),segments);
  assert.deepEqual(view.filterPreviewLeg(segments,'return').map(s=>s.leg),['return']);
  assert.deepEqual(view.filterPreviewLeg(segments,'outbound').map(s=>s.leg),['outbound']);
  assert.deepEqual(segments,before);
});

const source=readFileSync(new URL('../../../autodrive_console/web/deployment.js',import.meta.url),'utf8');
function controller(name){const start=source.indexOf(`function ${name}(`);assert.notEqual(start,-1,`${name} exists`);return source.slice(start,source.indexOf('\n}',start)+2);}
const plain=value=>JSON.parse(JSON.stringify(value));

test('return-only paints filtered planner results but sends all routes to the planner',()=>{
  const segments=[{leg:'outbound',points:[{x:0,y:0},{x:9,y:0}]},{leg:'return',points:[{x:1,y:0},{x:0,y:0}]}];
  const planned=[],painted=[];
  const state={activeMap:{id:'hall'},mapImage:{naturalWidth:100,src:'map.png'},selectedProject:{id:'p'},
    taskPreviewOpen:true,taskPreviewLeg:'return',filterPreviewLeg:view.filterPreviewLeg,
    syncTaskLineMapPreview(){},
    currentMapRouteSegments:()=>segments,routeVehicleWidth:.8,mapBeautyIdentity:()=>'',virtualWallsForActiveMap:()=>[],
    routePreview:{sync(request){planned.push(request);return {phase:'ready',result:{segments}};}},
    paintRoutePreview:(_ctx,result)=>painted.push(result),context:{},worldCanvasPoint:p=>p,updateRoutePreviewHint(){}};
  runInNewContext(controller('drawMapRoutes')+'\ndrawMapRoutes();',state);
  assert.deepEqual(plain(planned[0].segments),segments);
  assert.deepEqual(plain(painted[0]),[segments[1]]);
});

test('return-only anchor dots use actual return nodes and exclude outgoing pickup',()=>{
  assert.equal(typeof view.previewWaypointNodes,'function');
  const dots=[];
  const state={taskPreviewOpen:true,taskPreviewLeg:'return',taskPreviewLineId:'all',selectTaskLinePreview,taskCompilerPreview:preview,activeMap:{id:'hall'},mapImage:{},selectedProject:project,
    previewWaypointNodes:view.previewWaypointNodes,filterPreviewLeg:view.filterPreviewLeg,worldCanvasPoint:p=>p,
    context:{save(){},restore(){},beginPath(){},arc(x,y){dots.push([x,y]);},fill(){},stroke(){}}};
  runInNewContext(controller('drawCompiledTaskPreview')+'\ndrawCompiledTaskPreview();',state);
  assert.deepEqual(dots,[[1,0],[0,0]]);
});

test('direction toolbar exposes native keyboard buttons and pressed state',()=>{
  const html=readFileSync(new URL('../../../autodrive_console/web/deployment.html',import.meta.url),'utf8');
  assert.match(html,/id="taskPreviewDirection"[^>]*role="group"[^>]*aria-label="预览路线方向"/);
  for(const [leg,label] of [['all','全部'],['outbound','去程'],['return','返程']])
    assert.match(html,new RegExp(`<button[^>]*data-task-preview-leg="${leg}"[^>]*aria-pressed="(?:true|false)"[^>]*>${label}</button>`));
});

test('return-only saved annotations include only actual return sources, hiding pickup and outbound transitions',()=>{
  assert.equal(typeof view.previewDirectionProject,'function');
  const p={...project,waypoints:[{id:'outbound-door',kind:'transition',map_asset_id:'hall'}]};
  const result=view.previewDirectionProject(preview,p,'return');
  assert.deepEqual(result.components.map(item=>item.id),['start']);
  assert.deepEqual(result.waypoints,[]);
  assert.equal(view.previewDirectionProject(preview,p,'all'),p);
  assert.equal(p.components.length,3);
});

test('mismatched trace cannot assign another waypoint label or map to cached poses',()=>{
  assert.equal(typeof view.previewWaypointNodes,'function');
  const bad=structuredClone(preview);bad.manifest.waypoint_trace.reverse();
  const nodes=view.previewWaypointNodes(bad,project);
  assert.deepEqual(nodes.map(node=>node.mapAssetId),['hall','hall','floor','floor','floor','hall','hall']);
  assert.ok(nodes.every(node=>!node.label));
});

test('an empty subtask on another map still breaks the visible map line',()=>{
  const cached={manifest:{subtask_map_asset_ids:['hall','floor','hall']},task_json:{subtasks:[
    {subtask_name:'outbound_hall',waypoints:[wp('a',0,0)]},
    {subtask_name:'outbound_floor',waypoints:[]},
    {subtask_name:'return_hall',waypoints:[wp('b',1,0),wp('c',2,0)]},
  ]}};
  assert.deepEqual(view.previewRouteSegments(cached,project,'hall').map(segment=>segment.points),[
    [{x:0,y:0}],[{x:1,y:0},{x:2,y:0}],
  ]);
});

test('legacy chain-only return nodes follow return traversal across maps',()=>{
  const cached={manifest:{execution_chain:{block_1:{map_asset_id:'hall',outbound:[],return:[{x:0,y:0,source_kind:'component',source_id:'start'}]},block_2:{map_asset_id:'floor',outbound:[],return:[{x:4,y:4,source_kind:'component',source_id:'home'}]}}}};
  assert.deepEqual(view.previewTaskItems(cached,project,'return').map(item=>item.mapAssetId),['floor','hall']);
});

test('compiled lift nodes distinguish waiting, riding and arriving even with one shared component name',()=>{
  const traced=structuredClone(preview);
  const roles=['elevator_approach','elevator_center','elevator_arrival','return_start'];
  traced.manifest.waypoint_trace.slice(3).forEach((node,index)=>{node.label='1 号电梯';node.role=roles[index];});
  const rows=view.previewTaskItems(traced,project,'return');
  assert.match(rows[0].detail,/电梯门前/);
  assert.match(rows[1].detail,/电梯中心/);
  assert.match(rows[2].detail,/出梯/);
  assert.match(rows[3].detail,/回到起点/);
});

test('return details retain the runtime speed_mode for narrow passage nodes',()=>{
  const traced=structuredClone(preview);
  traced.task_json.subtasks[2].waypoints[0].speed_mode='narrow_point';
  assert.equal(view.previewWaypointNodes(traced,project)[3].speed,'narrow_point');
  assert.match(view.previewTaskItems(traced,project,'return')[0].detail,/窄通道/);
});

test('return view clearly identifies route errors from full-route validation',()=>{
  const hint={textContent:''};
  const state={taskPreviewOpen:true,taskPreviewLeg:'return',filterPreviewLeg:view.filterPreviewLeg,
    routePreview:{state:{phase:'ready',result:{failures:[{leg:'outbound',reason:'去程阻断'}]}}},
    currentMapRouteSegments:()=>[{leg:'return',points:[{x:0,y:0},{x:1,y:0}]}],
    $:id=>id==='taskPreviewInspectorHint'?hint:null};
  runInNewContext(controller('updateRoutePreviewHint')+'\nupdateRoutePreviewHint();',state);
  assert.match(hint.textContent,/完整路线校验.*去程阻断/);
});

const taggedChain={
  block_1:{map_asset_id:'hall',leg:'outbound',start_anchor:{x:0,y:0},end_anchor:{x:9,y:0},
    outbound:[{x:9,y:0,source_kind:'component',source_id:'market',role:'waypoint'}],
    return:[{x:90,y:0,source_kind:'transition',source_id:'phantom'}]},
  block_2:{map_asset_id:'hall',leg:'return',start_anchor:{x:2,y:0},end_anchor:{x:0,y:0},
    outbound:[{x:1,y:0,source_kind:'component',source_id:'start',role:'waypoint'}],
    return:[{x:99,y:0,source_kind:'transition',source_id:'phantom'}]},
};

test('tagged chain blocks retain explicit leg and chain-only fallback uses each actual directed block once',()=>{
  assert.deepEqual(view.executionChainSections(taggedChain,project).map(section=>section.leg),['outbound','return']);
  const cached={manifest:{execution_chain:taggedChain}};
  assert.deepEqual(view.previewWaypointNodes(cached,project).map(node=>[node.leg,node.x]),[['outbound',9],['return',1]]);
  assert.deepEqual(view.previewRouteSegments(cached,project,'hall').map(segment=>[segment.leg,segment.points]),[
    ['outbound',[{x:0,y:0},{x:9,y:0},{x:9,y:0}]],
    ['return',[{x:2,y:0},{x:1,y:0},{x:0,y:0}]],
  ]);
});

for (const [leg,count,rows] of [['all','9 个去程节点 · 4 个返程节点',13],['outbound','9 个去程节点',9],['return','4 个返程节点',4]]) {
  test(`${leg} inspector count and rendered rows describe the complete compiled itinerary`,()=>{
    const elements=new Map();
    const state={taskPreviewOverlay:{},selectedProject:project,activeMap:{id:'floor'},taskPreviewLeg:leg,taskPreviewLineId:'all',selectTaskLinePreview,
      previewMapAssets:()=>project.map_assets,fixedTaskPreviewSummary:view.fixedTaskPreviewSummary,
      previewTaskItems:view.previewTaskItems,esc:String,updateRoutePreviewHint(){},
      $(id){if(!elements.has(id))elements.set(id,{parentElement:{},textContent:'',innerHTML:'',querySelectorAll:()=>[]});return elements.get(id);}};
    runInNewContext(controller('renderTaskPreviewOverlay'),state);
    state.renderTaskPreviewOverlay(facilityPreview());
    assert.equal(elements.get('taskPreviewStepCount').textContent,count);
    assert.equal((elements.get('taskPreviewTaskList').innerHTML.match(/<li /g)||[]).length,rows);
  });
}

test('technical audit labels independently compiled return blocks without rendering local reverse candidates',()=>{
  const p={...project,waypoints:[{id:'phantom',kind:'transition',label:'不应展示的反转候选'}]};
  const state={selectedProject:p,executionChainSections:view.executionChainSections,executionNodeLabel:view.executionNodeLabel,
    executionNodeRoleLabel:view.executionNodeRoleLabel,executionNodeSpeedLabel:view.executionNodeSpeedLabel,esc:value=>String(value)};
  runInNewContext(controller('renderExecutionChainTrace'),state);
  const html=state.renderExecutionChainTrace(taggedChain);
  assert.match(html,/去程实际通行节点/);
  assert.match(html,/返程实际通行节点/);
  assert.match(html,/带方向的地图段按编译段序执行/);
  assert.doesNotMatch(html,/返程按相反段序|不应展示的反转候选/);
  assert.equal((html.match(/实际通行节点<\/b>/g)||[]).length,2);
});
