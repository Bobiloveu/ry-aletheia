# Aletheia Mobile Core Interaction Motion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Aletheia Mobile's core controls mathematical, interruptible Apple-style feedback without changing robot safety, network, or real-time rendering behavior.

**Architecture:** Extend the existing `AletheiaMotion` token source with explicit curve and spring helpers, then add small presentation-only widgets for press feedback, keyed status transitions, and one-shot haptics. Integrate those widgets only into high-value connection, tool, settings, dialog/sheet, and manual-control surfaces; all controllers and repositories remain untouched.

**Tech Stack:** Flutter 3.47.1, Material 3, Dart `AnimationController` / `Curve` / `Tween` / `SpringSimulation`, `HapticFeedback`, flutter_test, Riverpod.

**Spec:** `docs/superpowers/specs/2026-09-23-mobile-core-interaction-motion-design.md`

## Global Constraints

- Modify only `mobile/` production/test code and this plan; never modify Backend, Web, ROS, HTTP/WS contracts, map/video/point-cloud rendering, or control repositories/controllers.
- Every animation derives from `Tween`, `Curve`, or `SpringSimulation`; do not use frame timers, GIF/Lottie, looping effects, or delayed business callbacks.
- Respect `MediaQuery.disableAnimationsOf(context)`; the reduced-motion path keeps semantic color/Ink feedback but removes scale, travel, and spring movement.
- Do not wrap live map/video workspaces in `AnimatedSwitcher`, animate telemetry values, or add transition latency to root navigation.
- Manual control must keep its current direct pointer path, vector/latest-wins/STOP behavior, three STOP confirmations, lifecycle release, and lock timing unchanged.
- Existing worktree has unrelated uncommitted changes and Golden failure images. Scope edits to the files listed below; do not reset, delete, stage, or regenerate unrelated files. No automatic commit.

## File Structure

- Modify `mobile/lib/app/motion/aletheia_motion.dart`: mathematical timing/curve tokens and route/surface animation helpers.
- Create `mobile/lib/app/motion/aletheia_interaction.dart`: press-feedback wrapper, keyed local status transition, and one-shot haptic gate.
- Create `mobile/test/app/motion/aletheia_interaction_test.dart`: deterministic widget tests for press, interruption, reduced motion, and haptic de-duplication.
- Modify `mobile/lib/features/tools/presentation/tools_screen.dart`: wrap low-frequency tool cards in press feedback.
- Modify `mobile/lib/features/app_settings/presentation/app_settings_screen.dart`: wrap settings rows in press feedback and use the standard sheet animation style.
- Modify `mobile/lib/features/manual_control/presentation/manual_control_screen.dart`: use status transition and semantic haptics without touching controllers or joystick pointer dispatch.
- Modify `mobile/lib/features/robot_connection/presentation/robot_connection_screen.dart`: animate only the connection status surface by key.
- Modify `mobile/lib/debug_ui/gallery_preview.dart` and `mobile/lib/debug_ui/gallery_manifest.dart`: expose formal states for surface/feedback review with production components.
- Modify targeted existing Widget tests and add Gallery coverage assertions; do not alter existing Golden image files.

---

### Task 1: Mathematical Motion and Interaction Primitives

**Files:**
- Modify: `mobile/lib/app/motion/aletheia_motion.dart`
- Create: `mobile/lib/app/motion/aletheia_interaction.dart`
- Create: `mobile/test/app/motion/aletheia_interaction_test.dart`

**Interfaces:**
- Produces `AletheiaMotion.pressDuration`, `stateDuration`, `surfaceDuration`, `pressCurve`, `stateCurve`, `surfaceAnimationStyle(BuildContext)` and `isReducedMotion(BuildContext)`.
- Produces `AletheiaPressFeedback({required Widget child, bool enabled = true})`, `AletheiaStatusTransition({required Object stateKey, required Widget child})`, and `AletheiaHapticGate.triggerOnce(String eventId, Future<void> Function() emit)`.
- Consumed by Tasks 2–4; no Controller, Repository, or API model consumes these interfaces.

- [x] **Step 1: Write failing primitive tests**

