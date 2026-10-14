import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { deriveDeploymentTask, deriveDeploymentWorkflow } from "../../../autodrive_console/web/deployment/workflow.js";
import { readDeploymentSession, writeDeploymentSession } from "../../../autodrive_console/web/deployment/session-state.js";

const parameters = { z_min: 0.2, z_max: 1.8, resolution: 0.05, min_points: 1, denoise: false };
const projection = (state = "ready", extra = {}) => ({ id: "cloud-1", project_id: "site-1", state, revision: 2, parameters, analysis: { bounds: { z: [-1, 3] }, candidates: [{ label: "候选地面", z_min: 0.2, z_max: 1.8 }] }, ...extra });
const project = { id: "site-1", scene_model: "indoor", map_assets: [] };
const topology = { stages: [{ stage: "lobby", label: "电梯大厅", map_asset_id: null }] };
const workflow = deriveDeploymentWorkflow(project, topology, null);
const taskFor = (snapshot, extra = {}) => deriveDeploymentTask({ project, topology, workflow, draft: { mapSource: "pcd", projection: snapshot, ...extra } });
const deferred = () => { let resolve; const promise = new Promise((done) => { resolve = done; }); return { promise, resolve }; };

function wheelForm() {
  const elements = new Map();
  return { getElementById(id) {
    if (!elements.has(id)) elements.set(id, {
      handlers: {}, options: {}, value: '0.20', disabled: false,
      setAttribute() {}, removeAttribute() {},
      addEventListener(event, handler, options) { this.handlers[event] = handler; this.options[event] = options; },
      stepUp(direction) { this.value = direction > 0 ? '0.21' : '0.19'; },
    });
    return elements.get(id);
  } };
}

test('hover wheel adjusts either height slider through the existing parameter update', async () => {
  const { bindPcdImportUI } = await import('../../../autodrive_console/web/deployment/pcd-import.js');
  for (const [id, key] of [['pcdZMinRange', 'z_min'], ['pcdZMaxRange', 'z_max']]) {
    for (const [deltaY, expected] of [[-120, .21], [120, .19], [-1, .21], [1, .19]]) {
      const root = wheelForm(), updates = [];
      bindPcdImportUI({ root, controller: { setParameters: value => updates.push(value) } });
      const range = root.getElementById(id);
      let prevented = false, stopped = false;
      assert.equal(range.options.wheel.passive, false);
      range.handlers.wheel({ deltaY, preventDefault() { prevented = true; }, stopPropagation() { stopped = true; } });
      assert.deepEqual(updates, [{ [key]: expected }]);
      assert.equal(prevented, true);
      assert.equal(stopped, true);
    }
  }
});

test('wheel preserves browser zoom and page scrolling outside editable vertical slider input', async () => {
  const { bindPcdImportUI } = await import('../../../autodrive_console/web/deployment/pcd-import.js');
  const root = wheelForm(), updates = [];
  bindPcdImportUI({ root, controller: { setParameters: value => updates.push(value) } });
  const range = root.getElementById('pcdZMinRange');
  for (const [disabled, event] of [[true, {deltaY: -120}], [false, {deltaY: -120, ctrlKey: true}], [false, {deltaY: 0}]]) {
    range.disabled = disabled;
    range.handlers.wheel({ ...event, preventDefault() { assert.fail('scroll or zoom intercepted'); }, stopPropagation() { assert.fail('event intercepted'); } });
  }
  assert.deepEqual(updates, []);
  range.stepUp = () => {};
  range.handlers.wheel({ deltaY: -120, preventDefault() {}, stopPropagation() {} });
  assert.deepEqual(updates, [], 'a slider at its limit does not invalidate the preview');
});

async function controller(options = {}) {
  const { createPcdImportController } = await import("../../../autodrive_console/web/deployment/pcd-import.js");
  return createPcdImportController({ request: async () => ({ projection: projection() }), setTimer: () => 1, clearTimer: () => {}, ...options });
}

test('new PCD conversions default to isolated-cell cleanup with single-point density', async()=>{
  const ui=await controller();
  assert.equal(ui.view.parameters.denoise,true);
  assert.equal(ui.view.parameters.min_points,1);
});

const largeAnalysis = { bounds: { x: [-111.524, 62.436], y: [-248.758, 252.082], z: [-3.496, 66.151] } };

