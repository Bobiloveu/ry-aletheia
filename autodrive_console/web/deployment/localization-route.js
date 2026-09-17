export function orderedRouteBindingIds(existingIds, bindings, building, unit) {
  const eligible = (Array.isArray(bindings) ? bindings : []).filter(
    (item) => item.building === building && item.unit === unit,
  );
  const eligibleIds = new Set(eligible.map((item) => item.id));
  const ordered = [];
  for (const id of Array.isArray(existingIds) ? existingIds : []) {
    if (eligibleIds.has(id) && !ordered.includes(id)) ordered.push(id);
  }
  if (!Array.isArray(existingIds)) {
    for (const item of eligible) ordered.push(item.id);
  }
  return ordered;
}

export function routeBindingChoices(bindings, building, unit, selectedIds) {
  const included = new Set(selectedIds || []);
  return (Array.isArray(bindings) ? bindings : [])
    .filter((binding) => binding.building === building && binding.unit === unit)
    .map((binding) => ({ ...binding, included: included.has(binding.id) }));
}

function withBindingIds(draft, bindingIds) {
  const oldIds = draft.binding_ids || [];
  const links = new Map((draft.links || []).map((link) => [
    `${link.from_binding_id}:${link.to_binding_id}`, link.anchor,
  ]));
  return {
    ...draft,
    binding_ids: bindingIds,
    task_start_waypoint_id: oldIds[0] === bindingIds[0] ? draft.task_start_waypoint_id : "",
    task_target_waypoint_id: oldIds.at(-1) === bindingIds.at(-1) ? draft.task_target_waypoint_id : "",
    links: bindingIds.slice(0, -1).map((fromId, index) => {
      const toId = bindingIds[index + 1];
      const anchor = links.get(`${fromId}:${toId}`);
      return { from_binding_id: fromId, to_binding_id: toId, anchor: anchor ? { ...anchor } : null };
    }),
  };
}

export function setRouteBindingIncluded(draft, bindings, bindingId, included) {
  const eligible = routeBindingChoices(bindings, draft.building, draft.unit, draft.binding_ids);
  if (!eligible.some((binding) => binding.id === bindingId)) return draft;
  const identifiers = [...draft.binding_ids];
  if (included && !identifiers.includes(bindingId)) identifiers.push(bindingId);
  return withBindingIds(draft, included ? identifiers : identifiers.filter((id) => id !== bindingId));
}

export function moveRouteBinding(draft, index, offset) {
  const identifiers = [...draft.binding_ids];
  const destination = index + offset;
  if (index < 0 || index >= identifiers.length || destination < 0 || destination >= identifiers.length) return draft;
  [identifiers[index], identifiers[destination]] = [identifiers[destination], identifiers[index]];
  return withBindingIds(draft, identifiers);
}

export function resetRouteDraft(draft) {
  return {
    id: draft.id, building: draft.building, unit: draft.unit, binding_ids: [],
    task_start_waypoint_id: "", task_target_waypoint_id: "", links: [],
  };
}

export function routeEndpointFields(isFirst, isLast) {
  return [isFirst && "start", isLast && "target"].filter(Boolean);
}
