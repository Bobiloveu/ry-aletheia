# 手动控制急停与底盘参数 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变既有 miniapp / navigation 控制权、手动速度协议或建图逻辑的前提下，为现有车辆控制器加入真实急停门控、状态确认的软件解除急停和持久化底盘参数。

**Architecture:** 只扩展 `VehicleControlController`，使它继续拥有唯一 ROS2 node、executor、20 Hz timer 和安全 STOP 路径。`web_console.py` 保持为 HTTP 适配层，`SettingsStore` 是唯一的配置持久化入口；手动控制页渲染新增状态，建图工作台继续消费既有 `manual_ready`，无需重复控制实现。

**Tech Stack:** Python 3.10、ROS2 Humble (`std_msgs/Bool`、`std_msgs/String`、`geometry_msgs/Twist`)、原生 HTTP handler、现有 HTML/CSS/vanilla JavaScript、pytest、Pixi/Vite。

**Spec:** `docs/superpowers/specs/2026-09-03-vehicle-control-safety-extension-design.md`

## Global Constraints

- 不重新实现 `/cmd_vel_miniapp`、`/control_source_cmd`、`/control_source_state`、手动会话或控制权切换。
- `/is_emergency_stop` 是唯一的急停真值来源；未收到消息或运行时异常必须是 `unknown`，并 fail-closed。
- `/is_emergency_stop` 只订阅；绝不向它发布或伪造状态。
- `/command` 解除报文必须固定为 `{"speed":0.0,"angle":0.0,"acc":2000,"press":1400,"place":-1,"ulock":0}`，不读取用户配置，不新增 `place` UI/API。
- 非零手动 Twist 使用 `movement_acc`；任何零 Twist 使用 `stop_acc`；默认 `press=1400`、`movement_acc=1200`、`stop_acc=1200`，保持现有行为。
- `press` 为 20–2000，`movement_acc` 为 10–1000，`stop_acc` 为 20–2000；前端、Controller、SettingsStore 都校验。
- 急停解除不得发布控制源切换，也不得根据 String publish 成功显示解除成功；只允许 Bool false 回调确认。
- 只修改 Backend、正式 PC Web 控制页、文档和相应测试；Mobile、地图、任务、视频、MediaMTX、Supervisor 与实时观测不改。

---

### Task 1: 配置模型与共享控制契约

**Files:**
- Modify: `autodrive_console/settings.py:35-71, 106-220`
- Modify: `shared/contracts/robot_control.md:13-78`
- Modify: `PROJECT_OVERVIEW.md` 的机器人控制边界与配置事实章节
- Modify: `tests/test_offline_modules.py` 的 `SettingsStore` 测试区
- Modify: `tests/test_repository_conventions.py:104-130`

**Interfaces:**
- Produces `RobotSettings.vehicle_control: dict[str, int]`，键严格为 `press`、`movement_acc`、`stop_acc`。
- Produces契约中的 `emergency_stop` 状态字段、两个受控 HTTP endpoint 和 ROS topic 权限说明。
- Consumers: `web_console.py` 用持久化值初始化/更新 Controller；`vehicle_control.py` 使用已验证配置。

- [ ] **Step 1: 写入失败的 SettingsStore 边界与持久化测试**

```python
def test_vehicle_control_parameters_persist_and_reject_unsafe_values(self):
    with tempfile.TemporaryDirectory() as directory:
        store = SettingsStore(Path(directory) / "console.json")
        saved = store.save({"vehicle_control": {
            "press": 20, "movement_acc": 1000, "stop_acc": 2000,
        }})
        self.assertEqual(saved.vehicle_control["movement_acc"], 1000)
        self.assertEqual(store.load().vehicle_control["press"], 20)
        with self.assertRaisesRegex(ValueError, "运动加速度"):
            store.save({"vehicle_control": {
                "press": 1400, "movement_acc": 1001, "stop_acc": 1200,
            }})
```

