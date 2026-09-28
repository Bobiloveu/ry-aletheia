# Mobile Native Report Trajectory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the frozen map and trajectory evidence used by existing HTML reports inside the Flutter Mobile native report detail experience.

**Architecture:** Extend the Planned `native_report` contract with report-scoped trajectory references and fixed read-only endpoints. Mobile parses them fail-closed, lazily loads an individual frozen map segment, and renders it using one world-to-screen `CustomPaint` transform; it never parses HTML/SVG, follows JSON URLs, or uses the current Observation map as historical evidence.

**Tech Stack:** Flutter 3.47.1 / Dart, Riverpod, `CustomPaint`, existing `AletheiaApiClient`, existing report feature tests, Markdown Shared contract.

**Spec:** `docs/superpowers/specs/2026-09-28-mobile-native-report-trajectory-design.md`

## Global Constraints

- Modify only `mobile/`, `shared/contracts/task_execution.md`, and required Mobile documentation; do not modify Backend, PC Web, ROS, existing HTML/CSV output, Observation, or Deployment APIs.
- Keep these trajectory endpoints **Planned** until Backend, Mobile, and PC Web consumer verification is recorded in Shared.
- The App may call only fixed report-scoped paths and must reject unsafe IDs, malformed data, non-finite coordinates, invalid map geometry, and unordered/repeated raw samples.
- Do not return/render report directories, file paths, external URLs, HTML, CSV, SVG, raw ROS messages, credentials, or unredacted site data.
- HTML and Mobile consume the same archived evidence source, but Mobile must not parse HTML/SVG or use the current real-time map as a historical background.
- The visual layer order is fixed: frozen PNG → metric grid → virtual walls → ideal route → actual route → selected sample.
- Gesture updates are direct and interruptible. Do not add looping, decorative, page-wide, or joystick animations; preserve `MediaQuery.disableAnimationsOf`.
- Never stage build artifacts, signing material, maps, reports, caches, or Golden failure images.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `shared/contracts/task_execution.md` | Planned trajectory schema, endpoints, ownership, pagination, size, and error semantics |
| `mobile/lib/features/reports/domain/native_report_trajectory.dart` | Fail-closed trajectory references, map geometry, paths, walls, samples, and page parsing |
| `mobile/lib/features/reports/domain/aletheia_report.dart` | Add `trajectoryRefs` to `NativeReportItem` |
| `mobile/lib/features/reports/data/reports_repository.dart` | Fixed report-scoped trajectory/samples/PNG paths |
| `mobile/lib/features/reports/application/reports_controller.dart` | Per-trajectory async state and ordered sample append |
| `mobile/lib/features/reports/presentation/report_trajectory_workspace.dart` | Viewport math, painter, gestures, and nearest sample selection |
| `mobile/lib/features/reports/presentation/report_detail_screen.dart` | Lazy trajectory cards and sample inspector |
| `mobile/lib/debug_ui/gallery_manifest.dart`, `gallery_preview.dart` | Production-page Gallery states with fakes only |
| `mobile/test/features/reports/**` | Domain, transport, state, geometry, gesture, and UI regressions |

## Task 1: Publish the Planned Shared contract

**Files:**
- Modify: `shared/contracts/task_execution.md:81-151`
- Test: `git diff --check`

**Interfaces:**
- Consumes: Existing optional `native_report` and `GET /api/reports/{report_id}/native`.
- Produces: `trajectory_refs` plus planned trajectory, frozen PNG, and sample endpoints for Tasks 2–5.

- [ ] **Step 1: Write the failing trajectory-reference fixture**

Create `mobile/test/features/reports/domain/native_report_trajectory_test.dart` before implementation:

```dart
final validRef = {
  'trajectory_id': 'traj_01J8A',
  'label': 'T-003 · 一层大厅',
  'status': 'available',
  'sample_count': 624,
  'integrity_warning': null,
};

expect(NativeReportTrajectoryRef.tryFromJson(validRef), isNotNull);
expect(
  NativeReportTrajectoryRef.tryFromJson({...validRef, 'trajectory_id': '../map'}),
  isNull,
);
```

- [ ] **Step 2: Run the test to confirm the contract type is absent**

Run: `cd mobile && env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy fvm flutter test --no-pub test/features/reports/domain/native_report_trajectory_test.dart -r compact`

Expected: FAIL because `NativeReportTrajectoryRef` does not exist.

