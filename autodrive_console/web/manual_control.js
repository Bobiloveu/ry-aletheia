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
  let chassisSavePending = false;
  let chassisParametersDirty = false;
  let previousEmergencyRelease = null;

  const speedParameters = [
    { range: "linearSpeed", number: "linearSpeedNumber", output: "linearSpeedValue", unit: "m/s", decimals: 1 },
    { range: "angularSpeed", number: "angularSpeedNumber", output: "angularSpeedValue", unit: "rad/s", decimals: 1 },
  ];
  const chassisParameters = [
    { range: "chassisPressRange", number: "chassisPress", output: "chassisPressValue", minimum: 20, maximum: 2000 },
    { range: "movementAccRange", number: "movementAcc", output: "movementAccValue", minimum: 10, maximum: 1000 },
    { range: "stopAccRange", number: "stopAcc", output: "stopAccValue", minimum: 20, maximum: 2000 },
  ];

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

  function parameterIsValid(control) {
    const value = Number($(control.number).value);
    const minimum = Number($(control.number).min);
    const maximum = Number($(control.number).max);
    return Number.isFinite(value) && value >= minimum && value <= maximum && (control.decimals || Number.isInteger(value));
  }

  function setPairedParameter(control, value, { preserveActive = true } = {}) {
    const range = $(control.range);
    const number = $(control.number);
    if (preserveActive && (document.activeElement === range || document.activeElement === number)) return;
    const normalized = String(value);
    range.value = normalized;
    number.value = normalized;
    number.removeAttribute("aria-invalid");
    $(control.output).textContent = control.unit ? formatSpeed(normalized, control.unit) : normalized;
  }

  function syncPairedParameter(control, source) {
    const range = $(control.range);
    const number = $(control.number);
    const value = Number(source.value);
    const minimum = Number(number.min);
    const maximum = Number(number.max);
    const valid = Number.isFinite(value) && value >= minimum && value <= maximum && (control.decimals || Number.isInteger(value));
    if (!valid) {
      number.setAttribute("aria-invalid", "true");
      return false;
    }
    const normalized = String(value);
    range.value = normalized;
    number.value = normalized;
    number.removeAttribute("aria-invalid");
    $(control.output).textContent = control.unit ? formatSpeed(normalized, control.unit) : normalized;
    return true;
  }

  function renderSpeed(speed, ready) {
    if (!speed) return;
    const values = [speed.linear_mps, speed.angular_radps];
    speedParameters.forEach((control, index) => {
      const range = $(control.range);
      const number = $(control.number);
      range.min = number.min = String(speed.min);
      range.max = number.max = String(speed.max);
      range.disabled = number.disabled = !ready;
      setPairedParameter(control, values[index]);
    });
  }

  function setChassisParametersDirty(dirty, { announce = true } = {}) {
    chassisParametersDirty = dirty;
    const valid = chassisParameters.every(parameterIsValid);
    $("saveChassisParameters").disabled = chassisSavePending || !dirty || !valid;
    if (!announce || chassisSavePending) return;
    const status = $("chassisParameterMessage");
    if (!valid) {
      status.textContent = "请将每项参数修正到标注范围内后再保存。";
      status.className = "parameter-message error";
    } else if (dirty) {
      status.textContent = "参数尚未保存，不会影响当前车辆设置。";
      status.className = "parameter-message pending";
    } else if (status.classList.contains("pending")) {
      status.textContent = "";
      status.className = "parameter-message";
    }
  }

  function resetInvalidPairedParameter(control) {
    const range = $(control.range);
    const number = $(control.number);
    if (!parameterIsValid(control)) {
      number.value = range.value;
      number.removeAttribute("aria-invalid");
      $(control.output).textContent = control.unit ? formatSpeed(range.value, control.unit) : range.value;
      return false;
    }
    return true;
  }

  function onChassisParameterInput(control, source) {
    syncPairedParameter(control, source);
    setChassisParametersDirty(true);
  }

  function onChassisParameterChange(control) {
    resetInvalidPairedParameter(control);
    setChassisParametersDirty(true);
  }

  function onSpeedParameterInput(control, source) {
    if (syncPairedParameter(control, source)) scheduleSpeedUpdate();
  }

  function onSpeedParameterChange(control) {
    if (!resetInvalidPairedParameter(control)) return;
    if (speedTimer) window.clearTimeout(speedTimer);
    speedTimer = null;
    updateSpeed();
  }

  function setChassisParametersSaved() {
    chassisParametersDirty = false;
    setChassisParametersDirty(false, { announce: false });
  }

  function renderChassisParameterSaveState() {
    setChassisParametersDirty(chassisParametersDirty, { announce: false });
  }

  function renderChassisParameters(parameters) {
    if (!parameters) return;
    if (!chassisParametersDirty) {
      [parameters.press, parameters.movement_acc, parameters.stop_acc].forEach((value, index) => {
        if (Number.isFinite(Number(value))) setPairedParameter(chassisParameters[index], value);
      });
    }
    renderChassisParameterSaveState();
  }

  function renderEmergencyStop(emergency) {
    const state = emergency?.state || "unknown";
    const release = emergency?.release || "idle";
    const panel = $("emergencyStopPanel");
    const label = $("emergencyStopState");
    const detail = $("emergencyStopDetail");
    const releaseButton = $("releaseEmergencyStop");
    panel.dataset.state = state;

    if (state === "normal") {
      label.textContent = "未触发急停";
      detail.textContent = release === "confirmed" ? "已收到车端状态确认，急停已解除。" : "车端已确认急停未触发。";
    } else if (state === "triggered") {
      label.textContent = "急停已触发";
      detail.textContent = release === "failed" ? "未在限定时间内收到解除确认，请检查物理急停与底盘状态。" : "手动运动已锁定。解除后仍需等待车端状态恢复。";
    } else {
      label.textContent = "状态未知";
      detail.textContent = release === "unconfirmable" ? "解除结果无法确认，请检查 ROS2 与急停状态 Topic。" : "尚未收到 /is_emergency_stop 的真实状态，手动运动保持锁定。";
    }
    releaseButton.disabled = state !== "triggered" || release === "waiting_confirmation";
    releaseButton.textContent = release === "waiting_confirmation" ? "正在确认解除" : "解除急停";
    if (state !== "normal") clearHeld();
    if (release === "confirmed" && previousEmergencyRelease !== "confirmed") message("已由车端急停状态确认解除。", "success");
    previousEmergencyRelease = release;
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
    renderEmergencyStop(state.emergency_stop);
    renderChassisParameters(state.chassis_parameters);

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

    const emergencyState = state.emergency_stop?.state || "unknown";
    if (emergencyState === "triggered") {
      $("gateTitle").textContent = "急停已触发";
      $("gateText").textContent = "车端已锁定手动运动。可发起软件解除，但必须等待 /is_emergency_stop 返回未触发。";
    } else if (emergencyState !== "normal") {
      $("gateTitle").textContent = "急停状态未知";
      $("gateText").textContent = "未收到可靠急停状态，方向控制会保持锁定。请先检查车端 ROS2 状态。";
    } else if (state.runtime !== "ready") {
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

  function readChassisParameters() {
    const values = {
      press: Number($("chassisPress").value),
      movement_acc: Number($("movementAcc").value),
      stop_acc: Number($("stopAcc").value),
    };
    const limits = [["press", "底盘压力", 20, 2000], ["movement_acc", "运动加速度", 10, 1000], ["stop_acc", "停止加速度", 20, 2000]];
    for (const [key, label, minimum, maximum] of limits) {
      if (!Number.isInteger(values[key]) || values[key] < minimum || values[key] > maximum) {
        throw new Error(`${label}必须是 ${minimum}-${maximum} 的整数`);
      }
    }
    return values;
  }

  async function saveChassisParameters() {
    if (chassisSavePending) return;
    let parameters;
    try {
      parameters = readChassisParameters();
    } catch (error) {
      $("chassisParameterMessage").textContent = error.message;
      $("chassisParameterMessage").className = "parameter-message error";
      return;
    }
    chassisSavePending = true;
    renderChassisParameters(lastStatus?.chassis_parameters);
    $("chassisParameterMessage").textContent = "正在保存车端手动控制参数…";
    $("chassisParameterMessage").className = "parameter-message";
    try {
      const state = await request("/api/vehicle-control/chassis-parameters", parameters);
      setChassisParametersSaved();
      render(state);
      $("chassisParameterMessage").textContent = "参数已保存，将用于后续运动和 STOP 指令。";
      $("chassisParameterMessage").className = "parameter-message success";
    } catch (error) {
      if (error.status) render(error.status);
      $("chassisParameterMessage").textContent = error.message;
      $("chassisParameterMessage").className = "parameter-message error";
    } finally {
      chassisSavePending = false;
      renderChassisParameters(lastStatus?.chassis_parameters);
    }
  }

  async function releaseEmergencyStop() {
    if (lastStatus?.emergency_stop?.state !== "triggered") return;
    message("已发送解除急停请求，正在等待车端状态确认。");
    try {
      render(await request("/api/vehicle-control/release-emergency-stop", {}));
    } catch (error) { if (error.status) render(error.status); message(error.message, "error"); }
  }

  function scheduleSpeedUpdate() {
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
  $("releaseEmergencyStop").addEventListener("click", releaseEmergencyStop);
  $("saveChassisParameters").addEventListener("click", saveChassisParameters);
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
  speedParameters.forEach((control) => {
    const range = $(control.range);
    const number = $(control.number);
    range.addEventListener("input", () => onSpeedParameterInput(control, range));
    number.addEventListener("input", () => onSpeedParameterInput(control, number));
    range.addEventListener("change", () => onSpeedParameterChange(control));
    number.addEventListener("change", () => onSpeedParameterChange(control));
  });
  chassisParameters.forEach((control) => {
    const range = $(control.range);
    const number = $(control.number);
    range.addEventListener("input", () => onChassisParameterInput(control, range));
    number.addEventListener("input", () => onChassisParameterInput(control, number));
    range.addEventListener("change", () => onChassisParameterChange(control));
    number.addEventListener("change", () => onChassisParameterChange(control));
  });
  window.addEventListener("pagehide", leavePageSafely);
  window.addEventListener("beforeunload", leavePageSafely);
  statusTimer = window.setInterval(refresh, 350);
  heartbeatTimer = window.setInterval(heartbeat, 250);
  refresh();
  window.addEventListener("unload", () => { window.clearInterval(statusTimer); window.clearInterval(heartbeatTimer); if (speedTimer) window.clearTimeout(speedTimer); });
})();
