import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext,createContext} from 'node:vm';
import {createTaskLineSession,taskLineSelectionReady} from '../../../autodrive_console/web/deployment/task-lines.js';
import {isActivePreviewRequest,projectWithPreviewHash,previewMatchesTaskMode,reusableTaskPreview} from '../../../autodrive_console/web/deployment/task-compiler-preview.js';

const source=readFileSync(new URL('../../../autodrive_console/web/deployment.js',import.meta.url),'utf8');
function fn(name){const start=source.indexOf(`function ${name}(`);return source.slice(source.slice(start-6,start)==='async '?start-6:start,source.indexOf('\n}',start)+2);}
function editor(operation) {
 const project={id:'a',name:'甲',task_mode:'single',task_compiler:{identity:{community:'甲'}},components:[{id:'start',kind:'start'},{id:'target',kind:'target'}],task_lines:[{id:'line',name:'线路',start_component_id:'start',steps:[{kind:'component',id:'target',action:{purpose:'visit'}}]}],active_task_line_id:'line'};
 const nodes=new Map(),waiting=[],events=[];
 const state={selectedProject:project,deploymentProjectGeneration:1,deploymentStageEditGeneration:1,projectSettingsEditGeneration:1,
  taskCompilerConfigSaveSequence:0,deploymentFlowSaveSequence:0,taskCompilerConfigSavePending:null,deploymentFlowSavePending:null,taskLinePreviewGeneration:0,
  deploymentFlow:[{id:'target_floor',type:'target_floor',label:'用户楼层'}],editingDeploymentStage:operation==='saveCurrentDeploymentFlow'?'project':'export',
  taskCompilerPreview:null,taskCompilerProjectId:'a',topology:null,events,
  $(id){if(!nodes.has(id))nodes.set(id,{disabled:false,value:'甲修改'});return nodes.get(id);},
  request:(url,options)=>new Promise((resolve,reject)=>waiting.push({url,body:options?.body&&JSON.parse(options.body),resolve,reject})),
  validateFlow:()=>({valid:true}),flowForProject:p=>p.flow||[],compilerRecovery:s=>s,
  renderProject(p){events.push(['project',p]);state.selectedProject=p;},renderTopology(){events.push(['topology']);},renderDeploymentGuide(){events.push(['guide']);},
  renderDeploymentFlowEditor(){state.$('saveDeploymentFlow').disabled=false;events.push(['flow']);},
  taskCompilerMessage:(...args)=>events.push(['message',...args]),renderTaskCompilerState:p=>events.push(['compiler',p]),
  completeDeploymentTask:m=>events.push(['complete',m]),note:(...args)=>events.push(['note',...args]),
  renderTaskCompilerPreview:p=>events.push(['preview',p]),renderTaskCompilerCompletionAction(){events.push(['completion']);},openTaskPreview:p=>events.push(['open',p]),
  updateTaskLineCompileControls(){},scheduleMapDraw(){},
  isActivePreviewRequest,projectWithPreviewHash,previewMatchesTaskMode,reusableTaskPreview,taskLineSelectionReady,
  bindTaskLinesUI:options=>createTaskLineSession(options),
 };
 createContext(state);
 const binding=source.slice(source.indexOf('const taskLinesUI = bindTaskLinesUI('),source.indexOf('\nfunction taskLineCompileBlocked'));
 runInNewContext(`${binding}\n${fn('taskLineCompileBlocked')}\n${fn('updateDeploymentSaveControls')}\n${fn(operation)}`,state);
 const session=runInNewContext('taskLinesUI',state);session.load(project);events.length=0;
 return {state,project,nodes,waiting,events,session,resolve(index=0){waiting[index].resolve(operation==='saveTaskCompilerConfig'?{task_compiler:{identity:{community:'甲修改'}}}:operation==='saveCurrentDeploymentFlow'?{project:{...project,name:'保存的甲'},stage_plan:{valid:true}}:{preview:{status:'ready',task_mode:'single',input_sha256:'saved-old-line',manifest:{task_mode:'single'},artifacts:[{path:'tasks/line.json'}]}});}};
}

for(const operation of ['saveTaskCompilerConfig','saveCurrentDeploymentFlow']) {
 test(`${operation} applies a current save and keeps its request payload`,async()=>{
  const f=editor(operation),pending=f.state[operation]();
  assert.equal(f.waiting[0].url,`/api/deployments/a/${operation==='saveTaskCompilerConfig'?'task-compiler/config':'deployment-flow'}`);
  assert.deepEqual(f.waiting[0].body,operation==='saveTaskCompilerConfig'?{community:'甲修改'}:{flow:f.state.deploymentFlow});
  f.resolve();await pending;assert.ok(f.events.some(e=>e[0]==='complete'));
 });
 for(const change of ['other-project','same-project-reopen','project-generation','new-edit','new-input'])for(const outcome of ['success','failure']) {
  test(`${operation}: ${change} ignores late ${outcome} without clearing preview or completing the new editor`,async()=>{
   const f=editor(operation),pending=f.state[operation]();
   if(change==='other-project')f.state.selectedProject={id:'b',name:'乙'};
   if(change==='same-project-reopen')f.state.selectedProject={...f.project,name:'重新打开'};
   if(change==='project-generation')f.state.deploymentProjectGeneration++;
   if(change==='new-edit')f.state.deploymentStageEditGeneration++;
   if(change==='new-input'){if(operation==='saveTaskCompilerConfig')f.state.$('taskCompilerCommunity').value='下一份草稿';else f.state.deploymentFlow.push({id:'lobby',type:'lobby'});}
   const project=f.state.selectedProject,preview={status:'ready',input_sha256:'new'};f.state.taskCompilerPreview=preview;f.events.length=0;
   if(outcome==='success')f.resolve();else f.waiting[0].reject(Error('old failure'));
   await pending;
   assert.equal(f.state.selectedProject,project);assert.equal(f.state.taskCompilerPreview,preview);assert.deepEqual(f.events,[]);
  });
 }
}

test('preview accepts unchanged saved intent',async()=>{
 const f=editor('refreshTaskCompilerPreview'),pending=f.state.refreshTaskCompilerPreview();f.resolve();await pending;
 assert.equal(f.state.taskCompilerPreview.input_sha256,'saved-old-line');assert.ok(f.events.some(e=>e[0]==='open'));
});
for(const edit of ['action','reorder','discard','busy','partial-selection'])for(const outcome of ['success','failure']) {
 test(`preview pending: ${edit} suppresses late ${outcome}`,async()=>{
  const f=editor('refreshTaskCompilerPreview'),pending=f.state.refreshTaskCompilerPreview();
  if(edit==='action'||edit==='discard')f.session.setAction(0,{purpose:'pickup',cargo_id:1,operation:'open'});
  if(edit==='reorder'){f.session.append({kind:'component',id:'target'});f.session.move(1,0);}
  if(edit==='discard')f.session.discard();
  if(edit==='busy')f.session.activate();
  if(edit==='partial-selection')f.state.selectedProject={...f.project,active_task_line_id:null};
  f.events.length=0;
  if(outcome==='success')f.resolve();else f.waiting[0].reject(Error('old preview failure'));
  await pending;
  assert.equal(f.state.taskCompilerPreview,null);assert.ok(!f.events.some(e=>['open','preview','completion','guide'].includes(e[0])));
  if(edit==='busy'){f.waiting[1].resolve({project:f.project});await new Promise(setImmediate);}
 });
}
