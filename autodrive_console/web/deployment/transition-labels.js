// Project responses replace the snapshot when names change. Geometry gestures
// may mutate poses locally; they do not change this naming index.
const indexes = new WeakMap();
const generic = label => !label || label === '过渡点' || label === 'transition';

function namingIndex(project) {
  if (!project || typeof project !== 'object') return new Map();
  const waypoints = project.waypoints || [];
  const cached = indexes.get(project);
  if (cached?.source === waypoints && cached.length === waypoints.length) return cached.names;
  const maps = new Map(), names = new Map();
  for (const point of waypoints) {
    if (point.kind !== 'transition' || point.generated_by) continue;
    if (!maps.has(point.map_asset_id)) maps.set(point.map_asset_id, []);
    maps.get(point.map_asset_id).push(point);
  }
  for (const points of maps.values()) {
    const counts = new Map(), used = new Set();
    for (const point of points) {
      const label = String(point.label || '').trim();
      if (!generic(label)) { used.add(label); counts.set(label, (counts.get(label) || 0) + 1); }
    }
    const ordinals = new Map();
    let number = 1;
    for (const point of points) {
      let label = String(point.label || '').trim();
      if (generic(label)) {
        while (used.has(`过渡点 ${number}`)) number++;
        label = `过渡点 ${number++}`;
      } else if (counts.get(label) > 1) {
        const base = label;
        let ordinal = (ordinals.get(base) || 0) + 1;
        while (used.has(`${base}（${ordinal}）`)) ordinal++;
        ordinals.set(base, ordinal);
        label = `${base}（${ordinal}）`;
      }
      used.add(label);
      names.set(point.id, label);
    }
  }
  indexes.set(project, {source:waypoints, length:waypoints.length, names});
  return names;
}

export function transitionDisplayLabel(project, point) {
  if (!point) return '过渡点';
  return namingIndex(project).get(point.id) || String(point.label || '').trim() || '过渡点';
}

export function nextTransitionLabel(project, mapId) {
  const names = namingIndex(project);
  const used = new Set((project?.waypoints || [])
    .filter(point => point.map_asset_id === mapId)
    .flatMap(point => [String(point.label || '').trim(), names.get(point.id)]));
  let number = 1;
  while (used.has(`过渡点 ${number}`)) number++;
  return `过渡点 ${number}`;
}