```dart
testWidgets('press feedback scales immediately and returns on pointer cancel', (tester) async {
  await tester.pumpWidget(const MaterialApp(
    home: AletheiaPressFeedback(child: SizedBox(key: ValueKey('press-target'), width: 44, height: 44)),
  ));
  final gesture = await tester.startGesture(tester.getCenter(find.byKey(const ValueKey('press-target'))));
  await tester.pump();
  expect(tester.widget<Transform>(find.byType(Transform).first).transform.storage[0], lessThan(1));
  await gesture.cancel();
  await tester.pump(AletheiaMotion.pressDuration);
  expect(tester.widget<Transform>(find.byType(Transform).first).transform.storage[0], 1);
});

testWidgets('reduced motion never scales the press surface', (tester) async {
  await tester.pumpWidget(const MediaQuery(
    data: MediaQueryData(disableAnimations: true),
    child: MaterialApp(home: AletheiaPressFeedback(child: SizedBox(width: 44, height: 44))),
  ));
  final gesture = await tester.startGesture(tester.getCenter(find.byType(AletheiaPressFeedback)));
  await tester.pump();
  expect(tester.widget<Transform>(find.byType(Transform).first).transform.storage[0], 1);
  await gesture.cancel();
});

test('a haptic event id emits once until reset', () async {
  var count = 0;
  final gate = AletheiaHapticGate();
  await gate.triggerOnce('manual-ready:session-1', () async => count++);
  await gate.triggerOnce('manual-ready:session-1', () async => count++);
  expect(count, 1);
});
```

- [x] **Step 2: Run the primitive tests and verify failure**

Run: `cd mobile && env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy fvm flutter test --no-pub test/app/motion/aletheia_interaction_test.dart -r compact`

Expected: compilation failure because the new motion symbols do not exist.

- [x] **Step 3: Implement the primitives with mathematical curves**

```dart
abstract final class AletheiaMotion {
  static const pressDuration = Duration(milliseconds: 120);
  static const stateDuration = Duration(milliseconds: 180);
  static const surfaceDuration = Duration(milliseconds: 240);
  static const pressCurve = Cubic(0.23, 1, 0.32, 1);
  static const stateCurve = Cubic(0.23, 1, 0.32, 1);
  static bool isReducedMotion(BuildContext context) =>
      MediaQuery.disableAnimationsOf(context);
}

// AletheiaPressFeedback owns only a local AnimationController whose
// Tween<double>(begin: 1, end: .97) is driven by pressCurve. Listener events
// never compete with a descendant InkWell/GestureRecognizer.
```

Implement `AletheiaPressFeedback` using `Listener` and a local controller; pointer down targets `.97`, pointer up/cancel targets `1.0`, and disabled/reduced-motion paths stay at `1.0`. Implement `AletheiaStatusTransition` with `AnimatedSwitcher`, a `ValueKey<Object>(stateKey)`, opacity, and a maximum `.985 → 1` scale only outside reduced-motion. Implement `AletheiaHapticGate` as an instance-scoped set of emitted IDs with `reset()`; pages call it only after a confirmed local state transition and `HapticFeedback` remains outside the gate's state logic.

- [x] **Step 4: Run primitive tests and analyzer**

Run: `cd mobile && env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy fvm flutter test --no-pub test/app/motion/aletheia_interaction_test.dart -r compact && env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy fvm flutter analyze`

Expected: all primitive tests pass and analyzer reports no issues.

### Task 2: Core Press, State, and Surface Integration

**Files:**
- Modify: `mobile/lib/features/tools/presentation/tools_screen.dart`
- Modify: `mobile/lib/features/app_settings/presentation/app_settings_screen.dart`
- Modify: `mobile/lib/features/robot_connection/presentation/robot_connection_screen.dart`
- Modify: `mobile/lib/app/motion/aletheia_motion.dart`
- Modify: `mobile/test/features/robot_connection/presentation/robot_connection_screen_test.dart`
- Create: `mobile/test/features/tools/presentation/tools_screen_test.dart`

**Interfaces:**
- Consumes `AletheiaPressFeedback`, `AletheiaStatusTransition`, and `AletheiaMotion.surfaceAnimationStyle` from Task 1.
- Produces unchanged routes, callbacks, texts, and connection state behavior; only local visual presentation changes.

- [x] **Step 1: Write failing integration tests**

```dart
testWidgets('tool entry receives press feedback without changing navigation callback', (tester) async {
  await tester.pumpWidget(const MaterialApp(home: ToolsScreen()));
  expect(find.byType(AletheiaPressFeedback), findsWidgets);
  await tester.tap(find.text('手动控制'));
  await tester.pump();
  // Assert the existing navigation route/callback outcome, not animation timing.
});

testWidgets('connection status replacement uses one keyed local transition', (tester) async {
  await tester.pumpWidget(connectionHarness(phase: ConnectionPhase.idle));
  await tester.pumpWidget(connectionHarness(phase: ConnectionPhase.connected));
  expect(find.byType(AletheiaStatusTransition), findsOneWidget);
  expect(find.byKey(const ValueKey<Object>('connected')), findsOneWidget);
});
```

- [x] **Step 2: Run focused tests and verify failure**

