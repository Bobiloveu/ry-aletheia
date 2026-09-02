# Unity Map Viewport Authority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate Unity map anisotropic distortion by making Flutter's logical viewport the sole 2D projection authority.

**Architecture:** Flutter computes an atomic map viewport packet from the same camera state used for gestures and HUD scale. The packet crosses the existing latest-wins native camera bridge and Unity sets its aspect, orthographic size, and `MapCanvas` position only from that packet; Unity's internal `pixelWidth` and `pixelHeight` remain diagnostics, not projection inputs.

**Tech Stack:** Flutter/Dart, Dart FFI, C11 shared bridge, Kotlin Unity-as-a-Library host, Unity 2022.3 C#, Android Debug Gallery.

**Spec:** `docs/superpowers/specs/2026-09-02-unity-map-viewport-authority-design.md`

## Global Constraints

- Do not change robot HTTP, WebSocket, ROS2, map, point-cloud, or video protocols.
- Unity remains map rendering only; Flutter owns gestures and HMI layout.
- Keep the Flutter `CustomPaint` renderer unchanged and build-selectable.
- Map, grid, virtual walls, point cloud, and vehicle must use one `MapCanvas` map-space transform.
- Do not use Unity internal render-buffer dimensions to choose 2D projection.
- Preserve process-wide Unity runtime and existing fullscreen route ownership.
- Do not auto-commit or alter unrelated dirty files.

---

### Task 1: Define a Flutter logical viewport model

**Files:**
- Create: `mobile/lib/features/live_observation/visualization/unity_viewport.dart`
- Create: `mobile/test/features/live_observation/visualization/unity_viewport_test.dart`

**Interfaces:**
- Consumes: `LiveMapMetadata`, `VizCameraState`, and `Size`.
- Produces: immutable `UnityViewport` with `width`, `height`, `pixelsPerMetre`, `centerX`, `centerY`, and `revision`.
- Used by: `_UnityMapSurface` in Task 3 and `VisualizationController.setCamera` in Task 4.

- [ ] **Step 1: Write the failing viewport geometry test**

```dart
test('logical viewport keeps map metres isotropic in portrait and landscape', () {
  const metadata = LiveMapMetadata(
    width: 3480,
    height: 10017,
    resolution: .05,
    originX: -87,
    originY: -250.425,
  );
  const camera = VizCameraState(scale: 2, offset: Offset(1.5, -2));

  final portrait = UnityViewport.fromCamera(
    metadata: metadata,
    camera: camera,
    size: const Size(888, 1252),
    revision: 1,
  );
  final landscape = UnityViewport.fromCamera(
    metadata: metadata,
    camera: camera,
    size: const Size(1705, 788),
    revision: 2,
  );

  expect(portrait.visibleWidthMetres / portrait.width,
      closeTo(portrait.visibleHeightMetres / portrait.height, 1e-9));
  expect(landscape.visibleWidthMetres / landscape.width,
      closeTo(landscape.visibleHeightMetres / landscape.height, 1e-9));
  expect(portrait.centerX, closeTo(1.5, 1e-9));
  expect(portrait.centerY, closeTo(-2, 1e-9));
});
```

- [ ] **Step 2: Run the test and confirm it fails because `UnityViewport` does not exist**

Run:

```bash
cd mobile
flutter test test/features/live_observation/visualization/unity_viewport_test.dart
```

Expected: compilation failure naming missing `UnityViewport`.

- [ ] **Step 3: Implement the smallest viewport value object**

```dart
@immutable
class UnityViewport {
  const UnityViewport({
    required this.width,
    required this.height,
    required this.pixelsPerMetre,
    required this.centerX,
    required this.centerY,
    required this.revision,
  });

  factory UnityViewport.fromCamera({
    required LiveMapMetadata metadata,
    required VizCameraState camera,
    required Size size,
    required int revision,
  }) {
    final baseView = math.max(metadata.worldWidth, metadata.worldHeight) * 1.1;
    final pixelsPerMetre = size.width * camera.scale / baseView;
    return UnityViewport(
      width: size.width,
      height: size.height,
      pixelsPerMetre: pixelsPerMetre,
      centerX: metadata.originX + metadata.worldWidth / 2 + camera.offset.dx,
      centerY: metadata.originY + metadata.worldHeight / 2 + camera.offset.dy,
      revision: revision,
    );
  }

  final double width, height, pixelsPerMetre, centerX, centerY;
  final int revision;
  double get visibleWidthMetres => width / pixelsPerMetre;
  double get visibleHeightMetres => height / pixelsPerMetre;
}
```

- [ ] **Step 4: Run the test and confirm it passes**

Run:

```bash
cd mobile
flutter test test/features/live_observation/visualization/unity_viewport_test.dart
```

Expected: PASS.

### Task 2: Extend the latest-wins camera ABI with the viewport packet

