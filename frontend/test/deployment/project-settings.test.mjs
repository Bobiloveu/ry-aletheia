import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {deriveDeploymentTask} from '../../../autodrive_console/web/deployment/workflow.js';
import {hasPersistedPreview,projectWithPreviewHash,previewMatchesProject} from '../../../autodrive_console/web/deployment/task-compiler-preview.js';

const source=readFileSync(new URL('../../../autodrive_console/web/deployment.js',import.meta.url),'utf8');
const page=readFileSync(new URL('../../../autodrive_console/web/deployment.html',import.meta.url),'utf8');
function fn(name) {
  const start=source.indexOf(`function ${name}(`);
  return source.slice(source.slice(start-6,start)==='async '?start-6:start,source.indexOf('\n}',start)+2);
}
function editor() {
  let respond,fail;
  const nodes={saveProjectSettings:{disabled:false},editProjectName:{value:'新项目'},editProjectTaskMode:{value:'multi'}};
  const state={selectedProject:{id:'p',name:'旧项目',task_mode:'single'},deploymentProjectGeneration:1,projectSettingsEditGeneration:0,editingDeploymentStage:'project',
    $:id=>nodes[id],renders:[],notes:[],returns:[],
    request:async(url,options)=>{state.sent={url,body:JSON.parse(options.body)};return new Promise((resolve,reject)=>{respond=resolve;fail=reject;});},
    renderProject:p=>{state.renders.push(p);state.selectedProject=p;},note:(...args)=>state.notes.push(args),loadProjects:async()=>{},
    completeDeploymentEdit:message=>state.returns.push(message)};
  runInNewContext([fn('resetProjectSettings'),fn('saveProjectSettings')].join('\n'),state);
  return {state,nodes,respond,success(){respond({project:{id:'p',name:'新项目',task_mode:'multi'}});},fail(){fail(Error('保存失败'));}};
}

test('project settings submit both fields to the current project and retain drafts on failure',async()=>{
  const e=editor(),pending=e.state.saveProjectSettings();
  assert.equal(e.nodes.saveProjectSettings.disabled,true);
  assert.deepEqual(e.state.sent,{url:'/api/deployments/p/settings',body:{name:'新项目',task_mode:'multi'}});
  e.fail();await pending;
  assert.equal(e.state.renders.length,0);assert.equal(e.nodes.editProjectName.value,'新项目');
  assert.equal(e.nodes.saveProjectSettings.disabled,false);
  const retry=e.state.saveProjectSettings();e.success();await retry;
  assert.equal(e.state.selectedProject.task_mode,'multi');assert.equal(e.state.returns.length,1);
});

test('a late settings save cannot replace another project or a newly reopened copy',async()=>{
  for(const id of ['other','p']) {
    const e=editor(),pending=e.state.saveProjectSettings();
    const replacement={id,name:'当前项目'};e.state.selectedProject=replacement;
    e.success();await pending;
    assert.equal(e.state.selectedProject,replacement);assert.equal(e.state.renders.length,0);assert.equal(e.state.returns.length,0);
  }
});

test('reopening the same project through openProject invalidates the preceding save response',async()=>{
  const e=editor(),pending=e.state.saveProjectSettings(),request=e.state.request;
  Object.assign(e.state,{projectOpenSequence:0,topology:null,creatingAnotherProject:false,
    persistDeploymentSession(){},closeElevatorLandingDialog(){},refreshMappingStatus:async()=>{},refreshTopology:async()=>{},restoreTaskCompilerPreview:async()=>{}});
  const replacement={id:'p',name:'重新打开的项目',task_mode:'single'};
  e.state.request=(url,options)=>options?request(url,options):Promise.resolve({project:replacement});
  runInNewContext(fn('openProject'),e.state);
  await e.state.openProject('p');
  e.nodes.editProjectName.value='重新打开后未保存的修改';
  e.success();await pending;
  assert.equal(e.state.selectedProject,replacement);
  assert.equal(e.nodes.editProjectName.value,'重新打开后未保存的修改');
  assert.equal(e.state.returns.length,0);
});

test('a previous edit session save cannot discard the next session draft',async()=>{
  const e=editor(),pending=e.state.saveProjectSettings();
  e.state.resetProjectSettings();e.nodes.editProjectName.value='再次进入编辑后的草稿';
  e.success();await pending;
  assert.equal(e.nodes.editProjectName.value,'再次进入编辑后的草稿');
  assert.equal(e.state.returns.length,0);
});

test('every completed deployment stage still exposes its existing editing workspace',()=>{
  const ids=['project','maps','annotations','localization','export'];
  const workflow={current:{id:'export'},next:{id:'export',label:'下载实验包'},steps:ids.map(id=>({id,label:id,status:'complete'})),checklist:ids.map(label=>({label,done:true}))};
  const panels=[...page.matchAll(/<article\b[^>]*data-deployment-tasks="([^"]+)"[^>]*>/g)].map(match=>({
    dataset:{deploymentTasks:match[1]},tag:match[0],visible:false,classList:{toggle(name,value){if(name==='deployment-task-visible')this.owner.visible=value;}},setAttribute(){}}));
  for(const panel of panels)panel.classList.owner=panel;
  for(const id of ids) {
    const task=deriveDeploymentTask({workflow,project:{},viewedStage:id,editingStage:id});
    assert.equal(task.readOnly,false);
    let redraws=0;
    const state={deploymentTask:task,activeTool:'pan',scheduleMapDraw:()=>redraws++,document:{body:{dataset:{}},querySelectorAll:()=>panels}};
    runInNewContext(`${fn('applyDeploymentTaskGating')}\napplyDeploymentTaskGating()`,state);
    const visible=panels.filter(p=>p.visible);
    assert.ok(visible.length>0,`${id} must have editable panels`);
    assert.equal(redraws,id==='localization'?1:0,'entering route configuration refreshes its complete map route');
    if(id==='project')assert.ok(visible.some(p=>p.tag.includes('deployment-setup-project')),'name and mode form must be available');
  }
});

test('an old preview restore cannot confirm a project whose settings have changed',async()=>{
  let respond;
  const original={id:'p',task_mode:'single',task_compiler:{identity:{last_preview_input_sha256:'old'}}};
  const state={selectedProject:original,taskCompilerPreview:null,taskCompilerProjectId:'p',hasPersistedPreview,projectWithPreviewHash,previewMatchesProject,
    request:()=>new Promise(resolve=>{respond=resolve;}),renderTaskCompilerState(){},taskCompilerMessage(){}};
  runInNewContext(fn('restoreTaskCompilerPreview'),state);
  const pending=state.restoreTaskCompilerPreview('p');
  const saved={...original,task_mode:'multi',task_compiler:{identity:{last_preview_input_sha256:null}}};state.selectedProject=saved;
  respond({preview:{status:'ready',input_sha256:'old'}});await pending;
  assert.equal(state.selectedProject,saved);assert.equal(state.taskCompilerPreview,null);
});