- [ ] **Step 3: Extend only the Planned Shared section**

Add the following fixed paths and declare the full validation rules from the spec:

```text
NativeReportItem.trajectory_refs: [{trajectory_id, label, status, sample_count, integrity_warning}]
GET /api/reports/{report_id}/native/trajectories/{trajectory_id}
GET /api/reports/{report_id}/native/trajectories/{trajectory_id}/map.png
GET /api/reports/{report_id}/native/trajectories/{trajectory_id}/samples?cursor=<opaque>&limit=<1..1000>
```

Document: opaque identifiers/cursors; `display_paths` capped at 2,000 finite points per path; finite, positive map dimensions/resolution; no cross-map joins; report-scoped `image/png`; backend-defined byte/dimension bounds; invalid parameters `400`; missing/deleted/cross-report evidence `404`; no JSON URL/path/file field; report-time archival from the same evidence source as HTML rather than request-time HTML parsing.

- [ ] **Step 4: Check the focused test still fails only for missing Dart code**

Run the command from Step 2.

Expected: FAIL naming the missing Dart type, not a test harness or documentation failure.

- [ ] **Step 5: Commit the isolated contract change**

```bash
git add shared/contracts/task_execution.md docs/superpowers/specs/2026-09-28-mobile-native-report-trajectory-design.md
git commit -m "docs(shared): define native report trajectory contract"
```

## Task 2: Add fail-closed trajectory domain models

**Files:**
- Create: `mobile/lib/features/reports/domain/native_report_trajectory.dart`
- Modify: `mobile/lib/features/reports/domain/aletheia_report.dart:166-219`
- Modify: `mobile/test/features/reports/domain/native_report_test.dart`
- Test: `mobile/test/features/reports/domain/native_report_trajectory_test.dart`

**Interfaces:**
- Consumes: Task 1 JSON.
- Produces: `NativeReportTrajectoryRef`, `NativeReportTrajectory`, `NativeTrajectoryMap`, `NativeTrajectoryPath`, `NativeTrajectorySample`, and `NativeTrajectorySamplePage`.

- [ ] **Step 1: Add parser regression cases**

Add valid data plus these negative cases:

```dart
expect(
  NativeReportTrajectory.tryFromJson({...validTrajectory, 'map': {...validMap, 'resolution_m': 0}}),
  isNull,
);
expect(
  () => NativeTrajectorySamplePage.fromJson({
    'samples': [sample(index: 2), sample(index: 1)],
    'next_cursor': null,
  }),
  throwsFormatException,
);
expect(NativeReportTrajectory.tryFromJson(pathContainingNaN), isNull);
```

Also assert that an existing `NativeReportItem` accepts absent `trajectory_refs` as an empty list but rejects a present malformed reference list.

- [ ] **Step 2: Run the domain tests to confirm red**

Run: `cd mobile && env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy fvm flutter test --no-pub test/features/reports/domain/native_report_trajectory_test.dart test/features/reports/domain/native_report_test.dart -r compact`

Expected: FAIL because trajectory types and `trajectoryRefs` are absent.

- [ ] **Step 3: Implement focused immutable models**

Create exactly these public types:

```dart
enum NativeTrajectoryAvailability { available, incomplete, unavailable }
enum NativeTrajectoryPathKind { actual, ideal }

class NativeReportTrajectoryRef { /* trajectoryId, label, availability, sampleCount, integrityWarning */ }
class NativeTrajectoryMap { /* label, resolutionM, widthCells, heightCells, originXM, originYM */ }
class NativeTrajectoryPoint { /* xM, yM */ }
class NativeTrajectoryPath { /* routeName, kind, points */ }
class NativeTrajectorySample extends NativeTrajectoryPoint { /* timestampNs, routeName, sampleIndex */ }
class NativeReportTrajectory { /* trajectoryId, itemId, label, map, displayPaths, virtualWalls, sampleCount, integrityWarning, samplesNextCursor */ }
class NativeTrajectorySamplePage { /* samples, nextCursor */ }
```

Reuse the existing report identifier/text/cursor validators rather than creating divergent rules. Require non-empty paths, no more than 2,000 display points per path, at least two finite points in each virtual wall, and strictly increasing sample indices across each page. An invalid whole endpoint payload throws `FormatException`; an invalid optional reference returns `null`.

- [ ] **Step 4: Attach trajectory references to detail items**