**Files:**
- Modify: `mobile/packages/aletheia_visualization/lib/src/camera_bridge.dart`
- Modify: `mobile/packages/aletheia_visualization/shared/aletheia_viz_bridge.h`
- Modify: `mobile/packages/aletheia_visualization/shared/aletheia_viz_bridge.c`
- Modify: `unity/aletheia_viz/Assets/Scripts/NativeCloudBridge.cs`
- Modify: `mobile/test/features/live_observation/visualization/unity_camera_restore_contract_test.dart`

**Interfaces:**
- Consumes: `UnityViewport` fields emitted by Task 1.
- Produces: ABI-compatible `av_camera` / `AvCamera` fields `viewport_width`, `viewport_height`, `pixels_per_metre`, `center_x`, `center_y`, `viewport_revision`.
- Used by: `VizCamera.SetCamera` in Task 4.

- [ ] **Step 1: Write the failing ABI source contract**

```dart
test('Unity camera ABI carries one complete Flutter viewport', () {
  expect(dartBridge, contains('viewportWidth'));
  expect(dartBridge, contains('pixelsPerMetre'));
  expect(header, contains('float viewport_width;'));
  expect(header, contains('float pixels_per_metre;'));
  expect(unityBridge, contains('public float viewport_width;'));
  expect(unityBridge, contains('public float pixels_per_metre;'));
});
```

- [ ] **Step 2: Run the source contract and confirm it fails**

Run:

```bash
cd mobile
flutter test test/features/live_observation/visualization/unity_camera_restore_contract_test.dart
```

Expected: FAIL because no viewport ABI field exists.

- [ ] **Step 3: Add fields at the end of every camera ABI declaration**

```c
float viewport_width;
float viewport_height;
float pixels_per_metre;
float center_x;
float center_y;
int64_t viewport_revision;
```

Use the same ordering in Dart FFI and C# `[StructLayout(LayoutKind.Sequential)]`; validate all dimensions and scale are finite and greater than zero before staging.

- [ ] **Step 4: Run the source contract plus C syntax validation**

Run:

```bash
cd mobile
flutter test test/features/live_observation/visualization/unity_camera_restore_contract_test.dart
clang -std=c11 -fsyntax-only -Ipackages/aletheia_visualization/shared packages/aletheia_visualization/shared/aletheia_viz_bridge.c
```

Expected: both PASS.

### Task 3: Publish one viewport packet whenever Flutter layout or camera changes

**Files:**
- Modify: `mobile/lib/features/live_observation/visualization/unity_visualization_engine.dart`
- Test: `mobile/test/features/live_observation/visualization/unity_viewport_test.dart`

**Interfaces:**
- Consumes: `UnityViewport.fromCamera` from Task 1 and ABI fields from Task 2.
- Produces: de-duplicated `VisualizationController.setCamera(camera, viewport)` calls.
- Used by: the existing native latest-wins camera staging bridge.

- [ ] **Step 1: Add a failing widget-level source/behaviour assertion**

```dart
testWidgets('a changed Unity host size publishes a new viewport revision', (tester) async {
  // Pump the production map surface at 888×1252, then 1705×788.
  // Assert the fake controller receives two camera packets with revisions 1 and 2.
});
```

Use a real `LiveMapAsset` fixture and fake `VisualizationController` seam; assert the second packet has the landscape width and height rather than asserting a native buffer size.

- [ ] **Step 2: Run the test and confirm it fails because size changes do not stage camera state**

Run:

```bash
cd mobile
flutter test test/features/live_observation/visualization/unity_viewport_test.dart
```

Expected: FAIL with only the initial camera packet observed.

- [ ] **Step 3: Implement layout-aware, post-frame viewport publication**

```dart
void _syncViewportAfterLayout(BoxConstraints constraints) {
  final size = constraints.biggest;
  if (size.isEmpty || size == _lastViewportSize) return;
  _lastViewportSize = size;
  final revision = ++_viewportRevision;
  WidgetsBinding.instance.addPostFrameCallback((_) {
    if (mounted && _lastViewportSize == size) _scheduleCameraSync();
  });
}
```

Call it in the map `LayoutBuilder`.  `_scheduleCameraSync` creates `UnityViewport.fromCamera(...)` using the current camera and latest constraints, then stages camera and viewport together.  Do not mutate camera scale simply because orientation changed; preserve its relative zoom and calculate only the new pixels-per-metre.

- [ ] **Step 4: Run the focused Flutter tests**

Run:

```bash
cd mobile
flutter test test/features/live_observation/visualization/unity_viewport_test.dart test/features/live_observation/visualization/visualization_engine_test.dart
```

Expected: PASS.

### Task 4: Make Unity projection consume only the Flutter viewport

**Files:**
- Modify: `unity/aletheia_viz/Assets/Scripts/VizTypes.cs`
- Modify: `unity/aletheia_viz/Assets/Scripts/NativeCloudBridge.cs`
- Modify: `unity/aletheia_viz/Assets/Scripts/VizCamera.cs`
- Create: `unity/aletheia_viz/Assets/Editor/VizCameraViewportValidation.cs`

**Interfaces:**
- Consumes: `VizCameraMsg` with Task 2 viewport fields.
- Produces: `VizCamera.ApplyViewport` with `Camera.aspect`, `orthographicSize`, and `MapCanvas` derived solely from the packet.
- Used by: `VizBridge.LateUpdate` and static editor validation.

