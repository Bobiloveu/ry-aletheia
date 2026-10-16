import test from 'node:test';
import assert from 'node:assert/strict';
import * as taskLines from '../../../autodrive_console/web/deployment/task-lines.js';
const project = {
  id:'project-a', map_assets:[{id:'map-a',label:'大厅'}],
  components:[{id:'start-a',kind:'start',map_asset_id:'map-a',label:'仓库'},{id:'target-a',kind:'target',map_asset_id:'map-a',label:'商店'},{id:'gate-a',kind:'gate',map_asset_id:'map-a'}],
  waypoints:[{id:'door-a',kind:'transition',map_asset_id:'map-a',speed_mode:'normal'}], task_lines:[],active_task_line_id:null,
};
const line = {id:'line-a',name:'取货配送',start_component_id:'start-a',steps:[{kind:'transition',id:'door-a'},{kind:'component',id:'target-a',action:{purpose:'pickup',cargo_id:2,operation:'close'}},{kind:'transition',id:'door-a'},{kind:'component',id:'target-a',action:{purpose:'delivery',cargo_id:1,operation:'open'}}]};

test('line validation keeps repeated visits and independent cargo operations',()=>{
  assert.equal(typeof taskLines.validateTaskLine,'function');
  assert.deepEqual(taskLines.validateTaskLine(project,line),[]);
  assert.match(taskLines.validateTaskLine(project,{...line,start_component_id:'other'})[0],/起点/);
  assert.match(taskLines.validateTaskLine(project,{...line,steps:[{kind:'component',id:'gone'}]}).join(' '),/第 1 步/);
  assert.match(taskLines.validateTaskLine(project,{...line,steps:[{kind:'component',id:'target-a',action:{purpose:'pickup',cargo_id:0,operation:'open'}}]}).join(' '),/仓位/);
});

test('draft return intent reverses visits and strips all business actions',()=>{
  assert.equal(typeof taskLines.taskLineReturnPreview,'function');
  assert.deepEqual(taskLines.taskLineReturnPreview(line),[
    {kind:'component',id:'target-a'},{kind:'transition',id:'door-a'},
    {kind:'component',id:'target-a'},{kind:'transition',id:'door-a'},
    {kind:'component',id:'start-a'},
  ]);
  assert.equal(line.steps[1].action.operation,'close');
});

test('editing and reordering drafts leave saved project immutable and discard restores it',()=>{
  assert.equal(typeof taskLines.createTaskLineSession,'function');
  const saved={...project,task_lines:[line],active_task_line_id:'line-a'};
  const session=taskLines.createTaskLineSession(); session.load(saved);
  session.move(3,0); session.remove(1); session.append({kind:'component',id:'target-a'});
  assert.equal(session.dirty,true); assert.equal(saved.task_lines[0].steps.length,4);
  assert.equal(saved.task_lines[0].steps[0].id,'door-a');
  assert.deepEqual(session.draft.steps.at(-1).action,{purpose:'visit'});
  session.discard(); assert.deepEqual(session.draft,line); assert.equal(session.dirty,false);
  session.setAction(1,{purpose:'visit',cargo_id:2,operation:'unload'});
  assert.deepEqual(session.draft.steps[1].action,{purpose:'visit'});
});

test('save submits only outbound intent then explicitly activates returned saved line',async()=>{
  assert.equal(typeof taskLines.createTaskLineSession,'function');
  const calls=[]; const saved={...project,task_lines:[line]};
  const session=taskLines.createTaskLineSession({request:async(url,options)=>{
    calls.push([url,options.method,JSON.parse(options.body)]);
    return calls.length===1 ? {task_line:line,project:saved} : {project:{...saved,active_task_line_id:'line-a'}};
  }});
  session.load(project); session.newDraft(); session.change({name:line.name,start_component_id:line.start_component_id,steps:line.steps});
  await session.save();
  assert.deepEqual(calls,[['/api/deployments/project-a/task-lines','POST',{name:'取货配送',start_component_id:'start-a',steps:line.steps}],['/api/deployments/project-a/task-lines/line-a/select','POST',{}]]);
  assert.equal(session.project.active_task_line_id,'line-a'); assert.equal(session.dirty,false);
});

test('a configured first draft saves without clicking new line first',async()=>{
  const calls=[];
  const saved={...project,task_lines:[line],active_task_line_id:line.id};
  const session=taskLines.createTaskLineSession({request:async(url,options)=>{
    calls.push([url,JSON.parse(options.body)]);return {task_line:line,project:saved};
  }});
  session.load(project);
  session.change({name:line.name,start_component_id:line.start_component_id,steps:line.steps});
  session.newDraft();
  assert.deepEqual(session.draft.steps,line.steps);
  await session.save();
  assert.equal(calls.length,1);assert.equal(calls[0][0],'/api/deployments/project-a/task-lines');
  assert.equal(calls[0][1].name,line.name);
});

