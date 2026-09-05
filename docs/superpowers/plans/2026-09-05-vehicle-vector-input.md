# 车辆连续向量输入与移动驾驶台实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Flutter 移动端提供安全、连续的双轴手动驾驶摇杆，并在不修改 PC Web 四方向控制页面的前提下由 Backend 新增受控向量输入接口。

**Architecture:** `VehicleControlController` 继续是唯一的 ROS Twist 发布者。新增 `/api/vehicle-control/vector` 只接受会话内的归一化线性/转向比例，在车端按当前已验证速度档换算目标速度；旧 command 目标与新 vector 目标互斥。Flutter 通过 Repository → Riverpod Controller → 直接操控页面调用新接口，所有离开、回中和安全锁定仍走 STOP。

**Tech Stack:** Python 3 / Pixi / ROS2 `geometry_msgs/Twist`、HTTP JSON、Flutter 3.47.1 / Dart / Riverpod / `CustomPaint`。

**Spec:** `docs/superpowers/specs/2026-09-05-vehicle-vector-input-design.md`

## Global Constraints

- PC Web 的 `autodrive_console/web/manual-control.html`、`manual_control.js` 与 `manual_control.css` 不得修改；继续使用既有四方向 `/command`。
- Mobile 和 Web 不得直接访问 ROS Topic；仅 Backend 产生 Twist。
- `linear_ratio` 与 `angular_ratio` 必须是有限 `[-1.0, 1.0]` 数值；`(0,0)` 清除运动并走已有 STOP 路径。
- 保持会话、控制源确认、急停、350ms 输入看门狗、1200ms 心跳、STOP→EXIT 和 `stop_acc` 语义。
- Flutter 仅使用 FVM 3.47.1；本地 widget 测试用例需要清除 HTTP(S)_PROXY，避免代理影响 loopback 测试服务器。
- 不提交构建产物、缓存、签名材料、日志、地图或 Golden failure 图片；不自动创建 Git 提交。

---

## 文件结构

| 文件 | 责任 |
| --- | --- |
| `autodrive_console/vehicle_control.py` | 受控向量状态、校验、速度换算与统一 STOP 清理。 |
| `web_console.py` | 将 `/api/vehicle-control/vector` 适配到控制器；不让 HTTP 层接触 ROS。 |
| `tests/test_vehicle_control.py` | Backend 向量、HTTP、安全门控及旧 command 回归。 |
| `shared/contracts/robot_control.md` | 唯一接口事实来源、消费者影响与验证矩阵。 |
| `mobile/lib/features/manual_control/domain/vehicle_control_state.dart` | 可测试的摇杆轴向量、范围/中心死区和车体坐标映射。 |
| `mobile/lib/features/manual_control/data/manual_control_repository.dart` | `/vector` HTTP 请求。 |
| `mobile/lib/features/manual_control/application/manual_control_controller.dart` | 持续向量续传、回中 STOP、速度与参数保存协调。 |
| `mobile/lib/features/manual_control/presentation/manual_control_screen.dart` | Apple 风格移动驾驶台、连续摇杆、速度区与高级参数面板。 |
| `mobile/test/features/manual_control/**` | Domain、Repository、Controller 与 UI 行为测试。 |
| `mobile/docs/*`、`docs/UI_SPEC.md`、`PROJECT_OVERVIEW.md` | 移动控制边界、视觉与开发文档。 |

### Task 1: Backend 连续向量状态机

**Files:**
- Modify: `tests/test_vehicle_control.py`
- Modify: `autodrive_console/vehicle_control.py`

**Interfaces:**
- Produces: `VehicleControlController.set_vector(session_id, linear_ratio, angular_ratio) -> dict[str, Any]`。
- Consumes: 既有有效 session、`_linear_speed`、`_angular_speed`、`_clear_motion_locked()` 与统一 Twist 发布路径。

- [ ] **Step 1: 写入失败的安全与换算测试**

