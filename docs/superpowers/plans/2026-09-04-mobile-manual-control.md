# 移动端手动操作实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变 PC Web、Backend 或 ROS 协议的前提下，为 Flutter App 增加安全的手动操作页面和四向触摸摇杆。

**Architecture:** 新增独立 `manual_control` feature，遵循现有 Repository → Riverpod Notifier → Production Page 结构。该 feature 只消费既有 `/api/vehicle-control*` 接口，Controller 持有短生命周期会话、轮询/心跳与停止优先的 App/路由收尾；页面只负责呈现状态和将摇杆手势映射为四个已有命令。

**Tech Stack:** Flutter 3.47.1、Dart、Riverpod、GoRouter、Material 3、`flutter_test`、现有 Debug UI Gallery、FVM、iOS Simulator。

**Spec:** `docs/superpowers/specs/2026-09-04-mobile-manual-control-design.md`

## Global Constraints

- 只修改 `mobile/` 和必需的 `shared/contracts/robot_control.md`、移动端文档；`frontend/`、`autodrive_console/`、`web_console.py` 必须保持零 diff。
- 不直连 ROS，不新增 HTTP endpoint，不改 Topic、速度、控制权或急停语义。
- 非零命令只允许 `forward`、`backward`、`left`、`right`；状态 `emergency_stop.state != normal`、没有会话或 `manual_ready == false` 时绝不发送。
- 所有离开/取消/后台/断线收尾严格执行 `stop`，然后尽力 `exit`；Backend 看门狗和急停状态是最终权威。
- 一级导航继续是首页、观测、工具、设置；路由只新增 `/tools/manual-control`。
- 新页面必须具有 production loading/未连接/不可用/急停/错误状态、Gallery mock、定向测试、必要 Golden、生成的 UI 文档和 iPhone 17 Pro 横竖屏检查。
- 不提交构建产物、缓存、日志、签名材料、地图、现场数据或 `mobile/test/debug_ui/failures/` 中现有的用户失败图。

---

## 文件结构

| 路径 | 责任 |
| --- | --- |
| `mobile/lib/features/manual_control/domain/vehicle_control_state.dart` | 后端快照、会话、急停、速度、底盘参数与命令枚举的纯 Dart 解析。 |
| `mobile/lib/features/manual_control/data/manual_control_repository.dart` | 既有受控 vehicle-control HTTP 调用；不管理计时器。 |
| `mobile/lib/features/manual_control/application/manual_control_controller.dart` | endpoint、会话 ID、轮询、心跳、epoch、lifecycle 与 stop/exit 收尾。 |
| `mobile/lib/features/manual_control/presentation/manual_control_screen.dart` | 生产页面、状态卡、操作确认、速度、摇杆与高级参数 Sheet。 |
| `mobile/lib/features/manual_control/presentation/widgets/directional_joystick.dart` | Pointer capture、死区与四向映射；不调用 HTTP。 |
| `mobile/lib/app/router.dart`、`mobile/lib/features/tools/presentation/tools_screen.dart`、`mobile/lib/app/app.dart` | 路由、工具入口、统一 App lifecycle 转交。 |
| `mobile/lib/app/theme/aletheia_theme.dart` | 将日间主题从绿青改为白蓝，不改变深色 HMI 默认主题。 |
| `mobile/lib/debug_ui/gallery_manifest.dart`、`mobile/lib/debug_ui/gallery_preview.dart` | 新页面及状态的真实 production Preview。 |
| `mobile/test/features/manual_control/**` | domain、repository/controller、widget 行为测试。 |
| `mobile/test/app/app_shell_layout_test.dart`、`mobile/test/app/aletheia_theme_test.dart` | 路由入口/主题关键语义回归。 |
| `shared/contracts/robot_control.md` 与 Mobile 文档 | Mobile Existing 消费、页面边界和验证方式。 |

---

### Task 1: 受控控制领域模型

**Files:**
- Create: `mobile/lib/features/manual_control/domain/vehicle_control_state.dart`
- Create: `mobile/test/features/manual_control/domain/vehicle_control_state_test.dart`

