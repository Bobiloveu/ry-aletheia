import { requestVehicleControl } from "./platform/vehicle-control.js";
import {
  commandForKeyboardCode,
  DEFAULT_KEYBOARD_BINDINGS,
  isBindableKeyboardCode,
  keyboardCodeLabel,
  normalizeKeyboardBindings,
  vectorForActiveCommands,
  vectorsEqual,
} from "./manual_control_input.js";

(() => {
  const $ = (id) => document.getElementById(id);
  const driveButtons = [...document.querySelectorAll("[data-command]")];
  let sessionId = null;
  const heldInputs = new Map();
  let heldVector = { linearRatio: 0, angularRatio: 0 };
  let inputSequence = 0;
  let inputTimer = null;
  let statusTimer = null;
  let heartbeatTimer = null;
  let lastStatus = null;
  let adoptingExistingMiniapp = false;
  let speedTimer = null;
  let chassisSavePending = false;
  let chassisParametersDirty = false;
  let previousEmergencyRelease = null;
  let requestedSource = null;
  const keyBindingsStorageKey = "ry-aletheia.manual-control.key-bindings.v1";
  let keyboardBindings = loadKeyboardBindings();
  let capturingKeyBindingCommand = null;
  let keyBindingDialogPending = false;

  const speedParameters = [
    { range: "linearSpeed", number: "linearSpeedNumber", output: "linearSpeedValue", unit: "m/s", decimals: 1 },
    { range: "angularSpeed", number: "angularSpeedNumber", output: "angularSpeedValue", unit: "rad/s", decimals: 1 },
  ];
  const chassisParameters = [
    { range: "chassisPressRange", number: "chassisPress", output: "chassisPressValue", minimum: 20, maximum: 2000 },
    { range: "movementAccRange", number: "movementAcc", output: "movementAccValue", minimum: 10, maximum: 1000 },
    { range: "stopAccRange", number: "stopAcc", output: "stopAccValue", minimum: 20, maximum: 2000 },
  ];

  const request = (path, payload, keepalive = false) => requestVehicleControl(path, payload, keepalive);

  function loadKeyboardBindings() {
    try {
      return normalizeKeyboardBindings(JSON.parse(window.localStorage.getItem(keyBindingsStorageKey)));
    } catch {
      return { ...DEFAULT_KEYBOARD_BINDINGS };
    }
  }

  function saveKeyboardBindings() {
    try {
      window.localStorage.setItem(keyBindingsStorageKey, JSON.stringify(keyboardBindings));
      return true;
    } catch {
      return false;
    }
  }

  function keyboardDirectionsSummary() {
    return ["forward", "left", "backward", "right"].map((command) => keyboardCodeLabel(keyboardBindings[command])).join("/");
  }

  function renderKeyboardBindings() {
    document.querySelectorAll("[data-key-binding-display]").forEach((element) => {
      element.textContent = keyboardCodeLabel(keyboardBindings[element.dataset.keyBindingDisplay]);
    });
    document.querySelectorAll("[data-key-binding-command]").forEach((button) => {
      button.classList.toggle("is-capturing", button.dataset.keyBindingCommand === capturingKeyBindingCommand);
    });
  }

  function setKeyBindingMessage(text, kind = "") {
    const target = $("keyBindingMessage");
    target.textContent = text;
    target.className = `key-binding-message ${kind}`;
  }

  function cancelKeyBindingCapture() {
    if (!capturingKeyBindingCommand) return;
    capturingKeyBindingCommand = null;
    renderKeyboardBindings();
    setKeyBindingMessage("已取消按键设置。选择一个方向后按下新按键。", "");
  }

  function closeKeyBindingDialog() {
    cancelKeyBindingCapture();
    $("keyBindingDialog").close();
  }

  async function openKeyBindingDialog() {
    if (keyBindingDialogPending || $("keyBindingDialog").open) return;
    keyBindingDialogPending = true;
    const trigger = $("editKeyBindings");
    trigger.disabled = true;
    trigger.textContent = "正在停止车辆…";
    driveButtons.forEach((button) => { button.disabled = true; });
    $("stopButton").disabled = true;
    const stopped = await stopForKeyBinding();
    keyBindingDialogPending = false;
    trigger.disabled = false;
    trigger.textContent = "设置按键";
    render(lastStatus);
    if (!stopped) {
      message("车辆停止请求未被确认，不能修改按键。请检查控制连接后重试。", "error");
      return;
    }
    const dialog = $("keyBindingDialog");
    dialog.showModal();
    capturingKeyBindingCommand = null;
    renderKeyboardBindings();
    setKeyBindingMessage("选择一个方向后按下新按键。", "");
  }

  function startKeyBindingCapture(command) {
    capturingKeyBindingCommand = command;
    renderKeyboardBindings();
    setKeyBindingMessage(`请按下用于${command === "forward" ? "前进" : command === "backward" ? "后退" : command === "left" ? "左转" : "右转"}的按键；按 Esc 取消。`, "");
  }

  function applyCapturedKeyBinding(code) {
    const command = capturingKeyBindingCommand;
    if (!command) return;
    if (!isBindableKeyboardCode(code)) {
      setKeyBindingMessage("该按键不可用于方向控制。请使用字母、数字、方向键或数字键盘按键。", "error");
      return;
    }
    const owner = commandForKeyboardCode(code, keyboardBindings);
    if (owner && owner !== command) {
      setKeyBindingMessage(`该按键已绑定${owner === "forward" ? "前进" : owner === "backward" ? "后退" : owner === "left" ? "左转" : "右转"}，请先选择其他按键。`, "error");
      return;
    }
    keyboardBindings = normalizeKeyboardBindings({ ...keyboardBindings, [command]: code });
    capturingKeyBindingCommand = null;
    renderKeyboardBindings();
    const saved = saveKeyboardBindings();
    setKeyBindingMessage(saved ? `已将${keyboardCodeLabel(code)}绑定为方向控制按键。` : "按键已在当前页面生效，但浏览器拒绝保存本机偏好。", saved ? "success" : "error");
  }

  function resetKeyboardBindings() {
    keyboardBindings = { ...DEFAULT_KEYBOARD_BINDINGS };
    capturingKeyBindingCommand = null;
    renderKeyboardBindings();
    const saved = saveKeyboardBindings();
    setKeyBindingMessage(saved ? "已恢复默认 I/J/K/L 按键。" : "默认按键已在当前页面生效，但浏览器拒绝保存本机偏好。", saved ? "success" : "error");
  }

  function sourceLabel(source) {
    if (source === "navigation") return "自动驾驶";
    if (source === "miniapp") return "手动控制";
    return source && source !== "unknown" ? `外部控制：${source}` : "未知";
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

  function renderEmergencyStop(emergency, carStateSync) {
    const state = emergency?.state || "unknown";
    const release = emergency?.release || "idle";
    const pending = carStateSync?.emergency_stop === "pending";
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
    } else if (pending) {
      label.textContent = "正在读取";
      detail.textContent = "正在从车端读取急停状态；读取完成前手动运动保持锁定。";
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
    const carStateSync = state.car_state_sync || {};
    const readingCarState = carStateSync.control_source === "pending" || carStateSync.emergency_stop === "pending";
    const sourceDot = $("sourceDot");
    sourceDot.className = `source-dot ${switching ? "switching" : readingCarState ? "syncing" : isManual ? "manual" : state.actual_source === "navigation" ? "auto" : "unknown"}`;
    $("sourceName").textContent = switching ? `正在切换至 ${sourceLabel(state.transition)}` : readingCarState && state.actual_source === "unknown" ? "正在读取…" : sourceLabel(state.actual_source);
    $("sessionBadge").textContent = state.manual_ready ? "控制已就绪" : state.session?.state === "expired" ? "心跳已失效" : switching ? "切换中" : readingCarState ? "读取中" : "未接管";
    $("sessionBadge").className = `session-badge ${state.manual_ready ? "ready" : readingCarState ? "pending" : state.transition_error || state.session?.state === "expired" ? "error" : ""}`;
    $("publishRate").textContent = state.safety ? `${state.safety.publish_hz} Hz` : "—";
    $("inputTimeout").textContent = state.safety ? `${state.safety.input_timeout_ms} ms` : "—";
    $("heartbeatTimeout").textContent = state.safety ? `${state.safety.heartbeat_timeout_ms} ms` : "—";
    renderEmergencyStop(state.emergency_stop, carStateSync);
    renderChassisParameters(state.chassis_parameters);

    const enter = $("enterManual");
    const requestNavigation = $("requestNavigation");
    const exit = $("exitManual");
    const ready = Boolean(state.manual_ready && sessionId && !keyBindingDialogPending);
    renderSpeed(state.speed, ready);
    enter.disabled = !state.can_begin_manual || switching;
    enter.textContent = isManual ? "开始手动控制" : "进入手动控制";
    enter.hidden = Boolean(sessionId);
    requestNavigation.hidden = Boolean(sessionId) || state.actual_source === "navigation";
    requestNavigation.disabled = !state.can_request_navigation || switching;
    exit.hidden = !sessionId;
    exit.disabled = switching && state.transition === "navigation";
    $("driveArea").setAttribute("aria-disabled", String(!ready));
    driveButtons.forEach((button) => { button.disabled = !ready; });
    $("stopButton").disabled = keyBindingDialogPending || !sessionId || state.session?.state === "none";

    const emergencyState = state.emergency_stop?.state || "unknown";
    if (readingCarState) {
      $("gateTitle").textContent = "正在读取车端状态";
      $("gateText").textContent = "正在读取急停与实际控制源；完成前方向控制保持锁定。";
    } else if (emergencyState === "triggered") {
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
      $("gateText").textContent = `可组合按住 ${keyboardDirectionsSummary()} 进行前后转向弧线行驶。请保持观察车辆周边，并随时使用停止键。`;
    } else if (state.can_begin_manual) {
      if (isManual) {
        $("gateTitle").textContent = adoptingExistingMiniapp ? "正在建立安全会话" : "手动控制源已确认";
        $("gateText").textContent = "车端已反馈 miniapp。Aletheia 会先写入 STOP 并建立看门狗会话，然后才允许方向控制。";
      } else {
        const externalSource = state.actual_source && state.actual_source !== "unknown" ? state.actual_source : "未知";
        $("gateTitle").textContent = state.actual_source === "navigation" ? "当前为自动驾驶" : `外部控制源 ${externalSource} 已接管`;
        $("gateText").textContent = "可请求切换至手动控制或自动驾驶；只有 /control_source_state 实际确认后才会更新结果，确认前不会发送非零速度。";
      }
    } else {
      $("gateTitle").textContent = "当前无法请求手动控制";
      $("gateText").textContent = state.transition_error || "自动化测试正在执行或已有控制会话，请等待当前状态结束后再试。";
    }
    if (!switching && requestedSource) {
      if (state.actual_source === requestedSource) {
        message(`已由车端确认切换至 ${sourceLabel(requestedSource)}。`, "success");
        requestedSource = null;
      } else if (state.transition_error) {
        requestedSource = null;
      }
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
      if (error.vehicleState) render(error.vehicleState);
      message(error.message, "error");
    }
  }

  function clearHeld() {
    heldInputs.clear();
    heldVector = { linearRatio: 0, angularRatio: 0 };
    if (inputTimer) window.clearInterval(inputTimer);
    inputTimer = null;
    driveButtons.forEach((button) => button.classList.remove("is-held"));
  }

  async function stop() {
    const wasMoving = heldVector.linearRatio !== 0 || heldVector.angularRatio !== 0;
    clearHeld();
    if (!sessionId) return true;
    // Use a newer zero vector rather than an unordered legacy STOP request:
    // any in-flight earlier movement request is then ignored by the Backend.
    if (wasMoving) return sendVector({ linearRatio: 0, angularRatio: 0 }, nextInputSequence());
    else {
      try {
        render(await request("/api/vehicle-control/stop", { session_id: sessionId }));
        return true;
      } catch (error) {
        if (error.vehicleState) render(error.vehicleState);
        message(error.message, "error");
        return false;
      }
    }
  }

  async function stopForKeyBinding() {
    clearHeld();
    if (!sessionId) return true;
    // Always send a newer zero vector. A previous key-up may already have
    // cleared local state while its zero vector is still in flight.
    return sendVector({ linearRatio: 0, angularRatio: 0 }, nextInputSequence());
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
    } catch (error) { if (error.vehicleState) render(error.vehicleState); message(error.message, "error"); }
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
      if (error.vehicleState) render(error.vehicleState);
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
    } catch (error) { if (error.vehicleState) render(error.vehicleState); message(error.message, "error"); }
  }

  function scheduleSpeedUpdate() {
    if (speedTimer) window.clearTimeout(speedTimer);
    speedTimer = window.setTimeout(() => { speedTimer = null; updateSpeed(); }, 100);
  }

  function nextInputSequence() {
    inputSequence += 1;
    return inputSequence;
  }

  function renderHeldButtons() {
    const activeCommands = new Set(heldInputs.values());
    driveButtons.forEach((button) => button.classList.toggle("is-held", activeCommands.has(button.dataset.command)));
  }

  async function sendVector(vector, sequence) {
    if (!sessionId) return false;
    try {
      const state = await request("/api/vehicle-control/vector", {
        session_id: sessionId,
        linear_ratio: vector.linearRatio,
        angular_ratio: vector.angularRatio,
        input_sequence: sequence,
      });
      // A response to an older overlapping request must not overwrite the UI
      // state already confirmed for a newer input.
      if (sequence === inputSequence) render(state);
      return true;
    } catch (error) {
      if (sequence !== inputSequence) return false;
      clearHeld();
      if (error.vehicleState) render(error.vehicleState);
      message(error.message, "error");
      return false;
    }
  }

  function refreshHeldMotion() {
    const nextVector = vectorForActiveCommands(new Set(heldInputs.values()));
    if (vectorsEqual(nextVector, heldVector)) return;
    heldVector = nextVector;
    const sequence = nextInputSequence();
    if (nextVector.linearRatio === 0 && nextVector.angularRatio === 0) {
      if (inputTimer) window.clearInterval(inputTimer);
      inputTimer = null;
      sendVector(nextVector, sequence);
      return;
    }
    sendVector(nextVector, sequence);
    if (!inputTimer) {
      // 20 Hz is below the 350 ms vehicle watchdog with adequate margin and
      // removes the former browser-side 0–100 ms command-start delay.
      inputTimer = window.setInterval(() => sendVector(heldVector, inputSequence), 50);
    }
  }

  function beginHold(inputId, command) {
    if (keyBindingDialogPending || !lastStatus?.manual_ready || !sessionId) return;
    if (heldInputs.get(inputId) === command) return;
    heldInputs.set(inputId, command);
    renderHeldButtons();
    refreshHeldMotion();
  }

  function releaseHold(inputId) {
    if (!heldInputs.delete(inputId)) return;
    renderHeldButtons();
    refreshHeldMotion();
  }

  async function enterManual({ adoptExisting = false } = {}) {
    if (!adoptExisting && !window.confirm("确认进入手动控制？\n\n车辆在收到 /control_source_state=miniapp 前不会解锁方向控制。")) return;
    message(adoptExisting ? "正在建立车端手动控制安全会话…" : "正在请求车端切换控制源…");
    requestedSource = "miniapp";
    try {
      const state = await request("/api/vehicle-control/enter", {});
      sessionId = state.session?.id || null;
      render(state);
    } catch (error) { requestedSource = null; if (error.vehicleState) render(error.vehicleState); message(error.message, "error"); }
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
    requestedSource = "navigation";
    try {
      const state = await request("/api/vehicle-control/exit", { session_id: sessionId });
      // 退出请求一经车端接受，浏览器就不再维持会话；车端仍保持 STOP，直到
      // /control_source_state 实际确认 navigation。
      sessionId = null;
      render(state);
    }
    catch (error) { requestedSource = null; if (error.vehicleState) render(error.vehicleState); message(error.message, "error"); }
  }

  async function requestNavigation() {
    if (!window.confirm("确认请求切换至自动驾驶？\n\n页面会等待 /control_source_state=navigation 的实际回报，再显示结果。")) return;
    message("正在请求车端切换至自动驾驶…");
    requestedSource = "navigation";
    try {
      render(await request("/api/vehicle-control/navigation", {}));
    } catch (error) { requestedSource = null; if (error.vehicleState) render(error.vehicleState); message(error.message, "error"); }
  }

  async function heartbeat() {
    if (!sessionId) return;
    try { render(await request("/api/vehicle-control/heartbeat", { session_id: sessionId })); }
    catch (error) { clearHeld(); if (error.vehicleState) render(error.vehicleState); message(error.message, "error"); }
  }

  function leavePageSafely() {
    clearHeld();
    if (!sessionId) return;
    const payload = new Blob([JSON.stringify({ session_id: sessionId })], { type: "application/json" });
    navigator.sendBeacon?.("/api/vehicle-control/exit", payload);
  }

  $("enterManual").addEventListener("click", enterManual);
  $("requestNavigation").addEventListener("click", requestNavigation);
  $("exitManual").addEventListener("click", exitManual);
  $("stopButton").addEventListener("click", stop);
  $("releaseEmergencyStop").addEventListener("click", releaseEmergencyStop);
  $("saveChassisParameters").addEventListener("click", saveChassisParameters);
  $("editKeyBindings").addEventListener("click", openKeyBindingDialog);
  $("closeKeyBindings").addEventListener("click", closeKeyBindingDialog);
  $("doneKeyBindings").addEventListener("click", closeKeyBindingDialog);
  $("resetKeyBindings").addEventListener("click", resetKeyboardBindings);
  document.querySelectorAll("[data-key-binding-command]").forEach((button) => {
    button.addEventListener("click", () => startKeyBindingCapture(button.dataset.keyBindingCommand));
  });
  $("keyBindingDialog").addEventListener("cancel", (event) => {
    if (!capturingKeyBindingCommand) return;
    event.preventDefault();
    cancelKeyBindingCapture();
  });
  $("keyBindingDialog").addEventListener("close", () => {
    capturingKeyBindingCommand = null;
    renderKeyboardBindings();
  });
  driveButtons.forEach((button) => {
    button.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      button.setPointerCapture?.(event.pointerId);
      beginHold(`pointer:${event.pointerId}`, button.dataset.command);
    });
    ["pointerup", "pointercancel", "lostpointercapture"].forEach((eventName) => button.addEventListener(eventName, (event) => {
      releaseHold(`pointer:${event.pointerId}`);
    }));
  });
  document.addEventListener("keydown", (event) => {
    if (keyBindingDialogPending) {
      const command = commandForKeyboardCode(event.code, keyboardBindings);
      if (command || event.key === " " || event.key === "Escape") event.preventDefault();
      return;
    }
    if ($("keyBindingDialog").open) {
      if (!capturingKeyBindingCommand || event.repeat) return;
      event.preventDefault();
      if (event.code === "Escape") cancelKeyBindingCapture();
      else if (event.ctrlKey || event.metaKey || event.altKey) setKeyBindingMessage("请不要组合 Ctrl、Alt 或系统快捷键。", "error");
      else applyCapturedKeyBinding(event.code);
      return;
    }
    if (event.repeat || event.target.matches("input, textarea, select")) return;
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.key === " " || event.key === "Escape") { event.preventDefault(); stop(); return; }
    const command = commandForKeyboardCode(event.code, keyboardBindings);
    if (!command || !lastStatus?.manual_ready || !sessionId) return;
    event.preventDefault();
    beginHold(`key:${event.code}`, command);
  });
  document.addEventListener("keyup", (event) => {
    if ($("keyBindingDialog").open) return;
    if (!commandForKeyboardCode(event.code, keyboardBindings) || !lastStatus?.manual_ready || !sessionId) return;
    event.preventDefault();
    releaseHold(`key:${event.code}`);
  });
  document.addEventListener("visibilitychange", () => { if (document.hidden) stop(); });
  window.addEventListener("blur", stop);
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
  renderKeyboardBindings();
  statusTimer = window.setInterval(refresh, 350);
  heartbeatTimer = window.setInterval(heartbeat, 250);
  refresh();
  window.addEventListener("unload", () => { window.clearInterval(statusTimer); window.clearInterval(heartbeatTimer); if (speedTimer) window.clearTimeout(speedTimer); });
})();
