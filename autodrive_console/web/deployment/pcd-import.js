import { bindEmbeddedSource } from "./embedded-source.js";
import { bindPreviewViewport } from "./preview-viewport.js";
import { bindRasterPreview } from "./raster-preview.js";
import { bindTrajectoryPreview } from "./trajectory-preview.js";

const ACTIVE_STATES = new Set(["analyzing", "processing"]);
const PARAMETER_KEYS = ["z_min", "z_max", "resolution", "min_points", "denoise"];
const DEFAULT_PARAMETERS = { z_min: 0.2, z_max: 1.8, resolution: 0.05, min_points: 1, denoise: true };

function sameParameters(left, right) {
  return PARAMETER_KEYS.every((key) => left?.[key] === right?.[key]);
}

export function pcdParameterError(parameters) {
  if (![parameters.z_min, parameters.z_max, parameters.resolution, parameters.min_points].every(Number.isFinite)) return "请填写有效的数值。";
  if (parameters.z_min >= parameters.z_max) return "高度下限必须小于高度上限。";
  if (parameters.resolution <= 0) return "分辨率必须大于零。";
  if (!Number.isInteger(parameters.min_points) || parameters.min_points < 1) return "每格最少点数必须是大于零的整数。";
  return "";
}

/** Finest millimeter step fitting the existing bounded Backend raster budget. */
export function automaticPcdResolution(analysis) {
  const bounds = [analysis?.bounds?.x, analysis?.bounds?.y];
  if (!bounds.every((pair) => Array.isArray(pair) && pair.length === 2 && pair.every(Number.isFinite) && pair[0] <= pair[1])) return null;
  const spans = bounds.map(([low, high]) => high - low);
  if (!spans.every(Number.isFinite)) return null;
  // Allow the extra cell from aligning the full world XY extent to its origin.
  const dimensions = (size) => spans.map((span) => Math.ceil(span / size) + 1);
  const fits = (dims) => Math.max(...dims) <= 16384 && dims[0] * dims[1] <= 16000000;
  const minimum = Math.max(Math.sqrt(spans[0] / 16000000) * Math.sqrt(spans[1]), ...spans.map((span) => span / 16383));
  let millimeters = Math.max(1, Math.ceil(minimum * 1000));
  if (!Number.isSafeInteger(millimeters)) return null;
  if (!fits(dimensions(millimeters / 1000))) {
    let upper = Math.min(Number.MAX_SAFE_INTEGER, Math.max(millimeters + 1, millimeters * 2));
    if (!fits(dimensions(upper / 1000))) return null;
    while (millimeters < upper) {
      const middle = millimeters + Math.floor((upper - millimeters) / 2);
      if (fits(dimensions(middle / 1000))) upper = middle;
      else millimeters = middle + 1;
    }
  }
  return millimeters / 1000;
}

export function pcdProcessingProgress(projection, pending) {
  const processing = projection?.state === 'processing' && pending !== 'preview';
  const value = processing && Number.isFinite(projection.progress) && projection.progress > 0
    ? Math.min(99, Math.floor(projection.progress)) : null;
  return {
    visible: processing || pending === 'preview', value,
    text: processing ? `${projection.message || '正在生成二维地图预览…'}${value === null ? '' : ` · ${value}%`}`
      : '正在提交转换，请稍候…',
  };
}

