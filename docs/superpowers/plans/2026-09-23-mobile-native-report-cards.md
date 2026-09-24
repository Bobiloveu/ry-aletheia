# Aletheia Mobile Native Report Cards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Mobile's browser/HTML/CSV report flow with native structured report cards and a paginated native detail page, while publishing the future Backend protocol in Shared.

**Architecture:** `GET /api/reports` remains backward compatible and may supply a small `native_report` summary. Mobile renders only that structured data and fetches detail on demand through a Riverpod pagination controller. Missing native data is a migration state, never a browser fallback; PC Web and Backend implementation are not changed.

**Tech Stack:** Flutter 3.47.1, Material 3, Riverpod 3, GoRouter, existing `http` client, Flutter tests, Debug UI Gallery.

**Spec:** `docs/superpowers/specs/2026-09-23-mobile-native-report-cards-design.md`

## Global Constraints

- Modify only `mobile/`, `shared/contracts/task_execution.md`, this plan, and the implementation handoff. Do not modify `frontend/`, Backend code, ROS, report generators, HTML/CSV archives or shared JSON Schema files.
- The new endpoint stays **Planned** until Backend implements it and consumer checks succeed. Existing list fields and existing filename-based delete behavior remain compatible.
- Never expose or render a local path, file URL, HTML, CSV, SVG, arbitrary rich text, or raw ROS data. `report_id` and `cursor` are opaque server-issued identifiers; request `limit=50` and cap it to `100`.
- Native data missing, malformed, unsupported, or containing unknown status/kind values must render “车端尚未提供原生报告数据”; never parse HTML/CSV, invoke a browser, WebView, download, file save, Photos permission, share, PNG export or a new dependency.
- Use existing Aletheia dark/daylight tokens, direct press feedback, local reduced-motion-safe state feedback and 44pt+ targets. Do not add looping, staggered or large report animations.
- Gallery uses production report components with fake providers; never edit/re-record `mobile/test/debug_ui/failures/` Golden feedback.
- Preserve unrelated dirty work. Do not reset, delete, stage, commit or overwrite it automatically.

## File Structure

- `shared/contracts/task_execution.md`: Planned protocol, consumers, compatibility, migration and verification conditions.
- `mobile/lib/features/reports/domain/aletheia_report.dart`: legacy index plus fail-closed native summary/detail/item values and enums.
- `mobile/lib/features/reports/data/reports_repository.dart`: optional index summary parsing and bounded native detail request.
- `mobile/lib/features/reports/application/reports_controller.dart`: existing list provider plus endpoint-aware detail pagination provider.
- `mobile/lib/features/reports/presentation/reports_screen.dart`: native/legacy list cards and existing confirmed delete, without browser/download actions.
- `mobile/lib/features/reports/presentation/report_detail_screen.dart`: detail overview, metrics, evidence summary, exceptions and pagination UI.
- `mobile/lib/app/router.dart`: `/tools/reports/:reportId` detail route.
- `mobile/lib/debug_ui/{gallery_manifest,gallery_preview}.dart`: real native report review states and fakes.
- `mobile/test/features/reports/**`, `mobile/test/debug_ui/debug_ui_gallery_screen_test.dart`: model, request, controller, presentation and Gallery coverage.
- `mobile/README.md`, `docs/AI_CONTINUATION.md`: public migration behavior and handoff evidence after implementation.

---

### Task 1: Publish the Planned Shared Contract

**Files:**
- Modify: `shared/contracts/task_execution.md`
- Test: `git diff --check -- shared/contracts/task_execution.md`

**Interfaces:**
- Consumes: Existing `GET /api/reports` fields and filename-based delete endpoint.
- Produces: Planned optional `native_report` summary and Planned `GET /api/reports/{report_id}/native?cursor=&limit=` detail protocol.

- [ ] **Step 1: Verify that the current Shared contract lacks the native protocol**

Run: `rg -n 'native_report|/api/reports/\\{report_id\\}/native' shared/contracts/task_execution.md`

Expected: no match, proving the protocol is not yet documented.

- [ ] **Step 2: Add the Planned native-report section**

Under `## Planned`, add `### Mobile Native Reports` with these exact compatibility rules:

```text
GET /api/reports preserves filename,size,modified_at,csv_filename,report_type,title.
Optional native_report contains schema_version,report_id,kind,title,status,
created_at,duration_ms,summary(total,passed,failed,blocked,pass_rate),headline.
GET /api/reports/{report_id}/native accepts opaque cursor and limit; default 50, max 100.
The response repeats fixed report metadata, returns one items page and next_cursor.
```