test("manual resolution defaults to .05 and is submitted without being silently changed", async () => {
  const calls = [];
  const ui = await controller({ request: async (url, options) => {
    calls.push({ url, options });
    return { projection: projection(url.endsWith('/preview') ? 'processing' : 'awaiting_parameters', { analysis: largeAnalysis }) };
  } });
  await ui.loadProject("site-1");
  assert.equal(ui.view.canPreview, true);
  assert.equal(ui.view.parameters.resolution, .05);
  assert.equal(ui.view.parameterError, '');
  ui.setParameters({ z_min: 2.36, z_max: 10.49, resolution: .5, min_points: 8 });
  assert.equal(ui.view.parameters.resolution, .5, 'operator-selected precision stays unchanged');
  await ui.preview();
  const submitted = JSON.parse(calls.at(-1).options.body);
  assert.deepEqual(submitted, { ...parameters, z_min: 2.36, z_max: 10.49, resolution: .5 });
});

test('new preview preserves single-point details even when restoring an older density filter', async () => {
  let submitted;
  const ui = await controller({ request: async (url, options) => {
    if (url.endsWith('/preview')) submitted = JSON.parse(options.body);
    return { projection: projection(url.endsWith('/preview') ? 'processing' : 'ready', {
      parameters: {...parameters, min_points: 8}, analysis: largeAnalysis,
    }) };
  } });
  await ui.loadProject('site-1');
  ui.markPreviewLoaded(ui.view.previewUrl);
  assert.equal(ui.view.canConfirm, true, 'existing saved preview stays readable');
  await ui.preview();
  assert.equal(submitted.min_points, 1);
  assert.equal(submitted.resolution, .05);
});

test('conversion progress uses server stages and stops showing on failure or cancellation', async () => {
  const { pcdProcessingProgress } = await import('../../../autodrive_console/web/deployment/pcd-import.js');
  assert.deepEqual(pcdProcessingProgress({state:'processing', progress:45, message:'正在生成地图栅格。'}), {visible:true, value:45, text:'正在生成地图栅格。 · 45%'});
  assert.deepEqual(pcdProcessingProgress(null, 'preview'), {visible:true, value:null, text:'正在提交转换，请稍候…'});
  for (const state of ['failed','ready','cancelled','interrupted']) assert.equal(pcdProcessingProgress({state,progress:100}).visible, false);
  const ui = await controller({request:async()=>({projection:projection('processing',{progress:45,message:'正在生成地图栅格。'})})});
  await ui.loadProject('site-1');
  assert.match(ui.view.previewMessage, /生成地图栅格.*45%/);
});

test('conversion polls frequently enough to show intermediate stages and backs off on errors', async () => {
  const delays = [];
  let tick;
  let failed = false;
  const ui = await controller({ setTimer: (fn, delay) => { tick = fn; delays.push(delay); return 1; }, request: async () => {
    if (failed) throw Error('连接暂时中断');
    return {projection:projection('processing',{progress:35,message:'正在生成地图栅格。'})};
  } });
  await ui.loadProject('site-1');
  assert.equal(delays.at(-1), 250);
  failed = true;
  await tick();
  assert.ok(delays.at(-1) >= 1000);
});

test('automatic precision uses the finest millimeter step allowed by cell and side limits', async () => {
  const { automaticPcdResolution } = await import('../../../autodrive_console/web/deployment/pcd-import.js');
  for (const [x, y, expected] of [[1,1,.001], [10,10,.003], [174,501,.074], [40,0,.003]]) {
    const analysis = { bounds: { x: [-10, x-10], y: [20, y+20] } };
    const resolution = automaticPcdResolution(analysis);
    assert.equal(resolution, expected);
    const fits = r => {
      const w = Math.ceil(x/r)+1, h = Math.ceil(y/r)+1;
      return Math.max(w,h) <= 16384 && w*h <= 16000000;
    };
    assert.equal(fits(resolution), true);
    if(resolution > .001) assert.equal(fits(resolution-.001), false);
  }
  assert.equal(automaticPcdResolution({ bounds: { z: [0,1] } }), null);
});

