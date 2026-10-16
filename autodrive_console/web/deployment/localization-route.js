// Read-only helpers for Backend-derived deployment routes. Route ordering is
// intentionally absent from the browser: it is derived from the scene flow
// and the traversable map path on the backend.

export function automaticRouteBindings(route, bindings) {
  if (!route || !Array.isArray(route.binding_ids) || !Array.isArray(bindings)) return [];
  const byId = new Map(bindings.filter((item) => item?.id).map((item) => [item.id, item]));
  return route.binding_ids.map((id) => byId.get(id)).filter(Boolean);
}

export function automaticExecutionNodes(route, bindingId) {
  const entry = Array.isArray(route?.execution_nodes)
    ? route.execution_nodes.find((item) => item?.binding_id === bindingId)
    : null;
  return Array.isArray(entry?.node_refs)
    ? entry.node_refs.filter((ref) => ref && ["transition", "component"].includes(ref.kind) && ref.id)
    : [];
}

export function automaticRouteStatus(route, bindings) {
  const orderedBindings = automaticRouteBindings(route, bindings);
  if (!route || !orderedBindings.length) return { ready: false, reason: "尚未生成自动路线" };
  if (orderedBindings.length !== route.binding_ids.length) return { ready: false, reason: "自动路线引用的定位绑定不完整" };
  if (orderedBindings.length > 1 && orderedBindings.at(-1).type !== "floor") return { ready: false, reason: "场景流程必须以用户楼层结束" };
  return {
    ready: true,
    mapCount: orderedBindings.length,
    nodeCount: orderedBindings.reduce(
      (count, binding) => count + automaticExecutionNodes(route, binding.id).length,
      0,
    ),
  };
}
