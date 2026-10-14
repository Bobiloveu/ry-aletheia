import { componentName } from "./component-specs.js";
import {transitionDisplayLabel} from './transition-labels.js';
import {componentDisplayLabel} from './component-labels.js';
import {constrainPassageAxes} from './route-passages.js';

const ROLE_LABELS = {
  waypoint: "路径过渡",
  entry: "进入",
  exit: "离开",
  start: "任务起点",
  pickup: "取货位置",
  delivery: "送货位置",
  visit: "仅到达",
  transition: "过渡点",
  elevator_approach: "电梯门前",
  elevator_wait: "候梯 / 呼梯",
  elevator_center: "电梯中心 / 乘梯",
  elevator_arrival: "出梯 / 关门",
  return_start: "回到起点",
};

const SPEED_LABELS = {
  normal: "常规通过",
  task_point: "任务点",
  single_point: "单点停靠",
  slow_point: "减速",
  narrow_point: "窄通道",
  backward: "出梯速度",
};

export function executionNodeLabel(node, project = {}) {
  if (node?.source_kind === "component") {
    const component = (project.components || []).find((item) => item.id === node.source_id);
    if (!component) return "组件";
    if(component.kind==='target')return componentDisplayLabel(project,component);
    const typeName = componentName(component);
    const customLabel = String(component.label || "").trim();
    return customLabel && customLabel !== typeName
      ? `${typeName} · ${customLabel}`
      : typeName;
  }
  const waypoint = (project.waypoints || []).find((item) => item.id === node?.source_id);
  if (!waypoint) return "过渡点";
  return transitionDisplayLabel(project,waypoint);
}

export function executionNodeRoleLabel(role) {
  return ROLE_LABELS[role] || "路径节点";
}

export function executionNodeSpeedLabel(speed) {
  return SPEED_LABELS[speed] || "常规";
}

/** Preserve each traversal of a map; fixed block keys are ordered numerically. */
export function executionChainSections(chain, project = {}) {
  if (!chain || typeof chain !== 'object') return [];
  const bindings = project.localization_bindings || [];
  const maps = project.map_assets || [];
  const entries = Object.entries(chain).filter(([, value]) => value && typeof value === 'object' && (Array.isArray(value.outbound) || Array.isArray(value.return)));
  entries.sort(([a], [b]) => /^block_\d+$/.test(a) && /^block_\d+$/.test(b) ? Number(a.slice(6)) - Number(b.slice(6)) : 0);
  return entries.map(([key, value], index) => {
    const mapAssetId = value.map_asset_id || bindings.find(binding => binding.id === value.binding_id)?.map_asset_id || null;
    const map = maps.find(map => map.id === mapAssetId);
    return {
      key, mapAssetId,
      leg: ['outbound','return'].includes(value.leg) ? value.leg : null,
      label: key === 'lobby' ? '电梯大厅' : key === 'target' ? '用户楼层' : `第 ${index + 1} 段 · ${map?.label || '地图通行段'}`,
      outbound: Array.isArray(value.outbound) ? value.outbound : [],
      return: Array.isArray(value.return) ? value.return : [],
      startAnchor: value.start_anchor || null, endAnchor: value.end_anchor || null,
      endSpeedMode: value.end_speed_mode || null,
    };
  });
}

const finitePoint = point => point && Number.isFinite(point.x) && Number.isFinite(point.y);
const pointsOf = nodes => nodes.filter(finitePoint).map(({x, y}) => ({x, y}));

/** Keep the full set for planning. Direction selection only changes presentation. */
export function filterPreviewLeg(items, leg = 'all') {
  return leg === 'outbound' || leg === 'return' ? items.filter(item => item.leg === leg) : items;
}

function attributedWaypointNodes(preview) {
  const subtasks = preview?.task_json?.subtasks;
  if (!Array.isArray(subtasks)) return null;
  const flattened = subtasks.flatMap((subtask, subtaskIndex) => (subtask.waypoints || []).map(waypoint => ({waypoint, subtask, subtaskIndex})));
  const trace = preview?.manifest?.waypoint_trace;
  const traced = Array.isArray(trace) && trace.length === flattened.length && trace.every((node, index) =>
    node.waypoint_id === flattened[index].waypoint.waypoint_id && ['outbound','return'].includes(node.leg) && node.map_asset_id);
  const maps = preview?.manifest?.subtask_map_asset_ids;
  if (!traced && (!Array.isArray(maps) || maps.length !== subtasks.length)) return null;
  return flattened.map(({waypoint, subtask, subtaskIndex}, index) => ({
    ...waypoint.pose?.position,
    waypointId: waypoint.waypoint_id,
    mapAssetId: traced ? trace[index].map_asset_id : maps[subtaskIndex],
    leg: traced ? trace[index].leg : String(subtask.subtask_name || '').startsWith('return_') ? 'return' : 'outbound',
    label: traced ? trace[index].label : null,
    role: traced ? trace[index].role : null,
    sourceId: traced ? trace[index].source_id : null,
    taskLineId: traced ? trace[index].task_line_id : preview?.manifest?.subtask_task_line_ids?.[subtaskIndex],
    speed: waypoint.speed_mode || waypoint.speed_profile,
    order: index + 1, subtaskIndex,
  }));
}