Add `required List<NativeReportTrajectoryRef> trajectoryRefs` to `NativeReportItem`. Keep all existing summary/detail, status, duration, task cursor, and legacy report behavior unchanged.

- [ ] **Step 5: Format and verify green**

```bash
cd mobile
dart format lib/features/reports/domain/aletheia_report.dart lib/features/reports/domain/native_report_trajectory.dart test/features/reports/domain/native_report_trajectory_test.dart test/features/reports/domain/native_report_test.dart
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy fvm flutter test --no-pub test/features/reports/domain/native_report_trajectory_test.dart test/features/reports/domain/native_report_test.dart -r compact
```

Expected: PASS.

- [ ] **Step 6: Commit the domain layer**

```bash
git add mobile/lib/features/reports/domain mobile/test/features/reports/domain
git commit -m "feat(mobile): model native report trajectory evidence"
```

## Task 3: Add fixed-path repository and trajectory controller

**Files:**
- Modify: `mobile/lib/features/reports/data/reports_repository.dart:1-67`
- Modify: `mobile/lib/features/reports/application/reports_controller.dart:1-124`
- Modify: `mobile/test/features/reports/data/reports_repository_test.dart`
- Create: `mobile/test/features/reports/application/native_report_trajectory_controller_test.dart`

**Interfaces:**
- Consumes: Task 2 models and Task 1 endpoint definitions.
- Produces: `loadNativeTrajectory`, `loadNativeTrajectorySamples`, `nativeTrajectoryMapUri`, and family state used by Task 4.

- [ ] **Step 1: Add exact request/validation tests**

Use a fake API client capture:

```dart
expect(request.url.path, '/api/reports/rpt_01/native/trajectories/traj_01');
expect(samples.url.path, '/api/reports/rpt_01/native/trajectories/traj_01/samples');
expect(samples.url.queryParameters, {'cursor': 'opaque+cursor', 'limit': '1000'});
expect(() => repository.loadNativeTrajectory(endpoint, 'rpt_01', '../traj'), throwsArgumentError);
```

- [ ] **Step 2: Run repository/controller tests to confirm red**

Run: `cd mobile && env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy fvm flutter test --no-pub test/features/reports/data/reports_repository_test.dart test/features/reports/application/native_report_trajectory_controller_test.dart -r compact`

Expected: FAIL because fixed trajectory methods and state do not exist.

- [ ] **Step 3: Implement only fixed report-scoped methods**

```dart
Future<NativeReportTrajectory> loadNativeTrajectory(RobotEndpoint endpoint, String reportId, String trajectoryId);
Future<NativeTrajectorySamplePage> loadNativeTrajectorySamples(
  RobotEndpoint endpoint, String reportId, String trajectoryId, {
  String? cursor, int limit = 1000,
});
Uri nativeTrajectoryMapUri(RobotEndpoint endpoint, String reportId, String trajectoryId);
```

Validate both IDs before I/O; clamp sample limit to `1..1000`; preserve existing detail limit `1..100`. The PNG URI is calculated from `RobotEndpoint` and validated IDs, never read from JSON.

- [ ] **Step 4: Implement family state keyed by both opaque IDs**

```dart
class NativeReportTrajectoryKey {
  const NativeReportTrajectoryKey(this.reportId, this.trajectoryId);
  final String reportId;
  final String trajectoryId;
}

class NativeReportTrajectoryState {
  const NativeReportTrajectoryState({
    required this.trajectory,
    required this.samples,
    required this.nextCursor,
    this.isLoadingMore = false,
    this.loadMoreError,
  });
}
```

`loadMoreSamples()` must exit for disconnect/loading/no cursor, accept only a page whose first `sampleIndex` follows the last loaded sample, and preserve already loaded samples plus a local append error on failure. It must not reload the detail task page.

- [ ] **Step 5: Verify green behavior**

Test initial loading, valid append, duplicate/out-of-order rejection, failed append preservation, and stale response discard after endpoint change.

Run: `cd mobile && env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy fvm flutter test --no-pub test/features/reports/data/reports_repository_test.dart test/features/reports/application/native_report_detail_controller_test.dart test/features/reports/application/native_report_trajectory_controller_test.dart -r compact`

Expected: PASS.

- [ ] **Step 6: Commit transport and state**

```bash
git add mobile/lib/features/reports/data/reports_repository.dart mobile/lib/features/reports/application/reports_controller.dart mobile/test/features/reports/data/reports_repository_test.dart mobile/test/features/reports/application
git commit -m "feat(mobile): load native report trajectory evidence"
```