**Interfaces:**
- Consumes: `GET /api/vehicle-control` 和所有 vehicle-control action 的既有 JSON 快照。
- Produces: `VehicleControlState.fromJson(Map<String, dynamic>)`、`VehicleCommand`、`EmergencyStopState`、`VehicleControlSession`、`VehicleSpeed`、`ChassisParameters`。

- [ ] **Step 1: 写入会失败的领域解析测试**

```dart
test('decodes a backend-confirmed manual-ready state', () {
  final state = VehicleControlState.fromJson(_readyPayload(sessionId: 'a' * 32));
  expect(state.manualReady, isTrue);
  expect(state.session.id, 'a' * 32);
  expect(state.emergency.state, EmergencyStopState.normal);
  expect(state.canSendMotion, isTrue);
});

test('fails closed when the emergency status is absent or unknown', () {
  final state = VehicleControlState.fromJson({'manual_ready': true});
  expect(state.emergency.state, EmergencyStopState.unknown);
  expect(state.canSendMotion, isFalse);
});

test('exposes only the four backend motion commands', () {
  expect(VehicleCommand.values, {
    VehicleCommand.forward,
    VehicleCommand.backward,
    VehicleCommand.left,
    VehicleCommand.right,
  });
});
```

- [ ] **Step 2: 运行测试并确认因类型不存在而失败**

Run: `cd mobile && fvm flutter test test/features/manual_control/domain/vehicle_control_state_test.dart -r compact`
Expected: FAIL，提示 `VehicleControlState` 或导入目标不存在。

- [ ] **Step 3: 实现最小不可变模型与 fail-closed 解析**

```dart
bool get motionPermittedByBackend =>
    manualReady && emergency.state == EmergencyStopState.normal;

factory EmergencyStop.fromJson(Object? value) {
  final map = value is Map ? value : const <Object?, Object?>{};
  return EmergencyStop(
    state: EmergencyStopState.fromWire(map['state']),
    release: EmergencyReleaseState.fromWire(map['release']),
  );
}
```

仅接收后端定义的字符串，未知/缺字段均映射为不可运动状态；会话 ID 只接受非空字符串，不生成或缓存伪造 ID。普通轮询没有 ID 是后端既有语义，Controller 必须同时检查该模型的 `motionPermittedByBackend` 和自身持有的 enter 会话 ID。

- [ ] **Step 4: 运行领域测试并确认通过**

Run: `cd mobile && fvm flutter test test/features/manual_control/domain/vehicle_control_state_test.dart -r compact`
Expected: PASS。

- [ ] **Step 5: 格式化本任务文件**

Run: `cd mobile && dart format lib/features/manual_control/domain/vehicle_control_state.dart test/features/manual_control/domain/vehicle_control_state_test.dart`

### Task 2: 受控 HTTP Repository

**Files:**
- Create: `mobile/lib/features/manual_control/data/manual_control_repository.dart`
- Create: `mobile/test/features/manual_control/data/manual_control_repository_test.dart`

**Interfaces:**
- Consumes: `AletheiaApiClient`、`RobotEndpoint` 与 Task 1 的 `VehicleControlState`、`VehicleCommand`、`ChassisParameters`。
- Produces: `status`、`enter`、`heartbeat`、`command`、`setSpeed`、`stop`、`exit`、`releaseEmergencyStop`、`saveChassisParameters`，各方法均返回 `Future<VehicleControlState>`。

- [ ] **Step 1: 写入请求路径与 payload 的失败测试**

使用 `package:http/testing.dart` 的 `MockClient` 构造真实
`AletheiaApiClient` 与 `ManualControlRepository`；callback 记录 `http.Request` 的
`url.path` 和 JSON body，并返回最小合法 `VehicleControlState` payload。验证：

```dart
expect(request.path, 'api/vehicle-control/command');
expect(request.body, {
  'session_id': 'session-1',
  'command': 'forward',
});

expect(releaseRequest.path, 'api/vehicle-control/release-emergency-stop');
expect(releaseRequest.body, isEmpty);
```

另覆盖 `exit`、`stop` 和 chassis save 精确字段 `{press, movement_acc, stop_acc}`，确保 Repository 从不传路径、ROS 数据或前端扩展字段。

- [ ] **Step 2: 运行测试并确认因 Repository 不存在而失败**