List valid `kind` values (`test`, `acceptance`), valid status values (`passed`, `failed`, `blocked`, `cancelled`, `incomplete`, `unknown`), nonnegative finite metric rules, no-path/no-file/no-raw-ROS security rules, 404 behavior, existing/future consumers, PC Web non-consumer status, and Backend migration/promotion requirements.

- [ ] **Step 3: Verify the change is additive and Planned**

Run: `rg -n 'Status: Existing|## Planned|native_report|/api/reports/\\{report_id\\}/native|PC Web' shared/contracts/task_execution.md && git diff --check -- shared/contracts/task_execution.md`

Expected: existing report behavior remains intact; only the new endpoint is Planned.

### Task 2: Add Fail-Closed Native Report Values and Repository Access

**Files:**
- Modify: `mobile/lib/features/reports/domain/aletheia_report.dart`
- Modify: `mobile/lib/features/reports/data/reports_repository.dart`
- Create: `mobile/test/features/reports/domain/native_report_test.dart`
- Create: `mobile/test/features/reports/data/reports_repository_test.dart`

**Interfaces:**
- Produces: `NativeReportSummary? AletheiaReport.nativeReport`, `NativeReportDetailPage`, `NativeReportItem`, `ReportStatus`, `ReportKind`, and `ReportsRepository.loadNativeDetail`.

- [ ] **Step 1: Write failing model tests**

Write tests that require the missing API:

```dart
final report = AletheiaReport.fromJson({'native_report': {
  'schema_version': 1, 'report_id': 'rpt_01J8', 'kind': 'test',
  'title': '路径验证', 'status': 'failed',
  'created_at': '2026-09-23T10:30:00+08:00', 'duration_ms': 184000,
  'summary': {'total': 12, 'passed': 10, 'failed': 1, 'blocked': 1, 'pass_rate': 83.3},
  'headline': '定位收敛超时。',
}});
expect(report.nativeReport!.status, ReportStatus.failed);
expect(report.nativeReport!.summary.exceptionCount, 2);
```

Add cases where schema version is `2`, identifier is `../unsafe`, enum is unknown, metric is negative/NaN, or cardinalities exceed total; each must yield `nativeReport == null`. Test detail `next_cursor: null` as terminal pagination and unknown item status as `ReportStatus.unknown`.

- [ ] **Step 2: Run model tests and observe RED**

Run:

```sh
cd mobile
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy fvm flutter test --no-pub test/features/reports/domain/native_report_test.dart -r compact
```

Expected: compile failure because native report types do not exist.

- [ ] **Step 3: Implement immutable conservative models**

Implement these signatures:

```dart
enum ReportStatus { passed, failed, blocked, cancelled, incomplete, unknown }
enum ReportKind { test, acceptance, unknown }

class NativeReportSummary {
  static NativeReportSummary? tryFromJson(Object? value);
}

class NativeReportDetailPage {
  const NativeReportDetailPage({required this.report, required this.items, required this.nextCursor});
  factory NativeReportDetailPage.fromJson(Map<String, dynamic> json);
}
```

Accept only schema version `1`, IDs matching `[A-Za-z0-9_-]{1,128}`, valid ISO dates, finite nonnegative integer metrics/durations, and `passed + failed + blocked <= total`. Malformed optional summary becomes `null`; it never invalidates the whole legacy list response.

- [ ] **Step 4: Write failing repository request tests**

With a fake `http.Client`, assert:

```dart
expect(request.url.path, '/api/reports/rpt_01J8/native');
expect(request.url.queryParameters, {'cursor': 'opaque-next', 'limit': '50'});
```

Also assert input limit `101` becomes `100`, unsafe IDs fail locally, a non-2xx JSON response stays `ApiException`, and one malformed optional summary does not reject `load()`.

- [ ] **Step 5: Implement the bounded detail request and verify GREEN**

Implement:

```dart
Future<NativeReportDetailPage> loadNativeDetail(
  RobotEndpoint endpoint,
  String reportId, {String? cursor, int limit = 50},
)
```

Use `_apiClient.getJson(endpoint, 'api/reports/$reportId/native', queryParameters: ...)`, clamp limit to `[1, 100]`, send no cursor when null and parse only through `NativeReportDetailPage.fromJson`.

Run:

```sh
cd mobile
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy fvm flutter test --no-pub test/features/reports/domain/native_report_test.dart test/features/reports/data/reports_repository_test.dart -r compact
```

Expected: all parsing and request safety assertions pass.

### Task 3: Build Detail Pagination State

**Files:**
- Modify: `mobile/lib/features/reports/application/reports_controller.dart`
- Create: `mobile/test/features/reports/application/native_report_detail_controller_test.dart`

**Interfaces:**
- Consumes: `loadNativeDetail`, selected endpoint and `NativeReportDetailPage`.
- Produces: `nativeReportDetailProvider(String reportId)` and state with `items`, `nextCursor`, `isLoadingMore`, `loadMoreError`.

- [ ] **Step 1: Write failing pagination tests**

Create a fake repository with two server pages. Assert that after initial load and `loadNextPage()`, `task_1` stays before `task_2`, the second request uses only the first response's cursor, and `nextCursor` becomes null only after successful append. Make the second request throw `ApiException`; assert initial items remain readable, `nextCursor` remains retryable and `loadMoreError` is separate from initial load failure.

- [ ] **Step 2: Run the controller test and observe RED**

Run:

```sh
cd mobile
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy fvm flutter test --no-pub test/features/reports/application/native_report_detail_controller_test.dart -r compact
```

Expected: compile failure because the detail provider/controller does not exist.

- [ ] **Step 3: Implement bounded endpoint-aware pagination**

Use an `AutoDisposeFamilyAsyncNotifier` (or project-equivalent provider) whose `build(reportId)` reads the connected endpoint and fetches the first page. `loadNextPage()` returns before requesting while disconnected, initial loading, append loading or `nextCursor == null`; otherwise it appends exactly one server page in received order. It must not poll, prefetch, debounce, cache files or reorder existing items.

- [ ] **Step 4: Verify controller behavior and analyzer**

Run:

```sh
cd mobile
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy fvm flutter test --no-pub test/features/reports/application/native_report_detail_controller_test.dart test/features/reports/domain/native_report_test.dart test/features/reports/data/reports_repository_test.dart -r compact
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy fvm flutter analyze
```

Expected: no duplicate page call, stable existing items after append failure, no analyzer issue.

### Task 4: Replace Browser Reports with Native Production Screens

**Files:**
- Modify: `mobile/lib/features/reports/presentation/reports_screen.dart`
- Create: `mobile/lib/features/reports/presentation/report_detail_screen.dart`
- Modify: `mobile/lib/app/router.dart`
- Create: `mobile/test/features/reports/presentation/reports_screen_test.dart`
- Create: `mobile/test/features/reports/presentation/report_detail_screen_test.dart`

**Interfaces:**
- Consumes: native summary/detail providers, existing delete repository method and Aletheia theme/motion.
- Produces: `ReportDetailScreen({required String reportId})` at `/tools/reports/:reportId`.

- [ ] **Step 1: Write failing list/detail widget tests**

In a list harness with a passed report, a failed report and a legacy report, assert:

```dart
expect(find.text('路径验证 · 第 3 次运行'), findsOneWidget);
expect(find.text('通过 10'), findsOneWidget);
expect(find.text('异常 2'), findsOneWidget);
expect(find.text('车端尚未提供原生报告数据'), findsOneWidget);
expect(find.text('在浏览器打开'), findsNothing);
expect(find.text('下载 HTML'), findsNothing);
expect(find.text('下载 CSV'), findsNothing);
```

Tap only the native card and assert `ReportDetailScreen` receives `rpt_01J8`. Detail tests assert conclusion/metrics, exception-first row, `全部任务`, load-more, append retry and preserved ordering.

- [ ] **Step 2: Run widget tests and observe RED**

Run:

```sh
cd mobile
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy fvm flutter test --no-pub test/features/reports/presentation/reports_screen_test.dart test/features/reports/presentation/report_detail_screen_test.dart -r compact
```

Expected: current browser-oriented screen fails no-browser/detail-route assertions.

- [ ] **Step 3: Implement native cards, detail and route**

Remove `url_launcher` import and all `launchUrl` calls from the reports feature. Native cards use existing press feedback, type icon, semantic status pill, created-at/duration row, exactly three labels `任务` / `通过` / `异常`, and optional headline. A legacy card is non-navigable and shows the migration message. Retain only the existing overflow delete action and confirmation.