// A tagged block's outbound array is already directed along its declared leg.
// Untagged legacy blocks retain their explicit return arrays in reverse map order.
function executionChainTraversals(sections) {
  return [
    ...sections.map(section => ({...section,leg:section.leg || 'outbound',nodes:section.outbound})),
    ...sections.filter(section => !section.leg).reverse().map(section => ({...section,
      leg:'return',nodes:section.return,startAnchor:section.endAnchor,endAnchor:section.startAnchor,
    })),
  ];
}

/** Actual compiled nodes only; trace is aligned with flattened task waypoints. */
export function previewWaypointNodes(preview, project = {}) {
  const attributed = attributedWaypointNodes(preview);
  if (attributed) return attributed;
  const sections = executionChainSections(preview?.manifest?.execution_chain, project);
  return executionChainTraversals(sections).flatMap(section => section.nodes.map((node, index) => ({
    ...node, leg:section.leg, mapAssetId: section.mapAssetId, order:index + 1,
    label:executionNodeLabel(node,project), role:node.role,
  })));
}

/** Project only server-attributed map nodes. Never infer a map from coordinates or runtime paths. */
export function previewRouteSegments(preview, project, mapAssetId) {
  const constrain=segments=>constrainPassageAxes(segments,(project.components || []).filter(c=>c.map_asset_id===mapAssetId));
  const nodes = attributedWaypointNodes(preview);
  if (nodes) {
    const result = [];
    let previous = null, current = null;
    for (const node of nodes) {
      if (!finitePoint(node)) { previous = current = null; continue; }
      if (node.mapAssetId !== mapAssetId) { previous = node; current = null; continue; }
      if (!current || previous?.subtaskIndex !== node.subtaskIndex || previous?.leg !== node.leg || previous?.taskLineId!==node.taskLineId) {
        current = {leg:node.leg, points:[], order:node.subtaskIndex + 1,...(node.taskLineId?{taskLineId:node.taskLineId}:{})};
        if (previous?.taskLineId===node.taskLineId && previous?.mapAssetId === node.mapAssetId && node.subtaskIndex - previous.subtaskIndex <= 1) current.points.push({x:previous.x,y:previous.y});
        result.push(current);
      }
      current.points.push({x:node.x,y:node.y});
      previous = node;
    }
    return constrain(result);
  }
  const sections = executionChainSections(preview?.manifest?.execution_chain, project);
  return constrain(executionChainTraversals(sections)
    .map((section, index) => ({leg:section.leg, mapAssetId:section.mapAssetId, order:index + 1,
      points:pointsOf([section.startAnchor,...section.nodes,section.endAnchor])}))
    .filter(segment => segment.mapAssetId === mapAssetId && segment.points.length));
}

function targetActionLabel(intent = {purpose:'visit'}) {
  return intent.purpose === 'visit' ? '仅到达 · 无仓控' : [
    intent.purpose === 'pickup' ? '取货' : '送货',
    intent.cargo_id === 2 ? '下仓 2' : '上仓 1',
    ({open:'开仓',close:'关仓',unload:'自动卸货'})[intent.operation] || '仓控待确认',
  ].join(' · ');
}

