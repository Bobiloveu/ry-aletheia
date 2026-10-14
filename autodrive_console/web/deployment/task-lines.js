import { componentName } from './component-specs.js';
import {transitionDisplayLabel} from './transition-labels.js';
import {componentDisplayLabel} from './component-labels.js';
import { executionNodeSpeedLabel } from './execution-chain-view.js';
import {narrowPassageEnds,constrainPassageAxes} from './route-passages.js';

const list = value => Array.isArray(value) ? value : [];
const copy = value => JSON.parse(JSON.stringify(value));
const emptyLine = () => ({name:'',start_component_id:'',steps:[]});
const allowedKinds = new Set(['target','gate','auto_door','slow_zone','ramp','narrow_passage']);
export function taskLineLocations(project) {
  return [
    ...list(project?.components).filter(item=>allowedKinds.has(item.kind)).map(item=>({kind:'component',id:item.id,location:item})),
    ...list(project?.waypoints).filter(item=>item.kind==='transition'&&!item.generated_by&&!item.exclude_task_export).map(item=>({kind:'transition',id:item.id,location:item})),
  ];
}
export function resolveTaskLineLocation(project, ref) {
  return list(ref?.kind==='transition' ? project?.waypoints : project?.components).find(item=>item.id===ref?.id) || null;
}
export function taskLineLocationLabel(project, ref) {
  const item=resolveTaskLineLocation(project,ref);
  if (!item) return `失效引用 · ${ref?.id || '未选择'}`;
  const map=list(project?.map_assets).find(map=>map.id===item.map_asset_id);
  return `${ref.kind==='transition' ? transitionDisplayLabel(project,item) : componentDisplayLabel(project,item)} · ${map?.label || item.map_asset_id}`;
}
export function validateTaskLine(project,line) {
  const errors=[];
  if (!line?.name?.trim()) errors.push('请填写线路名称。');
  const start=list(project?.components).find(item=>item.id===line?.start_component_id && item.kind==='start');
  if (!start) errors.push('请选择当前项目中有效的起点组件。');
  const steps=list(line?.steps);
  if (!steps.length || steps.length>512) errors.push('去程需包含 1–512 步。');
  steps.forEach((ref,index)=>{
    const item=resolveTaskLineLocation(project,ref);
    const prefix=`第 ${index+1} 步：`;
    if (!item || (ref.kind==='transition' ? item.kind!=='transition'||item.generated_by||item.exclude_task_export : ref.kind!=='component'||!allowedKinds.has(item.kind))) {errors.push(`${prefix}位置已失效，请删除该步或恢复地图标记。`);return;}
    if (item.kind==='target') {
      if (!['pickup','delivery','visit'].includes(ref.action?.purpose)) errors.push(`${prefix}请选择取货、送货或仅到达。`);
      else if (ref.action.purpose!=='visit') {
        if (![1,2].includes(ref.action.cargo_id)) errors.push(`${prefix}仓位只支持上仓 1 或下仓 2。`);
        if (!['open','close','unload'].includes(ref.action.operation)) errors.push(`${prefix}请选择有效仓控操作。`);
      }
    }
  });
  const last=steps.at(-1),lastLocation=resolveTaskLineLocation(project,last);
  if(lastLocation&&!['target','transition'].includes(lastLocation.kind))errors.push('线路末步应为目标点或过渡点，请在最后一个通行设施后添加出口过渡点。');
  return errors;
}
export function taskLineSelectionReady(project) {
  if(!Array.isArray(project?.task_lines))return true;
  const active=project.task_lines.find(line=>line.id===project.active_task_line_id);
  return Boolean(active&&!validateTaskLine(project,active).length);
}
// This is a physical-visit intent preview. Backend expands doors, elevators and map switches.
export function taskLineReturnPreview(line) {
  return [...list(line?.steps)].reverse().map(({kind,id})=>({kind,id}))
    .concat(line?.start_component_id ? [{kind:'component',id:line.start_component_id}] : []);
}
export function taskLineMapVisits(project,line,mapId) {
  return [{kind:'component',id:line?.start_component_id},...list(line?.steps)]
    .map((ref,index)=>({location:resolveTaskLineLocation(project,ref),order:index}))
    .filter(visit=>visit.location?.map_asset_id===mapId);
}