- [ ] **Step 2: 运行失败测试并确认失败原因是字段不存在**

Run: `env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest -q tests/test_offline_modules.py -k vehicle_control_parameters_persist`

Expected: FAIL，`RobotSettings` 尚无 `vehicle_control` 或校验尚未生效。

- [ ] **Step 3: 实现默认、迁移与严格校验**

在 `RobotSettings` 增加：

```python
vehicle_control: dict = field(default_factory=lambda: {
    "press": 1400,
    "movement_acc": 1200,
    "stop_acc": 1200,
})
```

在 `SettingsStore._validate()` 读取这三个键，拒绝缺键、额外键、`bool`、非有限数、非整值或超出范围；保留旧文件不含该键时的默认合并行为。更新契约，明确 `/is_emergency_stop` 只读、`/command` 固定解除 payload、GET 状态增量字段、POST endpoint 与当前 Web 消费者；更新工程手册的控制边界，说明它不接管物理急停或底盘安全策略。

- [ ] **Step 4: 运行 Settings 与契约相关测试**

Run: `env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest -q tests/test_offline_modules.py tests/test_repository_conventions.py -k 'vehicle_control_parameters or robot_control_contract'`

Expected: PASS。

- [ ] **Step 5: 提交独立配置/契约变更**

```bash
git add autodrive_console/settings.py shared/contracts/robot_control.md PROJECT_OVERVIEW.md \
  tests/test_offline_modules.py tests/test_repository_conventions.py
git commit -m "feat: define vehicle control emergency settings"
```

### Task 2: Controller 急停状态机、固定解除命令和统一 acceleration 选择

**Files:**
- Modify: `autodrive_console/vehicle_control.py:35-64, 82-590`
- Modify: `tests/test_vehicle_control.py:47-164`

**Interfaces:**
- Consumes `VehicleControlController.update_chassis_parameters(parameters: dict[str, object]) -> None` 和启动时的已验证参数。
- Produces `status()["emergency_stop"]` 与 `status()["chassis_parameters"]`。
- Produces `release_emergency_stop() -> dict[str, Any]`；只有 `/is_emergency_stop=False` 回调确认结果。

- [ ] **Step 1: 写入失败的急停门控与 zero-Twist acceleration 测试**

```python
def test_unknown_or_triggered_emergency_stop_blocks_motion_and_uses_stop_acc(self):
    self.control._on_source_state(SimpleNamespace(data="miniapp"))
    self.assertFalse(self.control.status()["manual_ready"])
    self.control._on_emergency_stop(SimpleNamespace(data=False))
    session_id = self.control.begin_manual_session()["session"]["id"]
    self.control.set_command(session_id, "forward")
    self.control._on_publish_tick()
    self.assertEqual(self.control._velocity_publisher.messages[-1].linear.z, 1200.0)
    self.control._on_emergency_stop(SimpleNamespace(data=True))
    stop = self.control._velocity_publisher.messages[-1]
    self.assertEqual((stop.linear.x, stop.angular.z, stop.linear.z), (0.0, 0.0, 1200.0))
    with self.assertRaises(VehicleControlConflict):
        self.control.set_command(session_id, "forward")
```

- [ ] **Step 2: 写入失败的解除确认测试**

```python
def test_release_emergency_stop_requires_false_feedback_after_fixed_command(self):
    self.control._on_emergency_stop(SimpleNamespace(data=True))
    pending = self.control.release_emergency_stop()
    self.assertEqual(pending["emergency_stop"]["release"], "waiting_confirmation")
    self.assertEqual(
        self.control._command_publisher.messages[-1].data,
        '{"speed":0.0,"angle":0.0,"acc":2000,"press":1400,"place":-1,"ulock":0}',
    )
    self.assertNotEqual(pending["emergency_stop"]["release"], "confirmed")
    self.control._on_emergency_stop(SimpleNamespace(data=False))
    self.assertEqual(self.control.status()["emergency_stop"]["release"], "confirmed")
```

