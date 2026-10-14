import test from 'node:test';
import {strict as assert} from 'node:assert';
import {transitionDisplayLabel,nextTransitionLabel} from '../../../autodrive_console/web/deployment/transition-labels.js';
import {taskLineLocationLabel} from '../../../autodrive_console/web/deployment/task-lines.js';
import {executionNodeLabel,fixedTaskPreviewSummary} from '../../../autodrive_console/web/deployment/execution-chain-view.js';

const point=(id,label='过渡点',map_asset_id='hall')=>({id,label,map_asset_id,kind:'transition',x:0,y:0,yaw:0});
test('legacy duplicate transitions have matching distinct names in map, picker and preview without rewriting data',()=>{
  const waypoints=[point('exit'),point('entry')];
  const project={waypoints,map_assets:[{id:'hall',label:'摆渡大厅'}]};
  const before=structuredClone(project);
  const preview={manifest:{active_task_line:{steps:waypoints.map(p=>({kind:'transition',id:p.id}))}}};
  const titles=fixedTaskPreviewSummary(preview,project).items.slice(1,-1).map(p=>p.title);
  assert.deepEqual(titles,['过渡点 1','过渡点 2']);
  for(const [i,p] of waypoints.entries()){
    assert.equal(transitionDisplayLabel(project,p),titles[i]);
    assert.equal(taskLineLocationLabel(project,{kind:'transition',id:p.id}),`${titles[i]} · 摆渡大厅`);
    assert.equal(executionNodeLabel({source_kind:'waypoint',source_id:p.id},project),titles[i]);
  }
  assert.deepEqual(project,before);
});
test('new names avoid legacy display numbers and stored names, and stored names survive deletion',()=>{
  const project={waypoints:[point('old'),point('named','过渡点 1'),point('custom','2号门出口'),point('else','过渡点 9','floor')]};
  assert.equal(transitionDisplayLabel(project,project.waypoints[0]),'过渡点 2');
  assert.equal(nextTransitionLabel(project,'hall'),'过渡点 3');
  assert.equal(nextTransitionLabel(project,'floor'),'过渡点 1');
  const after={...project,waypoints:project.waypoints.filter(p=>p.id!=='old')};
  assert.equal(transitionDisplayLabel(after,after.waypoints[0]),'过渡点 1');
  assert.equal(transitionDisplayLabel(after,after.waypoints[1]),'2号门出口');
});
test('duplicate custom names remain distinguishable within the same map',()=>{
  const project={waypoints:[point('a','门口'),point('b','门口'),point('c','门口','floor')]};
  assert.equal(transitionDisplayLabel(project,project.waypoints[0]),'门口（1）');
  assert.equal(transitionDisplayLabel(project,project.waypoints[1]),'门口（2）');
  assert.equal(transitionDisplayLabel(project,project.waypoints[2]),'门口');
});