test('restored ready preview retains its actual precision on regeneration', async () => {
  const ui = await controller({ request: async url => ({ projection: projection(url.endsWith('/preview')?'processing':'ready', { analysis:largeAnalysis, parameters:{...parameters,resolution:.1} }) }) });
  await ui.loadProject('site-1');
  ui.markPreviewLoaded(ui.view.previewUrl);
  assert.equal(ui.view.canConfirm, true);
  assert.equal(ui.view.parameters.resolution, .1);
  await ui.preview();
  assert.equal(ui.view.parameters.resolution, .1);
  assert.equal(ui.view.parameters.z_min, .2);
  assert.equal(ui.view.parameters.z_max, 1.8);
});

test('oversized jobs explain the budget without silently coarsening the operator setting', async () => {
  const ui = await controller({ request: async url => ({ projection: projection('failed', {
    analysis: url.includes('site-1') ? largeAnalysis : {bounds:{x:[0,10],y:[0,10],z:[0,2]}},
    message: '栅格超过 1600 万格限制，请增大分辨率',
  }) }) });
  await ui.loadProject('site-1');
  assert.equal(ui.view.parameters.resolution, .05);
  assert.equal(ui.view.canPreview, true);
  assert.match(ui.view.previewMessage, /0.074/);
  assert.match(ui.view.previewMessage, /分辨率/);
  await ui.loadProject('site-2');
  assert.equal(ui.view.parameters.resolution, .05);
});

test("background projection failure remains visible in empty preview and can recover", async () => {
  let poll;
  let ready = false;
  const ui = await controller({ setTimer: (fn) => { poll = fn; return 1; }, request: async (url) => {
    if (url.endsWith('/latest')) return { projection: projection('awaiting_parameters') };
    if (url.endsWith('/preview')) return { projection: projection('processing') };
    return { projection: projection(ready ? 'ready' : 'failed', { message: ready ? '预览已就绪' : '栅格超过 1600 万格限制，请增大分辨率' }) };
  } });
  await ui.loadProject('site-1');
  await ui.preview();
  assert.match(ui.view.previewMessage, /生成/);
  await poll();
  assert.equal(ui.view.previewIsError, true);
  assert.match(ui.view.previewMessage, /1600 万/);
  assert.equal(ui.view.canConfirm, false);
  ready = true;
  await ui.preview();
  assert.equal(ui.view.previewIsError, false);
  await poll();
  ui.markPreviewLoaded(ui.view.previewUrl);
  assert.equal(ui.view.imageReady, true);
  assert.equal(ui.view.previewIsError, false);
});

test("PCD keeps the guided import task while analyzing and processing", () => {
  for (const state of ["analyzing", "processing"]) {
    const task = taskFor(projection(state));
    assert.equal(task.id, "maps.import");
    assert.equal(task.primaryAction.disabled, true);
    assert.notEqual(task.primaryAction.id, "confirm-pcd");
  }
});

test("PCD ready preview requires unchanged parameters before guided confirmation", () => {
  assert.equal(taskFor(projection()).primaryAction.id, "confirm-pcd");
  assert.equal(taskFor(projection(), { projectionStale: true }).primaryAction.id, "preview-pcd");
  assert.equal(taskFor(projection("failed")).id, "maps.import");
});

test("PCD source survives storage without persisting server-owned results", () => {
  let value;
  const store = { setItem: (_key, next) => { value = next; }, getItem: () => value };
  writeDeploymentSession(store, { projectId: "site-1", deploymentTaskDraft: { mapSource: "pcd", projection: projection() } });
  assert.equal(readDeploymentSession(store).deploymentTaskDraft.mapSource, "pcd");
  assert.doesNotMatch(value, /cloud-1|revision|parameters/);
});

test("parameter edits invalidate ready preview and prevent confirm HTTP request", async () => {
  const requests = [];
  const ui = await controller({ request: async (url) => { requests.push(url); return { projection: projection() }; } });
  await ui.loadProject("site-1");
  ui.markPreviewLoaded(ui.view.previewUrl);
  assert.equal(ui.view.canConfirm, true);
  ui.setParameters({ z_max: 2.1 });
  assert.equal(ui.view.canConfirm, false);
  assert.equal(ui.view.stale, true);
  await ui.confirm("大厅");
  assert.equal(requests.length, 1);
  ui.setParameters({ z_max: 1.8 });
  ui.markPreviewLoaded(ui.view.previewUrl);
  assert.equal(ui.view.canConfirm, true);
});

