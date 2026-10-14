import { strict as assert } from "node:assert";
import test from "node:test";

import {
  executionNodeLabel,
  executionNodeRoleLabel,
  executionNodeSpeedLabel,
} from "../../../autodrive_console/web/deployment/execution-chain-view.js";

test("execution-chain display uses operator names instead of opaque node identifiers", () => {
  const project = {
    components: [{ id: "component-75376a39f52d", kind: "gate", label: "东侧闸机" }],
    waypoints: [{ id: "waypoint-3d1448c8878", kind: "transition", label: "过渡点" }],
  };

  assert.equal(
    executionNodeLabel({ source_kind: "component", source_id: "component-75376a39f52d" }, project),
    "闸机 · 东侧闸机",
  );
  assert.equal(
    executionNodeLabel({ source_kind: "transition", source_id: "waypoint-3d1448c8878" }, project),
    "过渡点 1",
  );
  assert.equal(executionNodeRoleLabel("entry"), "进入");
  assert.equal(executionNodeSpeedLabel("slow_point"), "减速");
});

test("execution-chain display never falls back to an opaque identifier", () => {
  assert.equal(
    executionNodeLabel({ source_kind: "component", source_id: "component-75376a39f52d" }, {}),
    "组件",
  );
});

test("execution-chain speed labels distinguish passing through from a single-point stop", () => {
  assert.equal(executionNodeSpeedLabel("normal"), "常规通过");
  assert.equal(executionNodeSpeedLabel("single_point"), "单点停靠");
});

test('fixed execution blocks preserve numeric trip order and repeated map membership',async()=>{
  const {executionChainSections}=await import('../../../autodrive_console/web/deployment/execution-chain-view.js');
  assert.equal(typeof executionChainSections,'function');
  const project={map_assets:[{id:'map-a',label:'大厅'},{id:'map-b',label:'楼层'}],localization_bindings:[{id:'bind-a',map_asset_id:'map-a'}]};
  const node={source_kind:'transition',source_id:'p',x:1,y:2};
  const sections=executionChainSections({block_10:{map_asset_id:'map-a',outbound:[node],return:[node]},block_2:{map_asset_id:'map-b',outbound:[],return:[]},block_1:{binding_id:'bind-a',outbound:[node],return:[]}},project);
  assert.deepEqual(sections.map(section=>[section.key,section.mapAssetId,section.label]),[['block_1','map-a','第 1 段 · 大厅'],['block_2','map-b','第 2 段 · 楼层'],['block_10','map-a','第 3 段 · 大厅']]);
  assert.equal(sections[0].outbound[0].source_id,'p');
  assert.deepEqual(executionChainSections({lobby:{binding_id:'bind-a',outbound:[],return:[]},target:{outbound:[],return:[]}},project).map(section=>section.label),['电梯大厅','用户楼层']);
});

test('preview segments use subtask map metadata without joining across other maps',async()=>{
  const {previewRouteSegments}=await import('../../../autodrive_console/web/deployment/execution-chain-view.js');
  assert.equal(typeof previewRouteSegments,'function');
  const wp=(x,y)=>({pose:{position:{x,y}}});
  const preview={manifest:{subtask_map_asset_ids:['a','a','b','a','a']},task_json:{subtasks:[
    {subtask_name:'start',waypoints:[wp(0,0)]},{subtask_name:'outbound_1',waypoints:[wp(1,0),wp(2,0)]},{subtask_name:'outbound_2',waypoints:[wp(100,100)]},{subtask_name:'outbound_3',waypoints:[wp(4,0)]},{subtask_name:'return_4',waypoints:[wp(2,0),wp(0,0)]},
  ]}};
  assert.deepEqual(previewRouteSegments(preview,{},'a').map(segment=>[segment.leg,segment.points]),[
    ['outbound',[{x:0,y:0}]],['outbound',[{x:0,y:0},{x:1,y:0},{x:2,y:0}]],['outbound',[{x:4,y:0}]],['return',[{x:4,y:0},{x:2,y:0},{x:0,y:0}]],
  ]);
});

test('legacy block-only preview draws only known finite nodes for its bound map',async()=>{
  const {previewRouteSegments}=await import('../../../autodrive_console/web/deployment/execution-chain-view.js');
  assert.equal(typeof previewRouteSegments,'function');
  const preview={manifest:{execution_chain:{lobby:{binding_id:'a',outbound:[{x:1,y:2},{x:3,y:4},{x:null,y:2}],return:[{x:3,y:4},{x:1,y:2}]},target:{binding_id:'b',outbound:[{x:8,y:9}],return:[]}}}};
  const project={localization_bindings:[{id:'a',map_asset_id:'map-a'},{id:'b',map_asset_id:'map-b'}]};
  assert.deepEqual(previewRouteSegments(preview,project,'map-a').map(segment=>[segment.leg,segment.points]),[['outbound',[{x:1,y:2},{x:3,y:4}]],['return',[{x:3,y:4},{x:1,y:2}]]]);
});

test('fixed preview summarizes six business visits and return without runtime names',async()=>{
  const {fixedTaskPreviewSummary}=await import('../../../autodrive_console/web/deployment/execution-chain-view.js');
  assert.equal(typeof fixedTaskPreviewSummary,'function');
  const project={map_assets:[{id:'lobby',label:'大厅'}],components:[
    {id:'start-opaque',kind:'start',label:'仓库',map_asset_id:'lobby'},
    {id:'market-opaque',kind:'target',label:'超市',map_asset_id:'lobby'},
    {id:'customer-opaque',kind:'target',label:'1509 住户',map_asset_id:'lobby'},
  ],waypoints:[{id:'door-opaque',kind:'transition',label:'常开门口',speed_mode:'normal',map_asset_id:'lobby'}]};
  const preview={manifest:{active_task_line:{id:'line-hash123',name:'超市配送',start_component_id:'start-opaque',steps:[
    {kind:'transition',id:'door-opaque'},
    {kind:'component',id:'market-opaque',action:{purpose:'pickup',cargo_id:1,operation:'open'}},
    {kind:'transition',id:'door-opaque'},
    {kind:'component',id:'market-opaque',action:{purpose:'pickup',cargo_id:2,operation:'close'}},
    {kind:'component',id:'customer-opaque',action:{purpose:'delivery',cargo_id:1,operation:'unload'}},
    {kind:'component',id:'market-opaque',action:{purpose:'visit'}},
  ]}},task_json:{subtasks:Array.from({length:23},(_,index)=>({subtask_name:`outbound_fl_hash123_lift_${index}`,waypoints:[]}))}};
  const summary=fixedTaskPreviewSummary(preview,project);
  assert.equal(summary.stepCount,6);assert.equal(summary.items.length,8);
  assert.deepEqual(summary.items.map(item=>item.title),['起点 · 仓库','常开门口','超市','常开门口','超市','1509 住户','超市','自动返程']);
  assert.match(summary.items[2].detail,/取货.*上仓 1.*开仓/);
  assert.match(summary.items[4].detail,/取货.*下仓 2.*关仓/);
  assert.match(summary.items[5].detail,/送货.*上仓 1.*自动卸货/);
  assert.match(summary.items[6].detail,/仅到达.*无仓控/);
  assert.match(summary.items[7].detail,/回到起点.*不重复.*开关仓/);
  assert.doesNotMatch(summary.items.map(item=>`${item.title} ${item.detail}`).join(' '),/hash123|outbound_|\.xml|opaque/);
  assert.equal(fixedTaskPreviewSummary({task_json:preview.task_json},project),null);
});