```python
def test_vector_scales_both_axes_and_reapplies_after_speed_change(self):
    self._confirm_emergency_normal()
    self.control._on_source_state(SimpleNamespace(data="miniapp"))
    session_id = self.control.begin_manual_session()["session"]["id"]
    self.control.set_speed(session_id, 0.8, 0.6)
    self.control.set_vector(session_id, 0.5, -0.75)
    self.control._on_publish_tick()
    twist = self.control._velocity_publisher.messages[-1]
    self.assertEqual((twist.linear.x, twist.angular.z), (0.4, -0.45))

    self.control.set_speed(session_id, 0.4, 0.8)
    self.control._on_publish_tick()
    twist = self.control._velocity_publisher.messages[-1]
    self.assertEqual((twist.linear.x, twist.angular.z), (0.2, -0.6))

def test_vector_zero_latches_stop_and_invalid_or_unsafe_vectors_are_rejected(self):
    self._confirm_emergency_normal()
    self.control._on_source_state(SimpleNamespace(data="miniapp"))
    session_id = self.control.begin_manual_session()["session"]["id"]
    self.control.set_vector(session_id, 1.0, 1.0)
    self.control.set_vector(session_id, 0.0, 0.0)
    stop = self.control._velocity_publisher.messages[-1]
    self.assertEqual((stop.linear.x, stop.angular.z, stop.linear.z), (0.0, 0.0, 1200.0))
    with self.assertRaises(VehicleControlError):
        self.control.set_vector(session_id, math.nan, 0.0)
    with self.assertRaises(VehicleControlError):
        self.control.set_vector(session_id, 1.1, 0.0)
    self.control._on_emergency_stop(SimpleNamespace(data=True))
    with self.assertRaises(VehicleControlConflict):
        self.control.set_vector(session_id, 0.5, 0.5)
```

- [ ] **Step 2: 运行测试并确认因缺少接口失败**

Run: `env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest -q tests/test_vehicle_control.py -k vector`

Expected: FAIL，`VehicleControlController` 没有 `set_vector`。

- [ ] **Step 3: 以最小状态扩展实现向量目标**

```python
def set_vector(self, session_id: str, linear_ratio: object, angular_ratio: object) -> dict[str, Any]:
    linear = self._validated_ratio(linear_ratio, "线速度比例")
    angular = self._validated_ratio(angular_ratio, "转向速度比例")
    # 在与 set_command 相同的安全前置条件下：
    # (0,0) 调用 _clear_motion_locked；否则保存 _target_vector，
    # 清除 _target_command，按当前两个配置速度换算 target，并刷新输入/心跳时间。
```

新增 `_target_vector: tuple[float, float] | None`、`_apply_target_vector_locked()` 与 `_validated_ratio()`；`set_command()` 清除 `_target_vector`，`set_speed()` 对当前 vector 重新换算，`stop()`、`end_manual_session()`、超时、急停、外部切源和 `_clear_motion_locked()` 均清除它。严禁在控制器之外发布 Twist。

- [ ] **Step 4: 运行定向 Backend 测试**

Run: `env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest -q tests/test_vehicle_control.py -k vector`

Expected: PASS，验证右上产生正线速度和负角速度，零向量使用 STOP，旧四方向 command 未回归。

### Task 2: HTTP 路由与 PC 兼容回归

**Files:**
- Modify: `tests/test_vehicle_control.py`
- Modify: `web_console.py`
- Do not modify: `autodrive_console/web/manual-control.html`
- Do not modify: `autodrive_console/web/manual_control.js`
- Do not modify: `autodrive_console/web/manual_control.css`

**Interfaces:**
- Consumes: `VehicleControlController.set_vector()`。
- Produces: `POST /api/vehicle-control/vector`，请求体仅为 `session_id`、`linear_ratio`、`angular_ratio`。

- [ ] **Step 1: 写入失败的 HTTP 适配测试**

```python
def test_vector_action_passes_session_and_ratios_without_changing_command_route(self):
    handler = _vehicle_control_handler(
        "/api/vehicle-control/vector",
        {"session_id": "session-1", "linear_ratio": 0.8, "angular_ratio": -0.6},
    )
    controller = Mock()
    controller.set_vector.return_value = {"transition": None, "emergency_stop": {"release": "idle"}}
    with patch.object(web_console, "VEHICLE_CONTROL", controller):
        handler._vehicle_control_action(handler.path)
    controller.set_vector.assert_called_once_with("session-1", 0.8, -0.6)
    self.assertEqual(handler._json.call_args.args[1], HTTPStatus.OK)
```

- [ ] **Step 2: 运行测试并确认路由尚未存在**

Run: `env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest -q tests/test_vehicle_control.py -k vector_action`

Expected: FAIL，因为 mock 的 `set_vector` 尚未被调用。

- [ ] **Step 3: 添加单一 `/vector` 分支**

```python
elif path == "/api/vehicle-control/vector":
    payload = VEHICLE_CONTROL.set_vector(
        str(data.get("session_id", "")),
        data.get("linear_ratio"),
        data.get("angular_ratio"),
    )
```

保留请求大小、JSON 对象验证、现有异常到 HTTP 状态码的映射；不改 `/command` 分支，也不改变 Web 静态文件。

- [ ] **Step 4: 验证 Backend 与 PC Web 不受影响**

Run: `env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest -q tests/test_vehicle_control.py && pixi run test-offline && scripts/test-web.sh`