/** Project-scoped offline import. Server snapshots remain the only job authority. */
export function createPcdImportController({ request, onChange = () => {}, onImported = () => {}, setTimer = globalThis.setTimeout, clearTimer = globalThis.clearTimeout } = {}) {
  let projectId = null;
  let projection = null;
  let parameters = { ...DEFAULT_PARAMETERS };
  let file = null;
  let pending = null;
  let error = "";
  let needsRestore = false;
  let loadedPreviewUrl = null;
  let failedPreviewUrl = null;
  let epoch = 0;
  let timer = null;
  let pollDelay = 1000;
  let disposed = false;
  const requests = new Set();
  const completedImports = new Set();
  const base = () => `/api/deployments/${encodeURIComponent(projectId)}/map-projections`;
  const path = () => `${base()}/${encodeURIComponent(projection.id)}`;
  const current = (generation) => !disposed && generation === epoch;
  function view() {
    const active = ACTIVE_STATES.has(projection?.state);
    const stale = Boolean(file || (projection && !sameParameters(parameters, projection.parameters)));
    const numericParameterError = pcdParameterError(parameters);
    const parameterError = numericParameterError;
    const previewUrl = projection?.state === "ready" && !stale && !needsRestore ? `${path()}/preview.png?revision=${encodeURIComponent(projection.revision)}&display=monochrome` : null;
    const sourceViewerUrl = projection?.analysis && !file && !pending && !needsRestore && !numericParameterError && !["cancelled", "imported"].includes(projection.state)
      ? `/vue/pcd-viewer.html?${new URLSearchParams({ project: projectId, projection: projection.id, z_min: String(parameters.z_min), z_max: String(parameters.z_max) })}` : null;
    const imageReady = Boolean(previewUrl && previewUrl === loadedPreviewUrl);
    const previewError = Boolean(previewUrl && failedPreviewUrl === previewUrl);
    const conversionFailure = ["failed", "interrupted"].includes(projection?.state)
      ? /栅格超过|地图边长超过/.test(projection.message || '') && automaticPcdResolution(projection.analysis)
        ? `${projection.message}；完整地图建议尝试 ${automaticPcdResolution(projection.analysis)} 米/格，参数由你确认后调整。`
        : projection.message || "处理未完成，请检查参数后重新生成预览。" : "";
    const previewIsError = !active && pending !== "preview" && Boolean(error || parameterError || conversionFailure || previewError);
    const processingProgress = pcdProcessingProgress(projection, pending);
    const previewMessage = processingProgress.visible ? processingProgress.text : active ? "正在分析点云，请稍候…"
      : error || parameterError || conversionFailure || (previewError ? "预览图片读取失败，请重新生成预览后检查。"
        : previewUrl && !imageReady ? "正在读取当前地图预览…"
          : stale ? "参数或源文件已更改，请重新生成预览后确认。" : "调整参数并生成预览，检查障碍轮廓与通道。");
    return {
      projectId, projection, parameters: { ...parameters }, file, pending, error, stale, parameterError, needsRestore, imageReady,
      previewError, previewIsError, previewMessage, processingProgress,
      canUpload: Boolean(projectId && file && !pending && !active && !needsRestore),
      canEdit: Boolean(projection?.analysis && !pending && !active && !["imported", "cancelled"].includes(projection.state)),
      canPreview: Boolean(projection?.analysis && !file && !pending && !active && !parameterError && !needsRestore && !["imported", "cancelled"].includes(projection.state)),
      canConfirm: Boolean(projection?.state === "ready" && !pending && !stale && !parameterError && imageReady && !needsRestore),
      previewUrl,
      sourceViewerUrl,
    };
  }
  const emit = () => { if (!disposed) onChange(view()); };
  function stopPolling() {
    if (timer !== null) clearTimer(timer);
    timer = null;
  }
  function invalidate() {
    epoch += 1;
    stopPolling();
    for (const controller of requests) controller.abort();
    requests.clear();
  }
  async function send(url, options = {}) {
    const abort = new AbortController();
    requests.add(abort);
    try { return await request(url, { ...options, signal: abort.signal }); }
    finally { requests.delete(abort); }
  }
  function adopt(snapshot, resetParameters = false) {
    if (projection?.id !== snapshot?.id || projection?.revision !== snapshot?.revision || projection?.state !== snapshot?.state) {
      loadedPreviewUrl = null;
      failedPreviewUrl = null;
    }
    projection = snapshot?.state === "imported" ? null : snapshot;
    if (resetParameters) {
      const candidate = projection?.analysis?.candidates?.[0];
      parameters = { ...DEFAULT_PARAMETERS, ...(candidate ? { z_min: candidate.z_min, z_max: candidate.z_max } : {}), ...(projection?.parameters || {}) };
    }
    error = "";
  }
  function schedulePoll() {
    stopPolling();
    if (disposed || pending || !ACTIVE_STATES.has(projection?.state)) return;
    const generation = epoch;
    const url = path();
    timer = setTimer(async () => {
      timer = null;
      if (!current(generation)) return;
      try {
        const data = await send(url);
        if (!current(generation)) return;
        const firstAnalysis = !projection?.analysis && Boolean(data.projection?.analysis);
        adopt(data.projection, firstAnalysis);
        pollDelay = 1000;
      } catch (failure) {
        if (!current(generation)) return;
        error = `${failure.message}；正在重试读取进度。`;
        pollDelay = Math.min(pollDelay * 2, 15000);
      }
      emit();
      schedulePoll();
    }, projection?.state === 'processing' && pollDelay === 1000 ? 250 : pollDelay);
  }
  async function mutate(action, options, apply) {
    if (disposed || pending || !projectId) return;
    invalidate();
    const generation = epoch;
    const url = action === "upload" ? base() : `${path()}${action === "cancel" ? "" : `/${action}`}`;
    pending = action;
    error = "";
    emit();
    try {
      const data = await send(url, options);
      if (!current(generation)) return;
      await apply(data, { isCurrent: () => current(generation) });
      return data;
    } catch (failure) {
      if (current(generation)) {
        error = failure.message;
        // A lost response can hide an accepted mutation. Read server authority
        // again before allowing an old revision to be used.
        needsRestore = !failure.status || failure.status >= 500 || failure.status === 409;
        if (needsRestore) loadedPreviewUrl = null;
      }
    } finally {
      if (current(generation)) {
        pending = null;
        emit();
        schedulePoll();
      }
    }
  }
  return {
    get view() { return view(); },
    async loadProject(id) {
      invalidate();
      disposed = false;
      projectId = id || null;
      projection = null;
      file = null;
      parameters = { ...DEFAULT_PARAMETERS };
      error = "";
      needsRestore = false;
      loadedPreviewUrl = null;
      failedPreviewUrl = null;
      pending = projectId ? "restore" : null;
      pollDelay = 1000;
      emit();
      if (!projectId) return;
      const generation = epoch;
      try {
        const data = await send(`${base()}/latest`);
        if (!current(generation)) return;
        adopt(data.projection, true);
        if (data.projection?.state === "imported") {
          const key = `${projectId}/${data.projection.id}`;
          if (!completedImports.has(key)) {
            const restored = await send(`/api/deployments/${encodeURIComponent(projectId)}`);
            if (!current(generation)) return;
            const map = restored.project?.map_assets?.find((item) => item.id === data.projection.map_asset_id);
            if (!map) throw new Error("已导入地图暂时无法读取，请重新读取项目。");
            await onImported({ map, project: restored.project }, { isCurrent: () => current(generation), restored: true });
            if (current(generation)) completedImports.add(key);
          }
        }
      } catch (failure) {
        if (current(generation)) { error = `${failure.message}；请重新读取项目中的转换状态。`; needsRestore = true; }
      } finally {
        if (current(generation)) { pending = null; emit(); schedulePoll(); }
      }
    },
    selectFile(next) {
      if (pending || ACTIVE_STATES.has(projection?.state)) return;
      file = next || null;
      error = file && !/\.pcd$/i.test(file.name) ? "请选择 .pcd 点云文件。" : "";
      if (error) file = null;
      emit();
    },
    setParameters(changes) {
      if (!view().canEdit) return;
      const next = { ...parameters, ...Object.fromEntries(Object.entries(changes).filter(([key]) => ['z_min', 'z_max', 'resolution', 'denoise'].includes(key))) };
      if (!sameParameters(parameters, next)) {
        next.min_points = 1;
      }
      if (!sameParameters(parameters, next)) { loadedPreviewUrl = null; failedPreviewUrl = null; }
      parameters = next;
      error = "";
      emit();
    },
    markPreviewLoaded(url) {
      if (disposed || !url || url !== view().previewUrl || loadedPreviewUrl === url) return;
      loadedPreviewUrl = url;
      failedPreviewUrl = null;
      emit();
    },
    markPreviewFailed(url) {
      if (disposed || !url || url !== view().previewUrl || failedPreviewUrl === url) return;
      loadedPreviewUrl = null;
      failedPreviewUrl = url;
      emit();
    },
    async upload() {
      if (!view().canUpload) return;
      const body = new FormData();
      body.append("file", file, file.name);
      return mutate("upload", { method: "POST", body }, (data) => { file = null; adopt(data.projection, true); });
    },
    async preview() {
      if (!view().canPreview) return;
      const requested = { ...parameters, min_points: 1 };
      return mutate("preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(requested) }, (data) => { adopt(data.projection); parameters = requested; });
    },
    async confirm(label) {
      if (!view().canConfirm) return;
      if (!String(label || "").trim()) { error = "请先填写地图显示名称。"; emit(); return; }
      const key = `${projectId}/${projection.id}`;
      return mutate("confirm", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ label: String(label).trim(), revision: projection.revision }) }, async (data, context) => {
        projection = null;
        file = null;
        // Clear the old preview before the project callback advances the guide.
        emit();
        await onImported(data, context);
        if (context.isCurrent()) completedImports.add(key);
      });
    },
    async cancel() {
      if (!projection || pending) return;
      return mutate("cancel", { method: "DELETE" }, (data) => adopt(data.projection || { ...projection, state: "cancelled" }));
    },
    dispose() { invalidate(); disposed = true; },
  };
}

