export function orderedRouteBindingIds(existingIds, bindings, building, unit) {
  const eligible = (Array.isArray(bindings) ? bindings : []).filter(
    (item) => item.building === building && item.unit === unit,
  );
  const eligibleIds = new Set(eligible.map((item) => item.id));
  const ordered = [];
  for (const id of Array.isArray(existingIds) ? existingIds : []) {
    if (eligibleIds.has(id) && !ordered.includes(id)) ordered.push(id);
  }
  for (const item of eligible) {
    if (!ordered.includes(item.id)) ordered.push(item.id);
  }
  return ordered;
}

export function routeEndpointFields(isFirst, isLast) {
  return [isFirst && "start", isLast && "target"].filter(Boolean);
}