Expected: PASS。`git diff -- autodrive_console/web/manual-control.html autodrive_console/web/manual_control.js autodrive_console/web/manual_control.css` 无输出。

### Task 3: Shared Contract 更新

**Files:**
- Modify: `shared/contracts/robot_control.md`
- Modify: `PROJECT_OVERVIEW.md`

**Interfaces:**
- Consumes: 已测试的 `/vector` Backend 行为。
- Produces: Backend、PC 和 Mobile 的唯一事实来源与影响记录。

- [ ] **Step 1: 写入契约完整性测试/检查**

```bash
rg -n "POST /api/vehicle-control/vector|linear_ratio|angular_ratio|PC Web|Flutter Mobile" \
  shared/contracts/robot_control.md
```

Expected before edit: command returns no matching `/vector` line.

- [ ] **Step 2: 更新 Existing 契约与影响矩阵**

明确字段范围、比例换算、八个方向的符号、`(0,0)`、速度档重算、全部安全门控和消费者：Backend 新增接口、PC 保持旧 command、Mobile 使用 vector。将契约变更的必需检查列为 Backend、PC Web 回归和 Mobile 检查。

- [ ] **Step 3: 运行文档检查**

Run: `git diff --check && rg -n "POST /api/vehicle-control/vector|linear_ratio|angular_ratio" shared/contracts/robot_control.md`

Expected: PASS，且仅 Shared Contract 声明新接口。

### Task 4: Mobile 向量域、Repository 与会话续传

**Files:**
- Modify: `mobile/lib/features/manual_control/domain/vehicle_control_state.dart`
- Modify: `mobile/lib/features/manual_control/data/manual_control_repository.dart`
- Modify: `mobile/lib/features/manual_control/application/manual_control_controller.dart`
- Modify: `mobile/test/features/manual_control/domain/vehicle_control_state_test.dart`
- Modify: `mobile/test/features/manual_control/data/manual_control_repository_test.dart`
- Modify: `mobile/test/features/manual_control/application/manual_control_controller_test.dart`

**Interfaces:**
- Produces: `VehicleControlVector(linearRatio, angularRatio)`、`repository.vector(...)`、`controller.sendVector(...)`。
- Consumes: `/vector`、`ManualControlScreenState.canSendMotion`、现有 `stop()`、`setSpeed()` 与会话 ID。

- [ ] **Step 1: 写入失败的 Mobile 映射与续传测试**

```dart
test('upper right joystick vector maps to forward and right turn', () {
  final vector = VehicleControlVector.fromJoystick(const Offset(1, -1));
  expect(vector.linearRatio, greaterThan(0));
  expect(vector.angularRatio, lessThan(0));
});

test('controller streams the active vector and stops when it reaches center', () async {
  await controller.enter();
  await controller.sendVector(const VehicleControlVector(.8, -.6));
  await controller.sendVector(VehicleControlVector.stop);
  expect(repository.calls, containsAllInOrder(['vector:.8:-.6', 'stop']));
});
```

- [ ] **Step 2: 运行测试并确认因新类型/方法缺失失败**

Run: `env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy NO_PROXY=127.0.0.1,localhost,::1 fvm flutter test test/features/manual_control/domain test/features/manual_control/data test/features/manual_control/application -r compact`

Expected: FAIL，缺少向量类型、Repository 方法或 Controller 行为。

- [ ] **Step 3: 实现连续向量请求与安全停止**

```dart
Future<VehicleControlState> vector(
  RobotEndpoint endpoint,
  String sessionId,
  VehicleControlVector vector,
) => _post(endpoint, 'api/vehicle-control/vector', {
  'session_id': sessionId,
  ...vector.toJson(),
});
```

Controller 保存当前非零向量，并以 200ms 周期续传；新向量取代旧向量而不是排队。中心、松手、取消、失去权限、API 错误、后台和退出均取消定时器并调用现有 `stop()`；`setSpeed()` 成功后不丢失当前会话。

- [ ] **Step 4: 运行 Mobile 域/数据/控制器测试**

Run: 同 Step 2。

Expected: PASS，且不触发直接 ROS 访问。

### Task 5: Mobile 驾驶台 UI 与全部既有参数

**Files:**
- Modify: `mobile/lib/features/manual_control/presentation/manual_control_screen.dart`
- Modify: `mobile/test/features/manual_control/presentation/manual_control_screen_test.dart`
- Modify: `mobile/lib/debug_ui/gallery_manifest.dart`
- Modify: `mobile/lib/debug_ui/gallery_preview.dart`
- Modify: `mobile/test/debug_ui/gallery_golden_test.dart`（仅当场景登记需要）