export function histogramBin(analysis, index) {
  const { edges = [], counts = [] } = analysis?.z_histogram || {};
  if (!Number.isInteger(index) || index < 0 || index >= counts.length || edges.length !== counts.length + 1) return null;
  return { z_min: edges[index], z_max: edges[index + 1], count: counts[index] };
}

export function pcdHistogramMarkup(analysis, parameters = {}) {
  const edges = analysis?.z_histogram?.edges || [];
  const counts = analysis?.z_histogram?.counts || [];
  if (!counts.length || edges.length !== counts.length + 1 || !edges.every((value, index) => Number.isFinite(value) && (!index || value > edges[index - 1])) || !counts.every((value) => Number.isFinite(value) && value >= 0)) return '<p class="page-muted">暂无可用高度分布；可根据现场坐标手动填写范围。</p>';
  const lower = edges[0];
  const upper = edges.at(-1);
  const span = upper - lower || 1;
  const peak = Math.max(1, ...counts);
  const x = (z) => Math.max(0, Math.min(1, (z - lower) / span)) * 600;
  const selection = Number.isFinite(parameters.z_min) && Number.isFinite(parameters.z_max)
    ? `<rect class="pcd-histogram-selection" x="${x(parameters.z_min)}" y="8" width="${Math.max(0, x(parameters.z_max) - x(parameters.z_min))}" height="104" /><path class="pcd-histogram-boundary" d="M${x(parameters.z_min)} 4V116 M${x(parameters.z_max)} 4V116" vector-effect="non-scaling-stroke" />` : "";
  const bars = counts.map((count, index) => {
    const height = count / peak * 104;
    const selected = edges[index + 1] >= parameters.z_min && edges[index] <= parameters.z_max;
    return `<rect class="pcd-histogram-bar${selected ? " selected" : ""}" data-histogram-bin="${index}" x="${x(edges[index])}" y="${112 - height}" width="${Math.max(.1, x(edges[index + 1]) - x(edges[index]) - 1)}" height="${height}" vector-effect="non-scaling-stroke"><title>${edges[index].toFixed(2)} 至 ${edges[index + 1].toFixed(2)} m：${count.toLocaleString("zh-CN")} 个点</title></rect>`;
  }).join("");
  return `<div class="pcd-histogram-y-axis" aria-hidden="true"><span>${peak.toLocaleString("zh-CN")}</span><span>0</span></div><div class="pcd-histogram-plot"><svg viewBox="0 0 600 120" preserveAspectRatio="xMidYMid meet" role="img" aria-label="点云高度分布，纵轴为点数，蓝色边界表示当前高度范围"><title>高度 ${lower.toFixed(2)} 至 ${upper.toFixed(2)} 米；最高区间 ${peak.toLocaleString("zh-CN")} 个点</title><path class="pcd-histogram-guide" d="M0 8H600 M0 112H600" vector-effect="non-scaling-stroke" />${selection}${bars}</svg><div class="pcd-histogram-x-axis" aria-hidden="true"><span>${lower.toFixed(2)} m</span><span>${((lower + upper) / 2).toFixed(2)} m</span><span>${upper.toFixed(2)} m</span></div></div>`;
}