Run: `cd mobile && env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy fvm flutter test --no-pub test/features/tools/presentation/tools_screen_test.dart test/features/robot_connection/presentation/robot_connection_screen_test.dart -r compact`

Expected: failures because press/status components are not integrated.

- [x] **Step 3: Integrate only low-frequency presentation surfaces**

Wrap `_ToolEntry` and `_SettingsRow` contents with `AletheiaPressFeedback` while retaining their existing `Material` + `InkWell`, callbacks, semantics, border radius, and hit targets. Use `AletheiaStatusTransition` around the connection status panel's semantic state label/icon only; do not transition the address field or whole page. Pass `AletheiaMotion.surfaceAnimationStyle(context)` to the two existing settings `showModalBottomSheet` calls. Preserve root navigation as `NoTransitionPage` and do not touch live-observation code.

- [x] **Step 4: Run focused tests and analyzer**

Run: `cd mobile && env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy fvm flutter test --no-pub test/features/tools/presentation/tools_screen_test.dart test/features/robot_connection/presentation/robot_connection_screen_test.dart test/app/motion/aletheia_interaction_test.dart -r compact && env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy fvm flutter analyze`

Expected: tests pass, connection/provider behavior is unchanged, analyzer has no issues.

### Task 3: Manual-Control Feedback Without Control-Path Changes

**Files:**
- Modify: `mobile/lib/features/manual_control/presentation/manual_control_screen.dart`
- Modify: `mobile/test/features/manual_control/presentation/manual_control_screen_test.dart`

**Interfaces:**
- Consumes presentation-only interfaces from Task 1.
- Produces unchanged `ManualControlController` calls: `enter`, `sendVector`, `stop`, `exit`, `release`, and chassis-parameter save.

- [x] **Step 1: Write failing safety-preservation tests**

```dart
testWidgets('manual control state uses a keyed local transition without changing STOP calls', (tester) async {
  final repository = _ManualControlFakeRepository();
  await tester.pumpWidget(manualControlHarness(repository));
  await enterManualControl(tester);
  expect(find.byType(AletheiaStatusTransition), findsWidgets);
  final joystick = find.bySemanticsLabel(RegExp('连续方向摇杆，当前停止'));
  final gesture = await tester.startGesture(tester.getCenter(joystick));
  await gesture.moveBy(const Offset(0, -80));
  await gesture.up();
  await tester.pump(const Duration(milliseconds: 150));
  expect(repository.calls.where((call) => call.startsWith('stop:')).length, 3);
});

testWidgets('reduced motion leaves joystick pointer ownership intact', (tester) async {
  await tester.pumpWidget(reducedMotionManualControlHarness());
  await enterManualControl(tester);
  final scrollable = tester.state<ScrollableState>(find.byType(Scrollable).first);
  final gesture = await tester.startGesture(tester.getCenter(find.bySemanticsLabel(RegExp('连续方向摇杆'))));
  await gesture.moveBy(const Offset(0, -96));
  expect(scrollable.position.pixels, 0);
  await gesture.up();
});
```

- [x] **Step 2: Run the manual-control tests and verify failure**

Run: `cd mobile && env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy fvm flutter test --no-pub test/features/manual_control/presentation/manual_control_screen_test.dart -r compact`

Expected: new keyed-transition assertion fails before integration.

- [x] **Step 3: Add local state feedback and haptics**

Wrap `_StatusPill`, `_ControlLinkIndicator`, and `_Notice` contents in keyed `AletheiaStatusTransition` instances whose keys derive from already-rendered link/emergency/session state. Use a page-owned `AletheiaHapticGate` only after state edges: accepted active session, active joystick returning to STOP, locked safety state, and explicit save outcome. Do not await haptic futures; do not add a `GestureDetector`, timer, debounce, controller call, or animation around `_DirectionJoystick` input. Keep its current `SpringSimulation` and route its reduced-motion branch to an immediate visual center after its existing `onStop` call.

- [x] **Step 4: Run manual-control regression tests and analyzer**

Run: `cd mobile && env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy fvm flutter test --no-pub test/features/manual_control/application/manual_control_controller_test.dart test/features/manual_control/presentation/manual_control_screen_test.dart test/app/motion/aletheia_interaction_test.dart -r compact && env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy fvm flutter analyze`

Expected: all manual-control tests pass, including three bounded STOP confirmations and vertical-drag scroll protection.

### Task 4: Debug Gallery and iPhone 18 Pro Review

**Files:**
- Modify: `mobile/lib/debug_ui/gallery_manifest.dart`
- Modify: `mobile/lib/debug_ui/gallery_preview.dart`
- Modify: `mobile/test/debug_ui/debug_ui_gallery_screen_test.dart`

