export const FLOW_NODE_TYPES = {
  outdoor: { label: "户外图", description: "从园区或室外起点进入", icon: "↗" },
  ferry: { label: "摆渡层", description: "中间摆渡或换乘地图", icon: "⇄" },
  lobby: { label: "电梯大厅", description: "电梯首层候梯地图", icon: "▥" },
  target_floor: { label: "用户楼层", description: "最终配送目标地图", icon: "⌂" },
};

export function legacyFlow(sceneModel) {
  const order = {
    outdoor: ["outdoor"],
    indoor: ["lobby", "target_floor"],
    indoor_outdoor: ["outdoor", "lobby", "target_floor"],
  }[sceneModel] || [];
  return order.map((type) => ({ id: type, type, label: FLOW_NODE_TYPES[type].label }));
}

export function flowForProject(project) {
  return Array.isArray(project?.deployment_flow) && project.deployment_flow.length
    ? project.deployment_flow.map((node) => ({ ...node }))
    : legacyFlow(project?.scene_model || "indoor_outdoor");
}

export function validateFlow(nodes) {
  const flow = Array.isArray(nodes) ? nodes : [];
  const typeCounts = flow.reduce((counts, node) => {
    counts[node?.type] = (counts[node?.type] || 0) + 1;
    return counts;
  }, {});
  if (!flow.length) return { valid: false, message: "至少添加两个地图阶段。" };
  if (typeCounts.lobby !== 1) return { valid: false, message: "流程需要一个电梯大厅。" };
  if (typeCounts.target_floor !== 1) return { valid: false, message: "流程需要一个用户楼层。" };
  if (flow.at(-1)?.type !== "target_floor") return { valid: false, message: "用户楼层必须放在最后。" };
  if (typeCounts.outdoor > 1) return { valid: false, message: "户外图最多配置一个。" };
  return { valid: true, message: "流程顺序已就绪。" };
}

export function createFlowNode(type, existing = []) {
  const base = FLOW_NODE_TYPES[type];
  if (!base) return null;
  const used = new Set(existing.map((node) => node.id));
  let index = 1;
  let id = type;
  while (used.has(id)) id = `${type}-${index++}`;
  return { id, type, label: base.label };
}

export function reorderFlow(nodes, from, to) {
  const flow = Array.isArray(nodes) ? nodes.map((node) => ({ ...node })) : [];
  if (!Number.isInteger(from) || !Number.isInteger(to) || from < 0 || from >= flow.length) return flow;
  const targetSlot = Math.max(0, Math.min(to, flow.length));
  const dragged = flow.splice(from, 1)[0];
  let insertion = targetSlot - (from < targetSlot ? 1 : 0);
  insertion = Math.max(0, Math.min(insertion, flow.length));
  if (dragged?.type === "target_floor") insertion = flow.length;
  flow.splice(insertion, 0, dragged);
  const finalTarget = flow.findIndex((node) => node.type === "target_floor");
  if (finalTarget >= 0 && finalTarget !== flow.length - 1) {
    const [target] = flow.splice(finalTarget, 1);
    flow.push(target);
  }
  return flow;
}

function animateFlowLayout(container, previousRects) {
  const play = () => {
    for (const element of container.querySelectorAll("[data-flow-id]")) {
      const previous = previousRects.get(element.dataset.flowId);
      if (!previous || typeof element.animate !== "function") continue;
      const current = element.getBoundingClientRect();
      const dx = previous.left - current.left;
      const dy = previous.top - current.top;
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1) continue;
      element.animate(
        [
          { transform: `translate(${dx}px, ${dy}px)`, opacity: 0.72 },
          { transform: "translate(0, 0)", opacity: 1 },
        ],
        { duration: 240, easing: "cubic-bezier(0.22, 1, 0.36, 1)" },
      );
    }
  };
  if (typeof requestAnimationFrame === "function") requestAnimationFrame(play);
  else play();
}