test("late project restore cannot replace a newer project's projection", async () => {
  const old = deferred();
  const ui = await controller({ request: (url) => url.includes("site-1") ? old.promise : Promise.resolve({ projection: projection("awaiting_parameters", { project_id: "site-2", id: "cloud-2" }) }) });
  const pending = ui.loadProject("site-1");
  await ui.loadProject("site-2");
  old.resolve({ projection: projection() });
  await pending;
  assert.equal(ui.view.projection.id, "cloud-2");
  assert.equal(ui.view.projectId, "site-2");
});

test("preview is single-flight and confirmation uses its current revision", async () => {
  const preview = deferred();
  const requests = [];
  const imported = [];
  const ui = await controller({ request: async (url, options) => {
    requests.push({ url, options });
    if (url.endsWith("/preview")) return preview.promise;
    if (url.endsWith("/confirm")) return { map: { id: "map-1" }, project };
    return { projection: projection("awaiting_parameters") };
  }, onImported: (result) => imported.push(result) });
  await ui.loadProject("site-1");
  const first = ui.preview();
  await ui.preview();
  assert.equal(requests.filter((item) => item.url.endsWith("/preview")).length, 1);
  assert.equal(ui.view.canConfirm, false);
  preview.resolve({ projection: projection("ready", { revision: 3 }) });
  await first;
  const previewUrl = new URL(ui.view.previewUrl, "http://localhost");
  assert.equal(previewUrl.searchParams.get("revision"), "3");
  assert.equal(previewUrl.searchParams.get("display"), "monochrome");
  ui.markPreviewLoaded(ui.view.previewUrl);
  await ui.confirm("大厅");
  const body = JSON.parse(requests.at(-1).options.body);
  assert.deepEqual(body, { label: "大厅", revision: 3 });
  assert.equal(imported.length, 1);
});

test("failed poll backs off and dispose prevents late updates and clears timers", async () => {
  const timers = [];
  const cleared = [];
  const changes = [];
  let calls = 0;
  const ui = await controller({ request: async () => { if (++calls > 1) throw Error("连接中断"); return { projection: projection("analyzing") }; }, setTimer: (fn, delay) => { timers.push({ fn, delay }); return timers.length; }, clearTimer: (id) => cleared.push(id), onChange: (view) => changes.push(view) });
  await ui.loadProject("site-1");
  await timers[0].fn();
  assert.ok(timers[1].delay > timers[0].delay);
  ui.dispose();
  assert.ok(cleared.length);
  const count = changes.length;
  await timers[1].fn();
  assert.equal(changes.length, count);
});

test("cancelled jobs cannot preview, while interrupted jobs with analysis can retry", async () => {
  for (const [state, expected] of [["cancelled", false], ["interrupted", true]]) {
    const ui = await controller({ request: async () => ({ projection: projection(state) }) });
    await ui.loadProject("site-1");
    assert.equal(ui.view.canPreview, expected);
    assert.equal(ui.view.canConfirm, false);
  }
  assert.equal(taskFor(projection("cancelled")).primaryAction.id, "select-pcd");
  assert.equal(taskFor(projection("interrupted")).primaryAction.id, "preview-pcd");
  assert.equal(taskFor(projection("interrupted", { analysis: null })).primaryAction.id, "select-pcd");
});

test("choosing a replacement source invalidates the previous ready preview", async () => {
  const ui = await controller();
  await ui.loadProject("site-1");
  ui.selectFile({ name: "replacement.pcd" });
  assert.equal(ui.view.canConfirm, false);
  assert.equal(ui.view.canPreview, false);
  assert.equal(ui.view.canUpload, true);
  assert.equal(ui.view.previewUrl, null);
  assert.equal(taskFor(projection(), { projectionStale: true, projectionHasFile: true }).primaryAction.id, "upload-pcd");
});

test("uncertain preview submission cannot re-enable an old ready result", async () => {
  const ui = await controller({ request: async (url) => {
    if (url.endsWith("/preview")) throw Error("连接中断");
    return { projection: projection() };
  } });
  await ui.loadProject("site-1");
  ui.markPreviewLoaded(ui.view.previewUrl);
  await ui.preview();
  assert.equal(ui.view.canConfirm, false);
  assert.equal(ui.view.needsRestore, true);
  ui.setParameters({ z_max: 1.8 });
  assert.equal(ui.view.canConfirm, false);
  await ui.loadProject("site-1");
  ui.markPreviewLoaded(ui.view.previewUrl);
  assert.equal(ui.view.canConfirm, true);
});