Run: `cd mobile && fvm flutter test test/features/manual_control/data/manual_control_repository_test.dart -r compact`
Expected: FAIL，提示 Repository 不存在。

- [ ] **Step 3: 最小实现 Repository**

```dart
Future<VehicleControlState> command(
  RobotEndpoint endpoint,
  String sessionId,
  VehicleCommand command,
) async {
  final payload = await _apiClient.postJson(endpoint, 'api/vehicle-control/command',
      body: {'session_id': sessionId, 'command': command.wireName});
  return VehicleControlState.fromJson(payload);
}
```

所有 HTTP URL 只能通过 `AletheiaApiClient` 与 `RobotEndpoint` 构造；不在 Repository 吞掉 `ApiException`。

- [ ] **Step 4: 运行 Repository 测试并确认通过**

Run: `cd mobile && fvm flutter test test/features/manual_control/data/manual_control_repository_test.dart -r compact`
Expected: PASS。

- [ ] **Step 5: 格式化本任务文件**

Run: `cd mobile && dart format lib/features/manual_control/data/manual_control_repository.dart test/features/manual_control/data/manual_control_repository_test.dart`

### Task 3: 会话、轮询、心跳和安全收尾 Controller

**Files:**
- Create: `mobile/lib/features/manual_control/application/manual_control_controller.dart`
- Create: `mobile/test/features/manual_control/application/manual_control_controller_test.dart`
- Modify: `mobile/lib/app/app.dart`

**Interfaces:**
- Consumes: Task 1 模型、Task 2 Repository、`robotConnectionControllerProvider`。
- Produces: `manualControlControllerProvider`、`ManualControlScreenState`，公开 `refresh()`、`enter()`、`sendCommand(VehicleCommand)`、`setSpeed()`、`stop()`、`exit()`、`releaseEmergencyStop()`、`saveChassisParameters()`、`pauseForLifecycle()`、`resumeAfterLifecycle()`。

- [ ] **Step 1: 写入会失败的 Controller 测试**

```dart
test('releases an active session in STOP then EXIT order', () async {
  final controller = container.read(manualControlControllerProvider.notifier);
  await controller.exit();
  expect(repository.calls, ['stop:session-1', 'exit:session-1']);
});

test('does not send motion when the newest state is emergency unknown', () async {
  await controller.sendCommand(VehicleCommand.forward);
  expect(repository.motionCalls, isEmpty);
});

test('drops an old endpoint response after endpoint changes', () async {
  final first = controller.refresh();
  reconnectTo(secondEndpoint);
  completeFirstRequest(_readyPayload());
  await first;
  expect(controller.state.status, isNull);
});
```

另覆盖：进入后在后端 `manual_ready=false` 时不能运动；指令网络失败后立即 stop 并清空本地 held command；`pauseForLifecycle()` 对有会话执行收尾且取消 timer；`resumeAfterLifecycle()` 只刷新状态、不自动重新进入控制。

- [ ] **Step 2: 运行 Controller 测试并确认因 provider 不存在而失败**

Run: `cd mobile && fvm flutter test test/features/manual_control/application/manual_control_controller_test.dart -r compact`
Expected: FAIL，提示 provider/Controller 不存在。

- [ ] **Step 3: 以 Notifier 实现安全状态机**

```dart
Future<void> _releaseActiveSession() async {
  final sessionId = _sessionId;
  _cancelTimers();
  _heldCommand = null;
  if (sessionId == null || _endpoint == null) return;
  try { await _repository.stop(_endpoint!, sessionId); } catch (_) {}
  try { await _repository.exit(_endpoint!, sessionId); } catch (_) {}
  _sessionId = null;
}
```

每个异步动作捕获开始时的 endpoint 与递增 request epoch；完成时二者不一致则丢弃响应。保活间隔应低于后端 1200ms watchdog，输入重复应低于后端 350ms watchdog；仅在 `canSendMotion` 时启动。`catch` 只能用于收尾 best-effort，主动作必须将可读 `ApiException` 写回页面状态。

- [ ] **Step 4: 将 App lifecycle 转交给该 Controller**