test('new line preserves configured edits and creates instead of overwriting the saved line',async()=>{
  const saved=structuredClone({...project,task_lines:[line],active_task_line_id:line.id});
  const calls=[];
  const session=taskLines.createTaskLineSession({request:async(url,options)=>{
    const payload=JSON.parse(options.body);calls.push(url);
    const created={...payload,id:'line-b'};
    return {task_line:created,project:{...saved,task_lines:[...saved.task_lines,created],active_task_line_id:created.id}};
  }});
  session.load(saved);session.change({name:'第二条线路'});session.move(3,0);
  const configured=structuredClone(session.draft);
  session.newDraft();
  assert.equal(session.draft.id,undefined);
  assert.equal(session.dirty,true);
  assert.equal(session.draft.name,configured.name);
  assert.deepEqual(session.draft.steps,configured.steps);
  await session.save();
  assert.deepEqual(calls,['/api/deployments/project-a/task-lines']);
  assert.deepEqual(saved.task_lines,[line]);
});

test('starting from a saved line retains its flow and discard can clear the new copy',()=>{
  const session=taskLines.createTaskLineSession();
  session.load({...project,task_lines:[line],active_task_line_id:line.id});
  session.newDraft();
  assert.deepEqual(session.draft.steps,line.steps);
  assert.equal(session.draft.start_component_id,line.start_component_id);
  assert.equal(session.draft.id,undefined);
  session.discard();assert.deepEqual(session.draft.steps,[]);
});

test('project switch clears drafts and ignores completion of an older save',async()=>{
  assert.equal(typeof taskLines.createTaskLineSession,'function');
  let resolve;const session=taskLines.createTaskLineSession({request:()=>new Promise(r=>{resolve=r;})});
  session.load({...project,task_lines:[line]}); session.change({name:'修改'}); const pending=session.save();
  session.load({...project,id:'project-b'}); resolve({task_line:line,project:{...project,task_lines:[line]}}); await pending;
  assert.equal(session.project.id,'project-b'); assert.equal(session.draft.name,''); assert.equal(session.busy,false);
});

test('failed save preserves draft and reports the backend reason',async()=>{
  assert.equal(typeof taskLines.createTaskLineSession,'function');
  const session=taskLines.createTaskLineSession({request:async()=>{throw new Error('第 2 步不可达');}});
  session.load({...project,task_lines:[line]}); session.change({name:'修改'}); await session.save();
  assert.equal(session.dirty,true); assert.match(session.error,/第 2 步不可达/); assert.equal(session.busy,false);
});

test('map visit numbers retain global order across maps and repeated positions',()=>{
  assert.equal(typeof taskLines.taskLineMapVisits,'function');
  assert.deepEqual(taskLines.taskLineMapVisits(project,line,'map-a').map(visit=>[visit.location.id,visit.order]),[['start-a',0],['door-a',1],['target-a',2],['door-a',3],['target-a',4]]);
});

test('fixed-line projects require an active line even after deleting all lines; legacy projects retain route mode',async()=>{
  const {deriveDeploymentWorkflow}=await import('../../../autodrive_console/web/deployment/workflow.js');
  const prepared={...project,scene_model:'indoor',map_instances:[{map_asset_id:'map-a',role:'outdoor',building:'1',unit:'1'}],localization_bindings:[{id:'binding',map_asset_id:'map-a',type:'outdoor'}],localization_routes:[{task_start_waypoint_id:'start',task_target_waypoint_id:'target'}],task_compiler:{identity:{community:'小区'}}};
  const topology={valid:true,stages:[{stage:'outdoor',map_asset_id:'map-a'}]};
  const unselected=deriveDeploymentWorkflow({...prepared,task_lines:[line]},topology,null);
  assert.equal(unselected.current.id,'localization');assert.equal(unselected.next.target,'taskLineName');
  assert.equal(deriveDeploymentWorkflow({...prepared,task_lines:[line],active_task_line_id:line.id},topology,null).current.id,'export');
  assert.equal(deriveDeploymentWorkflow(prepared,topology,null).current.id,'localization');
  const legacy={...prepared};delete legacy.task_lines;
  assert.equal(deriveDeploymentWorkflow(legacy,topology,null).current.id,'export');
  assert.equal(deriveDeploymentWorkflow({...prepared,task_lines:[{...line,start_component_id:'missing'}],active_task_line_id:line.id},topology,null).current.id,'localization');
});


test('terminal facilities require an explicit outlet before a fixed line can be saved',()=>{
  const errors=taskLines.validateTaskLine(project,{...line,steps:[{kind:'component',id:'gate-a'}]});
  assert.match(errors.join(' '),/末步.*出口|出口.*过渡点/);
});

test('generated and excluded transitions are unavailable to task-line intent',()=>{
  const restricted={...project,waypoints:[...project.waypoints,{id:'generated',kind:'transition',generated_by:'system'},{id:'excluded',kind:'transition',exclude_task_export:true}]};
  assert.deepEqual(taskLines.taskLineLocations(restricted).filter(ref=>ref.kind==='transition').map(ref=>ref.id),['door-a']);
  assert.match(taskLines.validateTaskLine(restricted,{...line,steps:[{kind:'transition',id:'generated'}]}).join(' '),/第 1 步/);
});

