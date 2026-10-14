import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
const source=readFileSync(new URL('../../../autodrive_console/web/deployment.js',import.meta.url),'utf8');
function fn(name){const start=source.indexOf(`function ${name}(`);return start<0?'':source.slice(source.slice(start-6,start)==='async '?start-6:start,source.indexOf('\n}',start)+2);}
const lift={id:'lift-10044',elevator_id:'10044',elevator_protocol:'mqtt',min_floor:-2,max_floor:20,unavailable_button_floors:[11]};
function editor(elevators=[lift]) {
 const nodes=new Map(),calls=[],notes=[];let mode='new';
 const radios=Object.fromEntries(['existing','new'].map(value=>[value,{value,disabled:false,get checked(){return mode===value;},set checked(on){if(on)mode=value;}}]));
 const state={selectedProject:{id:'p',physical_elevators:structuredClone(elevators),components:[]},activeMap:{id:'a',label:'大厅'},deploymentProjectGeneration:1,deploymentStageEditGeneration:1,elevatorLandingGeneration:0,selectedComponent:null,elevatorLandingDraft:null,renders:[],selections:[],completions:[],
  physicalElevators:()=>state.selectedProject.physical_elevators,protocolTitle:(_,id)=>id,protocolOptions:()=>[['mqtt','MQTT']],esc:String,
  document:{querySelector(selector){return selector.includes(':checked')?radios[mode]:radios[selector.includes('value="existing"')?'existing':'new'];}},
  $(id){if(!nodes.has(id)){
   const node={value:'',textContent:'',disabled:false,innerHTML:'',classList:{add(){},remove(){},toggle(){},contains:()=>false},focus(){},querySelector:()=>({classList:{toggle(){}}})};
   if(id==='existingPhysicalElevator'){
    let value='',html='',options=[];
    Object.defineProperties(node,{
     value:{get:()=>value,set:next=>{value=options.includes(next)?next:'';}},
     innerHTML:{get:()=>html,set:next=>{html=next;options=[...next.matchAll(/<option value="([^"]*)"/g)].map(m=>m[1]);value=options[0]||'';}}
    });
   }
   nodes.set(id,node);
  }return nodes.get(id);},
  renderProject:p=>{state.renders.push(p);state.selectedProject=p;},selectComponent:c=>{state.selections.push(c);state.selectedComponent=c;},refreshTopology:async()=>{},keepMapAnnotationOpen:()=>true,completeDeploymentEdit:m=>state.completions.push(m),
  note:(id,message)=>notes.push({id,message}),
  request:async(url,options)=>{calls.push({url,body:JSON.parse(options.body)});const component={id:'landing',kind:'elevator',attributes:JSON.parse(options.body).attributes};return {project:{...state.selectedProject,components:[component]},component};}};
 runInNewContext(['elevatorLandingMode','unavailableElevatorButtons','parseUnavailableElevatorButtons','renderElevatorLandingDialog','useExistingPhysicalElevator','openElevatorLandingDialog','closeElevatorLandingDialog','openPhysicalElevatorEditor','isCurrentElevatorLandingDraft','confirmElevatorLanding'].map(fn).join('\n'),state);
 state.$('newPhysicalElevatorNumber').value='10044';state.$('newPhysicalElevatorMinFloor').value='-2';state.$('newPhysicalElevatorMaxFloor').value='20';
 return {state,calls,notes,setMode:value=>{mode=value;},mode:()=>mode};
}

test('reopening a landing with retained shared elevator resets stale new mode and explains no map landings',()=>{
 const f=editor();f.state.openElevatorLandingDialog({x:1,y:2});
 assert.equal(f.mode(),'existing');assert.equal(f.state.$('existingPhysicalElevator').value,lift.id);
 assert.match(f.state.$('existingPhysicalElevatorSummary').textContent,/10044/);
 assert.match(f.state.$('existingPhysicalElevatorSummary').textContent,/暂无地图落点/);
 assert.equal(f.state.$('newPhysicalElevatorNumber').value,'');
});

test('a new project still starts with new elevator mode',()=>{
 const f=editor([]);f.state.openElevatorLandingDialog({x:1,y:2});assert.equal(f.mode(),'new');
});

test('replacing a deleted landing and adding the other map both reuse the existing shared ID',async()=>{
 const f=editor();
 for(const map of ['a','b']){
  f.state.activeMap={id:map};f.state.openElevatorLandingDialog({x:1,y:2});f.state.$('elevatorLandingButtonFloor').value=map==='a'?'1':'15';await f.state.confirmElevatorLanding();
 }
 assert.equal(f.calls.length,2);assert.ok(f.calls.every(c=>c.url.endsWith('/components')));
 assert.deepEqual(f.calls.map(c=>c.body.attributes.physical_elevator_id),[lift.id,lift.id]);
 assert.deepEqual(f.calls.map(c=>c.body.map_id),['a','b']);
});

test('typing a retained number in new mode guides association without issuing a duplicate POST',async()=>{
 const f=editor();f.state.openElevatorLandingDialog({x:1,y:2});f.setMode('new');
 f.state.$('newPhysicalElevatorNumber').value=' 10044 ';f.state.$('elevatorLandingButtonFloor').value='1';await f.state.confirmElevatorLanding();
 assert.equal(f.calls.length,0);assert.equal(f.mode(),'existing');assert.equal(f.state.$('existingPhysicalElevator').value,lift.id);
 assert.equal(f.state.$('elevatorLandingButtonFloor').value,'1');assert.match(f.notes.at(-1).message,/关联已有电梯/);
});

test('failed landing save after shared creation retries only the landing and preserves the shared configuration',async()=>{
 const f=editor([]);f.state.openElevatorLandingDialog({x:1,y:2});f.state.$('newPhysicalElevatorNumber').value='10044';f.state.$('elevatorLandingButtonFloor').value='1';
 let attempts=0;
 f.state.request=async(url,options)=>{
  f.calls.push({url,body:JSON.parse(options.body)});
  if(url.endsWith('/physical-elevators'))return {physical_elevator:lift,project:{...f.state.selectedProject,physical_elevators:[lift]}};
  if(++attempts===1)throw Error('落点保存失败');
  return {component:{id:'landing'},project:f.state.selectedProject};
 };
 await f.state.confirmElevatorLanding();assert.equal(f.mode(),'existing');
 await f.state.confirmElevatorLanding();
 assert.equal(f.calls.filter(c=>c.url.endsWith('/physical-elevators')).length,1);
 assert.equal(f.calls.filter(c=>c.url.endsWith('/components')).length,2);
 assert.equal(f.calls.at(-1).body.attributes.physical_elevator_id,lift.id);
});

test('an empty button floor cannot be coerced to zero and submitted',async()=>{
 const f=editor();f.state.openElevatorLandingDialog({x:1,y:2});await f.state.confirmElevatorLanding();
 assert.equal(f.calls.length,0);assert.match(f.notes.at(-1).message,/请填写/);
});

test('confirm stays disabled while the landing request follows a successful shared creation',async()=>{
 const f=editor([]);f.state.openElevatorLandingDialog({x:1,y:2});f.state.$('newPhysicalElevatorNumber').value='10044';f.state.$('elevatorLandingButtonFloor').value='1';
 let finish;
 f.state.request=async(url)=>url.endsWith('/physical-elevators')
  ? {physical_elevator:lift,project:{...f.state.selectedProject,physical_elevators:[lift]}}
  : new Promise(resolve=>{finish=resolve;});
 const pending=f.state.confirmElevatorLanding();await new Promise(setImmediate);
 assert.equal(f.state.$('confirmElevatorLanding').disabled,true,'mode rendering must not unlock an in-flight placement');
 finish({component:{id:'landing'},project:f.state.selectedProject});await pending;
});

test('new shared elevator remains selected after browser options are rebuilt, including a failed landing retry',async()=>{
 const f=editor(),created={...lift,id:'lift-10055',elevator_id:'10055'};
 f.state.openElevatorLandingDialog({x:1,y:2});f.setMode('new');f.state.$('newPhysicalElevatorNumber').value='10055';f.state.$('elevatorLandingButtonFloor').value='1';
 f.state.request=async(url,options)=>{
  f.calls.push({url,body:JSON.parse(options.body)});
  if(url.endsWith('/physical-elevators'))return {physical_elevator:created,project:{...f.state.selectedProject,physical_elevators:[lift,created]}};
  throw Error('落点保存失败');
 };
 await f.state.confirmElevatorLanding();
 assert.equal(f.state.$('existingPhysicalElevator').value,created.id,'a select cannot choose a value before its new option exists');
 await f.state.confirmElevatorLanding();
 assert.equal(f.calls.at(-1).body.attributes.physical_elevator_id,created.id);
});

test('landing draft keeps the opening point and refuses confirmation on a different map',async()=>{
 const f=editor(),point={x:1,y:2};f.state.openElevatorLandingDialog(point);point.x=88;
 f.state.$('elevatorLandingButtonFloor').value='1';await f.state.confirmElevatorLanding();
 assert.equal(f.calls[0].body.x,1,'the opening coordinate must be copied');
 f.state.openElevatorLandingDialog({x:3,y:4});f.state.$('elevatorLandingButtonFloor').value='15';f.state.activeMap={id:'b'};
 await f.state.confirmElevatorLanding();assert.equal(f.calls.length,1,'a stale map draft cannot submit a landing');
});

for(const change of ['map','project','generation','cancel-reopen','project-snapshot']) {
 test(`shared creation pending: ${change} cannot place an orphan landing or touch the new editor`,async()=>{
  const f=editor([]);f.state.openElevatorLandingDialog({x:1,y:2});f.state.$('newPhysicalElevatorNumber').value='10044';f.state.$('elevatorLandingButtonFloor').value='1';
  const original=f.state.selectedProject;let finish;
  f.state.request=(url,options)=>{f.calls.push({url,body:JSON.parse(options.body)});return url.endsWith('/physical-elevators')?new Promise(resolve=>{finish=resolve;}):Promise.resolve({component:{id:'landing'},project:original});};
  const pending=f.state.confirmElevatorLanding();
  if(change==='map')f.state.activeMap={id:'b'};
  if(change==='project')f.state.selectedProject={id:'other',physical_elevators:[],components:[]};
  if(change==='generation')f.state.deploymentProjectGeneration++;
  if(change==='project-snapshot')f.state.selectedProject={...original,name:'updated while pending'};
  if(change==='cancel-reopen'){f.state.closeElevatorLandingDialog();f.state.openElevatorLandingDialog({x:88,y:99});f.state.$('elevatorLandingButtonFloor').value='15';}
  const current=f.state.selectedProject,draft=f.state.elevatorLandingDraft,button=f.state.$('confirmElevatorLanding').disabled;
  finish({physical_elevator:lift,project:{...original,physical_elevators:[lift]}});await pending;
  assert.equal(f.calls.length,1,'shared creation may finish, but stale work must never POST a landing');
  assert.equal(f.state.selectedProject,current);assert.equal(f.state.elevatorLandingDraft,draft);assert.equal(f.state.$('confirmElevatorLanding').disabled,button);
  assert.equal(f.state.renders.length,0);assert.equal(f.notes.length,0);
 });
}

for(const operation of ['landing','shared-edit'])for(const outcome of ['success','failure']) {
 test(`${operation} ${outcome} after cancel/reopen cannot replace the project or close/report into the new draft`,async()=>{
  const f=editor();if(operation==='landing'){f.state.openElevatorLandingDialog({x:1,y:2});f.state.$('elevatorLandingButtonFloor').value='1';}
  else f.state.openPhysicalElevatorEditor(lift.id);
  const original=f.state.selectedProject;let finish,fail;
  f.state.request=()=>new Promise((resolve,reject)=>{finish=resolve;fail=reject;});
  const pending=f.state.confirmElevatorLanding();f.state.closeElevatorLandingDialog();f.state.openElevatorLandingDialog({x:88,y:99});
  const draft=f.state.elevatorLandingDraft;
  if(outcome==='success')finish({project:{...original,name:'stale'},component:{id:'stale'}});else fail(Error('old failure'));
  await pending;
  assert.equal(f.state.selectedProject,original);assert.equal(f.state.elevatorLandingDraft,draft);assert.equal(f.state.renders.length,0);assert.equal(f.state.selections.length,0);assert.equal(f.notes.length,0);
 });
}

test('a reopened landing remains pending when the preceding landing response arrives',async()=>{
 const f=editor(),waiting=[];f.state.request=()=>new Promise(resolve=>waiting.push(resolve));
 f.state.openElevatorLandingDialog({x:1,y:2});f.state.$('elevatorLandingButtonFloor').value='1';const old=f.state.confirmElevatorLanding();
 f.state.closeElevatorLandingDialog();f.state.openElevatorLandingDialog({x:88,y:99});f.state.$('elevatorLandingButtonFloor').value='15';const current=f.state.confirmElevatorLanding();
 waiting[0]({component:{id:'old'},project:f.state.selectedProject});await old;
 assert.equal(f.state.$('confirmElevatorLanding').disabled,true);assert.equal(f.state.elevatorLandingDraft?.point.x,88);
 waiting[1]({component:{id:'new'},project:f.state.selectedProject});await current;
 assert.equal(f.state.selectedComponent.id,'new');assert.equal(f.state.elevatorLandingDraft,null);
});

test('the actual map selector invalidates the landing even after returning to its map',async()=>{
 const f=editor();
 Object.assign(f.state,{routeDraft:[],cancelAnnotationGesture(){},finishPolygonVertexDrag(){},mapTools:{closePalette(){}},
  refreshDisplayProtection(){},persistDeploymentSession(){},Image:class {},mapBeauty:{sync(){}},rawMapDisplay:{setImage(){}},
  document:{...f.state.document,body:{classList:{remove(){}}}}});
 runInNewContext(fn('selectMap'),f.state);
 f.state.openElevatorLandingDialog({x:1,y:2});f.state.$('elevatorLandingButtonFloor').value='1';
 f.state.selectMap({id:'b',label:'用户楼层'});f.state.selectMap({id:'a',label:'大厅'});
 assert.equal(f.state.elevatorLandingDraft,null);await f.state.confirmElevatorLanding();assert.equal(f.calls.length,0);
});

test('reopening the same project invalidates pending shared creation and its draft',async()=>{
 const f=editor([]);let finish;
 const original=f.state.selectedProject;
 Object.assign(f.state,{projectOpenSequence:0,creatingAnotherProject:false,persistDeploymentSession(){},refreshMappingStatus:async()=>{},restoreTaskCompilerPreview:async()=>{}});
 f.state.request=(url,options)=>options?new Promise(resolve=>{finish=resolve;}):Promise.resolve({project:{...original}});
 runInNewContext(fn('openProject'),f.state);
 f.state.openElevatorLandingDialog({x:1,y:2});f.state.$('newPhysicalElevatorNumber').value='10044';f.state.$('elevatorLandingButtonFloor').value='1';
 const pending=f.state.confirmElevatorLanding();await f.state.openProject('p');const current=f.state.selectedProject;
 finish({physical_elevator:lift,project:{...original,physical_elevators:[lift]}});await pending;
 assert.equal(f.state.selectedProject,current);assert.equal(f.state.elevatorLandingDraft,null);assert.equal(f.state.renders.length,1);
});

test('finishing topology after a landing save cannot complete a newly opened editor',async()=>{
 const f=editor();let finish;
 f.state.refreshTopology=()=>new Promise(resolve=>{finish=resolve;});
 f.state.openElevatorLandingDialog({x:1,y:2});f.state.$('elevatorLandingButtonFloor').value='1';
 const pending=f.state.confirmElevatorLanding();await new Promise(setImmediate);
 f.state.openElevatorLandingDialog({x:88,y:99});const current=f.state.elevatorLandingDraft;
 finish();await pending;assert.equal(f.state.elevatorLandingDraft,current);assert.equal(f.notes.length,0);
});

test('canceling a reopened landing while old topology is pending still invalidates the old completion',async()=>{
 const f=editor();let finish;f.state.refreshTopology=()=>new Promise(resolve=>{finish=resolve;});
 f.state.openElevatorLandingDialog({x:1,y:2});f.state.$('elevatorLandingButtonFloor').value='1';const pending=f.state.confirmElevatorLanding();
 await new Promise(setImmediate);f.state.openElevatorLandingDialog({x:88,y:99});f.state.closeElevatorLandingDialog();
 finish();await pending;assert.equal(f.notes.length,0);assert.equal(f.state.completions.length,0);
});

for(const stage of ['project','export'])test(`topology completion cannot finish a newly opened ${stage} stage edit`,async()=>{
 const f=editor();let finish;
 Object.assign(f.state,{editingDeploymentStage:'annotations',viewedDeploymentStage:'annotations',deploymentTask:{stageId:'annotations',id:'annotations.edit'},
  deploymentWorkflow:{current:{id:'export'}},deploymentTaskDraft:{},persistDeploymentSession(){},renderDeploymentGuide(){},focusCurrentTaskHeading(){},
  resetProjectSettings(){},closeDeploymentEditImpact(){f.state.pendingEditStage=null;},focusGuideTarget(){},guideTargetForStep:()=>null});
 runInNewContext(['confirmDeploymentStageEdit','isMapAnnotationWorkspaceActive','keepMapAnnotationOpen','completeDeploymentEdit'].map(fn).join('\n'),f.state);
 f.state.refreshTopology=()=>new Promise(resolve=>{finish=resolve;});
 f.state.openElevatorLandingDialog({x:1,y:2});f.state.$('elevatorLandingButtonFloor').value='1';const pending=f.state.confirmElevatorLanding();
 await new Promise(setImmediate);f.state.pendingEditStage=stage;f.state.confirmDeploymentStageEdit();f.state.deploymentTask={stageId:stage,id:`${stage}.edit`};
 finish();await pending;assert.equal(f.state.editingDeploymentStage,stage);assert.equal(f.state.deploymentTaskDraft.receipt,undefined);assert.equal(f.notes.length,0);
});

for(const operation of ['shared-create','shared-edit','landing'])test(`${operation} response cannot render into a later stage edit`,async()=>{
 const f=editor(operation==='shared-create'?[]:[lift]),original=f.state.selectedProject;let finish,calls=0;
 Object.assign(f.state,{editingDeploymentStage:'annotations',persistDeploymentSession(){},renderDeploymentGuide(){},resetProjectSettings(){},closeDeploymentEditImpact(){},focusGuideTarget(){},guideTargetForStep:()=>null});
 runInNewContext(fn('confirmDeploymentStageEdit'),f.state);
 f.state.request=()=>{calls++;return calls===1?new Promise(resolve=>{finish=resolve;}):Promise.resolve({project:original,component:{id:'landing'}});};
 if(operation==='shared-edit')f.state.openPhysicalElevatorEditor(lift.id);
 else {f.state.openElevatorLandingDialog({x:1,y:2});f.state.$('elevatorLandingButtonFloor').value='1';f.state.$('newPhysicalElevatorNumber').value='10044';}
 const pending=f.state.confirmElevatorLanding();f.state.pendingEditStage='project';f.state.confirmDeploymentStageEdit();
 finish({project:{...original,physical_elevators:[lift]},physical_elevator:lift,component:{id:'landing'}});await pending;
 assert.equal(calls,1);assert.equal(f.state.renders.length,0);assert.equal(f.state.selectedProject,original);assert.equal(f.state.editingDeploymentStage,'project');
});