在 `AletheiaApp.didChangeAppLifecycleState` 中，和既有 test-runs 暂停/恢复并列调用：恢复仅 `resumeAfterLifecycle()`；其他状态调用 `pauseForLifecycle()`。不要改动既有连接、观测或测试运行逻辑。

- [ ] **Step 5: 运行 Controller 测试并确认通过**

Run: `cd mobile && fvm flutter test test/features/manual_control/application/manual_control_controller_test.dart -r compact`
Expected: PASS。

- [ ] **Step 6: 格式化本任务文件**

Run: `cd mobile && dart format lib/features/manual_control/application/manual_control_controller.dart test/features/manual_control/application/manual_control_controller_test.dart ../mobile/lib/app/app.dart`

### Task 4: 可测试的四向触摸摇杆

**Files:**
- Create: `mobile/lib/features/manual_control/presentation/widgets/directional_joystick.dart`
- Create: `mobile/test/features/manual_control/presentation/widgets/directional_joystick_test.dart`

**Interfaces:**
- Consumes: `VehicleCommand` 与 `enabled`、`onCommandStart(VehicleCommand)`、`onCommandStop()` 回调。
- Produces: `DirectionalJoystick`，无网络、Provider 或车端依赖。

- [ ] **Step 1: 写入会失败的 Pointer 行为测试**

```dart
testWidgets('maps an upward drag outside the dead zone to forward', (tester) async {
  await tester.pumpWidget(harness(onStart: started.add, onStop: stopped.add));
  final center = tester.getCenter(find.byType(DirectionalJoystick));
  final gesture = await tester.startGesture(center);
  await gesture.moveTo(center - const Offset(0, 56));
  expect(started, [VehicleCommand.forward]);
  await gesture.up();
  expect(stopped, hasLength(1));
});

testWidgets('keeps a drag inside the dead zone stopped', (tester) async {
  await tester.pumpWidget(harness(onStart: started.add, onStop: stopped.add));
  final center = tester.getCenter(find.byType(DirectionalJoystick));
  final gesture = await tester.startGesture(center);
  await gesture.moveTo(center + const Offset(8, 0));
  await gesture.up();
  expect(started, isEmpty);
  expect(stopped, hasLength(1));
});
```

另覆盖 disabled 时完全无回调、横向占优映射 left/right、`cancel` 触发 stop、从前进拖到右侧时只切换一次方向。

- [ ] **Step 2: 运行测试并确认因 Widget 不存在而失败**

Run: `cd mobile && fvm flutter test test/features/manual_control/presentation/widgets/directional_joystick_test.dart -r compact`
Expected: FAIL，提示 `DirectionalJoystick` 不存在。

- [ ] **Step 3: 最小实现直接操控 Widget**

使用 `Listener` 的 `onPointerDown/Move/Up/Cancel` 记录唯一 active pointer ID；后续事件只处理该 ID，其他触点不影响当前控制。以控件半径的固定比例定义死区，用 `abs(dx) >= abs(dy)` 决定横/纵轴，当前命令未改变时不重复触发 `onCommandStart`。手势结束总是调用 `onCommandStop`，视觉 thumb 以 `AnimatedContainer` 的短无过冲归位，减少动态效果时不应用弹性。

- [ ] **Step 4: 运行摇杆测试并确认通过**

Run: `cd mobile && fvm flutter test test/features/manual_control/presentation/widgets/directional_joystick_test.dart -r compact`
Expected: PASS。

- [ ] **Step 5: 格式化本任务文件**

Run: `cd mobile && dart format lib/features/manual_control/presentation/widgets/directional_joystick.dart test/features/manual_control/presentation/widgets/directional_joystick_test.dart`

### Task 5: 生产页面、路由和工具入口

**Files:**
- Create: `mobile/lib/features/manual_control/presentation/manual_control_screen.dart`
- Create: `mobile/test/features/manual_control/presentation/manual_control_screen_test.dart`
- Modify: `mobile/lib/app/router.dart`
- Modify: `mobile/lib/features/tools/presentation/tools_screen.dart`

**Interfaces:**
- Consumes: Tasks 1–4、`manualControlControllerProvider`、`DirectionalJoystick`、`AletheiaMotion.detailPage`。
- Produces: `ManualControlScreen.routePath = '/tools/manual-control'`，工具入口“手动操作”。