## Task 4: Build deterministic trajectory geometry and workspace

**Files:**
- Create: `mobile/lib/features/reports/presentation/report_trajectory_workspace.dart`
- Create: `mobile/test/features/reports/presentation/report_trajectory_geometry_test.dart`
- Create: `mobile/test/features/reports/presentation/report_trajectory_workspace_test.dart`

**Interfaces:**
- Consumes: Task 3 trajectory state and fixed PNG URI.
- Produces: `ReportTrajectoryWorkspace`, `ReportTrajectoryViewport`, painter output, pan/zoom, and nearest-sample selection for Task 5.

- [ ] **Step 1: Write pure geometry tests**

```dart
final viewport = ReportTrajectoryViewport.fit(
  map: map,
  viewportSize: const Size(320, 240),
);
expect(
  viewport.screenToWorld(viewport.worldToScreen(point)),
  closeToPoint(point),
);
expect(viewport.nearestSample(samples, tap, maxScreenDistance: 28)?.sampleIndex, 17);
```

Cover 2× zoom retaining the focal world point, grid/wall/path alignment, and no draw path joining two different `trajectoryId` values.

- [ ] **Step 2: Run geometry/workspace tests to confirm red**

Run: `cd mobile && env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy fvm flutter test --no-pub test/features/reports/presentation/report_trajectory_geometry_test.dart test/features/reports/presentation/report_trajectory_workspace_test.dart -r compact`

Expected: FAIL because viewport and workspace types do not exist.

- [ ] **Step 3: Implement one transform and one painter**

Implement `ReportTrajectoryViewport.fit`, `panBy`, and `zoomAround` using map resolution, origin, width, and height. `ReportTrajectoryWorkspace` owns no network I/O and accepts this shape:

```dart
class ReportTrajectoryWorkspace extends StatefulWidget {
  const ReportTrajectoryWorkspace({
    required this.trajectory,
    required this.samples,
    required this.mapImage,
    required this.onRequestMoreSamples,
    super.key,
  });
}
```

Its painter accepts only loaded `ui.Image?`, trajectory model, viewport, and selected sample. `shouldRepaint` compares every pixel-affecting input. Draw the exact global layer order. Use a gesture recognizer that leaves vertical page scrolling untouched until the user intentionally drags inside the map; two-finger zoom is focal-point anchored. Do not issue network calls on pointer move.

- [ ] **Step 4: Add interaction/widget regressions**

Test loading image placeholder, pan isolation, focal zoom, opaque map switching, nearest point selection/text, and Reduce Motion without looping animation state. `onRequestMoreSamples` may fire once only when a precision selection needs an available next page.

- [ ] **Step 5: Format and verify green**

```bash
cd mobile
dart format lib/features/reports/presentation/report_trajectory_workspace.dart test/features/reports/presentation/report_trajectory_geometry_test.dart test/features/reports/presentation/report_trajectory_workspace_test.dart
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy fvm flutter test --no-pub test/features/reports/presentation/report_trajectory_geometry_test.dart test/features/reports/presentation/report_trajectory_workspace_test.dart -r compact
```

Expected: PASS.

- [ ] **Step 6: Commit the workspace**

```bash
git add mobile/lib/features/reports/presentation/report_trajectory_workspace.dart mobile/test/features/reports/presentation/report_trajectory_geometry_test.dart mobile/test/features/reports/presentation/report_trajectory_workspace_test.dart
git commit -m "feat(mobile): render report trajectory workspace"
```

## Task 5: Integrate evidence cards, Gallery, and report detail UI

**Files:**
- Modify: `mobile/lib/features/reports/presentation/report_detail_screen.dart:39-152`
- Modify: `mobile/lib/debug_ui/gallery_manifest.dart`
- Modify: `mobile/lib/debug_ui/gallery_preview.dart`
- Modify: `mobile/test/features/reports/presentation/report_detail_screen_test.dart`
- Modify: `mobile/test/debug_ui/debug_ui_gallery_screen_test.dart`

**Interfaces:**
- Consumes: item trajectory references, Task 3 state, and Task 4 workspace.
- Produces: production detail evidence cards and formal Gallery states.

- [ ] **Step 1: Write screen regressions for evidence states**

Create a complete multi-map item, a no-trajectory item, and an incomplete item. Assert:

```dart
expect(find.text('地图运行轨迹证据'), findsOneWidget);
expect(find.text('轨迹证据不完整'), findsOneWidget);
expect(find.text('未采集到可验证轨迹'), findsOneWidget);
```

Also assert a trajectory `404` keeps the conclusion/task rows visible, offers only that card's retry, and never offers HTML/download/browser UI.

- [ ] **Step 2: Run screen/Gallery tests to confirm red**

Run: `cd mobile && env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy fvm flutter test --no-pub test/features/reports/presentation/report_detail_screen_test.dart test/debug_ui/debug_ui_gallery_screen_test.dart -r compact`

Expected: FAIL because the evidence section and Gallery states are absent.

- [ ] **Step 3: Integrate the production detail workspace**

Place `地图运行轨迹证据` after each task's factual status/feedback. An available reference expands one inline workspace; unavailable/incomplete references remain explicit evidence cards. The parent owns loading, PNG failures, per-card retry, and sample append; the workspace stays presentational.

Do not alter report summary metrics, ordinary task pagination, legacy-report handling, deletion, app shell, primary navigation, or other feature routes. Map replacement is immediately opaque.

- [ ] **Step 4: Register six formal Gallery states**

Use only production screen/widgets with fake providers for: complete trajectory, multiple map segments, no trajectory, integrity warning, map/trajectory load failure, and samples append failure. Generate in-memory fake PNG data; never contact a robot or copy screen widgets.

- [ ] **Step 5: Verify integration and inspect iPhone 18 Pro**

```bash
cd mobile
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy fvm flutter test --no-pub test/features/reports test/debug_ui/debug_ui_gallery_screen_test.dart -r compact
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy fvm flutter analyze
cd ..
git diff --check
```

Expected: selected tests pass, analyzer has no issues, and diff check has no output. Then launch each Gallery state on iPhone 18 Pro and verify dark/daylight, Reduce Motion, narrow portrait, map pan/zoom, point selection, opaque map switching, and error retry. Do not generate or commit Golden failures.

- [ ] **Step 6: Commit the integrated UI**

```bash
git add mobile/lib/features/reports/presentation/report_detail_screen.dart mobile/lib/debug_ui/gallery_manifest.dart mobile/lib/debug_ui/gallery_preview.dart mobile/test/features/reports/presentation/report_detail_screen_test.dart mobile/test/debug_ui/debug_ui_gallery_screen_test.dart
git commit -m "feat(mobile): show native report map trajectories"
```

## Task 6: Update Mobile handoff and final consumer verification

**Files:**
- Modify: `mobile/README.md`
- Modify: `docs/AI_CONTINUATION.md`
- Modify: `docs/superpowers/specs/2026-09-28-mobile-native-report-trajectory-design.md` only with actual verification evidence
- Test: targeted reports suite, analyzer, diff check, and staged-file inspection

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces: accurate Mobile handoff without representing Planned Backend work as delivered.

- [ ] **Step 1: Verify documentation claims before writing them**

```bash
rg -n 'native/trajectories|map\.png|trajectory_refs' shared/contracts/task_execution.md mobile/lib/features/reports
rg -n 'HTML|CSV|browser|WebView' mobile/README.md docs/AI_CONTINUATION.md
```

Expected: documentation continues to forbid Mobile HTML/CSV/browser fallback and marks native trajectory endpoints Planned.

- [ ] **Step 2: Update only verified Mobile facts**

Document frozen report-scoped maps, same-source structured evidence, lazy segment load, sample inspection, lack of realtime-map fallback, and lack of PNG/Photos export. Record exact tests, simulator states, remaining Backend dependency, and non-goals in `AI_CONTINUATION.md`. Do not claim the Backend has implemented endpoints.

- [ ] **Step 3: Run final evidence suite and stage review**

```bash
cd mobile
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy fvm flutter test --no-pub test/features/reports test/debug_ui/debug_ui_gallery_screen_test.dart -r compact
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy fvm flutter analyze
cd ..
git diff --check
git status --short
```

Expected: all selected tests pass, analyzer has no issues, diff check has no output, and no backend/PC Web files, iOS signing files, build output, or Golden failure images are staged.

- [ ] **Step 4: Commit the verified handoff**

```bash
git add mobile/README.md docs/AI_CONTINUATION.md docs/superpowers/specs/2026-09-28-mobile-native-report-trajectory-design.md
git commit -m "docs(mobile): document native report trajectory evidence"
```
