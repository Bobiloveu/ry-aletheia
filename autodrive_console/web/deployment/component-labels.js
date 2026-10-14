import {componentName} from './component-specs.js';

/** Operator identity shared by map labels, selectors, cards and route previews. */
export function componentDisplayLabel(project,item) {
  if(!item)return '位置不可用';
  const type=componentName(item),label=String(item.label||'').trim()||type;
  if(item.kind!=='target')return label;
  const door=String(item.attributes?.door||'').trim();
  if(door)return label===door?label:`${label} · ${door}`;
  const peers=(project?.components||[]).filter(c=>c.kind==='target'&&c.map_asset_id===item.map_asset_id&&
    (String(c.label||'').trim()||componentName(c))===label&&!String(c.attributes?.door||'').trim());
  return peers.length>1?`${label} ${Math.max(1,peers.findIndex(c=>c.id===item.id)+1)}`:label;
}