- [ ] **Step 1: 写入会失败的页面和入口测试**

```dart
testWidgets('shows a connection requirement before reading controls', (tester) async {
  await tester.pumpWidget(buildScreen(connection: disconnected));
  expect(find.text('请先连接机器人'), findsOneWidget);
  expect(find.byType(DirectionalJoystick), findsNothing);
});

testWidgets('renders the joystick only after backend confirms manual ready', (tester) async {
  await tester.pumpWidget(buildScreen(state: readyState));
  expect(find.byType(DirectionalJoystick), findsOneWidget);
  expect(find.text('结束操作'), findsOneWidget);
});
```

覆盖：急停 triggered/unknown 禁用摇杆；开始操作需要显式确认；长按解除按钮不能在 `normal` 使用；高级参数保存前校验整数范围；退出路由时调用 Controller 收尾；工具入口在未连接时跳转连接页。

- [ ] **Step 2: 运行页面测试并确认因页面/路由不存在而失败**

Run: `cd mobile && fvm flutter test test/features/manual_control/presentation/manual_control_screen_test.dart -r compact`
Expected: FAIL，提示页面、route 或 tools entry 不存在。

- [ ] **Step 3: 实现页面和确认交互**

页面使用 production `SafeArea`、`RefreshIndicator`、有限宽度 workspace 和 `LayoutBuilder`。开始操作、结束操作、长按解除急停、保存底盘参数均用明确目标/后果的确认 Sheet 或 Dialog。急停 unknown/triggered 以阻断状态卡优先展示；普通 STOP 使用独立显著但非破坏性按钮。摇杆只在 `state.canSendMotion` 时启用，回调依次调用 Controller 的 `sendCommand` 和 `stop`。

- [ ] **Step 4: 注册路由与工具入口**

在现有 ShellRoute 下注册 `ManualControlScreen` 的 detail page；仅在 `ToolsScreen` 增加“手动操作”卡片。不要修改四个一级 destination、PC Web 文件或 Backend。

- [ ] **Step 5: 运行页面与 Shell 定向测试并确认通过**

Run: `cd mobile && fvm flutter test test/features/manual_control/presentation/manual_control_screen_test.dart test/app/app_shell_layout_test.dart -r compact`
Expected: PASS。

- [ ] **Step 6: 格式化本任务文件**

Run: `cd mobile && dart format lib/features/manual_control/presentation/manual_control_screen.dart lib/app/router.dart lib/features/tools/presentation/tools_screen.dart test/features/manual_control/presentation/manual_control_screen_test.dart`

### Task 6: 白蓝日间主题与 UI Gallery

**Files:**
- Modify: `mobile/lib/app/theme/aletheia_theme.dart`
- Modify: `mobile/test/app/aletheia_theme_test.dart`
- Modify: `mobile/lib/debug_ui/gallery_manifest.dart`
- Modify: `mobile/lib/debug_ui/gallery_preview.dart`
- Modify: `mobile/test/debug_ui/debug_ui_gallery_screen_test.dart`
- Modify: `mobile/test/debug_ui/gallery_golden_test.dart` only if its harness requires a new explicit assertion; do not edit existing Golden failure images.

**Interfaces:**
- Consumes: Existing `AppThemePreference.daylight` and Task 5 production page.
- Produces: Semantic white-blue daylight palette and Gallery specs for manual-control disconnected, ready, emergency-triggered and release-waiting states.

- [ ] **Step 1: 写入会失败的主题与 Gallery 覆盖测试**

```dart
test('daylight keeps a white canvas and blue primary action', () {
  final theme = AletheiaTheme.light();
  expect(theme.scaffoldBackgroundColor, const Color(0xFFF7F9FC));
  expect(theme.colorScheme.primary, const Color(0xFF0A66D1));
});

test('gallery manifest contains the manual-control safety states', () {
  expect(galleryScreenManifest.map((item) => item.id), containsAll([
    'manual_control_disconnected',
    'manual_control_ready',
    'manual_control_emergency_triggered',
    'manual_control_release_waiting',
  ]));
});
```

- [ ] **Step 2: 运行定向测试并确认失败**

