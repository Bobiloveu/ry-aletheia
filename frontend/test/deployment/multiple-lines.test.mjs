import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {createTaskLineSession,taskLineLocationLabel} from '../../../autodrive_console/web/deployment/task-lines.js';

const source=readFileSync(new URL('../../../autodrive_console/web/deployment.js',import.meta.url),'utf8');
const fn=name=>{const start=source.indexOf(`function ${name}(`);return source.slice(start,source.indexOf('\n}',start)+2);};
for(const stage of ['project','maps','annotations','localization'])test(`saving in ${stage} retains editing until explicit return`,()=>{
  let focused=0;
  const state={editingDeploymentStage:stage,viewedDeploymentStage:stage,deploymentStageEditGeneration:3,
    deploymentTask:{id:`${stage}.edit`},deploymentTaskDraft:{},persistDeploymentSession(){},renderDeploymentGuide(){},focusCurrentTaskHeading(){focused++;}};
  runInNewContext(fn('completeDeploymentEdit')+'\n'+fn('runDeploymentGuideAction'),state);
  assert.equal(state.completeDeploymentEdit('已保存'),true);
  assert.equal(state.editingDeploymentStage,stage);assert.equal(state.viewedDeploymentStage,stage);
  assert.equal(focused,0,'a save must not steal map or form focus');
  state.runDeploymentGuideAction('return-current');
  assert.equal(state.editingDeploymentStage,null);assert.equal(state.viewedDeploymentStage,null);
});
const p={id:'p',task_mode:'multi',active_task_line_id:'a',task_lines:[{id:'a',name:'1508',start_component_id:'start',steps:[]}],components:[
  {id:'start',kind:'start',map_asset_id:'floor'},
  {id:'a',kind:'target',label:'目标点',map_asset_id:'floor',attributes:{door:'1508'}},
  {id:'b',kind:'target',label:'目标点',map_asset_id:'floor',attributes:{door:'1509'}},
],map_assets:[{id:'floor',label:'用户楼层15'}]};
test('same-floor target selectors include their room numbers',()=>{
  assert.equal(taskLineLocationLabel(p,{kind:'component',id:'a'}),'目标点 · 1508 · 用户楼层15');
  assert.equal(taskLineLocationLabel(p,{kind:'component',id:'b'}),'目标点 · 1509 · 用户楼层15');
});
test('a custom label containing multiple room numbers still exposes each actual door',()=>{
  const both=structuredClone(p);both.components.filter(c=>c.kind==='target').forEach(c=>c.label='1508/1509 配送');
  assert.notEqual(taskLineLocationLabel(both,{kind:'component',id:'a'}),taskLineLocationLabel(both,{kind:'component',id:'b'}));
});
test('a fresh line stays selected when the same project refreshes',()=>{
  const session=createTaskLineSession();session.load(p);session.newDraft();
  assert.equal(session.draft.id,undefined);
  session.load(structuredClone(p));assert.equal(session.draft.id,undefined);
  assert.equal(session.project.task_lines.length,1);
  session.change({name:'第二条'});session.editSaved('a');assert.equal(session.draft.name,'第二条','unsaved edits are retained');
  session.discard();session.editSaved('a');assert.equal(session.draft.id,'a');
});