export function taskLineRouteSegments(project,line,mapId) {
  const segments=[];
  let previous=null,current=null;
  for(const visit of taskLineMapVisits(project,line,mapId)) {
    const location=visit.location;
    if(!Number.isFinite(location.x)||!Number.isFinite(location.y)){previous=null;continue;}
    if(!previous || previous.order!==visit.order-1){current={leg:'outbound',points:[]};segments.push(current);previous=null;}
    const ends=narrowPassageEnds(location);
    if(ends) {
      const from=previous?.location;
      if(from&&Math.hypot(from.x-ends[0].x,from.y-ends[0].y)>Math.hypot(from.x-ends[1].x,from.y-ends[1].y))ends.reverse();
      (current.straightPairs ||= []).push(current.points.length);
      current.points.push(...ends);
    } else current.points.push({x:location.x,y:location.y});
    previous=visit;
  }
  // Retrace known local legs; cross-map lift connections still belong to Backend.
  segments.push(...segments.slice().reverse().map(segment=>({leg:'return',points:segment.points.slice().reverse(),
    ...(segment.straightPairs?{straightPairs:segment.straightPairs.map(i=>segment.points.length-2-i).sort((a,b)=>a-b)}:{})})));
  return constrainPassageAxes(segments,list(project?.components).filter(c=>c.map_asset_id===mapId));
}

export function taskLineFlowLayout(count, width) {
  const columns = Math.max(1, Math.min(4, count, Math.floor((width + 40) / 260)));
  return { columns, nodes: Array.from({length: count}, (_, index) => {
    const row = Math.floor(index / columns), offset = index % columns;
    return {
      row: row + 1,
      column: row % 2 ? columns - offset : offset + 1,
      direction: index === count - 1 ? null : offset === columns - 1 ? 'down' : row % 2 ? 'left' : 'right',
    };
  }) };
}