`ReportDetailScreen` uses production Aletheia surfaces and typography for conclusion, metric grid, controlled context/evidence summary, exception-first items, all-items section and load-more/retry. It renders no WebView, HTML, external URL, raw evidence or chart library.

Add the route under the current ShellRoute:

```dart
GoRoute(
  path: '${ReportsScreen.routePath}/:reportId',
  pageBuilder: (context, state) => AletheiaMotion.detailPage(
    key: state.pageKey,
    child: ReportDetailScreen(reportId: state.pathParameters['reportId']!),
  ),
),
```

- [ ] **Step 4: Verify native presentation behavior**

Run:

```sh
cd mobile
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy fvm flutter test --no-pub test/features/reports/presentation/reports_screen_test.dart test/features/reports/presentation/report_detail_screen_test.dart test/features/reports/domain/aletheia_report_test.dart -r compact
```

Expected: card/detail work without browser fallback; delete stays confirmed.

### Task 5: Gallery, Documentation and iPhone 18 Pro Review

**Files:**
- Modify: `mobile/lib/debug_ui/gallery_manifest.dart`
- Modify: `mobile/lib/debug_ui/gallery_preview.dart`
- Modify: `mobile/test/debug_ui/debug_ui_gallery_screen_test.dart`
- Modify: `mobile/README.md`
- Modify: `docs/AI_CONTINUATION.md`

**Interfaces:**
- Consumes: production report list/detail and fake report providers.
- Produces: reproducible native-ready, failed, legacy, detail-ready, detail-loading and detail-error states.

- [ ] **Step 1: Write failing Gallery assertions**

Require these IDs exactly:

```dart
for (final id in ['reports_native_ready', 'reports_native_failed', 'reports_native_legacy', 'report_native_detail', 'report_native_detail_loading', 'report_native_detail_error']) {
  expect(galleryScreenManifest.where((spec) => spec.id == id), hasLength(1));
}
```

Pump native-failed and native-detail Gallery previews in dark/daylight themes, asserting production labels rather than copied preview UI.

- [ ] **Step 2: Run Gallery test and observe RED**

Run:

```sh
cd mobile
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy fvm flutter test --no-pub test/debug_ui/debug_ui_gallery_screen_test.dart -r compact
```

Expected: failure because native report review states and fake detail data are absent.

- [ ] **Step 3: Wire Gallery and migration documentation**

Add the six manifest states and override only report data providers in Gallery; selecting a detail state must instantiate `ReportDetailScreen`. Do not duplicate report widgets or write Golden files. Update `mobile/README.md` with structured report behavior, legacy migration and deferred PNG export. At completion update `docs/AI_CONTINUATION.md` with Backend dependency, tests, Simulator outcome and known Golden baseline limitation.

- [ ] **Step 4: Run focused quality and Simulator checks**

Run:

```sh
cd mobile
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy fvm dart format lib/features/reports lib/app/router.dart lib/debug_ui/gallery_manifest.dart lib/debug_ui/gallery_preview.dart test/features/reports test/debug_ui/debug_ui_gallery_screen_test.dart
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy fvm flutter test --no-pub --concurrency=1 test/features/reports test/debug_ui/debug_ui_gallery_screen_test.dart -r compact
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy fvm flutter analyze
git diff --check
```

Launch Debug Gallery on iPhone 18 Pro `A49C5D93-E5D2-421F-8F4D-1F271512BB46` and review native-ready, failed, legacy, detail-ready, detail-error and daylight. Confirm no card action leaves the App and metric labels remain reachable at phone width.

- [ ] **Step 5: Run required Mobile script and classify Golden results**

Run:

```sh
cd /Users/bob/Desktop/code/ry-aletheia
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy ./scripts/test-mobile.sh
```

Expected: all source/unit/widget failures from this feature block delivery. Existing Gallery Golden failures are recorded separately and their generated files are neither re-recorded nor deleted.

## Plan Self-Review

- Spec coverage: Task 1 owns Shared compatibility/migration; Tasks 2–3 own fail-closed data and low-load pagination; Task 4 owns Apple-style native UI/no browser/delete safety; Task 5 owns Gallery, device review, docs and full script classification. PNG/Photos remains excluded.
- Placeholder scan: no TBD/TODO or unspecified code/test actions remain.
- Type consistency: `NativeReportSummary`, `NativeReportDetailPage`, `NativeReportItem`, `loadNativeDetail`, `nativeReportDetailProvider`, `reportId`, `cursor` and `nextCursor` use one spelling throughout.