- [ ] **Step 3: 运行两项测试并确认因方法/状态尚不存在而失败**

Run: `env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest -q tests/test_vehicle_control.py -k 'emergency_stop'`

Expected: FAIL，`_on_emergency_stop`、`release_emergency_stop` 或状态字段不存在。

- [ ] **Step 4: 最小实现 Controller 状态机与 ROS 接入**

实现常量 `EMERGENCY_STOP_TOPIC = "/is_emergency_stop"`、`COMMAND_TOPIC = "/command"`、固定 `EMERGENCY_RELEASE_COMMAND` 和 `release_timeout_s = 4.0`。在 `_ensure_started()` 以 `Bool` 创建 `RELIABLE + VOLATILE` subscription、以 `String` 创建 `/command` publisher；不向 `/is_emergency_stop` 创建 publisher。

在 `_on_emergency_stop()` 中把初始 `None` 映射为 unknown，`True` 清空非零目标并在锁外发送 STOP，`False` 仅确认 waiting release，不恢复旧方向。扩展 `_manual_ready_locked()` 和 `can_begin_manual` 要求状态 `False`。将 `MiniappTwistFactory.build()` 改为根据零/非零速度选择 profile 的 `stop_acc` / `movement_acc`，确保 `_publish_stop_now()`、watchdog、exit、外部切源和 close 复用同一路径。`release_emergency_stop()` 仅在真实 true 发布固定 String，并由 `_advance_safety_locked()` 把超时记为 failed。

- [ ] **Step 5: 添加边界回归并运行 Controller 测试**

新增测试覆盖 false 后可进入、unknown/true 拒绝进入、重复解除拒绝、false 前不成功、4 秒超时失败、参数更新后运动/停止分别使用对应 acc、所有现有 `stop()`/输入 watchdog/`end_manual_session()` 零 Twist 使用 `stop_acc`。

Run: `env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest -q tests/test_vehicle_control.py`

Expected: PASS。

- [ ] **Step 6: 提交 Controller 变更**

```bash
git add autodrive_console/vehicle_control.py tests/test_vehicle_control.py
git commit -m "feat: gate vehicle control on emergency stop"
```

### Task 3: HTTP 适配、配置保存与跨页面门控回归

**Files:**
- Modify: `web_console.py:81-88, 741-785, 1085-1089`
- Modify: `tests/test_vehicle_control.py` 或新增 `tests/test_vehicle_control_http.py`

**Interfaces:**
- Consumes `SETTINGS.load().vehicle_control`，`SETTINGS.save({"vehicle_control": ...})`，Controller 的 release/update/status 方法。
- Produces `POST /api/vehicle-control/release-emergency-stop` 与 `POST /api/vehicle-control/chassis-parameters`。
- Existing consumers retain `GET /api/vehicle-control` and receive unchanged fields plus emergency/parameter fields.

- [ ] **Step 1: 写入失败的 HTTP action 测试**

```python
def test_vehicle_control_parameter_action_persists_then_updates_controller(tmp_path):
    handler = _vehicle_control_handler(
        "/api/vehicle-control/chassis-parameters",
        {"press": 1500, "movement_acc": 700, "stop_acc": 1800},
    )
    controller = Mock()
    controller.update_chassis_parameters.return_value = {"runtime": "ready"}
    with patch.object(web_console, "SETTINGS", SettingsStore(tmp_path / "console.json")), \
         patch.object(web_console, "VEHICLE_CONTROL", controller):
        handler._vehicle_control_action(handler.path)
    assert controller.update_chassis_parameters.call_args.args[0] == {
        "press": 1500, "movement_acc": 700, "stop_acc": 1800,
    }
```

`_vehicle_control_handler()` 使用现有测试模式：`object.__new__(web_console.ConsoleHandler)`、`io.BytesIO(json.dumps(payload).encode())`、`headers` 与 `Mock()` 的 `_json`，不启动 HTTP server 或 ROS2。