**Interfaces:**
- Consumes production widgets and their existing fake data sources; no Gallery-only duplicated UI.
- Produces Gallery entries for press/status/surface review and documents their existing route/screenshot metadata.

- [x] **Step 1: Write failing Gallery assertions**

```dart
testWidgets('gallery exposes core interaction review surfaces', (tester) async {
  await tester.pumpWidget(debugGalleryHarness());
  expect(galleryScreenById('manual_control_ready').state, 'Manual control ready');
  expect(galleryScreenById('manual_control_latency_locked').state, 'Manual control safety lock');
  expect(galleryScreenById('bottom_sheet').state, 'Material BottomSheet');
  expect(galleryScreenById('snackbar').state, 'SnackBar');
});
```

- [x] **Step 2: Run the Gallery test and verify failure**

Run: `cd mobile && env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy fvm flutter test --no-pub test/debug_ui/debug_ui_gallery_screen_test.dart -r compact`

Expected: failure until interaction review state metadata is added.

- [x] **Step 3: Wire official production surfaces into Gallery review states**

Add/clarify Gallery metadata for connected status, manual-control ready/locked, bottom sheet, dialog, and Snackbar. Ensure Gallery uses `AletheiaPressFeedback` / `AletheiaStatusTransition` through the actual production screens and keeps fake data restricted to data sources. Do not write or update any PNG Golden baselines in this task.

- [x] **Step 4: Run automated and simulator verification**

Run:
`cd mobile && env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy fvm flutter test --no-pub --concurrency=1 test/app/motion/aletheia_interaction_test.dart test/features/tools/presentation/tools_screen_test.dart test/features/robot_connection/presentation/robot_connection_screen_test.dart test/features/manual_control/application/manual_control_controller_test.dart test/features/manual_control/presentation/manual_control_screen_test.dart test/debug_ui/debug_ui_gallery_screen_test.dart -r compact`

Then run the debug app on the booted iPhone 18 Pro (`A49C5D93-E5D2-421F-8F4D-1F271512BB46`) and inspect manual-control ready/locked, bottom sheet, Snackbar, dark, daylight, and reduced-motion states. Verify the joystick with an actual vertical drag and confirm the containing scroll position remains unchanged.

Expected: all focused tests pass; simulator shows instantaneous press feedback, no live-renderer transitions, and no control-input delay.

### Task 5: Final Mobile Verification and Handoff

**Files:**
- Modify: `mobile/README.md` only if the implemented public behavior differs from its existing animation/accessibility documentation.
- Modify: `docs/AI_CONTINUATION.md` only if required by the project handoff policy after implementation.

**Interfaces:**
- Consumes all completed Tasks 1–4.
- Produces verification evidence; no API or packaging output.

- [x] **Step 1: Format only changed Dart files**

Run: `cd mobile && fvm dart format lib/app/motion/aletheia_motion.dart lib/app/motion/aletheia_interaction.dart lib/features/tools/presentation/tools_screen.dart lib/features/app_settings/presentation/app_settings_screen.dart lib/features/robot_connection/presentation/robot_connection_screen.dart lib/features/manual_control/presentation/manual_control_screen.dart test/app/motion/aletheia_interaction_test.dart test/features/tools/presentation/tools_screen_test.dart test/features/robot_connection/presentation/robot_connection_screen_test.dart test/features/manual_control/presentation/manual_control_screen_test.dart test/debug_ui/debug_ui_gallery_screen_test.dart`

- [x] **Step 2: Run required mobile check and classify failures by ownership**

Run: `env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy ./scripts/test-mobile.sh`

Expected: report all source/test failures from the change as blockers. If the known unrelated Gallery Golden image mismatch recurs, preserve the failure evidence, do not modify those tracked/untracked PNGs, and report it separately from focused-test results.

- [x] **Step 3: Check only the owned diff**

Run: `git diff --check && git status --short -- mobile/lib/app/motion mobile/lib/features/tools/presentation/tools_screen.dart mobile/lib/features/app_settings/presentation/app_settings_screen.dart mobile/lib/features/robot_connection/presentation/robot_connection_screen.dart mobile/lib/features/manual_control/presentation/manual_control_screen.dart mobile/lib/debug_ui mobile/test/app/motion mobile/test/features/tools mobile/test/features/robot_connection mobile/test/features/manual_control mobile/test/debug_ui docs/superpowers/specs/2026-09-23-mobile-core-interaction-motion-design.md docs/superpowers/plans/2026-09-23-mobile-core-interaction-motion.md`

Expected: no whitespace errors; only intentional owned source/test/doc changes are described in the handoff.