test('maps marked only with start and target components can reach fixed-line configuration',async()=>{
  const {deriveDeploymentWorkflow}=await import('../../../autodrive_console/web/deployment/workflow.js');
  const prepared={...project,waypoints:[],scene_model:'indoor',map_instances:[{map_asset_id:'map-a',role:'outdoor',building:'1',unit:'1'}]};
  const topology={valid:true,stages:[{stage:'outdoor',map_asset_id:'map-a'}]};
  const workflow=deriveDeploymentWorkflow(prepared,topology,null);
  assert.equal(workflow.current.id,'localization');
  assert.equal(workflow.next.target,'taskLineName');
});

test('inserting a repeated visit between cards preserves its independent action and saved order',()=>{
  const saved={...project,task_lines:[line],active_task_line_id:line.id};
  const session=taskLines.createTaskLineSession();session.load(saved);
  assert.equal(typeof session.insert,'function');
  session.insert(1,{kind:'component',id:'target-a'});
  assert.deepEqual(session.draft.steps.map(step=>step.id),['door-a','target-a','target-a','door-a','target-a']);
  assert.deepEqual(session.draft.steps[1].action,{purpose:'visit'});
  assert.deepEqual(session.draft.steps[2].action,line.steps[1].action);
  assert.deepEqual(saved.task_lines[0],line);
  session.insert(0,{kind:'transition',id:'door-a'});
  session.insert(session.draft.steps.length,{kind:'transition',id:'door-a'});
  assert.equal(session.draft.steps.length,7);
  const before=structuredClone(session.draft);
  for(const index of [-1,99,1.5])session.insert(index,{kind:'transition',id:'door-a'});
  assert.deepEqual(session.draft,before);
});

test('flow placement snakes from left to right then right to left with downward row turns',()=>{
  assert.equal(typeof taskLines.taskLineFlowLayout,'function');
  assert.deepEqual(taskLines.taskLineFlowLayout(8,820),{
    columns:3,nodes:[
      {row:1,column:1,direction:'right'},{row:1,column:2,direction:'right'},{row:1,column:3,direction:'down'},
      {row:2,column:3,direction:'left'},{row:2,column:2,direction:'left'},{row:2,column:1,direction:'down'},
      {row:3,column:1,direction:'right'},{row:3,column:2,direction:null},
    ],
  });
  assert.deepEqual(taskLines.taskLineFlowLayout(3,280),{columns:1,nodes:[
    {row:1,column:1,direction:'down'},{row:2,column:1,direction:'down'},{row:3,column:1,direction:null},
  ]});
});

test('invalid drag indices never add undefined steps or disturb their cargo settings',()=>{
  const session=taskLines.createTaskLineSession();session.load({...project,task_lines:[line]});
  for(const from of [-1,99,1.5])session.move(from,1);
  assert.deepEqual(session.draft,line);
  session.move(3,0);
  assert.deepEqual(session.draft.steps[0].action,{purpose:'delivery',cargo_id:1,operation:'open'});
});

test('draft return retraces every local visit without inventing a cross-map connection',()=>{
  const p={...project,components:[{...project.components[0],x:0,y:0},{...project.components[1],x:9,y:0},{id:'home',kind:'target',map_asset_id:'map-a',x:2,y:0}],waypoints:[]};
  const draft={...line,steps:[{kind:'component',id:'target-a'},{kind:'component',id:'home'}]};
  assert.deepEqual(taskLines.taskLineRouteSegments(p,draft,'map-a').filter(s=>s.leg==='return').map(s=>s.points),[[{x:2,y:0},{x:9,y:0},{x:0,y:0}]]);
  p.components[2].map_asset_id='other-map';
  assert.deepEqual(taskLines.taskLineRouteSegments(p,draft,'map-a').filter(s=>s.leg==='return').map(s=>s.points),[[{x:9,y:0},{x:0,y:0}]]);
});

test('draft return reverses passage endpoints and their straight-pair indices',()=>{
  const p={...project,components:[{...project.components[0],x:0,y:0},{...project.components[1],x:9,y:0},
    {id:'passage',kind:'narrow_passage',map_asset_id:'map-a',x:4,y:0,yaw:0,attributes:{width_m:2,height_m:1}}],
    waypoints:[{...project.waypoints[0],x:1,y:0}]};
  const draft={...line,steps:[{kind:'transition',id:'door-a'},{kind:'component',id:'passage'},{kind:'component',id:'target-a'}]};
  const segments=taskLines.taskLineRouteSegments(p,draft,'map-a');
  assert.deepEqual(segments.map(s=>s.points),[
    [{x:0,y:0},{x:1,y:0},{x:3,y:0},{x:5,y:0},{x:9,y:0}],
    [{x:9,y:0},{x:5,y:0},{x:3,y:0},{x:1,y:0},{x:0,y:0}],
  ]);
  assert.deepEqual(segments.map(s=>s.straightPairs),[[2],[1]]);
});