- [ ] **Step 2: 运行 HTTP action 测试并确认 endpoint 尚未找到**

Run: `env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest -q tests/test_vehicle_control.py -k chassis_parameters_action`

Expected: FAIL，因为 `/chassis-parameters` 尚未路由或未保存后更新 Controller。

- [ ] **Step 3: 实现受控 HTTP action**

在启动时用 `SETTINGS.load().vehicle_control` 构造 Controller profile。`/chassis-parameters` 先让 Controller 的纯校验函数规范化输入，再调用 `SETTINGS.save`；只在保存成功后调用 `VEHICLE_CONTROL.update_chassis_parameters()` 并返回状态。`/release-emergency-stop` 仅调用 Controller 的 release 方法。pending release 返回 `202 Accepted`；其他既有 endpoint 的状态码分支不变。`_settings()` 可返回持久化字段供维护 API 读取，但不得使无关页面写入或重置该字典。

- [ ] **Step 4: 扩展 HTTP 测试并运行**

增加测试：release 路由调用 Controller、pending 返回 202、越界参数返回 400 且不保存/不更新、Controller 拒绝 release 时返回 409、既有 `/speed` 与 `/exit` 仍调用原 Controller 方法。

Run: `env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest -q tests/test_vehicle_control.py`

Expected: PASS。

- [ ] **Step 5: 提交 HTTP 变更**

```bash
git add web_console.py tests/test_vehicle_control.py
git commit -m "feat: expose vehicle emergency control actions"
```

### Task 4: 手动控制页状态与参数界面

**Files:**
- Modify: `autodrive_console/web/manual-control.html:32-114`
- Modify: `autodrive_console/web/manual_control.js:1-245`
- Modify: `autodrive_console/web/manual_control.css:1-70`
- Modify: `tests/test_offline_modules.py` 的静态 Web 资源测试区

**Interfaces:**
- Consumes existing `GET /api/vehicle-control` status additions and the two new POST endpoints.
- Produces no new ROS/HTTP protocol and leaves mapping workbench untouched; its existing `manual_ready` use is the safety linkage.

- [ ] **Step 1: 写入失败的结构与安全渲染测试**

```python
def test_manual_control_exposes_emergency_state_and_bounded_chassis_parameters(self):
    page = (web_console.WEB_ROOT / "manual-control.html").read_text(encoding="utf-8")
    script = (web_console.WEB_ROOT / "manual_control.js").read_text(encoding="utf-8")
    self.assertIn('id="emergencyStopState"', page)
    self.assertIn('id="releaseEmergencyStop"', page)
    self.assertIn('id="movementAcc" min="10" max="1000"', page)
    self.assertIn('id="stopAcc" min="20" max="2000"', page)
    self.assertIn('/api/vehicle-control/release-emergency-stop', script)
    self.assertIn('/api/vehicle-control/chassis-parameters', script)
```

- [ ] **Step 2: 运行页面测试并确认缺少急停/参数元素**

Run: `env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest -q tests/test_offline_modules.py -k manual_control_exposes_emergency`

Expected: FAIL，因为当前页面没有急停读数、解除按钮或三个 number input。

- [ ] **Step 3: 最小扩展 HTML 与 CSS**

在已有“安全状态”面板上方新增状态块，含 `emergencyStopState`、描述文本和 `releaseEmergencyStop`；normal/triggered/unknown 有明确文本。紧接既有运动速度区放入无嵌套卡片的 `chassis-settings` 区：三个 label-on-top number input、范围提示和单一“保存参数”按钮。使用现有 token、8–12px 小圆角、边界/明度层级和现有响应式断点；不改原方向盘、速度控件、控制源按钮或页面网格。

- [ ] **Step 4: 最小扩展 JS 状态渲染与提交**

