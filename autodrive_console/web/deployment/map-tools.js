import { COMPONENT_SPECS } from './component-specs.js';
import { isPointOnMap } from './canvas-geometry.js';

export function placementPreview(kind,point,map) {
  if(!(Object.hasOwn(COMPONENT_SPECS,kind) || kind==='transition') || !map || !Number.isFinite(point?.x) || !Number.isFinite(point?.y) || !isPointOnMap(point,map))return null;
  return {id:'__placement_preview__',kind,map_asset_id:map.id,x:point.x,y:point.y,yaw:0,attributes:{}};
}

export function canUseMapEditShortcut(event,workspace,{previewOpen=false}={}) {
  return !previewOpen&&!event.defaultPrevented&&workspace.contains(event.target)&&
    !event.target.closest?.('input,textarea,select,button,a,[contenteditable]:not([contenteditable="false"])');
}

// Presentation only: the existing editor remains responsible for saving edits.
export function bindMapTools(document) {
  const get=id=>document.getElementById(id);
  const workspace=get('mapWorkspace'),palette=get('mapToolPalette'),toggle=get('addMapComponent');
  function closePalette({focus=false}={}) {
    palette.hidden=true;toggle.setAttribute('aria-expanded','false');
    if(focus)toggle.focus();
  }
  toggle.addEventListener('click',()=>{
    if(!palette.hidden){closePalette();return;}
    palette.hidden=false;toggle.setAttribute('aria-expanded','true');
    palette.querySelector('.waypoint-tool').focus();
  });
  get('closeMapToolPalette').addEventListener('click',()=>closePalette({focus:true}));
  document.addEventListener('pointerdown',event=>{
    if(!palette.hidden&&!palette.contains(event.target)&&!toggle.contains(event.target))closePalette();
  });
  workspace.addEventListener('keydown',event=>{
    if(event.key==='Escape'&&!palette.hidden){event.preventDefault();closePalette({focus:true});}
  });
  function setActive(tool,{editMode="erase"}={}) {
    const wall=editMode==="wall";
    const component=Object.hasOwn(COMPONENT_SPECS,tool) || tool==='transition';
    closePalette();
    workspace.dataset.mapTool=tool;
    workspace.querySelectorAll('.waypoint-tool,#panTool').forEach(button=>{
      const active=button.id==='panTool'?tool==='pan':button.dataset.waypointKind===tool;
      button.classList.toggle('active-tool',active);button.setAttribute('aria-pressed',String(active));
    });
    toggle.setAttribute('aria-pressed',String(component));
    get('mapActiveTool').textContent=component?(COMPONENT_SPECS[tool]?.name || '过渡点'):
      ({virtual_wall:'虚拟墙',erase_brush:wall?'补墙笔刷':'橡皮擦',erase_polygon:wall?'框选补墙':'框选擦除'}[tool] || '选择与平移');
    get('mapActiveToolHint').textContent=component?'点击放置 · Esc 取消':
      tool==='virtual_wall'?'顶点自动吸附 · Enter 完成 · Ctrl / ⌘ Z 撤销':tool==='erase_polygon'?'拖动顶点微调 · Enter 完成':tool==='erase_brush'?`${wall?'涂成黑色障碍':'擦成白色'} · 滚轮调节直径`:'';
    get('mapToolContext').hidden=tool==='pan'||!(component||['virtual_wall','erase_brush','erase_polygon'].includes(tool));
    get('mapEditModeControl').hidden=!['erase_brush','erase_polygon'].includes(tool);
    get('mapEraseActions').hidden=!['erase_brush','erase_polygon'].includes(tool);
  }
  setActive('pan');
  return {setActive,closePalette};
}
