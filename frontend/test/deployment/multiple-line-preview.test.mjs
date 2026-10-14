import test from 'node:test';
import assert from 'node:assert/strict';
import * as view from '../../../autodrive_console/web/deployment/execution-chain-view.js';
import * as previewTools from '../../../autodrive_console/web/deployment/task-compiler-preview.js';

const lines=['a','b'].map((id,index)=>({id,name:`送货 ${1508+index}`,start_component_id:'start',steps:[{kind:'component',id,action:{purpose:'delivery',cargo_id:index+1,operation:'unload'}}],subtask_start:index*2,subtask_count:2}));
const project={components:[{id:'start',kind:'start',label:'起点'},{id:'a',kind:'target',label:'目标点',attributes:{door:'1508'}},{id:'b',kind:'target',label:'目标点',attributes:{door:'1509'}}],map_assets:[{id:'floor',label:'用户楼层15'}]};
const preview={status:'ready',manifest:{compiled_task_lines:lines,active_task_line:lines[0],subtask_map_asset_ids:['floor','floor','floor','floor'],subtask_task_line_ids:['a','a','b','b'],waypoint_trace:[]},task_json:{subtasks:[]}};
for(const [index,line] of lines.entries())for(const leg of ['outbound','return']){
 const points=leg==='outbound'?[{id:'start',x:0},{id:line.id,x:index+1}]:[{id:line.id,x:index+1},{id:'start',x:0}];
 const nodes=points.map((point,i)=>({waypoint_id:`${line.id}-${leg}-${i}`,pose:{position:{x:point.x,y:0}},speed_mode:'single_point'}));
 preview.task_json.subtasks.push({subtask_name:leg,waypoints:nodes});
 preview.manifest.waypoint_trace.push(...points.map((point,i)=>({waypoint_id:nodes[i].waypoint_id,leg,map_asset_id:'floor',task_line_id:line.id,source_id:point.id,role:point.id==='start'?'start':'delivery',label:point.id==='start'?'起点':'目标点'})));
}
test('all routes retain line attribution and never bridge independent lines',()=>{
 const segments=view.previewRouteSegments(preview,project,'floor');
 assert.equal(segments.length,4);
 assert.deepEqual(segments.map(s=>s.taskLineId),['a','a','b','b']);
 assert.equal(segments[2].points.length,2,'new route must not inherit the preceding return endpoint');
});
test('room labels and cargo actions belong to each line in all-route preview',()=>{
 const items=view.previewTaskItems(preview,project,'outbound');
 const destinations=items.filter(item=>item.title.includes('目标点'));
 assert.deepEqual(destinations.map(d=>d.title),['目标点 · 1508','目标点 · 1509']);
 assert.match(destinations[0].detail,/上仓 1/);assert.match(destinations[1].detail,/下仓 2/);
 assert.match(destinations[1].detail,/送货 1509/);
});
test('route selector uses actual compiled subtask spans without changing the full preview',()=>{
 assert.equal(typeof previewTools.selectTaskLinePreview,'function');
 const single=previewTools.selectTaskLinePreview(preview,'b');
 assert.equal(single.manifest.active_task_line.id,'b');
 assert.equal(single.task_json.subtasks.length,2);
 assert.equal(view.previewWaypointNodes(single,project).length,4);
 assert.deepEqual(view.previewRouteSegments(single,project,'floor').map(s=>s.taskLineId),['b','b']);
 assert.equal(preview.task_json.subtasks.length,4);
 assert.equal(previewTools.selectTaskLinePreview(preview,'all'),preview);
});