在 `render(state)` 中从 `state.emergency_stop` 显示 normal / triggered / unknown，release waiting 时禁用按钮且不显示成功；调用成功后的 `confirmed` 才显示确认文本。状态变成 triggered/unknown 时调用既有 `clearHeld()`，使浏览器不再保持按键 interval。新增 `renderChassisParameters()` 和 `saveChassisParameters()`：读取输入，先做有限数/范围前端检查，再 POST 三字段，使用后端响应重新渲染。页面刷新继续只调用已有 GET；不增加无界重试或 ROS 访问。

- [ ] **Step 5: 运行静态页面测试和 Web 构建**

Run: `env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest -q tests/test_offline_modules.py -k manual_control_exposes_emergency`

Expected: PASS。

Run: `node --check autodrive_console/web/manual_control.js`

Expected: exit 0。

Run: `./scripts/test-web.sh`

Expected: Web parity check and Vite production build PASS。

- [ ] **Step 6: 检查正式页面的窄屏和状态语义**

在本地控制台打开 `/manual-control.html`，一次检查桌面与 393px 窄屏：正常、触发、未知、等待解除、解除失败/确认的文字与按钮状态；确认 number input 标签、范围提示和焦点环可读，且不出现横向溢出。运行：

```bash
node /home/bob/.codex/skills/impeccable/scripts/detect.mjs --json \
  autodrive_console/web/manual-control.html \
  autodrive_console/web/manual_control.js \
  autodrive_console/web/manual_control.css
```

记录 detector 对无关既有问题的发现，但只修复本次文件中与新增控件直接相关的问题。

- [ ] **Step 7: 提交界面变更**

```bash
git add autodrive_console/web/manual-control.html autodrive_console/web/manual_control.js \
  autodrive_console/web/manual_control.css tests/test_offline_modules.py
git commit -m "feat: show emergency stop and chassis parameters"
```

### Task 5: 完整回归与实车交接

**Files:**
- Modify only if validation reveals a direct documentation inconsistency: `README.md` or `USER_GUIDE.md`
- Verify: modified files from Tasks 1–4

**Interfaces:**
- Confirms existing manual control and control source fields remain compatible.
- Produces an evidence-backed validation record and a bounded real-vehicle checklist; no new runtime interface.

- [ ] **Step 1: 运行完整自动化回归**

Run: `env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ./scripts/test-backend.sh`

Expected: all Backend tests PASS. If a pre-existing telemetry reconnect test times out, rerun that test once to distinguish its known connection-registration timing race from this feature; do not modify telemetry code in this feature branch.

Run: `./scripts/test-web.sh`

Expected: PASS。

Run: `git diff --check`

Expected: no whitespace errors。

- [ ] **Step 2: 检查变更边界与停止路径**

Run:

```bash
rg -n "place|/is_emergency_stop|/command|stop_acc|movement_acc" \
  autodrive_console/vehicle_control.py web_console.py \
  autodrive_console/web/manual-control.html autodrive_console/web/manual_control.js
```

Expected: no new place control UI/API; one fixed emergency String payload; all zero-Twist paths retain the shared factory.

- [ ] **Step 3: 提交最终回归记录（仅有文件变更时）**

若 Task 5 未修改文件，不创建空提交。若文档仅因发现直接不一致而修改：

```bash
git add README.md USER_GUIDE.md PROJECT_OVERVIEW.md
git commit -m "docs: record vehicle control emergency validation"
```

- [ ] **Step 4: 执行实车验收，不在无观察员情况下执行**

在安全场地、有物理急停和观察员时执行 Spec §9 的六项检查：topic QoS、false/true/unknown 门控、固定 `/command` 与 false 确认、所有 STOP 路径、参数重启持久化及建图工作台门控。任何 QoS 不兼容、状态不一致、非预期 `/command` 或非零 Twist 均停止测试，保留工具日志并回退到上一已签名发布包。