/** Bind stable form controls; parameter updates never replace focused inputs. */
export function bindPcdImportUI({ root, controller, onLabelChange = () => {}, escapeHtml = String }) {
  const $ = (id) => root.getElementById(id);
  const controls = { z_min: "pcdZMin", z_max: "pcdZMax", resolution: "pcdResolution" };
  const states = { analyzing: "正在分析点云高度…", awaiting_parameters: "分析完成，请选择高度范围并生成预览。", processing: "正在生成二维地图预览…", ready: "预览已就绪，请检查后确认导入。", failed: "转换未完成，请检查原因后重试。", cancelled: "本次转换已取消，可以重新上传点云。", interrupted: "处理已中断，可以重新生成预览或上传点云。" };
  const pendingLabels = { restore: "正在读取项目中的点云转换…", upload: "正在上传点云…", preview: "正在提交预览参数…", confirm: "正在保存地图快照…", cancel: "正在取消转换…" };
  let candidateSignature = "";
  let displayedPreviewUrl = null;
  let inspectedBin = null;
  let histogramAnalysis = null;
  const raster = bindRasterPreview({ canvas: $("pcdRasterPreview"), document: root });
  const viewport = bindPreviewViewport({ surface: $("pcdPreviewViewport"), getImage: () => $("pcdPreviewImage"), zoomIn: $("pcdZoomIn"), zoomOut: $("pcdZoomOut"), fit: $("pcdFitPreview"), readout: $("pcdZoomReadout"), onRender: (view) => raster.setView(view) });
  const trajectory = bindTrajectoryPreview({ root, raster });
  root.defaultView?.addEventListener("pagehide", (event) => { if (!event.persisted) { viewport.dispose(); raster.dispose(); trajectory.dispose(); } });
  $("pcdPointRadius").addEventListener("input", () => {
    const input = $("pcdPointRadius");
    const radius = Number(input.value);
    const valid = input.value !== '' && Number.isFinite(radius) && radius >= .5 && radius <= 4;
    input.setAttribute('aria-invalid', String(!valid));
    $("pcdPointRadiusError").hidden = valid;
    $("pcdPointRadiusError").textContent = valid ? '' : '预览点半径请输入 0.5 至 4 像素。';
    if (valid) raster.setRadius(radius);
  });
  function showHistogramBin(index) {
    const bin = histogramBin(histogramAnalysis, index);
    if (!bin) return;
    inspectedBin = index;
    $("pcdHistogramReadout").textContent = `${bin.z_min.toFixed(2)} 至 ${bin.z_max.toFixed(2)} m · ${bin.count.toLocaleString("zh-CN")} 个点`;
  }
  $("pcdHistogram").addEventListener("pointerover", (event) => {
    const bin = event.target.closest?.("[data-histogram-bin]");
    if (bin) showHistogramBin(Number(bin.dataset.histogramBin));
  });
  $("pcdHistogram").addEventListener("focus", () => showHistogramBin(inspectedBin ?? 0));
  $("pcdHistogram").addEventListener("keydown", (event) => {
    const count = histogramAnalysis?.z_histogram?.counts?.length || 0;
    if (!count || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    const index = event.key === "Home" ? 0 : event.key === "End" ? count - 1 : Math.max(0, Math.min(count - 1, (inspectedBin ?? 0) + (event.key === "ArrowRight" ? 1 : -1)));
    showHistogramBin(index);
    event.preventDefault();
  });
  const embeddedSource = bindEmbeddedSource({ container: $("pcdPreviewWindow"), viewport: $("pcdPreviewViewport"), zoom: $("pcdMapTools"), button: $("pcdSourceViewer"), frame: $("pcdSourceFrame"), help: $("pcdPreviewHelp"), fullscreen: $("pcdSourceFullscreen") });
  const update = (key, input) => controller.setParameters({ [key]: input.value === "" ? NaN : Number(input.value) });
  for (const [key, id] of Object.entries(controls)) $(id).addEventListener("input", () => update(key, $(id)));
  for (const [key, id] of [["z_min", "pcdZMinRange"], ["z_max", "pcdZMaxRange"]]) {
    const range = $(id);
    range.addEventListener("input", () => update(key, range));
    range.addEventListener("wheel", (event) => {
      if (range.disabled || event.ctrlKey || !Number.isFinite(event.deltaY) || event.deltaY === 0) return;
      event.preventDefault();
      event.stopPropagation();
      const previous = range.value;
      // Native stepping honors the slider's precision and min/max bounds.
      range.stepUp(event.deltaY < 0 ? 1 : -1);
      if (range.value !== previous) update(key, range);
    }, { passive: false });
  }
  $("pcdDenoise").addEventListener("change", () => controller.setParameters({ denoise: $("pcdDenoise").checked }));
  $("pcdFile").addEventListener("change", () => {
    const file = $("pcdFile").files?.[0];
    $("pcdFile").value = "";
    controller.selectFile(file);
  });
  $("pcdUpload").addEventListener("click", () => controller.upload());
  $("pcdPreview").addEventListener("click", () => controller.preview());
  $("pcdConfirm").addEventListener("click", () => controller.confirm($("pcdMapLabel").value));
  $("pcdCancel").addEventListener("click", () => controller.cancel());
  $("pcdRestore").addEventListener("click", () => controller.loadProject(controller.view.projectId));
  $("pcdMapLabel").addEventListener("input", () => onLabelChange($("pcdMapLabel").value));
  $("pcdCandidates").addEventListener("click", (event) => {
    const target = event.target.closest("[data-pcd-candidate]");
    if (!target) return;
    const candidate = controller.view.projection?.analysis?.candidates?.[Number(target.dataset.pcdCandidate)];
    if (candidate) controller.setParameters({ z_min: candidate.z_min, z_max: candidate.z_max });
  });
  return {
    get previewFailed() { return controller.view.previewError; },
    render(view, { source, label = "" } = {}) {
      $("pcdImportControls").classList.toggle("deployment-hidden", source !== "pcd");
      const { projection, parameters, pending } = view;
      const analysis = projection?.analysis;
      const active = ACTIVE_STATES.has(projection?.state);
      $("pcdImportControls").setAttribute("aria-busy", String(Boolean(pending || active)));
      $("pcdUpload").disabled = !view.canUpload;
      $("pcdUpload").textContent = pending === "upload" ? "正在上传…" : "上传并分析";
      $("pcdFile").disabled = Boolean(pending || active);
      $("pcdFileHelp").textContent = view.file ? `已选择 ${view.file.name}，点击“上传并分析”继续。` : "上传一个 PCD 文件，保留原始 XY 坐标。分析完成后再设置高度范围。";
      const requiresUpload = ["failed", "interrupted"].includes(projection?.state) && !analysis;
      $("pcdStatus").textContent = view.error || pendingLabels[pending] || (requiresUpload ? `${projection.state === "interrupted" ? "高度分析已中断" : "高度分析未完成"}，请重新选择 PCD 文件并上传。` : ["failed", "interrupted"].includes(projection?.state) ? view.previewMessage : projection?.message || states[projection?.state]) || "请选择 PCD 文件。";
      $("pcdStatus").classList.toggle("is-error", Boolean(view.error || ["failed", "interrupted"].includes(projection?.state)));
      $("pcdRestore").hidden = !(view.needsRestore && !pending);
      $("pcdCancel").hidden = !projection || ["cancelled", "imported"].includes(projection.state);
      $("pcdCancel").disabled = Boolean(pending);
      $("pcdProgress").hidden = !active;
      $("pcdProgress").value = Math.max(0, Math.min(100, Number(projection?.progress) || 0));
      if (active && !projection?.progress) $("pcdProgress").removeAttribute('value');
      $("pcdAnalysis").hidden = !analysis;
      $("pcdPointSummary").textContent = analysis ? `${Number(analysis.finite_point_count || 0).toLocaleString("zh-CN")} 个有效点 · Z ${Number(analysis.bounds?.z?.[0] || 0).toFixed(2)} 至 ${Number(analysis.bounds?.z?.[1] || 0).toFixed(2)} m` : "";
      $("pcdHistogram").innerHTML = pcdHistogramMarkup(analysis, parameters);
      if (histogramAnalysis !== analysis) inspectedBin = null;
      histogramAnalysis = analysis;
      if (inspectedBin !== null) showHistogramBin(inspectedBin);
      else $("pcdHistogramReadout").textContent = "横轴：高度（m） · 纵轴：点数。指向柱线或使用左右方向键查看区间。";
      embeddedSource.render(source === "pcd" ? view.sourceViewerUrl : null);
      trajectory.render(view);
      const candidates = analysis?.candidates || [];
      const signature = JSON.stringify([projection?.id, candidates]);
      if (signature !== candidateSignature) {
        candidateSignature = signature;
        $("pcdCandidates").innerHTML = candidates.length ? candidates.map((item, index) => `<button class="compact-action" type="button" data-pcd-candidate="${index}" aria-pressed="false">${escapeHtml(item.label || `候选高度 ${index + 1}`)}<span>${Number(item.z_min).toFixed(2)} 至 ${Number(item.z_max).toFixed(2)} m</span></button>`).join("") : '<p class="page-muted">未识别到可靠候选，请手动填写高度上下限。</p>';
      }
      root.querySelectorAll("[data-pcd-candidate]").forEach((button) => {
        const candidate = candidates[Number(button.dataset.pcdCandidate)];
        button.disabled = !view.canEdit;
        button.setAttribute("aria-pressed", String(candidate?.z_min === parameters.z_min && candidate?.z_max === parameters.z_max));
      });
      $("pcdParameters").disabled = !view.canEdit;
      for (const [key, id] of Object.entries(controls)) {
        const input = $(id);
        if (root.activeElement !== input) input.value = Number.isFinite(parameters[key]) ? parameters[key] : "";
      }
      for (const [key, id] of [["z_min", "pcdZMinRange"], ["z_max", "pcdZMaxRange"]]) {
        const range = $(id);
        range.min = Math.min(analysis?.bounds?.z?.[0] ?? -1, Number.isFinite(parameters[key]) ? parameters[key] : 0);
        range.max = Math.max(analysis?.bounds?.z?.[1] ?? 3, Number.isFinite(parameters[key]) ? parameters[key] : 0, Number(range.min) + .01);
        range.value = Number.isFinite(parameters[key]) ? parameters[key] : range.min;
      }
      $("pcdDenoise").checked = Boolean(parameters.denoise);
      $("pcdParameterError").hidden = !view.parameterError;
      $("pcdParameterError").textContent = view.parameterError;
      $("pcdPreview").disabled = !view.canPreview;
      $("pcdPreview").textContent = pending === "preview" || projection?.state === "processing" ? "正在生成预览…" : "生成二维预览";
      let image = $("pcdPreviewImage");
      if (view.previewUrl && displayedPreviewUrl !== view.previewUrl) {
        viewport.setImage(null);
        const url = view.previewUrl;
        const nextImage = root.createElement("img");
        nextImage.id = "pcdPreviewImage";
        nextImage.alt = image.alt;
        nextImage.hidden = true;
        nextImage.addEventListener("load", () => {
          if (nextImage === $("pcdPreviewImage") && nextImage.naturalWidth > 0 && url === controller.view.previewUrl) {
            try {
              raster.setImage(nextImage, controller.view.projection.result);
              viewport.setImage({ key: url, width: nextImage.naturalWidth, height: nextImage.naturalHeight });
              controller.markPreviewLoaded(url);
            } catch (error) { globalThis.RYAletheiaDiagnostics?.failure?.('deployment.pcd-raster-preview',error); controller.markPreviewFailed(url); }
          }
        });
        nextImage.addEventListener("error", () => {
          if (nextImage === $("pcdPreviewImage")) controller.markPreviewFailed(url);
        });
        displayedPreviewUrl = url;
        image.replaceWith(nextImage);
        nextImage.src = url;
        image = nextImage;
      }
      if (!view.previewUrl) { displayedPreviewUrl = null; image.removeAttribute("src"); viewport.setImage(null); raster.clearImage(); }
      image.hidden = !view.imageReady;
      $("pcdRasterPreview").hidden = !view.imageReady;
      $("pcdPreviewEmpty").hidden = view.imageReady || view.processingProgress.visible;
      $("pcdPreviewEmpty").textContent = view.previewMessage;
      $("pcdPreviewEmpty").classList.toggle("is-error", view.previewIsError);
      $("pcdConversionProgress").hidden = !view.processingProgress.visible;
      $("pcdConversionStage").textContent = view.processingProgress.text;
      const conversionBar = $("pcdConversionBar");
      if (view.processingProgress.value === null) conversionBar.removeAttribute('value');
      else conversionBar.value = view.processingProgress.value;
      const result = projection?.state === "ready" && !view.stale ? projection.result : null;
      const displayNote = "黑色为障碍，其他区域仅在此视图显示为白色；保存地图仍保留未知区域，白色不代表可通行。";
      $("pcdPreviewCaption").textContent = result ? `${result.width} × ${result.height} 格 · ${result.resolution_m} m / 格 · ${Number(result.selected_points || 0).toLocaleString("zh-CN")} 个截面点。${displayNote}` : displayNote;
      const warnings = [...new Set([...(analysis?.warnings || []), ...(result?.warnings || [])])];
      $("pcdWarnings").hidden = !warnings.length;
      $("pcdWarnings").innerHTML = warnings.map((warning) => `<li>${escapeHtml(warning)}</li>`).join("");
      $("pcdConfirmControls").hidden = projection?.state !== "ready" || view.stale;
      $("pcdConfirm").disabled = !view.canConfirm;
      $("pcdConfirm").textContent = pending === "confirm" ? "正在导入…" : "确认导入并继续";
      if (root.activeElement !== $("pcdMapLabel")) $("pcdMapLabel").value = label;
    },
    clear() { embeddedSource.close(); $("pcdFile").value = ""; $("pcdMapLabel").value = ""; },
  };
}