export function renderDeploymentFlow(container, nodes, { onAction } = {}) {
  if (!container) return;
  const flow = Array.isArray(nodes) ? nodes : [];
  container.classList.remove("is-dragging");
  const previousRects = new Map(
    [...container.querySelectorAll("[data-flow-id]")].map((element) => [
      element.dataset.flowId,
      element.getBoundingClientRect(),
    ]),
  );
  const dropZone = (index) => `<span class="deployment-flow-drop-zone" data-flow-drop-index="${index}" role="button" aria-label="放置在第 ${index + 1} 个阶段之前"></span>`;
  container.innerHTML = flow.length
    ? `${flow.map((node, index) => {
      const meta = FLOW_NODE_TYPES[node.type] || FLOW_NODE_TYPES.ferry;
      return `${dropZone(index)}${index ? '<span class="deployment-flow-arrow" aria-hidden="true">→</span>' : ''}
        <article class="deployment-flow-node" draggable="true" tabindex="0" aria-grabbed="false" data-flow-id="${node.id}" data-flow-drag-index="${index}">
          <div class="deployment-flow-node-head"><span class="deployment-flow-node-icon">${meta.icon}</span><span class="deployment-flow-node-index">${index + 1}</span></div>
          <strong>${meta.label}</strong><small>${meta.description}</small>
          <button type="button" class="deployment-flow-remove-action" data-flow-action="remove">移除阶段</button>
        </article>`;
    }).join("")}${dropZone(flow.length)}`
    : '<div class="deployment-flow-empty">从下方添加地图阶段，组成实际运行顺序。</div>';
  animateFlowLayout(container, previousRects);
  let draggedIndex = null;
  let pointerDrag = null;
  const clearDropState = () => {
    container.querySelectorAll(".is-drop-target").forEach((element) => element.classList.remove("is-drop-target"));
  };
  const activateDrag = (node, index) => {
    draggedIndex = index;
    node?.setAttribute("aria-grabbed", "true");
    node?.classList.add("is-dragging");
    container.classList.add("is-dragging");
  };
  const finishDrag = (node) => {
    node?.classList.remove("is-dragging");
    node?.setAttribute("aria-grabbed", "false");
    container.classList.remove("is-dragging");
    draggedIndex = null;
    clearDropState();
  };
  container.onclick = (event) => {
    const button = event.target.closest("[data-flow-action]");
    if (!button) return;
    const node = button.closest("[data-flow-drag-index]");
    onAction?.(button.dataset.flowAction, Number(node?.dataset.flowDragIndex));
  };
  container.ondragstart = (event) => {
    if (pointerDrag?.active) {
      event.preventDefault();
      return;
    }
    const node = event.target.closest("[data-flow-drag-index]");
    if (!node) return;
    activateDrag(node, Number(node.dataset.flowDragIndex));
    event.dataTransfer?.setData("text/plain", String(draggedIndex));
    if (event.dataTransfer) event.dataTransfer.effectAllowed = "move";
  };
  const resolveDropZone = (event) => {
    // Pointer capture keeps dispatching events to the dragged card even when
    // the pointer is over a sibling drop zone. Re-hit-test by coordinates so
    // the magnetic insertion slots remain discoverable during the drag.
    const hitTarget = container.ownerDocument?.elementFromPoint?.(event.clientX, event.clientY) || event.target;
    const direct = hitTarget?.closest?.("[data-flow-drop-index]");
    if (direct && container.contains(direct)) return direct;
    const cards = [...container.querySelectorAll("[data-flow-drag-index]")];
    const index = cards.findIndex((card) => {
      const rect = card.getBoundingClientRect();
      return event.clientX <= rect.left + rect.width / 2;
    });
    const dropIndex = index < 0 ? cards.length : index;
    return container.querySelector(`[data-flow-drop-index="${dropIndex}"]`);
  };
  const updateDropTarget = (event) => {
    const zone = resolveDropZone(event);
    const insertion = Number(zone?.dataset.flowDropIndex);
    if (!zone || insertion === draggedIndex || insertion === draggedIndex + 1) return null;
    clearDropState();
    zone.classList.add("is-drop-target");
    return zone;
  };
  const commitDrop = (zone) => {
    const insertion = Number(zone?.dataset.flowDropIndex);
    if (!zone || insertion === draggedIndex || insertion === draggedIndex + 1) return;
    onAction?.("reorder", { from: draggedIndex, to: insertion });
  };
  container.onpointerdown = (event) => {
    if (event.button !== 0 || event.target.closest("[data-flow-action]")) return;
    const node = event.target.closest("[data-flow-drag-index]");
    if (!node) return;
    pointerDrag = {
      node,
      index: Number(node.dataset.flowDragIndex),
      startX: event.clientX,
      startY: event.clientY,
      active: false,
      zone: null,
    };
  };
  container.onpointermove = (event) => {
    if (!pointerDrag) return;
    if (!pointerDrag.active) {
      const distance = Math.hypot(event.clientX - pointerDrag.startX, event.clientY - pointerDrag.startY);
      if (distance < 6) return;
      pointerDrag.active = true;
      activateDrag(pointerDrag.node, pointerDrag.index);
      try {
        pointerDrag.node.setPointerCapture?.(event.pointerId);
      } catch {
        // Synthetic or cancelled pointer streams may not expose a capturable id.
      }
    }
    event.preventDefault();
    pointerDrag.zone = updateDropTarget(event);
  };
  container.onpointerup = (event) => {
    if (!pointerDrag) return;
    const drag = pointerDrag;
    pointerDrag = null;
    if (!drag.active) return;
    event.preventDefault();
    commitDrop(updateDropTarget(event) || drag.zone);
    try {
      drag.node.releasePointerCapture?.(event.pointerId);
    } catch {
      // The browser may already have released the pointer after cancellation.
    }
    finishDrag(drag.node);
  };
  container.onpointercancel = () => {
    if (pointerDrag?.active) finishDrag(pointerDrag.node);
    pointerDrag = null;
  };
  container.ondragover = (event) => {
    if (draggedIndex === null) return;
    const zone = updateDropTarget(event);
    if (!zone) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
  };
  container.ondrop = (event) => {
    event.preventDefault();
    if (draggedIndex === null) return;
    const node = event.target.closest("[data-flow-drag-index]");
    const zone = updateDropTarget(event);
    commitDrop(zone);
    finishDrag(node);
  };
  container.ondragend = (event) => {
    const node = event.target.closest("[data-flow-drag-index]");
    finishDrag(node);
  };
}