test("only the successfully loaded current preview can be confirmed", async () => {
  let revision = 2;
  const changes = [];
  const ui = await controller({ request: async () => ({ projection: projection("ready", { revision }) }), onChange: (view) => changes.push(view) });
  await ui.loadProject("site-1");
  const originalUrl = ui.view.previewUrl;
  assert.equal(ui.view.canConfirm, false);
  ui.markPreviewLoaded(originalUrl);
  assert.equal(ui.view.canConfirm, true);
  assert.equal(changes.at(-1).imageReady, true);
  ui.setParameters({ z_max: 2 });
  assert.equal(ui.view.canConfirm, false);
  ui.setParameters({ z_max: 1.8 });
  assert.equal(ui.view.canConfirm, false);
  revision = 3;
  await ui.preview();
  const currentUrl = ui.view.previewUrl;
  ui.markPreviewLoaded(originalUrl);
  assert.equal(ui.view.canConfirm, false);
  ui.markPreviewLoaded(currentUrl);
  assert.equal(ui.view.canConfirm, true);
  ui.markPreviewFailed(currentUrl);
  assert.equal(ui.view.canConfirm, false);
  await ui.loadProject("site-2");
  ui.markPreviewLoaded(currentUrl);
  assert.equal(ui.view.canConfirm, false);
});

test("an import continuation can detect project navigation after its own await", async () => {
  const continuation = deferred();
  const entered = deferred();
  const completed = [];
  const ui = await controller({ request: async (url) => url.endsWith("/confirm") ? { map: { id: "map-1" }, project } : { projection: projection() }, onImported: async (_data, context) => {
    entered.resolve();
    await continuation.promise;
    if (context.isCurrent()) completed.push("saved");
  } });
  await ui.loadProject("site-1");
  ui.markPreviewLoaded(ui.view.previewUrl);
  const saving = ui.confirm("大厅");
  await entered.promise;
  await ui.loadProject("site-2");
  continuation.resolve();
  await saving;
  assert.deepEqual(completed, []);
});

test("capturing a native file clears the picker so the same PCD can be selected again", async () => {
  const { bindPcdImportUI } = await import("../../../autodrive_console/web/deployment/pcd-import.js");
  const elements = new Map();
  const selected = [];
  const root = { getElementById(id) {
    if (!elements.has(id)) elements.set(id, { handlers: {}, value: "", attributes: {}, setAttribute(name, value) { this.attributes[name] = value; }, removeAttribute(name) { delete this.attributes[name]; }, addEventListener(event, handler) { this.handlers[event] = handler; } });
    return elements.get(id);
  } };
  bindPcdImportUI({ root, controller: { selectFile: (file) => selected.push(file) } });
  const picker = root.getElementById("pcdFile");
  const file = { name: "same.pcd" };
  picker.files = [file];
  picker.value = "C:\\fakepath\\same.pcd";
  picker.handlers.change();
  assert.equal(selected[0], file);
  assert.equal(picker.value, "");
});

test("uncertain submission guides the user to restore server state", () => {
  const task = taskFor(projection(), { projectionNeedsRestore: true });
  assert.equal(task.primaryAction.id, "restore-pcd");
  assert.equal(task.id, "maps.import");
});

test("late topology reads cannot modify a different project or a new-project draft", async () => {
  const source = readFileSync(new URL("../../../autodrive_console/web/deployment.js", import.meta.url), "utf8");
  const functionSource = source.slice(source.indexOf("async function refreshTopology()"), source.indexOf("function renderMappingStatus()"));
  for (const navigating of ["project", "draft"]) {
    const response = deferred();
    const renders = [];
    const context = {
      selectedProject: { id: "site-1" }, topology: null, creatingAnotherProject: false, deploymentProjectGeneration: 1,
      request: () => response.promise,
      renderMapStages: () => renders.push("stages"), renderTopology: () => renders.push("topology"),
      renderDeploymentGuide: () => renders.push("guide"), drawMap: () => renders.push("map"), note: () => {},
    };
    const refresh = runInNewContext(`${functionSource}; refreshTopology;`, context);
    const pending = refresh();
    if (navigating === "project") context.selectedProject = { id: "site-2" };
    else context.creatingAnotherProject = true;
    context.deploymentProjectGeneration += 1;
    response.resolve({ topology: { stages: ["old-project-stage"] } });
    await pending;
    assert.equal(context.topology, null);
    assert.deepEqual(renders, []);
  }
});

