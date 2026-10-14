export function fitPreview({ width, height, imageWidth, imageHeight }) {
  const scale = Math.min(Math.max(1, width) / Math.max(1, imageWidth), Math.max(1, height) / Math.max(1, imageHeight));
  return { width, height, imageWidth, imageHeight, scale, fitScale: scale, x: (width - imageWidth * scale) / 2, y: (height - imageHeight * scale) / 2 };
}

export function zoomPreviewAt(view, point, factor) {
  const scale = Math.max(view.fitScale / 4, Math.min(view.fitScale * 32, view.scale * factor));
  const ratio = scale / view.scale;
  return { ...view, scale, x: point.x - (point.x - view.x) * ratio, y: point.y - (point.y - view.y) * ratio };
}

export function panPreview(view, dx, dy) {
  return { ...view, x: view.x + dx, y: view.y + dy };
}

/** A single image viewport; no image decoding or projection authority lives here. */
export function bindPreviewViewport({ surface, getImage, zoomIn, zoomOut, fit, readout, onRender = () => {}, ResizeObserverImpl = globalThis.ResizeObserver }) {
  let image = null;
  let view = null;
  let drag = null;
  const listeners = [];
  function listen(target, event, handler, options) {
    target.addEventListener(event, handler, options);
    listeners.push(() => target.removeEventListener(event, handler, options));
  }
  function render() {
    const enabled = Boolean(image && view);
    [zoomIn, zoomOut, fit].forEach((button) => { button.disabled = !enabled; });
    surface.setAttribute?.("data-preview-ready", String(enabled));
    const text = enabled ? `${Math.round(view.scale / view.fitScale * 100)}%` : "100%";
    if (readout.textContent !== text) readout.textContent = text;
    onRender(enabled ? { ...view } : null);
    if (!enabled) return;
    const target = getImage();
    target.style.width = `${image.width}px`;
    target.style.height = `${image.height}px`;
    target.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.scale})`;
    target.setAttribute("draggable", "false");
  }
  function refit() {
    if (!image) return;
    const box = surface.getBoundingClientRect();
    if (!box.width || !box.height) return;
    view = fitPreview({ width: box.width, height: box.height, imageWidth: image.width, imageHeight: image.height });
    drag = null;
    render();
  }
  function zoom(factor, point = { x: view.width / 2, y: view.height / 2 }) {
    if (!image || !view) return;
    view = zoomPreviewAt(view, point, factor);
    render();
  }
  function stopDrag(event) {
    if (!drag || (event?.pointerId !== undefined && event.pointerId !== drag.pointerId)) return;
    try { surface.releasePointerCapture?.(drag.pointerId); } catch { /* Capture can end before pointercancel. */ }
    drag = null;
    surface.style.cursor = "";
  }
  listen(surface, "wheel", (event) => {
    if (!image || !view) return;
    event.preventDefault();
    const box = surface.getBoundingClientRect();
    const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? box.height : 1;
    const delta = Math.max(-200, Math.min(200, event.deltaY * unit));
    zoom(Math.exp(-delta * .002), { x: event.clientX - box.left, y: event.clientY - box.top });
  }, { passive: false });
  listen(surface, "pointerdown", (event) => {
    if (!image || !view || event.button !== 0) return;
    event.preventDefault();
    drag = { pointerId: event.pointerId, x: event.clientX, y: event.clientY };
    surface.setPointerCapture?.(event.pointerId);
    surface.style.cursor = "grabbing";
  });
  listen(surface, "pointermove", (event) => {
    if (!drag || event.pointerId !== drag.pointerId) return;
    view = panPreview(view, event.clientX - drag.x, event.clientY - drag.y);
    drag.x = event.clientX;
    drag.y = event.clientY;
    render();
  });
  for (const event of ["pointerup", "pointercancel", "lostpointercapture"]) listen(surface, event, stopDrag);
  listen(surface, "keydown", (event) => {
    if (!image || !view) return;
    if (["+", "="].includes(event.key)) zoom(1.25);
    else if (event.key === "-") zoom(.8);
    else if (event.key === "0" || event.key === "Home") refit();
    else if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) {
      view = panPreview(view, event.key === "ArrowLeft" ? 24 : event.key === "ArrowRight" ? -24 : 0, event.key === "ArrowUp" ? 24 : event.key === "ArrowDown" ? -24 : 0);
      render();
    } else return;
    event.preventDefault();
  });
  listen(zoomIn, "click", () => { if (view) zoom(1.25); });
  listen(zoomOut, "click", () => { if (view) zoom(.8); });
  listen(fit, "click", refit);
  const observer = ResizeObserverImpl ? new ResizeObserverImpl(() => {
    if (!image) return;
    const box = surface.getBoundingClientRect();
    if (box.width && box.height && (!view || box.width !== view.width || box.height !== view.height)) refit();
  }) : null;
  observer?.observe(surface);
  render();
  return {
    get view() { return view ? { ...view } : null; },
    setImage(next) {
      if (image?.key === next?.key && image?.width === next?.width && image?.height === next?.height) return;
      stopDrag();
      image = next;
      view = null;
      if (image) refit();
      else render();
    },
    dispose() { stopDrag(); observer?.disconnect(); listeners.forEach((remove) => remove()); },
  };
}