Run: `cd mobile && fvm flutter test test/app/aletheia_theme_test.dart test/debug_ui/debug_ui_gallery_screen_test.dart -r compact`
Expected: FAIL，直到白蓝 token 与 Gallery 条目实际存在。

- [ ] **Step 3: 最小更新主题与 Gallery Preview**

仅替换 `_daylight` 的语义 token 为白蓝体系（浅白 canvas/surface、Apple 蓝 primary、可访问文本/边框、原有 warning/danger 语义保持）。新增 `GallerySurface.manualControl` 枚举值，在 `DebugGalleryPreview` 中用真实 `ManualControlScreen` 加 mock provider 构造四种状态；不复制静态页面。

- [ ] **Step 4: 运行 Gallery 与主题测试并确认通过**

Run: `cd mobile && fvm flutter test test/app/aletheia_theme_test.dart test/debug_ui/debug_ui_gallery_screen_test.dart -r compact`
Expected: PASS。

- [ ] **Step 5: 在 iPhone 17 Pro Simulator 进行实时 UI 检查**

Run:

```sh
xcrun simctl boot 07F538CE-2AF7-467B-BE8F-EF7B43643141 || true
open -a Simulator
cd mobile
fvm flutter run --debug -d 07F538CE-2AF7-467B-BE8F-EF7B43643141 \
  --dart-define=AV_DEBUG_ROUTE='/__debug/ui-gallery?screen=manual_control_ready'
```

在竖屏和横屏逐项检查白蓝主题、Safe Area、动态字体、44pt 触控区、摇杆拖动/松开、急停 mock 状态和 Sheet；记录任何布局或可达性问题后回到对应 TDD 任务修复。

### Task 7: 契约、移动端文档与全量验证

**Files:**
- Modify: `shared/contracts/robot_control.md`
- Modify: `mobile/README.md`
- Modify: `mobile/docs/ARCHITECTURE.md`
- Modify: `mobile/docs/DEVELOPMENT_WORKFLOW.md`
- Modify: `mobile/docs/DESIGN_SYSTEM.md`
- Modify: `docs/UI_SPEC.md`
- Generated: `docs/ui/SCREEN_INVENTORY.md`
- Generated: `docs/ui/SCREEN_MAP.md`

**Interfaces:**
- Consumes: 已实现的 route、Mobile 模型/Controller 与现有 vehicle-control contract。
- Produces: 唯一的 Mobile 控制事实来源、可复现开发/模拟器验证指引和 UI 清单。

- [ ] **Step 1: 更新契约和文档**

在 `robot_control.md` 中将 Mobile 标为 Existing 消费者，列出允许调用的 HTTP action、四向命令、后端控制权威、triggered/unknown fail-closed 和 `stop → exit` 客户端收尾；明确 Mobile 不直连 ROS、不能触发物理急停、不能发送任意向量或 `place`。同步移动端 route、feature 结构、Gallery 与 iPhone Simulator 命令；把日间主题描述改为白蓝，而非绿青。

- [ ] **Step 2: 生成 UI Inventory 与 Screen Map**

Run: `cd mobile && dart run tool/generate_ui_docs.dart`
Expected: `docs/ui/SCREEN_INVENTORY.md` 和 `docs/ui/SCREEN_MAP.md` 纳入新手动操作页面及四种状态。

- [ ] **Step 3: 运行完整 Mobile 检查**

Run:

```sh
scripts/test-mobile.sh
cd mobile
fvm flutter test --concurrency=1 -r compact
fvm flutter analyze
git diff --check
```

Expected: 全部命令退出 0。若现有用户 Golden failure 图导致工作树仍脏，只报告它们，不删除、重置或提交。

- [ ] **Step 4: 进行 diff 边界审查**

Run:

```sh
git diff --name-only | rg '^(frontend/|autodrive_console/|web_console\.py)' && exit 1 || true
git status --short
```

Expected: 不出现 PC Web 或 Backend 路径；保留并注明任务开始前已有的签名和 Golden failure 脏文件。

- [ ] **Step 5: 不自动提交**

本仓库当前存在用户本地修改。完成后仅报告精确 diff、验证结果和 Simulator 检查结果；除非用户明确要求，不执行 `git add`、`git commit` 或 `git push`。
