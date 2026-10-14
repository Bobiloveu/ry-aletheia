import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
const source=readFileSync(new URL('../../../autodrive_console/web/deployment.js',import.meta.url),'utf8');
function fn(name){const start=source.indexOf(`function ${name}(`);return start<0?'':source.slice(source.slice(start-6,start)==='async '?start-6:start,source.indexOf('\n}',start)+2);}
function editor(operation) {
 const nodes=new Map(),waiting=[],events=[];
 const project={id:'p',map_assets:[],name:'项目',task_compiler:{identity:{community:'小区'}}};
 const state={selectedProject:project,deploymentProjectGeneration:1,deploymentStageEditGeneration:1,projectSettingsEditGeneration:1,
  taskCompilerConfigSaveSequence:0,deploymentFlowSaveSequence:0,taskCompilerConfigSavePending:null,deploymentFlowSavePending:null,
  editingDeploymentStage:operation==='saveTaskCompilerConfig'?'export':'project',viewedDeploymentStage:'export',
  creatingAnotherProject:false,topology:null,taskCompilerPreview:null,deploymentFlow:[{id:'target_floor',type:'target_floor'}],
  $:id=>{if(!nodes.has(id))nodes.set(id,{disabled:false,value:id==='taskCompilerCommunity'?'首份草稿':'项目',classList:{toggle(){}}});return nodes.get(id);},
  request:(url,options)=>new Promise((resolve,reject)=>waiting.push({url,body:JSON.parse(options.body),resolve,reject})),
  taskCompilerMessage:(...args)=>events.push(['message',...args]),note:(...args)=>events.push(['note',...args]),compilerRecovery:s=>s,
  renderTaskCompilerState(){},renderProject(p){state.selectedProject=p;},renderTopology(){},renderDeploymentFlowEditor(){},
  flowForProject:()=>state.deploymentFlow,validateFlow:()=>({valid:true}),
  deriveDeploymentWorkflow:()=>({current:{id:'export'},next:{},completed:5,total:5,percent:100,steps:[{id:'project',label:'项目',status:'complete'},{id:'export',label:'导出',status:'complete'}]}),
  clampDeploymentStage:(_,stage)=>stage,GUIDE_STATUS_LABELS:{complete:'完成'},esc:String,
  renderDeploymentTaskConsole(){},persistDeploymentSession(){},focusCurrentTaskHeading(){},closeDeploymentEditImpact(){state.pendingEditStage=null;},focusGuideTarget(){},guideTargetForStep:()=>null,
  completeDeploymentTask:m=>events.push(['complete',m]),
 };
 runInNewContext(['resetProjectSettings','renderDeploymentGuide','runDeploymentGuideAction','confirmDeploymentStageEdit','updateDeploymentSaveControls',operation].map(fn).join('\n'),state);
 state.renderDeploymentGuide();
 return {state,waiting,events,transition(stage){state.runDeploymentGuideAction('return-current');state.pendingEditStage=stage;state.confirmDeploymentStageEdit();},resolve(index=0){waiting[index].resolve(operation==='saveTaskCompilerConfig'?{task_compiler:{identity:{community:'首份草稿'}}}:{project:{...project},stage_plan:{valid:true}});}};
}
for(const operation of ['saveTaskCompilerConfig','saveCurrentDeploymentFlow'])for(const outcome of ['success','failure']) {
 test(`${operation}: real stage transitions recover the button after late ${outcome}`,async()=>{
  const f=editor(operation),button=f.state.$(operation==='saveTaskCompilerConfig'?'saveTaskCompilerConfig':'saveDeploymentFlow');
  const old=f.state[operation]();assert.equal(button.disabled,true);
  f.transition(operation==='saveTaskCompilerConfig'?'project':'export');f.transition(operation==='saveTaskCompilerConfig'?'export':'project');
  if(outcome==='success')f.resolve();else f.waiting[0].reject(Error('old failure'));
  await old;assert.equal(button.disabled,false,'returning to a new editor must allow another save');
  f.events.length=0;f.state.$('taskCompilerCommunity').value='新草稿';const current=f.state[operation]();
  assert.equal(f.waiting.length,2);assert.equal(button.disabled,true);f.resolve(1);await current;
  assert.ok(f.events.some(e=>e[0]==='complete'));
 });
 test(`${operation}: an old finalizer preserves a newer save started through real transitions (${outcome})`,async()=>{
  const f=editor(operation),button=f.state.$(operation==='saveTaskCompilerConfig'?'saveTaskCompilerConfig':'saveDeploymentFlow');
  const old=f.state[operation]();f.transition(operation==='saveTaskCompilerConfig'?'export':'project');
  const current=f.state[operation]();assert.equal(f.waiting.length,2,'the new edit must be able to submit while old response is pending');
  f.state.renderDeploymentGuide();assert.equal(button.disabled,true,'guide rendering must retain the active save lock');
  f.events.length=0;if(outcome==='success')f.resolve();else f.waiting[0].reject(Error('old failure'));
  await old;assert.equal(button.disabled,true);assert.equal(f.events.length,0);f.resolve(1);await current;
  assert.equal(button.disabled,false);
 });
}