export function createTaskLineSession({request,onChange=()=>{},onProject=()=>{}}={}) {
  let project=null,draft=emptyLine(),baseline=copy(draft),busy=false,error='',message='',generation=0;
  const emit=()=>onChange(api);
  const reset=(line)=>{draft=copy(line || emptyLine());baseline=copy(draft);error='';message='';};
  const path=()=>`/api/deployments/${encodeURIComponent(project.id)}/task-lines`;
  const send=(url,method='POST',body={})=>request(url,{method,headers:{'Content-Type':'application/json'},...(method==='DELETE'?{}:{body:JSON.stringify(body)})});
  const accept=(data)=>{
    project=data.project;
    const saved=list(project.task_lines).find(item=>item.id===(data.task_line?.id || draft.id));
    reset(saved || list(project.task_lines).find(item=>item.id===project.active_task_line_id));
    onProject(project);
  };
  const transact=async(operation)=>{
    if (busy || !project) return;
    const current= generation; busy=true;error='';message='';emit();
    try {await operation(()=>current===generation);}
    catch(reason) {if(current===generation) error=reason.message || '保存失败，请重试。';}
    finally {if(current===generation) {busy=false;emit();}}
  };
  const api={
    get project(){return project;},get draft(){return draft;},get busy(){return busy;},get error(){return error;},get message(){return message;},
    get dirty(){return JSON.stringify(draft)!==JSON.stringify(baseline);},
    load(next){
      if(project?.id!==next?.id) {generation++;busy=false;project=next;reset(list(next?.task_lines).find(item=>item.id===next?.active_task_line_id) || list(next?.task_lines)[0]);}
      else {project=next;if(!api.dirty&&!busy&&draft.id) reset(list(next?.task_lines).find(item=>item.id===draft.id) || list(next?.task_lines).find(item=>item.id===next?.active_task_line_id));}
      emit();
    },
    newDraft(){if(busy||api.dirty)return;reset();emit();},
    editSaved(id){if(busy||api.dirty)return;reset(list(project?.task_lines).find(item=>item.id===id));emit();},
    discard(){if(busy)return;reset(list(project?.task_lines).find(item=>item.id===draft.id));emit();},
    change(fields){if(busy)return;draft={...draft,...copy(fields)};error='';message='';emit();},
    insert(index,ref){
      if(busy||draft.steps.length>=512||!Number.isInteger(index)||index<0||index>draft.steps.length)return;
      const item=taskLineLocations(project).find(item=>item.kind===ref.kind&&item.id===ref.id)?.location;
      if(!item)return;
      const steps=copy(draft.steps);
      steps.splice(index,0,{kind:ref.kind,id:ref.id,...(item.kind==='target'?{action:{purpose:'visit'}}:{})});
      api.change({steps});
    },
    append(ref){api.insert(draft.steps.length,ref);},
    move(from,to){if(busy||!Number.isInteger(from)||!Number.isInteger(to)||from<0||from>=draft.steps.length||to<0||to>=draft.steps.length||from===to)return;const steps=copy(draft.steps);steps.splice(to,0,steps.splice(from,1)[0]);api.change({steps});},
    remove(index){if(busy)return;api.change({steps:draft.steps.filter((_,at)=>at!==index)});},
    setAction(index,action){const steps=copy(draft.steps);if(!steps[index])return;steps[index].action=action.purpose==='visit'?{purpose:'visit'}:copy(action);api.change({steps});},
    async save(){
      const errors=validateTaskLine(project,draft);if(errors.length){error=errors.join(' ');emit();return;}
      await transact(async current=>{
        const payload={name:draft.name.trim(),start_component_id:draft.start_component_id,steps:copy(draft.steps)};
        const data=await send(`${path()}${draft.id?`/${encodeURIComponent(draft.id)}`:''}`,'POST',payload);
        if(!current())return;
        accept(data);
        const savedId=data.task_line.id;
        if(project.active_task_line_id!==savedId){const selected=await send(`${path()}/${encodeURIComponent(savedId)}/select`);if(!current())return;accept(selected);}
        message=project.task_mode==='multi'?`线路已保存；共 ${project.task_lines.length} 条线路将一起校验与导出。`:'线路已保存，作为本次校验与导出的线路。';
      });
    },
    async activate(){if(api.dirty||validateTaskLine(project,draft).length||!draft.id)return;await transact(async current=>{const data=await send(`${path()}/${encodeURIComponent(draft.id)}/select`);if(current()){accept(data);message=project.task_mode==='multi'?'已设为新增楼上目标的线路模板；全部已保存线路仍会导出。':'已切换本次导出线路，请重新生成实验预览。';}});},
    async deleteSaved(){if(api.dirty||!draft.id)return;await transact(async current=>{const data=await send(`${path()}/${encodeURIComponent(draft.id)}`,'DELETE');if(current()){accept(data);message='线路已删除，地图标记仍保留。';}});},
  };
  return api;
}