**Interfaces:**
- Consumes: `sendVector()`、`stop()`、`setSpeed(linearMps, angularRadps)`、`saveChassisParameters()`。
- Produces: 连续摇杆、双速度输入、高级底盘参数保存面板与横竖屏稳定布局。

- [ ] **Step 1: 写入失败的组件测试**

```dart
testWidgets('upper right drag sends a forward right vector and center sends STOP', (tester) async {
  await enterConfirmedManualSession(tester);
  final joystick = find.bySemanticsLabel(RegExp('连续方向摇杆，当前停止'));
  final center = tester.getCenter(joystick);
  final gesture = await tester.startGesture(center);
  await gesture.moveTo(center.translate(72, -72));
  await tester.pump();
  expect(repository.calls, contains('vector:manual-session:positive:negative'));
  await gesture.moveTo(center);
  await tester.pump();
  expect(repository.calls.last, 'stop:manual-session');
  await gesture.up();
});

testWidgets('advanced chassis panel exposes all three bounded parameters and saves explicitly', (tester) async {
  await tester.tap(find.text('底盘参数'));
  expect(find.text('底盘压力'), findsOneWidget);
  expect(find.text('运动加速度'), findsOneWidget);
  expect(find.text('停止加速度'), findsOneWidget);
  expect(find.text('保存参数'), findsOneWidget);
});
```

另加横向 `MediaQuery` 尺寸测试，确保控制区、速度区和退出按钮均可见；急停 `unknown` 时摇杆必须无语义可操作入口。

- [ ] **Step 2: 运行测试并确认旧四方向摇杆不满足连续映射**

Run: `env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy NO_PROXY=127.0.0.1,localhost,::1 fvm flutter test test/features/manual_control/presentation/manual_control_screen_test.dart -r compact`

Expected: FAIL，旧组件未发出 vector，未展示完整参数面板。

- [ ] **Step 3: 重构为移动驾驶台**

使用 `CustomPaint` 或现有 Flutter 组合组件实现车头向上、连续双轴、1:1 位移、中心死区和可访问性标签。以更紧凑的页面层级替代重复卡片：顶部状态/退出、中央摇杆、双速度控制、显式保存的底盘高级面板、只有异常时突出的急停面板。保留白蓝日间主题与暗色主题；不添加装饰性循环动画。

- [ ] **Step 4: 运行组件、Gallery 与 Golden 检查**

Run: `dart run tool/generate_ui_docs.dart && env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy NO_PROXY=127.0.0.1,localhost,::1 fvm flutter test test/features/manual_control/presentation/manual_control_screen_test.dart test/debug_ui/gallery_golden_test.dart -r compact`

Expected: PASS。若设计基线有意变化，仅更新对应的受控 Golden 基线，不保留 failure 图片。

### Task 6: 文档、模拟器与全量验证

**Files:**
- Modify: `mobile/README.md`
- Modify: `mobile/docs/ARCHITECTURE.md`
- Modify: `mobile/docs/DESIGN_SYSTEM.md`
- Modify: `docs/UI_SPEC.md`
- Modify: `PROJECT_OVERVIEW.md`
- Modify: `docs/ui/SCREEN_INVENTORY.md`
- Modify: `docs/ui/SCREEN_MAP.md`

**Interfaces:**
- Consumes: 已通过测试的 Backend 接口与 Mobile 页面。
- Produces: 后续维护者可执行的方向映射、参数范围、PC 兼容与验证说明。

- [ ] **Step 1: 更新文档事实**

记录 `/vector` 仅由 Mobile 摇杆调用、PC 四方向不变、五项参数范围、STOP 生命周期、白蓝主题和横竖屏规则。不得把新接口写成 PC 的必经依赖。

- [ ] **Step 2: 启动 iPhone Simulator 并检查日间/暗色、竖屏/横屏**

Run: `xcrun simctl bootstatus booted -b`

Run: `HTTP_PROXY=http://127.0.0.1:7890 HTTPS_PROXY=http://127.0.0.1:7890 fvm flutter run -d "iPhone 17 Pro"`

Expected: 页面实际运行；右上拖动体现前进右转状态；中心、松手、锁定、参数面板和旋转后布局清晰，无溢出。

- [ ] **Step 3: 执行按消费者划分的最终回归**

Run:

```bash
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run test
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run test-offline
scripts/test-web.sh
scripts/test-mobile.sh
git diff --check
git diff -- autodrive_console/web/manual-control.html \
  autodrive_console/web/manual_control.js \
  autodrive_console/web/manual_control.css
```

Expected: 全部通过；最后一条 diff 命令没有输出，证明 PC Web 控制页未受影响。
