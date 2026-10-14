import assert from "node:assert/strict";
import test from "node:test";

const moduleUrl = new URL("../../../autodrive_console/web/deployment/preview-viewport.js", import.meta.url);
const near = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-8, `${actual} != ${expected}`);

test("fit centers the entire image without changing its aspect ratio", async () => {
  const { fitPreview } = await import(moduleUrl);
  const view = fitPreview({ width: 400, height: 300, imageWidth: 200, imageHeight: 100 });
  assert.equal(view.scale, 2);
  assert.equal(view.x, 0);
  assert.equal(view.y, 50);
  assert.equal(view.fitScale, 2);
});

test("wheel zoom preserves the image coordinate beneath the pointer", async () => {
  const { fitPreview, zoomPreviewAt } = await import(moduleUrl);
  const view = fitPreview({ width: 400, height: 300, imageWidth: 200, imageHeight: 100 });
  const point = { x: 120, y: 95 };
  const next = zoomPreviewAt(view, point, 2);
  near((point.x - view.x) / view.scale, (point.x - next.x) / next.scale);
  near((point.y - view.y) / view.scale, (point.y - next.y) / next.scale);
  assert.equal(next.scale, 4);
});

test("zoom is bounded while pan moves in screen pixels", async () => {
  const { fitPreview, zoomPreviewAt, panPreview } = await import(moduleUrl);
  const view = fitPreview({ width: 400, height: 300, imageWidth: 200, imageHeight: 100 });
  assert.equal(zoomPreviewAt(view, { x: 0, y: 0 }, 1e6).scale, view.fitScale * 32);
  assert.equal(zoomPreviewAt(view, { x: 0, y: 0 }, 1e-6).scale, view.fitScale / 4);
  assert.deepEqual(panPreview(view, 50, -20), { ...view, x: 50, y: 30 });
});

test("viewport binds wheel and pointer drag, and resets when revision changes", async () => {
  const { bindPreviewViewport } = await import(moduleUrl);
  const handlers = {};
  const surface = { style: {}, addEventListener: (name, callback) => { handlers[name] = callback; }, removeEventListener: () => {}, getBoundingClientRect: () => ({ left: 10, top: 20, width: 400, height: 300 }), setPointerCapture: () => {}, releasePointerCapture: () => {} };
  const image = { style: {}, setAttribute: () => {} };
  const controls = Object.fromEntries(["zoomIn", "zoomOut", "fit"].map((key) => [key, { addEventListener: () => {}, removeEventListener: () => {}, disabled: true }]));
  const readout = { textContent: "" };
  const viewport = bindPreviewViewport({ surface, getImage: () => image, ...controls, readout, ResizeObserverImpl: null });
  viewport.setImage({ key: "revision-1", width: 200, height: 100 });
  assert.equal(readout.textContent, "100%");
  let prevented = false;
  handlers.wheel({ clientX: 110, clientY: 120, deltaY: -100, deltaMode: 0, preventDefault: () => { prevented = true; } });
  assert.equal(prevented, true);
  assert.ok(viewport.view.scale > 2);
  const beforeDrag = viewport.view;
  handlers.pointerdown({ button: 0, pointerId: 3, clientX: 110, clientY: 120, preventDefault: () => {} });
  handlers.pointermove({ pointerId: 3, clientX: 170, clientY: 150 });
  near(viewport.view.x, beforeDrag.x + 60);
  near(viewport.view.y, beforeDrag.y + 30);
  handlers.pointercancel({ pointerId: 3 });
  const cancelled = viewport.view;
  handlers.pointermove({ pointerId: 3, clientX: 190, clientY: 200 });
  assert.deepEqual(viewport.view, cancelled);
  viewport.setImage({ key: "revision-2", width: 200, height: 100 });
  assert.equal(viewport.view.scale, 2);
  assert.equal(viewport.view.x, 0);
  assert.equal(viewport.view.y, 50);
  viewport.setImage(null);
  assert.equal(controls.fit.disabled, true);
  viewport.dispose();
});

test("an image loaded while hidden fits when its viewport becomes visible", async () => {
  const { bindPreviewViewport } = await import(moduleUrl);
  let box = { width: 0, height: 0 };
  let resized;
  const surface = { style: {}, addEventListener: () => {}, removeEventListener: () => {}, getBoundingClientRect: () => box };
  const button = () => ({ addEventListener: () => {}, removeEventListener: () => {} });
  const fit = button();
  const viewport = bindPreviewViewport({ surface, getImage: () => ({ style: {}, setAttribute: () => {} }), zoomIn: button(), zoomOut: button(), fit, readout: {}, ResizeObserverImpl: class { constructor(callback) { resized = callback; } observe() {} disconnect() {} } });
  viewport.setImage({ key: "revision-1", width: 200, height: 100 });
  assert.equal(viewport.view, null);
  box = { width: 400, height: 300 };
  resized();
  assert.equal(viewport.view?.scale, 2);
  assert.equal(fit.disabled, false);
  viewport.dispose();
});
