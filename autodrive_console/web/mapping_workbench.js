(() => {
  const $ = (id) => document.getElementById(id);
  const driveButtons = [...document.querySelectorAll("[data-command]")];
  const canvas = $("liveMappingCanvas");
  const context = canvas.getContext("2d");
  let mapping = null;
  let vehicle = null;
  let sessionId = null;
  let heldCommand = null;
  let previewImage = null;
  let previewRevision = 0;
  let controlTimer = null;
  let speedTimer = null;

  async function request(path, payload, keepalive = false) {
    const response = await fetch(path, {
      method: payload === undefined ? "GET" : "POST",
      headers: payload === undefined ? undefined : { "Content-Type": "application/json" },
      body: payload === undefined ? undefined : JSON.stringify(payload),
      cache: "no-store",
      keepalive,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(data.error || `请求失败（${response.status}）`);
      error.status = data.status;
      throw error;
    }
    return data;
  }

  const sourceLabel = (source) => source === "navigation" ? "自动驾驶" : source === "miniapp" ? "手动控制" : source || "未知";
  const formatSpeed = (value, unit) => `${Number(value).toFixed(1)} ${unit}`;
  function message(text, kind = "") {
    $("workbenchMessage").textContent = text || "";
    $("workbenchMessage").className = `workbench-message ${kind}`;
  }
  function resizeCanvas() {
    const ratio = window.devicePixelRatio || 1;
    const { width, height } = canvas.getBoundingClientRect();
    const nextWidth = Math.max(1, Math.round(width * ratio));
    const nextHeight = Math.max(1, Math.round(height * ratio));
    if (canvas.width !== nextWidth || canvas.height !== nextHeight) {
      canvas.width = nextWidth;
      canvas.height = nextHeight;
    }
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, width, height);
    const grid = Math.max(40, Math.round(Math.min(width, height) / 16));
    context.strokeStyle = "rgba(29, 29, 31, .055)";
    context.lineWidth = 1;
    for (let x = grid; x < width; x += grid) { context.beginPath(); context.moveTo(x, 0); context.lineTo(x, height); context.stroke(); }
    for (let y = grid; y < height; y += grid) { context.beginPath(); context.moveTo(0, y); context.lineTo(width, y); context.stroke(); }
    if (!previewImage?.naturalWidth) return;
    const scale = Math.min((width - 44) / previewImage.naturalWidth, (height - 44) / previewImage.naturalHeight);
    const drawWidth = previewImage.naturalWidth * scale;
    const drawHeight = previewImage.naturalHeight * scale;
    context.imageSmoothingEnabled = false;
    context.drawImage(previewImage, (width - drawWidth) / 2, (height - drawHeight) / 2, drawWidth, drawHeight);
  }
  function renderMapping() {
    const session = mapping?.session;
    const state = session?.state || "idle";
    $("mappingTitle").textContent = session?.label || "实时建图";
    $("mappingSubtitle").textContent = session ? `${session.kind} · ${session.source_yaml || "项目工作区 YAML"}` : "请先在部署建图页面上传 YAML 并准备会话。";
    $("mappingStateName").textContent = state === "prepared" ? "待启动" : state === "running" ? "正在建图" : state === "saved" ? "已保存" : state === "failed" ? "建图失败" : "未准备";
    $("mappingStateDot").className = `mapping-state-dot ${state}`;
    $("startMapping").disabled = !mapping?.available || state !== "prepared";
    $("stopMapping").disabled = state !== "running";
    if (!session) {
      $("mappingEmptyTitle").textContent = "尚未准备建图会话";
      $("mappingEmptyText").textContent = "请返回部署建图页，从当前电脑选择 YAML 模板后准备会话。";
    } else if (state === "prepared") {
      $("mappingEmptyTitle").textContent = "空白画布已就绪";
      $("mappingEmptyText").textContent = "确认现场安全后，点击“开始实时建图”。";
    } else if (state === "running" && !previewRevision) {
      $("mappingEmptyTitle").textContent = "正在等待第一帧栅格";
      $("mappingEmptyText").textContent = "请确认上传的 YAML 已启用 system.with_g2p5: true，且雷达话题正常。";
    } else if (session.error) {
      $("mappingEmptyTitle").textContent = "建图会话需要检查";
      $("mappingEmptyText").textContent = session.error;
    }
    updatePreview(session);
  }
  function updatePreview(session) {
    const preview = session?.preview;
    if (!preview?.revision || preview.revision === previewRevision) return;
    previewRevision = preview.revision;
    const image = new Image();
    image.onload = () => {
      previewImage = image;
      $("mappingEmpty").classList.add("has-preview");
      $("mappingFrameMeta").hidden = false;
      $("mappingFrameMeta").textContent = `${preview.width} × ${preview.height} · ${preview.resolution} m/px · 第 ${preview.revision} 帧`;
      resizeCanvas();
    };
    image.src = `/api/mapping/sessions/${encodeURIComponent(session.id)}/preview.png?revision=${preview.revision}`;
  }
  function renderVehicle(state) {
    if (!state) return;
    vehicle = state;
    const ready = Boolean(state.manual_ready && sessionId);
    const switching = Boolean(state.transition);
    $("sourceName").textContent = switching ? `正在切换至 ${sourceLabel(state.transition)}` : sourceLabel(state.actual_source);
    $("sessionBadge").textContent = ready ? "控制已就绪" : switching ? "切换中" : state.session?.state === "expired" ? "心跳失效" : "未接管";
    $("sessionBadge").className = `deck-badge ${ready ? "ready" : state.transition_error || state.session?.state === "expired" ? "error" : ""}`;
    $("enterManual").hidden = Boolean(sessionId);
    $("exitManual").hidden = !sessionId;
    $("enterManual").disabled = !state.can_begin_manual || switching;
    $("exitManual").disabled = !sessionId || switching;
    $("stopVehicle").disabled = !sessionId;
    $("driveArea").setAttribute("aria-disabled", String(!ready));
    driveButtons.forEach((button) => { button.disabled = !ready; });
    const speed = state.speed;
    if (speed) {
      [[$("linearSpeed"), speed.linear_mps, "m/s", $("linearSpeedValue")], [$("angularSpeed"), speed.angular_radps, "rad/s", $("angularSpeedValue")]].forEach(([input, value, unit, output]) => {
        if (document.activeElement !== input) input.value = String(value);
        input.min = String(speed.min); input.max = String(speed.max); input.disabled = !ready;
        output.textContent = formatSpeed(input.value, unit);
      });
    }
    if (state.transition_error) message(state.transition_error, "error");
  }
  function clearHeld() {
    heldCommand = null;
    if (controlTimer) window.clearInterval(controlTimer);
    controlTimer = null;
    driveButtons.forEach((button) => button.classList.remove("is-held"));
  }
  async function stopVehicle() {
    clearHeld();
    if (!sessionId) return;
    try { renderVehicle(await request("/api/vehicle-control/stop", { session_id: sessionId })); }
    catch (error) { if (error.status) renderVehicle(error.status); message(error.message, "error"); }
  }
  async function sendHeld() {
    if (!sessionId || !heldCommand) return;
    try { renderVehicle(await request("/api/vehicle-control/command", { session_id: sessionId, command: heldCommand })); }
    catch (error) { clearHeld(); if (error.status) renderVehicle(error.status); message(error.message, "error"); }
  }
  function beginHold(command, button) {
    if (!vehicle?.manual_ready || !sessionId || heldCommand === command) return;
    clearHeld(); heldCommand = command; button.classList.add("is-held"); sendHeld();
    controlTimer = window.setInterval(sendHeld, 100);
  }
  async function enterManual() {
    try {
      message("正在请求车端确认手动控制源…");
      const state = await request("/api/vehicle-control/enter", {});
      sessionId = state.session?.id || null;
      renderVehicle(state);
    } catch (error) { if (error.status) renderVehicle(error.status); message(error.message, "error"); }
  }
  async function exitManual() {
    clearHeld();
    if (!sessionId) return;
    try {
      const state = await request("/api/vehicle-control/exit", { session_id: sessionId });
      sessionId = null; renderVehicle(state);
    } catch (error) { if (error.status) renderVehicle(error.status); message(error.message, "error"); }
  }
  async function updateSpeed() {
    if (!sessionId || !vehicle?.manual_ready) return;
    try {
      renderVehicle(await request("/api/vehicle-control/speed", { session_id: sessionId, linear_speed: Number($("linearSpeed").value), angular_speed: Number($("angularSpeed").value) }));
    } catch (error) { if (error.status) renderVehicle(error.status); message(error.message, "error"); }
  }
  async function startMapping() {
    if (!mapping?.session) return;
    try {
      const response = await request(`/api/mapping/sessions/${encodeURIComponent(mapping.session.id)}/start`, {});
      mapping = { ...mapping, session: response.session }; previewImage = null; previewRevision = 0;
      renderMapping(); message("在线建图已启动；可在确认手动接管后按住方向键移动。", "success");
    } catch (error) { message(error.message, "error"); await refresh(); }
  }
  async function stopAndSaveMapping() {
    if (!mapping?.session || mapping.session.state !== "running") return;
    await stopVehicle();
    try {
      message("已发送 STOP，正在保存地图…");
      const response = await request(`/api/mapping/sessions/${encodeURIComponent(mapping.session.id)}/stop`, { save: true });
      mapping = { ...mapping, session: response.session }; renderMapping();
      if (response.capture_error) message(`建图已停止，但地图快照未导入：${response.capture_error}`, "error");
      else message(response.map ? `地图已保存并导入“${response.map.label}”。` : "地图已停止并保存。", "success");
      await exitManual();
    } catch (error) { message(error.message, "error"); await refresh(); }
  }
  async function refresh() {
    try {
      const [mappingState, vehicleState] = await Promise.all([request("/api/mapping"), request("/api/vehicle-control")]);
      mapping = mappingState; renderMapping(); renderVehicle(vehicleState);
      if (vehicleState.actual_source === "miniapp" && vehicleState.can_begin_manual && !sessionId) {
        const adopted = await request("/api/vehicle-control/enter", {});
        sessionId = adopted.session?.id || null; renderVehicle(adopted);
      }
    } catch (error) { message(error.message, "error"); }
  }
  function leavePageSafely() {
    clearHeld();
    if (!sessionId) return;
    navigator.sendBeacon?.("/api/vehicle-control/exit", new Blob([JSON.stringify({ session_id: sessionId })], { type: "application/json" }));
  }
  $("startMapping").addEventListener("click", startMapping);
  $("stopMapping").addEventListener("click", stopAndSaveMapping);
  $("enterManual").addEventListener("click", enterManual);
  $("exitManual").addEventListener("click", exitManual);
  $("stopVehicle").addEventListener("click", stopVehicle);
  driveButtons.forEach((button) => {
    button.addEventListener("pointerdown", (event) => { event.preventDefault(); button.setPointerCapture?.(event.pointerId); beginHold(button.dataset.command, button); });
    ["pointerup", "pointercancel", "lostpointercapture", "pointerleave"].forEach((name) => button.addEventListener(name, stopVehicle));
  });
  const keyboard = { i: "forward", I: "forward", j: "left", J: "left", k: "backward", K: "backward", l: "right", L: "right" };
  document.addEventListener("keydown", (event) => { if (event.repeat || event.target.matches("input, textarea, select")) return; if (event.key === " " || event.key === "Escape") { event.preventDefault(); stopVehicle(); return; } const command = keyboard[event.key]; if (command) { event.preventDefault(); beginHold(command, driveButtons.find((button) => button.dataset.command === command)); } });
  document.addEventListener("keyup", (event) => { if (keyboard[event.key]) stopVehicle(); });
  document.addEventListener("visibilitychange", () => { if (document.hidden) stopVehicle(); });
  [$("linearSpeed"), $("angularSpeed")].forEach((input) => input.addEventListener("input", () => { $(input.id + "Value").textContent = formatSpeed(input.value, input.id === "linearSpeed" ? "m/s" : "rad/s"); if (speedTimer) window.clearTimeout(speedTimer); speedTimer = window.setTimeout(() => { speedTimer = null; updateSpeed(); }, 100); }));
  window.addEventListener("resize", resizeCanvas);
  window.addEventListener("pagehide", leavePageSafely);
  window.addEventListener("beforeunload", leavePageSafely);
  window.setInterval(refresh, 500);
  window.setInterval(async () => { if (sessionId) { try { renderVehicle(await request("/api/vehicle-control/heartbeat", { session_id: sessionId })); } catch (error) { clearHeld(); message(error.message, "error"); } } }, 250);
  resizeCanvas(); refresh();
})();