export function bindTaskLinesUI({container,request,onProject,onChange=()=>{}}) {
  const doc = container.ownerDocument;
  const esc = value => {const node=doc.createElement('span');node.textContent=value??'';return node.innerHTML;};
  const options = (items,value) => items.map(([id,label])=>`<option value="${esc(id)}" ${String(value)===String(id)?'selected':''}>${esc(label)}</option>`).join('');
  const svg = path => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
  const plusIcon = svg('<path d="M12 5v14M5 12h14"/>');
  const gripIcon = svg('<path d="M8 6h.01M16 6h.01M8 12h.01M16 12h.01M8 18h.01M16 18h.01" stroke-width="3.5"/>');
  let inputEditing=false, focusAfterEdit=null, editingStep=null, insertionIndex=null, renderedIdentity=null, pointerDrag=null;
  const session=createTaskLineSession({request,onProject,onChange(){if(!inputEditing)render();else refreshStatus();onChange(session);}});

  function refreshStatus() {
    const status=container.querySelector('[data-line-status]');
    const validation=validateTaskLine(session.project,session.draft);
    const validationMessage=(session.dirty||session.draft.id)?validation.join(' '):'';
    if(status){status.textContent=session.error||(insertionIndex!==null?'请在新卡片中选择位置并确认添加，或取消本步。':session.message)||(session.busy?'正在保存并选择线路…':validationMessage)||(session.dirty?'尚未保存。保存后将用于本次导出。':session.draft.id?(session.project?.active_task_line_id===session.draft.id?'已保存 · 本次导出线路':'已保存 · 尚未选为本次导出线路'):'从既有标记中编排一条去程线路。');status.classList.toggle('is-error',Boolean(session.error||validationMessage));}
    const save=container.querySelector('[data-line-command="save"]');
    if(save)save.disabled=session.busy||!session.project||validation.length>0||insertionIndex!==null;
    for(const control of container.querySelectorAll('[data-dirty-lock]')) {
      const command=control.dataset.lineCommand;
      control.disabled=session.busy||session.dirty||insertionIndex!==null||(['activate','delete'].includes(command)&&!session.draft.id)||(command==='activate'&&validation.length>0);
    }
    const discard=container.querySelector('[data-line-command="discard"]');
    if(discard)discard.disabled=session.busy||(!session.dirty&&insertionIndex===null);
  }
  function layoutFlow() {
    const flow=container.querySelector('[data-line-flow]');
    if(!flow)return;
    const cards=[...flow.querySelectorAll('[data-line-flow-node]')];
    const layout=taskLineFlowLayout(cards.length,flow.clientWidth);
    flow.style.setProperty('--task-flow-columns',layout.columns);
    cards.forEach((card,index)=>{
      const node=layout.nodes[index];
      card.style.gridRow=String(node.row);card.style.gridColumn=String(node.column);
      const connector=card.querySelector('[data-line-connector]');
      if(connector)connector.dataset.direction=node.direction||'none';
    });
  }
  function connector(slot) {
    return `<span class="task-line-connector" data-line-connector data-direction="right">
      <svg class="task-line-connector-horizontal" viewBox="0 0 40 24" fill="none" aria-hidden="true"><path d="M0 12H37M32 7l5 5-5 5"/></svg>
      <svg class="task-line-connector-vertical" viewBox="0 0 24 48" fill="none" aria-hidden="true"><path d="M12 0V45M7 40l5 5 5-5"/></svg>
      ${slot===null?'':`<button type="button" data-line-command="insert" data-line-index="${slot}" data-line-focus="insert-${slot}" aria-label="${slot===0?'在起点之后添加一步':`在第 ${slot} 步之后添加一步`}" title="在此添加一步" ${session.draft.steps.length>=512?'disabled':''}>${plusIcon}</button>`}
    </span>`;
  }
  function actionSummary(item,ref) {
    if(!item)return '位置已失效，请替换或删除';
    if(ref.kind==='transition')return `仅经过 · ${executionNodeSpeedLabel(item.speed_mode||'normal')}`;
    if(item.kind!=='target')return '按组件配置通行';
    const action=ref.action||{purpose:'visit'};
    if(action.purpose==='visit')return '仅到达 · 无仓控动作';
    return `${action.purpose==='pickup'?'取货':'送货'} · ${action.cargo_id===2?'下仓':'上仓'} · ${{open:'开仓',close:'关仓',unload:'自动卸货'}[action.operation]||'待设置'}`;
  }
  function actionFields(ref,index) {
    const action=ref.action||{purpose:'visit'};
    return `<div class="task-line-action-fields"><label>本次用途<select data-line-action="purpose" data-line-index="${index}" data-line-focus="purpose-${index}">${options([['visit','仅到达'],['pickup','取货'],['delivery','送货']],action.purpose)}</select></label>${action.purpose!=='visit'?`<label>仓位<select data-line-action="cargo_id" data-line-index="${index}" data-line-focus="cargo-${index}">${options([[1,'上仓 · 1'],[2,'下仓 · 2']],action.cargo_id)}</select></label><label>执行方式<select data-line-action="operation" data-line-index="${index}" data-line-focus="operation-${index}">${options([['open','开仓'],['close','关仓'],['unload','自动卸货']],action.operation)}</select></label>`:''}</div>`;
  }
  function insertionCard(index,locations) {
    return `<article class="task-line-flow-card task-line-insert-card is-selected" data-line-flow-node data-line-insertion-card="${index}" role="listitem" aria-label="添加第 ${index+1} 步">
      <div class="task-line-card-head"><span class="task-line-order">+</span><strong>${index===session.draft.steps.length?'添加下一步':`插入第 ${index+1} 步`}</strong></div>
      <div class="task-line-add"><label>选择已有位置<select data-line-add-location data-line-focus="add-location"><option value="">选择位置</option>${options(locations.map(ref=>[`${ref.kind}:${ref.id}`,taskLineLocationLabel(session.project,ref)]),'')}</select></label></div>
      <p class="task-line-card-note">${index===session.draft.steps.length?'添加后继续执行此位置的任务。':'后续步骤将顺延，原有动作设置保留。'}</p>
      <div class="task-line-insert-actions"><button type="button" class="compact-action" data-line-command="add" disabled>确认添加</button><button type="button" class="task-line-edit" data-line-command="close-insert">取消</button></div>${index<session.draft.steps.length?connector(null):''}
    </article>`;
  }
  function render() {
    if(pointerDrag)clearDrag();
    const focused=doc.activeElement;
    const focusKey=focusAfterEdit||(container.contains(focused)?focused.dataset.lineFocus:null);
    const returnOpen=container.querySelector('.task-line-return')?.open;
    focusAfterEdit=null;
    const project=session.project,draft=session.draft;
    const multi=project?.task_mode==='multi';
    const identity=`${project?.id||''}:${draft.id||''}`;
    if(identity!==renderedIdentity){editingStep=insertionIndex=null;renderedIdentity=identity;}
    if(!draft.steps[editingStep])editingStep=null;
    if(insertionIndex>draft.steps.length)insertionIndex=draft.steps.length;
    const starts=list(project?.components).filter(item=>item.kind==='start');
    const locations=taskLineLocations(project),saved=list(project?.task_lines);
    const start=starts.find(item=>item.id===draft.start_component_id);
    const mapLabel=item=>list(project?.map_assets).find(map=>map.id===item?.map_asset_id)?.label||item?.map_asset_id||'位置待选择';
    const name=(item,ref)=>!item?'位置已失效':ref?.kind==='transition'?transitionDisplayLabel(project,item):componentDisplayLabel(project,item);
    const disabled=session.busy||!project?'disabled':'';
    container.innerHTML=`<div class="task-line-toolbar"><label>已保存线路（${saved.length} 条）<select data-line-select data-line-focus="saved" data-dirty-lock ${session.dirty||session.busy?'disabled':''}><option value="">新线路</option>${options(saved.map(line=>[line.id,`${line.name}${project.active_task_line_id===line.id?(multi?' · 新目标模板':' · 本次导出'):''}`]),draft.id)}</select></label><button type="button" class="compact-action" data-line-command="new" data-line-focus="new" data-dirty-lock ${session.dirty||session.busy?'disabled':''}>新建线路</button></div>
      ${multi?'<p class="page-muted">每个楼上目标独立一条线路，导出时包含全部已保存线路及各户去返任务。</p>':''}
      <fieldset ${disabled}><div class="task-line-fields"><label>线路名称<input id="taskLineName" data-line-name data-line-focus="name" maxlength="80" value="${esc(draft.name)}" placeholder="例如：超市取货配送" /></label></div>
      <div class="task-line-flow-heading"><h3>去程任务流程</h3><span>${draft.steps.length} 步 · 自动生成返程</span></div>
      <p class="page-muted task-line-flow-help">沿箭头按 S 型顺序执行；拖动卡片手柄排序，点击连线上的加号插入一步。同一位置可多次经过。</p>
      <div class="task-line-flow" data-line-flow role="list" aria-label="去程任务流程">
        <article class="task-line-flow-card task-line-start-card" data-line-flow-node data-line-drop-index="0" role="listitem" aria-label="起点">
          <div class="task-line-card-head"><span class="task-line-order">起</span><strong>任务起点</strong></div>
          <label>选择已有起点<select data-line-start data-line-focus="start"><option value="">选择起点</option>${!start&&draft.start_component_id?`<option selected value="${esc(draft.start_component_id)}">失效起点 · ${esc(draft.start_component_id)}</option>`:''}${options(starts.map(item=>[item.id,taskLineLocationLabel(project,{kind:'component',id:item.id})]),draft.start_component_id)}</select></label>
          <p class="task-line-card-map">${start?esc(mapLabel(start)):'从已标记的起点出发'}</p><p class="task-line-card-note">返程自动回到此处</p>${connector(0)}
        </article>
        ${draft.steps.map((ref,index)=>{
          const item=resolveTaskLineLocation(project,ref),selected=index===editingStep;
          return `${insertionIndex===index?insertionCard(index,locations):''}<article class="task-line-flow-card ${!item?'is-error':''} ${selected?'is-selected':''}" data-line-flow-node data-line-step-card="${index}" data-line-drop-index="${index}" data-line-focus="row-${index}" tabindex="-1" role="listitem" aria-label="第 ${index+1} 步：${esc(name(item,ref))}">
            <div class="task-line-card-head"><span class="task-line-order">${index+1}</span><span class="task-line-card-kind">${ref.kind==='transition'?'过渡点':item?componentName(item):'失效位置'}</span><button type="button" class="task-line-grip" data-line-drag-handle="${index}" data-line-focus="grip-${index}" aria-label="拖动第 ${index+1} 步排序，也可用方向键调整" aria-pressed="false" title="拖动排序">${gripIcon}</button></div>
            <strong class="task-line-card-title">${esc(name(item,ref))}</strong><p class="task-line-card-map">${esc(mapLabel(item))}</p>
            <p class="task-line-card-action">${esc(actionSummary(item,ref))}</p>
            ${selected?`<div id="taskLineStepEditor-${index}" class="task-line-step-editor" data-line-action-editor="${index}" aria-label="第 ${index+1} 步动作设置">${actionFields(ref,index)}</div>`:''}
            <div class="task-line-card-footer">${item?.kind==='target'?`<button type="button" class="task-line-edit" data-line-command="edit" data-line-index="${index}" data-line-focus="edit-${index}" aria-expanded="${selected}" aria-controls="taskLineStepEditor-${index}">${selected?'完成设置':'设置动作'}</button>`:'<span class="task-line-card-note">返程动作自动派生</span>'}<div class="task-line-step-controls"><button type="button" data-line-command="up" data-line-index="${index}" data-line-focus="up-${index}" aria-label="第 ${index+1} 步前移" ${index===0?'disabled':''}>前移</button><button type="button" data-line-command="down" data-line-index="${index}" data-line-focus="down-${index}" aria-label="第 ${index+1} 步后移" ${index===draft.steps.length-1?'disabled':''}>后移</button><button type="button" class="danger-action" data-line-command="remove" data-line-index="${index}" data-line-focus="remove-${index}" aria-label="删除第 ${index+1} 步">删除</button></div></div>${index<draft.steps.length-1||draft.steps.length<512?connector(index+1):''}
          </article>`;
        }).join('')}
        ${draft.steps.length<512?insertionIndex===draft.steps.length?insertionCard(draft.steps.length,locations):`<div class="task-line-flow-card task-line-add-card" data-line-flow-node data-line-drop-index="${Math.max(0,draft.steps.length-1)}"><button type="button" data-line-command="insert" data-line-index="${draft.steps.length}" data-line-focus="add">${plusIcon}<strong>${draft.steps.length?'添加下一步':'添加第一步'}</strong><span>目标点、过渡点或通行设施</span></button></div>`:''}
      </div>
      <p class="task-line-drag-status" data-line-drag-status role="status" aria-live="polite"></p>
      <details class="task-line-return" ${returnOpen?'open':''}><summary>原路返程 · 回到起点</summary><p class="page-muted">完成末步后沿去程原路返回，逆序经过同一过渡点、窄通道首末端点和电梯连接，不重复取货、送货或仓控动作。实际通行节点与顺序请在实验预览中选择“返程”查看。</p><ol>${taskLineReturnPreview(draft).map((ref,index,refs)=>`<li>${esc(taskLineLocationLabel(project,ref))}<small>${index===refs.length-1?'返程终点 · 保持起点朝向':index===0?'返程起点':'仅经过 · 无取送货或仓控动作'}</small></li>`).join('')}</ol></details></fieldset>
      <p data-line-status role="status" aria-live="polite" class="inline-message task-line-status"></p>
      <div class="task-line-save-actions"><button type="button" class="page-top-action" data-line-command="save" data-line-focus="save">${session.busy?'正在保存…':multi?'保存线路':'保存并选为本次线路'}</button><button type="button" class="compact-action" data-line-command="activate" data-line-focus="activate" data-dirty-lock ${!draft.id||session.dirty||session.busy||validateTaskLine(project,draft).length?'disabled':''}>${multi?'作为新目标模板':'选为本次导出'}</button><button type="button" class="compact-action" data-line-command="discard" data-line-focus="discard">放弃修改</button><button type="button" class="compact-action danger-action" data-line-command="delete" data-line-focus="delete" data-dirty-lock ${!draft.id||session.dirty||session.busy?'disabled':''}>删除线路</button></div>`;
    layoutFlow();refreshStatus();
    if(focusKey)container.querySelector(`[data-line-focus="${focusKey}"]`)?.focus({preventScroll:true});
  }
  function moveStep(from,to) {
    if(session.busy||from===to||to<0||to>=session.draft.steps.length)return;
    if(editingStep!==null){
      if(editingStep===from)editingStep=to;
      else if(from<editingStep&&to>=editingStep)editingStep--;
      else if(from>editingStep&&to<=editingStep)editingStep++;
    }
    insertionIndex=null;focusAfterEdit=`grip-${to}`;session.move(from,to);
  }
  container.addEventListener('input',event=>{if(!event.target.matches('[data-line-name]'))return;inputEditing=true;session.change({name:event.target.value});inputEditing=false;});
  container.addEventListener('change',event=>{
    const control=event.target;
    if(control.matches('[data-line-add-location]'))container.querySelector('[data-line-command="add"]').disabled=!control.value;
    if(control.matches('[data-line-select]')){editingStep=insertionIndex=null;session.editSaved(control.value);}
    if(control.matches('[data-line-start]'))session.change({start_component_id:control.value});
    if(control.matches('[data-line-action]')){
      const index=Number(control.dataset.lineIndex),old=session.draft.steps[index]?.action||{purpose:'visit'},key=control.dataset.lineAction;
      let next={...old,[key]:key==='cargo_id'?Number(control.value):control.value};
      if(key==='purpose'&&next.purpose!=='visit'&&old.purpose==='visit')next={purpose:next.purpose,cargo_id:1,operation:next.purpose==='pickup'?'open':'unload'};
      session.setAction(index,next);
    }
  });
  container.addEventListener('click',event=>{
    const button=event.target.closest('[data-line-command]');if(!button||button.disabled||session.busy)return;
    const index=Number(button.dataset.lineIndex);
    switch(button.dataset.lineCommand){
      case 'new':editingStep=insertionIndex=null;session.newDraft();container.querySelector('[data-line-name]')?.focus();break;
      case 'discard':editingStep=insertionIndex=null;session.discard();break;
      case 'save':session.save();break;
      case 'activate':session.activate();break;
      case 'delete':if(doc.defaultView.confirm(`删除线路“${session.draft.name}”？地图标记和其他线路会保留。`))session.deleteSaved();break;
      case 'up':moveStep(index,index-1);break;
      case 'down':moveStep(index,index+1);break;
      case 'edit':editingStep=editingStep===index?null:index;insertionIndex=null;focusAfterEdit=editingStep===null?`edit-${index}`:`purpose-${index}`;render();container.querySelector(`[data-line-step-card="${index}"]`)?.scrollIntoView({block:'nearest'});break;
      case 'insert':insertionIndex=index;editingStep=null;focusAfterEdit='add-location';render();container.querySelector('[data-line-insertion-card]')?.scrollIntoView({block:'nearest'});break;
      case 'close-insert':focusAfterEdit=insertionIndex===session.draft.steps.length?'add':`insert-${insertionIndex}`;insertionIndex=null;render();break;
      case 'remove':if(editingStep===index)editingStep=null;else if(editingStep>index)editingStep--;insertionIndex=null;focusAfterEdit=session.draft.steps.length>1?`row-${Math.min(index,session.draft.steps.length-2)}`:'add';session.remove(index);break;
      case 'add':{
        const value=container.querySelector('[data-line-add-location]').value,split=value.indexOf(':');
        if(split<1)return;
        const at=insertionIndex??session.draft.steps.length;
        const ref={kind:value.slice(0,split),id:value.slice(split+1)};
        editingStep=resolveTaskLineLocation(session.project,ref)?.kind==='target'?at:null;
        insertionIndex=null;focusAfterEdit=editingStep===null?`row-${at}`:`purpose-${at}`;
        session.insert(at,ref);
        container.querySelector(`[data-line-step-card="${at}"]`)?.scrollIntoView({block:'nearest'});break;
      }
    }
  });
  function clearDrag() {
    const drag=pointerDrag;pointerDrag=null;
    if(!drag)return;
    drag.card.classList.remove('is-dragging');drag.handle.setAttribute('aria-pressed','false');
    container.querySelectorAll('.is-drop-target').forEach(card=>card.classList.remove('is-drop-target'));
    const status=container.querySelector('[data-line-drag-status]');if(status)status.textContent='';
    if(drag.handle.hasPointerCapture?.(drag.pointerId))drag.handle.releasePointerCapture(drag.pointerId);
  }
  function dropTarget(event) {
    const hit=doc.elementFromPoint(event.clientX,event.clientY)?.closest('[data-line-drop-index]');
    return hit&&container.contains(hit)?hit:null;
  }
  container.addEventListener('pointerdown',event=>{
    const handle=event.target.closest('[data-line-drag-handle]');
    if(!handle||event.button!==0||session.busy)return;
    pointerDrag={handle,card:handle.closest('[data-line-step-card]'),from:Number(handle.dataset.lineDragHandle),pointerId:event.pointerId,x:event.clientX,y:event.clientY,active:false};
  });
  container.addEventListener('pointermove',event=>{
    const drag=pointerDrag;if(!drag||drag.pointerId!==event.pointerId)return;
    if(!drag.active){
      if(Math.hypot(event.clientX-drag.x,event.clientY-drag.y)<6)return;
      drag.active=true;drag.handle.setPointerCapture(event.pointerId);drag.handle.setAttribute('aria-pressed','true');drag.card.classList.add('is-dragging');
    }
    event.preventDefault();
    container.querySelectorAll('.is-drop-target').forEach(card=>card.classList.remove('is-drop-target'));
    const target=dropTarget(event),to=Number(target?.dataset.lineDropIndex);
    if(target&&to!==drag.from)target.classList.add('is-drop-target');
    const status=container.querySelector('[data-line-drag-status]');
    if(status)status.textContent=target&&to!==drag.from?`松开，将第 ${drag.from+1} 步移到第 ${to+1} 步。`:'拖到其他卡片上调整顺序。';
    const height=doc.defaultView.innerHeight;
    if(event.clientY<70)doc.defaultView.scrollBy(0,-18);
    else if(event.clientY>height-70)doc.defaultView.scrollBy(0,18);
  });
  container.addEventListener('pointerup',event=>{
    const drag=pointerDrag;if(!drag||drag.pointerId!==event.pointerId)return;
    const target=drag.active?dropTarget(event):null,to=Number(target?.dataset.lineDropIndex);
    clearDrag();if(target)moveStep(drag.from,to);
  });
  for(const type of ['pointercancel','lostpointercapture'])container.addEventListener(type,event=>{if(pointerDrag?.pointerId===event.pointerId)clearDrag();});
  container.addEventListener('dragstart',event=>{if(event.target.closest('[data-line-drag-handle]'))event.preventDefault();});
  container.addEventListener('keydown',event=>{
    const handle=event.target.closest('[data-line-drag-handle]');if(!handle)return;
    const from=Number(handle.dataset.lineDragHandle);
    if(['ArrowUp','ArrowLeft','ArrowDown','ArrowRight'].includes(event.key)){
      event.preventDefault();moveStep(from,from+(['ArrowUp','ArrowLeft'].includes(event.key)?-1:1));
    }
  });
  if(doc.defaultView.ResizeObserver)new doc.defaultView.ResizeObserver(layoutFlow).observe(container);
  render();
  return session;
}