- [ ] **Step 1: Write the failing Unity projection validation**

```csharp
var portrait = VizCamera.ProjectionFor(888f, 1252f, 52f);
var landscape = VizCamera.ProjectionFor(1705f, 788f, 52f);
Assert.AreEqual(1f / 52f, portrait.MetresPerDisplayedPixelX, 1e-5f);
Assert.AreEqual(1f / 52f, portrait.MetresPerDisplayedPixelY, 1e-5f);
Assert.AreEqual(1f / 52f, landscape.MetresPerDisplayedPixelX, 1e-5f);
Assert.AreEqual(1f / 52f, landscape.MetresPerDisplayedPixelY, 1e-5f);
```

Expose the validator as `Aletheia.Viz.EditorTools.VizCameraViewportValidation.Validate` so it can run in Unity batch mode.

- [ ] **Step 2: Run the Unity validation and confirm it fails**

Run:

```bash
/Applications/Unity/Hub/Editor/2022.3.62f1/Unity.app/Contents/MacOS/Unity \
  -batchmode -quit -projectPath "$PWD/unity/aletheia_viz" \
  -executeMethod Aletheia.Viz.EditorTools.VizCameraViewportValidation.Validate
```

Expected: compile failure because `ProjectionFor` is not defined.

- [ ] **Step 3: Replace buffer-derived projection with packet-derived projection**

```csharp
public static Projection ProjectionFor(float width, float height, float ppm) =>
    new Projection(width / height, height / (2f * ppm), 1f / ppm);

private void ApplyViewport(in VizCameraMsg m) {
    var p = ProjectionFor(m.viewportWidth, m.viewportHeight, m.pixelsPerMetre);
    _cam.aspect = p.Aspect;
    _cam.orthographicSize = p.OrthographicSize;
    _mapCanvas.localPosition = new Vector3(-m.centerX, 0f, -m.centerY);
}
```

Delete the `OnPreCull` branch that writes `_cam.aspect` from `pixelWidth` and `pixelHeight`.  Retain those values only in an optional diagnostic log comparing render buffer to received logical viewport.

- [ ] **Step 4: Run Unity validation and export Android Unity library**

Run the validation command above, then:

```bash
/Applications/Unity/Hub/Editor/2022.3.62f1/Unity.app/Contents/MacOS/Unity \
  -batchmode -quit -projectPath "$PWD/unity/aletheia_viz" \
  -executeMethod Aletheia.Viz.EditorTools.UaaLBuild.ExportAndroidDevelopment
```

Expected: validation and export PASS.

### Task 5: Verify the Android fullscreen route against geometry rather than presence

**Files:**
- Modify: `mobile/integration_test/unity_map_lifecycle_test.dart`
- Modify: `mobile/docs/DEVELOPMENT_WORKFLOW.md`
- Modify: `docs/AI_CONTINUATION.md`

**Interfaces:**
- Consumes: viewport diagnostics from Task 4 and the existing deterministic `observe_stress` fixture.
- Produces: repeatable Android manual/automated verification steps and an evidence record.

- [ ] **Step 1: Add a failing integration assertion for viewport revision changes**

```dart
expect(find.byKey(const ValueKey('unity-map-gesture-surface')), findsOneWidget);
// Enter fullscreen, return, and assert the production diagnostic bridge
// observed distinct logical viewport revisions for card and fullscreen hosts.
```

Expose only revision and logical dimensions through an existing debug-only diagnostic seam; do not expose Unity controls in production UI.

- [ ] **Step 2: Run the integration test and confirm failure before the diagnostic is wired**

Run:

```bash
cd mobile
ALETHEIA_UNITY_ENABLED=1 flutter test integration_test/unity_map_lifecycle_test.dart \
  -d emulator-5554 \
  --dart-define=AV_ENGINE=unity \
  --dart-define=AV_UNITY_RUNTIME=true
```

Expected: FAIL because no logical viewport revision is reported.

- [ ] **Step 3: Wire the narrow diagnostic and assert five complete cycles**

Keep the existing five-cycle test. At each card/fullscreen transition assert the newest reported logical width/height matches Flutter's current surface orientation and that Unity reports equal displayed metres-per-pixel on X and Y within `1e-4`.

- [ ] **Step 4: Run all required verification**

Run:

```bash
cd mobile
dart format lib/features/live_observation/visualization test/features/live_observation/visualization integration_test/unity_map_lifecycle_test.dart
flutter analyze
flutter test --concurrency=1 -r compact
ALETHEIA_UNITY_ENABLED=1 flutter build apk --debug --target lib/main.dart \
  --dart-define=AV_ENGINE=unity --dart-define=AV_UNITY_RUNTIME=true
git diff --check
```

Then install only `build/app/outputs/flutter-apk/app-debug.apk` (never the APK produced by `flutter test`) and complete five Android device cycles: portrait card → fullscreen landscape → return card. Capture log lines showing identical X/Y metre scale for every final stable host.