/** Business intent stays available separately from the complete compiled itinerary. */
export function fixedTaskPreviewSummary(preview, project = {}) {
  const lines=preview?.manifest?.compiled_task_lines;
  if(lines?.length>1) {
    const summaries=lines.map(line=>fixedTaskPreviewSummary({manifest:{active_task_line:line}},project));
    return {name:`全部线路（${lines.length} 条）`,stepCount:summaries.reduce((n,s)=>n+s.stepCount,0),items:summaries.flatMap(s=>s.items)};
  }
  const line = preview?.manifest?.active_task_line;
  if (!line || !Array.isArray(line.steps)) return null;
  const components = project.components || [];
  const transitions = project.waypoints || [];
  const maps = project.map_assets || [];
  const component = id => components.find(item => item.id === id);
  const label = (location, fallback) => location?.kind==='target'?componentDisplayLabel(project,location):String(location?.label || '').trim() || fallback;
  const detail = (location, text) => {
    const mapName = maps.find(map => map.id === location?.map_asset_id)?.label;
    return [mapName, text].filter(Boolean).join(' · ');
  };
  const start = component(line.start_component_id);
  const items = [{title:`起点 · ${label(start,'起点位置')}`,detail:detail(start,'开始去程'),mapAssetId:start?.map_asset_id || null}];
  for (const step of line.steps) {
    const location = step.kind === 'transition' ? transitions.find(item => item.id === step.id) : component(step.id);
    let action;
    if (location?.kind === 'target') {
      action = targetActionLabel(step.action);
    } else if (step.kind === 'transition') action = `过渡点 · ${executionNodeSpeedLabel(location?.speed_mode)}`;
    else action = '通行设施 · 沿用既有参数';
    items.push({title:step.kind === 'transition' ? transitionDisplayLabel(project,location) : label(location,location ? componentName(location) : '位置不可用'),detail:detail(location,action),mapAssetId:location?.map_asset_id || null});
  }
  items.push({title:'自动返程',detail:'从末步位置按可通行路径直接回到起点；不重复取货、卸货或开关仓。',mapAssetId:null});
  return {name:line.name || '固定任务线路',stepCount:line.steps.length,items};
}

/** Both directions follow actual compiled nodes; annotate each target visit's business action. */
export function previewTaskItems(preview, project = {}, leg = 'all') {
  const summary = fixedTaskPreviewSummary(preview, project);
  const nodes = previewWaypointNodes(preview, project);
  if (!nodes.length) return filterPreviewLeg(summary ? summary.items.slice(0,-1).map(item=>({...item,leg:'outbound'})) : [],leg);
  const lines=preview?.manifest?.compiled_task_lines || [preview?.manifest?.active_task_line].filter(Boolean);
  const visits = new Map();
  for (const line of lines)for (const step of line.steps || []) {
    if (step.kind !== 'component' || !(project.components || []).some(item=>item.id===step.id && item.kind==='target')) continue;
    const key=`${line.id || ''}:${step.id}`;
    if (!visits.has(key)) visits.set(key,[]);
    visits.get(key).push(step.action);
  }
  const nodeItems = nodes.map((node, index) => {
    const sourceId = node.sourceId || node.source_id;
    const line=lines.find(line=>line.id===node.taskLineId) || lines[0];
    const key=`${line?.id || ''}:${sourceId}`;
    const targetVisit = node.leg === 'outbound' && ['pickup','delivery','visit','target','waypoint'].includes(node.role) && visits.get(key)?.length;
    const action = targetVisit ? targetActionLabel(visits.get(key).shift()) : null;
    const transition = (project.waypoints || []).find(item=>item.id===sourceId);
    const component=(project.components || []).find(item=>item.id===sourceId);
    const start = node.leg === 'outbound' && sourceId === line?.start_component_id &&
      (node.role==='start'||index===0||nodes[index-1]?.taskLineId!==node.taskLineId);
    return {
      leg:node.leg, mapAssetId:node.mapAssetId,
      title:start && summary ? `起点 · ${componentDisplayLabel(project,component)}` : transition ? transitionDisplayLabel(project,transition) : component?.kind==='target'?componentDisplayLabel(project,component):node.label || `${node.leg === 'return' ? '返程' : '去程'}节点 ${index + 1}`,
      detail:[
        lines.length>1?line?.name:null,
        (project.map_assets || []).find(map => map.id === node.mapAssetId)?.label || '地图归属待确认',
        node.leg === 'return' ? '返程' : '去程',
        action || executionNodeRoleLabel(node.role),
        node.speed ? executionNodeSpeedLabel(node.speed) : null,
      ].filter(Boolean).join(' · '),
    };
  });
  return filterPreviewLeg(nodeItems,leg);
}

/** Saved annotation symbols must not suggest outbound stops in a return-only view. */
export function previewDirectionProject(preview, project = {}, leg = 'all') {
  if (leg !== 'outbound' && leg !== 'return') return project;
  const sources = new Set(filterPreviewLeg(previewWaypointNodes(preview, project),leg).map(node => node.sourceId || node.source_id).filter(Boolean));
  return {...project,
    components:(project.components || []).filter(item => sources.has(item.id)),
    waypoints:(project.waypoints || []).filter(item => sources.has(item.id)),
  };
}
