(() => {
  const $ = (id) => document.getElementById(id);
  const driveButtons = [...document.querySelectorAll("[data-command]")];
  let sessionId = null;
  let heldCommand = null;
  let inputTimer = null;
  let statusTimer = null;
  let heartbeatTimer = null;
  let lastStatus = null;
  let adoptingExistingMiniapp = false;
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

  function sourceLabel(source) {
    return source === "navigation" ? "自动驾驶" : source === "miniapp" ? "手动控制" : source || "未知";
  }

  function message(text, kind = "") {
    const target = $("controlMessage");
    target.textContent = text || "";
    target.className = `control-message ${kind}`;
  }

  function formatSpeed(value, unit) {
    return `${Number(value).toFixed(1)} ${unit}`;
  }

  function renderSpeed(speed, ready) {
    if (!speed) return;
    const linear = $("linearSpeed");
    const angular = $("angularSpeed");
    if (document.activeElement !== linear) linear.value = String(speed.linear_mps);
    if (document.activeElement !== angular) angular.value = String(speed.angular_radps);
    linear.min = angular.min = String(speed.min);
    linear.max = angular.max = String(speed.max);
    linear.disabled = angular.disabled = !ready;
    $("linearSpeedValue").textContent = formatSpeed(linear.value, "m/s");
    $("angularSpeedValue").textContent = formatSpeed(angular.value, "rad/s");
  }

  function render(state) {
    if (!state) return;
    lastStatus = state;
    const switching = Boolean(state.transition);
    const isManual = state.actual_source === "miniapp";
    const sourceDot = $("sourceDot");
    sourceDot.className = `source-dot ${switching ? "switching" : isManual ? "manual" : state.actual_source === "navigation" ? "auto" : "unknown"}`;
    $("sourceName").textContent = switching ? `正在切换至 ${sourceLabel(state.transition)}` : sourceLabel(state.actual_source);
    $("sessionBadge").textContent = state.manual_ready ? "控制已就绪" : state.session?.state === "expired" ? "心跳已失效" : switching ? "切换中" : "未接管";
    $("sessionBadge").className = `session-badge ${state.manual_ready ? "ready" : state.transition_error || state.session?.state === "expired" ? "error" : ""}`;
    $("publishRate").textContent = state.safety ? `${state.safety.publish_hz} Hz` : "—";
    $("inputTimeout").textContent = state.safety ? `${state.safety.input_timeout_ms} ms` : "—";
    $("heartbeatTimeout").textContent = state.safety ? `${state.safety.heartbeat_timeout_ms} ms` : "—";

    const enter = $("enterManual");
    const exit = $("exitManual");
    const ready = Boolean(state.manual_ready && sessionId);
    renderSpeed(state.speed, ready);
    enter.disabled = !state.can_begin_manual || switching;
    enter.textContent = isManual ? "开始手动控制" : "进入手动控制";
    enter.hidden = Boolean(sessionId);
    exit.hidden = !sessionId;
    exit.disabled = switching && state.transition === "navigation";
    $("driveArea").setAttribute("aria-disabled", String(!ready));
    driveButtons.forEach((button) => { button.disabled = !ready; });
    $("stopButton").disabled = !sessionId || state.session?.state === "none";

    if (state.runtime !== "ready") {
      $("gateTitle").textContent = "本机 ROS2 控制不可用";
      $("gateText").textContent = state.runtime_error || "正在初始化车辆控制节点。";
    } else if (switching) {
      $("gateTitle").textContent = `正在等待实际切换至 ${sourceLabel(state.transition)}`;
      $("gateText").textContent = "切换命令已由车端发送；方向控制会保持锁定，直到 /control_source_state 确认。";
    } else if (ready) {
      $("gateTitle").textContent = "手动控制已确认";
      $("gateText").textContent = "可按住方向键移动。请保持观察车辆周边，并随时使用停止键。";
    } else if (state.can_begin_manual) {
      if (isManual) {
        $("gateTitle").textContent = adoptingExistingMiniapp ? "正在建立安全会话" : "手动控制源已确认";
        $("gateText").textContent = "车端已反馈 miniapp。Aletheia 会先写入 STOP 并建立看门狗会话，然后才允许方向控制。";
      } else {
        $("gateTitle").textContent = "当前为自动驾驶";
        $("gateText").textContent = "请求接管后，仍须等待车端实际状态确认；确认前不会发送非零速度。";
      }
    } else {
      $("gateTitle").textContent = "等待安全接管条件";
      $("gateText").textContent = "当前控制源不是 navigation，或已有失效会话。请先恢复自动驾驶后再进入手动控制。";
    }
    if (state.transition_error) message(state.transition_error, "error");
  }

  async function refresh() {
    try {
      const state = await request("/api/vehicle-control");
      render(state);
      // 若现场已先把控制源切到了 miniapp，页面打开时直接建立 Aletheia
      // 的短生命期会话。该动作只发送 STOP，不发送任何非零速度。
      if (state.actual_source === "miniapp" && state.can_begin_manual && !sessionId && !adoptingExistingMiniapp) {
        adoptExistingMiniapp();
      }
    } catch (error) {
      if (error.status) render(error.status);
      message(error.message, "error");
    }
  }

  function clearHeld() {
    heldCommand = null;
    if (inputTimer) window.clearInterval(inputTimer);
    inputTimer = null;
    driveButtons.forEach((button) => button.classList.remove("is-held"));
  }

  async function stop() {
    clearHeld();
    if (!sessionId) return;
    try { render(await request("/api/vehicle-control/stop", { session_id: sessionId })); }
    catch (error) { if (error.status) render(error.status); message(error.message, "error"); }
  }

  async function updateSpeed() {
    if (!sessionId || !lastStatus?.manual_ready) return;
    try {
      const state = await request("/api/vehicle-control/speed", {
        session_id: sessionId,
        linear_speed: Number($("linearSpeed").value),
        angular_speed: Number($("angularSpeed").value),
      });
      render(state);
    } catch (error) { if (error.status) render(error.status); message(error.message, "error"); }
  }

  function scheduleSpeedUpdate() {
    $("linearSpeedValue").textContent = formatSpeed($("linearSpeed").value, "m/s");
    $("angularSpeedValue").textContent = formatSpeed($("angularSpeed").value, "rad/s");
    if (speedTimer) window.clearTimeout(speedTimer);
    speedTimer = window.setTimeout(() => { speedTimer = null; updateSpeed(); }, 100);
  }

  async function sendHeld() {
    if (!sessionId || !heldCommand) return;
    try { render(await request("/api/vehicle-control/command", { session_id: sessionId, command: heldCommand })); }
    catch (error) { clearHeld(); if (error.status) render(error.status); message(error.message, "error"); }
  }

  function beginHold(command, button) {
    if (!lastStatus?.manual_ready || !sessionId) return;
    if (heldCommand === command) return;
    clearHeld();
    heldCommand = command;
    button.classList.add("is-held");
    sendHeld();
    // 此频率只维持前端输入活性；ROS2 的 20 Hz 发布在车端控制器内完成。
    inputTimer = window.setInterval(sendHeld, 100);
  }

  async function enterManual({ adoptExisting = false } = {}) {
    if (!adoptExisting && !window.confirm("确认进入手动控制？\n\n车辆在收到 /control_source_state=miniapp 前不会解锁方向控制。")) return;
    message(adoptExisting ? "正在建立车端手动控制安全会话…" : "正在请求车端切换控制源…");
    try {
      const state = await request("/api/vehicle-control/enter", {});
      sessionId = state.session?.id || null;
      render(state);
    } catch (error) { if (error.status) render(error.status); message(error.message, "error"); }
  }

  async function adoptExistingMiniapp() {
    adoptingExistingMiniapp = true;
    try {
      await enterManual({ adoptExisting: true });
    } finally {
      adoptingExistingMiniapp = false;
    }
  }

  async function exitManual() {
    clearHeld();
    if (!sessionId) return;
    message("正在 STOP 并等待自动驾驶实际接管…");
    try {
      const state = await request("/api/vehicle-control/exit", { session_id: sessionId });
      // 退出请求一经车端接受，浏览器就不再维持会话；车端仍保持 STOP，直到
      // /control_source_state 实际确认 navigation。
      sessionId = null;
      render(state);
    }
    catch (error) { if (error.status) render(error.status); message(error.message, "error"); }
  }

  async function heartbeat() {
    if (!sessionId) return;
    try { render(await request("/api/vehicle-control/heartbeat", { session_id: sessionId })); }
    catch (error) { clearHeld(); if (error.status) render(error.status); message(error.message, "error"); }
  }

  function leavePageSafely() {
    clearHeld();
    if (!sessionId) return;
    const payload = new Blob([JSON.stringify({ session_id: sessionId })], { type: "application/json" });
    navigator.sendBeacon?.("/api/vehicle-control/exit", payload);
  }

  $("enterManual").addEventListener("click", enterManual);
  $("exitManual").addEventListener("click", exitManual);
  $("stopButton").addEventListener("click", stop);
  driveButtons.forEach((button) => {
    button.addEventListener("pointerdown", (event) => { event.preventDefault(); button.setPointerCapture?.(event.pointerId); beginHold(button.dataset.command, button); });
    ["pointerup", "pointercancel", "lostpointercapture", "pointerleave"].forEach((eventName) => button.addEventListener(eventName, stop));
  });
  const keyboardCommand = { i: "forward", I: "forward", j: "left", J: "left", k: "backward", K: "backward", l: "right", L: "right" };
  document.addEventListener("keydown", (event) => {
    if (event.repeat || event.target.matches("input, textarea, select")) return;
    if (event.key === " " || event.key === "Escape") { event.preventDefault(); stop(); return; }
    const command = keyboardCommand[event.key];
    if (!command) return;
    event.preventDefault(); beginHold(command, driveButtons.find((button) => button.dataset.command === command));
  });
  document.addEventListener("keyup", (event) => { if (keyboardCommand[event.key]) stop(); });
  document.addEventListener("visibilitychange", () => { if (document.hidden) stop(); });
  [$("linearSpeed"), $("angularSpeed")].forEach((input) => {
    input.addEventListener("input", scheduleSpeedUpdate);
    input.addEventListener("change", () => { if (speedTimer) window.clearTimeout(speedTimer); speedTimer = null; updateSpeed(); });
  });
  window.addEventListener("pagehide", leavePageSafely);
  window.addEventListener("beforeunload", leavePageSafely);
  statusTimer = window.setInterval(refresh, 350);
  heartbeatTimer = window.setInterval(heartbeat, 250);
  refresh();
  window.addEventListener("unload", () => { window.clearInterval(statusTimer); window.clearInterval(heartbeatTimer); if (speedTimer) window.clearTimeout(speedTimer); });
})();