test("restoring a lost successful confirmation refreshes the imported map exactly once", async () => {
  let imported = false;
  const recovered = [];
  const savedMap = { id: "map-1", label: "大厅" };
  const savedProject = { ...project, map_assets: [savedMap] };
  const ui = await controller({ request: async (url) => {
    if (url.endsWith("/confirm")) { imported = true; throw Error("response lost"); }
    if (url.endsWith("/latest")) return { projection: imported ? projection("imported", { map_asset_id: savedMap.id }) : projection() };
    if (url.endsWith("/site-1")) return { project: savedProject };
    throw Error(`unexpected ${url}`);
  }, onImported: (result, context) => {
    assert.equal(context.isCurrent(), true);
    recovered.push(result);
  } });
  await ui.loadProject("site-1");
  ui.markPreviewLoaded(ui.view.previewUrl);
  await ui.confirm("大厅");
  assert.equal(ui.view.needsRestore, true);
  await ui.loadProject("site-1");
  assert.equal(recovered.length, 1);
  assert.deepEqual(recovered[0], { map: savedMap, project: savedProject });
  assert.equal(ui.view.projection, null);
  assert.equal(ui.view.needsRestore, false);
  await ui.loadProject("site-1");
  assert.equal(recovered.length, 1);
});

test("late imported-project recovery cannot replace the current project", async () => {
  const oldProject = deferred();
  const recovered = [];
  const ui = await controller({ request: async (url) => {
    if (url.endsWith("/site-1")) return oldProject.promise;
    if (url.includes("site-1")) return { projection: projection("imported", { map_asset_id: "map-1" }) };
    return { projection: null };
  }, onImported: (result) => recovered.push(result) });
  const reading = ui.loadProject("site-1");
  await new Promise((resolve) => setImmediate(resolve));
  await ui.loadProject("site-2");
  oldProject.resolve({ project: { ...project, map_assets: [{ id: "map-1" }] } });
  await reading;
  assert.deepEqual(recovered, []);
  assert.equal(ui.view.projectId, "site-2");
});

test("source viewer is available after analysis before a 2D preview and safely encodes the selection", async () => {
  const ui = await controller({ request: async () => ({ projection: projection("awaiting_parameters", { id: "cloud / 1?", parameters: null }) }) });
  await ui.loadProject("site / 1&");
  assert.equal(ui.view.previewUrl, null);
  const url = new URL(ui.view.sourceViewerUrl, "http://localhost");
  assert.equal(url.pathname, "/vue/pcd-viewer.html");
  assert.equal(url.searchParams.get("project"), "site / 1&");
  assert.equal(url.searchParams.get("projection"), "cloud / 1?");
  assert.equal(url.searchParams.get("z_min"), "0.2");
  ui.setParameters({ z_max: 2.2 });
  assert.equal(new URL(ui.view.sourceViewerUrl, "http://localhost").searchParams.get("z_max"), "2.2");
  ui.selectFile({ name: "replacement.pcd" });
  assert.equal(ui.view.sourceViewerUrl, null);
  await ui.loadProject(null);
  assert.equal(ui.view.sourceViewerUrl, null);
});

test("height histogram uses real bin widths and keeps typography outside stretched geometry", async () => {
  const { pcdHistogramMarkup, histogramBin } = await import("../../../autodrive_console/web/deployment/pcd-import.js");
  const analysis = { z_histogram: { edges: [-1, 0, 2], counts: [4, 12] } };
  const markup = pcdHistogramMarkup(analysis, { z_min: 0.2, z_max: 1.5 });
  assert.doesNotMatch(markup, /preserveAspectRatio="none"|<text\b/);
  assert.match(markup, /pcd-histogram-boundary/);
  assert.match(markup, /data-histogram-bin="1"/);
  assert.deepEqual(histogramBin(analysis, 1), { z_min: 0, z_max: 2, count: 12 });
});
