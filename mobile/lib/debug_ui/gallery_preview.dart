import 'dart:async';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../app/app_shell.dart';
import '../app/theme/aletheia_theme.dart';
import '../core/connection/observation_status.dart';
import '../core/connection/robot_connection_controller.dart';
import '../core/connection/robot_connection_state.dart';
import '../core/connection/robot_endpoint.dart';
import '../features/live_observation/application/cloud_telemetry_provider.dart';
import '../features/live_observation/application/live_observation_controller.dart';
import '../features/live_observation/application/pose_telemetry_provider.dart';
import '../features/live_observation/application/video_status_controller.dart';
import '../features/live_observation/data/cloud_telemetry_client.dart';
import '../features/live_observation/data/pose_telemetry_client.dart';
import '../features/live_observation/domain/cloud_frame.dart';
import '../features/live_observation/domain/live_map.dart';
import '../features/live_observation/domain/pose_frame.dart';
import '../features/live_observation/domain/video_status.dart';
import '../features/live_observation/presentation/live_observation_screen.dart';
import '../features/live_observation/presentation/whep_video_view.dart';
import '../features/reports/application/reports_controller.dart';
import '../features/reports/domain/aletheia_report.dart';
import '../features/reports/presentation/reports_screen.dart';
import '../features/robot_connection/presentation/robot_connection_screen.dart';
import '../features/test_cases/application/test_cases_controller.dart';
import '../features/test_cases/data/test_cases_repository.dart';
import '../features/test_cases/domain/aletheia_test_case.dart';
import '../features/test_cases/presentation/test_cases_screen.dart';
import '../features/test_runs/application/test_runs_controller.dart';
import '../features/test_runs/domain/aletheia_run.dart';
import '../features/test_runs/presentation/test_runs_screen.dart';
import '../features/tool_logs/application/tool_logs_controller.dart';
import '../features/tool_logs/domain/tool_log_entry.dart';
import '../features/tool_logs/presentation/tool_logs_screen.dart';
import '../features/tools/presentation/tools_screen.dart';
import '../features/runtime_settings/application/runtime_settings_controller.dart';
import '../features/runtime_settings/domain/runtime_settings.dart';
import '../features/runtime_settings/presentation/runtime_settings_screen.dart';
import '../features/scenario_setup/application/scenario_setup_controller.dart';
import '../features/scenario_setup/domain/scenario_setup.dart';
import '../features/scenario_setup/presentation/scenario_setup_screen.dart';
import '../features/system_maintenance/presentation/system_maintenance_screen.dart';
import '../features/app_settings/presentation/app_settings_screen.dart';
import '../features/app_settings/presentation/app_update_screen.dart';
import '../features/app_settings/presentation/feedback_screen.dart';
import '../features/app_settings/domain/feedback_draft.dart';
import 'debug_map_fixture.dart';
import 'gallery_manifest.dart';

/// Renders a real production page with deterministic local state.
///
/// Every service-facing provider used below is overridden before the page is
/// built. This makes the gallery safe to open with no robot or network.
class DebugGalleryPreview extends StatelessWidget {
  const DebugGalleryPreview({
    required this.spec,
    this.includeShell = true,
    super.key,
  });

  final GalleryScreenSpec spec;
  final bool includeShell;

  static DebugMapFixtureData? _loadedSampleMap;
  static Future<DebugMapFixtureData>? _sampleMapLoad;

  /// Used by the deterministic screenshot pipeline so its first frame uses
  /// the same real fixture that appears after the Debug Gallery has loaded on
  /// a handset.
  static Future<void> preloadSampleMap() async {
    await _loadSampleMap();
  }

  static Future<DebugMapFixtureData> _loadSampleMap() =>
      _sampleMapLoad ??= DebugMapFixture.load().then((map) {
        _loadedSampleMap = map;
        return map;
      });

  @override
  Widget build(BuildContext context) {
    final loadedMap = _loadedSampleMap;
    if (loadedMap != null) {
      return _GalleryPreviewScope(
        spec: spec,
        includeShell: includeShell,
        map: loadedMap.map,
        previewBuilder: _decodedMapPreview(loadedMap.previewImage),
      );
    }
    return FutureBuilder<DebugMapFixtureData>(
      future: _loadSampleMap(),
      builder: (context, snapshot) => _GalleryPreviewScope(
        spec: spec,
        includeShell: includeShell,
        // A short, deterministic fallback keeps the normal Gallery states
        // renderable while the debug asset bundle is being read. The real PGM
        // fixture replaces it as soon as it is available.
        map: snapshot.data?.map ?? _galleryFallbackMap,
        previewBuilder: snapshot.data == null
            ? _mockMapPreview
            : _decodedMapPreview(snapshot.data!.previewImage),
      ),
    );
  }
}

class _GalleryPreviewScope extends StatelessWidget {
  const _GalleryPreviewScope({
    required this.spec,
    required this.includeShell,
    required this.map,
    required this.previewBuilder,
  });

  final GalleryScreenSpec spec;
  final bool includeShell;
  final LiveMapAsset map;
  final LiveMapPreviewBuilder previewBuilder;

  @override
  Widget build(BuildContext context) {
    // Provider overrides are intentionally captured when a ProviderScope is
    // created. Key it by screen id and map asset so switching a Gallery item
    // or finishing the asynchronous real-map load both rebuild the mock
    // graph instead of retaining the placeholder-map controller state.
    return ProviderScope(
      key: ValueKey('${spec.id}-${map.id}'),
      overrides: [
        robotConnectionControllerProvider.overrideWith(
          () => _GalleryRobotConnectionController(_connectionFor(spec)),
        ),
        liveObservationControllerProvider.overrideWith(
          () => _GalleryObservationController(_observationFor(spec, map)),
        ),
        videoStatusControllerProvider.overrideWith(
          () => _GalleryVideoStatusController(_videoFor(spec)),
        ),
        poseTelemetryProvider.overrideWith((ref) => _poseStreamFor(spec)),
        cloudTelemetryProvider.overrideWith((ref) => _cloudStreamFor(spec)),
        testRunsControllerProvider.overrideWith(
          () => _GalleryTestRunsController(_testRunsStateFor(spec)),
        ),
        caseCatalogProvider.overrideWith(
          () => _GalleryCaseCatalogController(_catalogModeFor(spec)),
        ),
        selectedCaseIdProvider.overrideWith(
          () => _GallerySelectedCaseIdController(
            _catalogModeFor(spec) == _CatalogMode.ready
                ? _galleryCase.id
                : null,
          ),
        ),
        toolLogScopeProvider.overrideWith(
          () => _GalleryLogScopeController(
            spec.id == 'logs_errors' ? ToolLogScope.errors : ToolLogScope.all,
          ),
        ),
        toolLogEntriesProvider.overrideWith((ref) => _logsFor(spec)),
        diagnosticFilesProvider.overrideWith((ref) async => _galleryLogFiles),
        reportsProvider.overrideWith((ref) => _reportsFor(spec)),
        runtimeSettingsProvider.overrideWith((ref) async => _gallerySettings),
        supervisorProcessesProvider.overrideWith(
          (ref) async => _gallerySupervisorProcesses,
        ),
        scenarioSetupProvider.overrideWith((ref) async => _scenarioFor(spec)),
        liveMapPreviewBuilderProvider.overrideWith((ref) => previewBuilder),
        whepVideoPreviewBuilderProvider.overrideWith((ref) => _mockVideoFrame),
      ],
      child: _PreviewPage(spec: spec, includeShell: includeShell),
    );
  }
}

class _PreviewPage extends StatefulWidget {
  const _PreviewPage({required this.spec, required this.includeShell});

  final GalleryScreenSpec spec;
  final bool includeShell;

  @override
  State<_PreviewPage> createState() => _PreviewPageState();
}

class _PreviewPageState extends State<_PreviewPage> {
  ScrollController? _testRunScrollController;
  bool _previewSheetQueued = false;

  @override
  void initState() {
    super.initState();
    _configureTestRunScrollController();
    _showGalleryFilePreview();
  }

  @override
  void didUpdateWidget(covariant _PreviewPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.spec.focusTestRunDetails != widget.spec.focusTestRunDetails) {
      _configureTestRunScrollController();
    }
    if (oldWidget.spec.id != widget.spec.id) {
      _previewSheetQueued = false;
      _showGalleryFilePreview();
    }
  }

  void _showGalleryFilePreview() {
    if (widget.spec.id != 'scenario_setup_file_preview' ||
        _previewSheetQueued) {
      return;
    }
    _previewSheetQueued = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      showModalBottomSheet<void>(
        context: context,
        isScrollControlled: true,
        builder: (context) =>
            ScenarioFilePreviewSheet(preview: _galleryScenarioFilePreview),
      );
    });
  }

  void _configureTestRunScrollController() {
    _testRunScrollController?.dispose();
    _testRunScrollController = widget.spec.focusTestRunDetails
        ? ScrollController(initialScrollOffset: 560)
        : null;
  }

  @override
  void dispose() {
    _testRunScrollController?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final child = switch (widget.spec.surface) {
      GallerySurface.robot => const RobotConnectionScreen(embedded: true),
      GallerySurface.observationMap => LiveObservationScreen(
        key: ValueKey(widget.spec.id),
      ),
      GallerySurface.observationVideo => LiveObservationScreen(
        key: ValueKey(widget.spec.id),
        initialWorkspace: ObservationWorkspace.camera,
      ),
      GallerySurface.toolsHome => const ToolsScreen(),
      GallerySurface.testRuns => TestRunsScreen(
        scrollController: _testRunScrollController,
      ),
      GallerySurface.testCases => const TestCasesScreen(),
      GallerySurface.logs => const ToolLogsScreen(),
      GallerySurface.reports => const ReportsScreen(),
      GallerySurface.runtimeSettings => const RuntimeSettingsScreen(),
      GallerySurface.scenarioSetup => const ScenarioSetupScreen(),
      GallerySurface.maintenance => const SystemMaintenanceScreen(),
      GallerySurface.appSettings => const AppSettingsScreen(embedded: true),
      GallerySurface.appUpdate => AppUpdateScreen(
        initialHasChecked: widget.spec.showUpdateCheckResult,
      ),
      GallerySurface.appFeedback => AppFeedbackScreen(
        initialDraft: FeedbackDraft.gallery,
        initialScrollOffset: widget.spec.focusFeedbackAttachments ? 500 : 0,
      ),
      GallerySurface.dialog ||
      GallerySurface.bottomSheet ||
      GallerySurface.snackbar ||
      GallerySurface.permission ||
      GallerySurface.offline ||
      GallerySurface.empty => _GlobalStatePreview(spec: widget.spec),
    };
    if (!widget.includeShell || widget.spec.module == GalleryModule.global) {
      return child;
    }
    return AletheiaAppShell(location: widget.spec.route, child: child);
  }
}

class _GalleryRobotConnectionController extends RobotConnectionController {
  _GalleryRobotConnectionController(this._preview);

  final RobotConnectionState _preview;

  @override
  RobotConnectionState build() => _preview;

  @override
  Future<void> connect(String rawAddress) async {}

  @override
  Future<void> refresh() async {}

  @override
  Future<void> startObservation() async {}

  @override
  void pauseHeartbeats() {}

  @override
  void resumeHeartbeats() {}
}

class _GalleryObservationController extends LiveObservationController {
  _GalleryObservationController(this._preview);

  final LiveObservationState _preview;

  @override
  LiveObservationState build() => _preview;

  @override
  Future<void> refresh() async {}

  @override
  void activate() {}

  @override
  void pauseMapPolling() {}

  @override
  void resumeMapPolling() {}
}

class _GalleryVideoStatusController extends VideoStatusController {
  _GalleryVideoStatusController(this._preview);

  final VideoStatusState _preview;

  @override
  VideoStatusState build() => _preview;

  @override
  void activate() {}

  @override
  void pause() {}

  @override
  Future<void> refresh() async {}

  @override
  Future<void> setPrimaryStreamEnabled(bool enabled) async {}

  @override
  Future<void> setSelectedStreamEnabled(bool enabled) async {}

  @override
  void selectStream(String streamName) {}
}

class _GalleryTestRunsController extends TestRunsController {
  _GalleryTestRunsController(this._preview);

  final TestRunsScreenState _preview;

  @override
  TestRunsScreenState build() => _preview;

  @override
  Future<void> refresh() async {}

  @override
  Future<void> create(TestRunRequest request) async {}

  @override
  Future<void> cancel() async {}

  @override
  Future<void> resume() async {}

  @override
  void pausePolling() {}

  @override
  void resumePolling() {}
}

enum _CatalogMode { loading, error, empty, ready, validation }

class _GalleryCaseCatalogController extends CaseCatalogController {
  _GalleryCaseCatalogController(this._mode);

  final _CatalogMode _mode;

  @override
  Future<CaseCatalog> build() => switch (_mode) {
    _CatalogMode.loading => Completer<CaseCatalog>().future,
    _CatalogMode.error => Future<CaseCatalog>.error(StateError('无法读取测试内容。')),
    _CatalogMode.empty => Future.value(const CaseCatalog.empty()),
    _CatalogMode.ready => Future.value(
      const CaseCatalog(cases: [_galleryCase], validationIssues: []),
    ),
    _CatalogMode.validation => Future.value(
      const CaseCatalog(
        cases: [_galleryCase],
        validationIssues: [
          CaseValidationIssue(
            filename: 'lobby-route.yaml',
            message: '起点信息不完整，请在机器人端补全后再执行。',
          ),
        ],
      ),
    ),
  };

  @override
  Future<void> refresh() async {}
}

class _GallerySelectedCaseIdController extends SelectedCaseIdController {
  _GallerySelectedCaseIdController(this._initial);

  final String? _initial;

  @override
  String? build() => _initial;

  @override
  void select(String? caseId) {}
}

class _GalleryLogScopeController extends ToolLogScopeController {
  _GalleryLogScopeController(this._initial);

  final ToolLogScope _initial;

  @override
  ToolLogScope build() => _initial;

  @override
  void select(ToolLogScope scope) {}
}

const _galleryCase = AletheiaTestCase(
  id: 'gallery-lobby-route',
  filename: 'lobby-route.yaml',
  name: '大厅路线验证',
  alias: '大厅路线',
  parameters: TestCaseParameters(
    community: '示例园区',
    building: 1,
    unit: 2,
    floor: 3,
    door: 305,
  ),
  management: TestCaseManagement(
    lifecycle: 'approved',
    version: '1.2.0',
    summary: '验证机器人从起点到大厅目标点的标准路线。',
    tags: ['路径', '回归'],
  ),
);

final _galleryEndpoint = RobotEndpoint.parse('192.168.1.20');

RobotConnectionState _connectionFor(GalleryScreenSpec spec) {
  final healthy = ObservationStatus(
    enabledInConfiguration: true,
    telemetryOnline: true,
    telemetryWebSocketPort: 8768,
    telemetryDetail: '实时数据正常',
    preprocessorAvailable: true,
    preprocessorManaged: true,
    activeMapId: 'gallery-map',
    idleStopSeconds: 120,
  );
  switch (spec.id) {
    case 'robot_disconnected':
    case 'observe_disconnected':
    case 'tools_disconnected':
    case 'test_disconnected':
    case 'case_disconnected':
    case 'logs_disconnected':
    case 'reports_disconnected':
      return const RobotConnectionState(phase: ConnectionPhase.idle);
    case 'robot_restoring':
      return RobotConnectionState(
        phase: ConnectionPhase.restoring,
        endpoint: _galleryEndpoint,
        message: '正在恢复上次使用的机器人。',
      );
    case 'robot_connecting':
      return RobotConnectionState(
        phase: ConnectionPhase.checking,
        endpoint: _galleryEndpoint,
        message: '正在检查 192.168.1.20:8087…',
      );
    case 'robot_connection_failed':
      return RobotConnectionState(
        phase: ConnectionPhase.failure,
        endpoint: _galleryEndpoint,
        message: '无法连接到机器人，请检查地址和局域网连接。',
      );
    case 'robot_network_error':
      return RobotConnectionState(
        phase: ConnectionPhase.connected,
        endpoint: _galleryEndpoint,
        observation: healthy,
        message: '网络暂时不可用，正在等待下一次检查。',
      );
    case 'robot_health_warning':
      return RobotConnectionState(
        phase: ConnectionPhase.connected,
        endpoint: _galleryEndpoint,
        observation: ObservationStatus(
          enabledInConfiguration: true,
          telemetryOnline: false,
          telemetryWebSocketPort: null,
          telemetryDetail: '实时数据未启动',
          preprocessorAvailable: true,
          preprocessorManaged: false,
          activeMapId: null,
          idleStopSeconds: 120,
        ),
        message: '实时观测尚未准备好。',
      );
    default:
      return RobotConnectionState(
        phase: ConnectionPhase.connected,
        endpoint: _galleryEndpoint,
        observation: healthy,
        lastChecked: DateTime(2026, 8, 27, 10, 30),
      );
  }
}

LiveObservationState _observationFor(
  GalleryScreenSpec spec,
  LiveMapAsset galleryMap,
) => switch (spec.id) {
  'observe_loading' => const LiveObservationState(),
  'observe_empty' => const LiveObservationState(
    phase: LiveObservationPhase.ready,
    message: '暂未找到活动地图，实时位置仍会继续更新。',
  ),
  'observe_unavailable' => const LiveObservationState(
    phase: LiveObservationPhase.unavailable,
    message: '实时观测暂不可用，请稍后重试。',
  ),
  'observe_error' => const LiveObservationState(
    phase: LiveObservationPhase.failure,
    message: '地图服务暂时没有响应。',
  ),
  _ => LiveObservationState(
    phase: LiveObservationPhase.ready,
    map: galleryMap,
    message: spec.id == 'observe_telemetry_interrupted'
        ? '地图可用，正在等待实时位置和点云。'
        : '',
  ),
};

final _galleryFallbackMap = LiveMapAsset(
  id: 'gallery-map',
  metadata: const LiveMapMetadata(
    width: 80,
    height: 60,
    resolution: .1,
    originX: -4,
    originY: -3,
    frameId: 'map',
  ),
  previewBytes: Uint8List.fromList(const [
    137,
    80,
    78,
    71,
    13,
    10,
    26,
    10,
    0,
    0,
    0,
    13,
    73,
    72,
    68,
    82,
    0,
    0,
    0,
    1,
    0,
    0,
    0,
    1,
    8,
    6,
    0,
    0,
    0,
    31,
    21,
    196,
    137,
    0,
    0,
    0,
    13,
    73,
    68,
    65,
    84,
    8,
    215,
    99,
    248,
    207,
    192,
    240,
    31,
    0,
    5,
    0,
    1,
    255,
    137,
    153,
    61,
    29,
    0,
    0,
    0,
    0,
    73,
    69,
    78,
    68,
    174,
    66,
    96,
    130,
  ]),
  virtualWalls: const [
    LiveMapVirtualWall(
      coordinateMode: VirtualWallCoordinateMode.world,
      points: [
        VirtualWallPoint(x: -2.8, y: -2.1),
        VirtualWallPoint(x: -1.2, y: -2.1),
        VirtualWallPoint(x: -1.2, y: -.4),
      ],
    ),
  ],
);

VideoStatusState _videoFor(GalleryScreenSpec spec) {
  if (spec.id == 'video_loading') {
    return const VideoStatusState();
  }
  if (spec.id == 'video_error') {
    return const VideoStatusState(
      phase: VideoStatusPhase.failure,
      message: '视频状态服务暂时不可用。',
    );
  }
  if (spec.id == 'video_empty') {
    return const VideoStatusState(
      phase: VideoStatusPhase.ready,
      status: VideoStatus(
        enabled: true,
        gateway: VideoGateway(online: true, detail: '正常'),
        streams: [],
      ),
    );
  }
  final availability = switch (spec.id) {
    'video_waiting' => VideoStreamAvailability.waiting,
    'video_offline' => VideoStreamAvailability.offline,
    _ => VideoStreamAvailability.online,
  };
  final gatewayOnline = spec.id != 'video_offline';
  return VideoStatusState(
    phase: VideoStatusPhase.ready,
    status: VideoStatus(
      enabled: true,
      gateway: VideoGateway(
        online: gatewayOnline,
        detail: gatewayOnline ? '视频服务正常' : '视频服务离线',
      ),
      streams: [
        for (final descriptor in const [
          ('front_camera', '1280 × 720'),
          ('back_camera', '1280 × 720'),
          ('left_camera', '1024 × 576'),
          ('right_camera', '1024 × 576'),
          ('detection_camera', '1280 × 720'),
          ('segmentation_overlay', '1280 × 720'),
        ])
          VideoStream(
            name: descriptor.$1,
            enabled: true,
            availability: availability,
            resolution: descriptor.$2,
            fps: 30,
            sourceTopic: descriptor.$1,
            codec: 'H264',
            whepUri: Uri.parse('http://gallery.invalid/whep/${descriptor.$1}'),
          ),
      ],
    ),
  );
}

Stream<PoseTelemetrySample> _poseStreamFor(GalleryScreenSpec spec) {
  if (spec.id == 'observe_telemetry_interrupted') {
    return const Stream<PoseTelemetrySample>.empty();
  }
  return Stream<PoseTelemetrySample>.value(
    PoseTelemetrySample(
      receivedPackets: 2,
      frame: PoseFrame(
        sequence: 42,
        sourceTimestampNanoseconds:
            DateTime.now().microsecondsSinceEpoch * 1000,
        x: .5,
        y: .5,
        yaw: .7,
      ),
    ),
  );
}

Stream<CloudTelemetrySample> _cloudStreamFor(GalleryScreenSpec spec) {
  if (spec.id == 'observe_telemetry_interrupted') {
    return const Stream<CloudTelemetrySample>.empty();
  }
  return Stream<CloudTelemetrySample>.value(
    CloudTelemetrySample(
      receivedPackets: 2,
      frame: CloudFrame(
        sequence: 42,
        sourceTimestampNanoseconds:
            DateTime.now().microsecondsSinceEpoch * 1000,
        packedMapPoints: Float32List.fromList(const [
          .15,
          .2,
          .28,
          .45,
          .55,
          .55,
          .7,
          .4,
          .82,
          .72,
        ]),
      ),
    ),
  );
}

TestRunsScreenState _testRunsStateFor(GalleryScreenSpec spec) {
  if (spec.id == 'test_empty' ||
      spec.id == 'test_cases_loading' ||
      spec.id == 'test_cases_error') {
    return const TestRunsScreenState();
  }
  final status = switch (spec.id) {
    'test_queued' => AletheiaRunStatus.queued,
    'test_preparing' ||
    'test_supervisor_waiting' => AletheiaRunStatus.preparing,
    'test_running' ||
    'test_stall_alert' ||
    'test_trajectory_evidence' ||
    'test_supervisor_ready' ||
    'test_supervisor_optional_warning' => AletheiaRunStatus.running,
    'test_awaiting_recovery' ||
    'test_supervisor_recovery' => AletheiaRunStatus.awaitingRecovery,
    'test_recovering' => AletheiaRunStatus.recovering,
    'test_cancelling' => AletheiaRunStatus.cancelling,
    'test_cancelled' => AletheiaRunStatus.cancelled,
    'test_completed' => AletheiaRunStatus.completed,
    'test_blocked' ||
    'test_supervisor_required_failure' => AletheiaRunStatus.blocked,
    'test_failed' => AletheiaRunStatus.failed,
    _ => AletheiaRunStatus.unknown,
  };
  return TestRunsScreenState(
    run: _galleryRun(
      status,
      _supervisorSnapshotFor(spec.id),
      hasStallAlert: spec.id == 'test_stall_alert',
      hasTrajectoryEvidence: spec.id == 'test_trajectory_evidence',
    ),
  );
}

AletheiaRun _galleryRun(
  AletheiaRunStatus status,
  _GallerySupervisorSnapshot supervisorSnapshot, {
  bool hasStallAlert = false,
  bool hasTrajectoryEvidence = false,
}) => AletheiaRun.fromJson({
  'id': 'G-042',
  'case': {
    'id': _galleryCase.id,
    'filename': _galleryCase.filename,
    'name': _galleryCase.name,
  },
  'requestedCount': 3,
  'intervalSeconds': 3,
  'status': switch (status) {
    AletheiaRunStatus.awaitingRecovery => 'awaiting_recovery',
    _ => status.name,
  },
  'error': status == AletheiaRunStatus.failed
      ? '机器人未在预期时间内到达目标点。'
      : supervisorSnapshot == _GallerySupervisorSnapshot.requiredFailure
      ? '必需运行依赖未全部处于 RUNNING 状态。'
      : null,
  'preflight': {
    'task_sync': supervisorSnapshot == _GallerySupervisorSnapshot.waiting
        ? '正在读取运行依赖状态'
        : '测试条件已确认',
    'node_states': _gallerySupervisorNodes(supervisorSnapshot),
  },
  'liveProgress': {
    'visible': status.isActive,
    'percent': status.isActive ? 58 : null,
    'state': status.isActive ? '正在验证路线' : '',
    'progress_available': status.isActive,
    'alert': hasStallAlert,
    'alert_reason': hasStallAlert ? '车辆位置持续无明显变化' : '',
    'stalled_seconds': hasStallAlert ? 46 : 0,
  },
  'cancelRequested': status == AletheiaRunStatus.cancelling,
  'activeAttempt': 2,
  'summary': {
    'completed': status == AletheiaRunStatus.completed ? 3 : 1,
    'passed': status == AletheiaRunStatus.completed ? 3 : 1,
    'failed': status == AletheiaRunStatus.failed ? 1 : 0,
    'cancelled': status == AletheiaRunStatus.cancelled ? 1 : 0,
    'passRate': status == AletheiaRunStatus.failed ? 50 : 100,
  },
  'attempts': [
    {
      'index': 1,
      'status': 'passed',
      'message': '已完成路线验证。',
      if (hasTrajectoryEvidence)
        'trajectory': {
          'visualizations': [
            {'map_id': 'floor-1', 'label': '一层主地图'},
            {'map_id': 'elevator', 'label': '电梯区域'},
          ],
        },
    },
  ],
  'interventions': [],
});

enum _GallerySupervisorSnapshot {
  waiting,
  ready,
  optionalWarning,
  requiredFailure,
  recovery,
}

_GallerySupervisorSnapshot _supervisorSnapshotFor(String id) => switch (id) {
  'test_queued' ||
  'test_preparing' ||
  'test_supervisor_waiting' => _GallerySupervisorSnapshot.waiting,
  'test_supervisor_optional_warning' =>
    _GallerySupervisorSnapshot.optionalWarning,
  'test_blocked' || 'test_failed' || 'test_supervisor_required_failure' =>
    _GallerySupervisorSnapshot.requiredFailure,
  'test_awaiting_recovery' ||
  'test_recovering' ||
  'test_supervisor_recovery' => _GallerySupervisorSnapshot.recovery,
  _ => _GallerySupervisorSnapshot.ready,
};

List<Map<String, dynamic>> _gallerySupervisorNodes(
  _GallerySupervisorSnapshot snapshot,
) {
  if (snapshot == _GallerySupervisorSnapshot.waiting) {
    return const [];
  }
  return [
    {
      'id': 'navigation',
      'label': '导航服务',
      'supervisor': 'robot-navigation',
      'required': true,
      'status': 'RUNNING',
    },
    {
      'id': 'localization',
      'label': '定位服务',
      'supervisor': 'robot-localization',
      'required': true,
      'status': snapshot == _GallerySupervisorSnapshot.requiredFailure
          ? 'FATAL'
          : snapshot == _GallerySupervisorSnapshot.recovery
          ? 'BACKOFF'
          : 'RUNNING',
    },
    {
      'id': 'recorder',
      'label': '轨迹记录',
      'supervisor': 'robot-recorder',
      'required': false,
      'status': snapshot == _GallerySupervisorSnapshot.optionalWarning
          ? 'BACKOFF'
          : snapshot == _GallerySupervisorSnapshot.requiredFailure
          ? 'STOPPED'
          : 'RUNNING',
    },
  ];
}

_CatalogMode _catalogModeFor(GalleryScreenSpec spec) => switch (spec.id) {
  'test_cases_loading' || 'case_loading' => _CatalogMode.loading,
  'test_cases_error' || 'case_error' => _CatalogMode.error,
  'case_empty' => _CatalogMode.empty,
  'case_validation' => _CatalogMode.validation,
  _ => _CatalogMode.ready,
};

Future<List<ToolLogEntry>> _logsFor(GalleryScreenSpec spec) =>
    switch (spec.id) {
      'logs_loading' => Completer<List<ToolLogEntry>>().future,
      'logs_error' => Future<List<ToolLogEntry>>.error(StateError('无法读取诊断日志。')),
      'logs_empty' => Future.value(const []),
      'logs_errors' => Future.value(
        _galleryLogs.where((entry) => entry.level.isError).toList(),
      ),
      _ => Future.value(_galleryLogs),
    };

const _galleryLogs = <ToolLogEntry>[
  ToolLogEntry(
    time: '10:30:42',
    level: ToolLogLevel.info,
    source: 'navigation',
    message: '已收到新的实时位置。',
    exception: '',
  ),
  ToolLogEntry(
    time: '10:31:06',
    level: ToolLogLevel.warning,
    source: 'observer',
    message: '点云数据短暂延迟，正在等待下一帧。',
    exception: '',
  ),
  ToolLogEntry(
    time: '10:31:18',
    level: ToolLogLevel.error,
    source: 'test-run',
    message: '路线验证未完成。',
    exception: '任务在时限内没有到达目标区域。',
  ),
];

Future<List<AletheiaReport>> _reportsFor(GalleryScreenSpec spec) =>
    switch (spec.id) {
      'reports_loading' => Completer<List<AletheiaReport>>().future,
      'reports_error' => Future<List<AletheiaReport>>.error(
        StateError('无法读取测试报告。'),
      ),
      'reports_empty' => Future.value(const []),
      _ => Future.value([
        AletheiaReport(
          filename: 'route-validation-2026-08-27.html',
          sizeBytes: 234112,
          modifiedAt: DateTime(2026, 8, 27, 10, 32),
          csvFilename: 'route-validation-2026-08-27.csv',
        ),
      ]),
    };

Widget _mockVideoFrame({required Uri endpoint, required String resolution}) =>
    const _MockVideoFrame();

Widget _mockMapPreview({required LiveMapAsset map}) =>
    const CustomPaint(painter: _GalleryMapPainter(), child: SizedBox.expand());

LiveMapPreviewBuilder _decodedMapPreview(ui.Image image) =>
    ({required LiveMapAsset map}) => RawImage(
      image: image,
      fit: BoxFit.fill,
      filterQuality: FilterQuality.none,
    );

class _GalleryMapPainter extends CustomPainter {
  const _GalleryMapPainter();

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawColor(const Color(0xFF1D2826), BlendMode.srcOver);
    final grid = Paint()
      ..color = AletheiaTheme.border.withValues(alpha: .42)
      ..strokeWidth = 1;
    const spacing = 28.0;
    for (double x = 0; x <= size.width; x += spacing) {
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), grid);
    }
    for (double y = 0; y <= size.height; y += spacing) {
      canvas.drawLine(Offset(0, y), Offset(size.width, y), grid);
    }

    final walls = Paint()..color = const Color(0xFF667470);
    canvas.drawRect(
      Rect.fromLTWH(0, size.height * .08, size.width * .63, 16),
      walls,
    );
    canvas.drawRect(
      Rect.fromLTWH(size.width * .38, size.height * .08, 16, size.height * .54),
      walls,
    );
    canvas.drawRect(
      Rect.fromLTWH(size.width * .38, size.height * .58, size.width * .47, 16),
      walls,
    );
    canvas.drawRect(
      Rect.fromLTWH(size.width * .76, size.height * .2, 16, size.height * .38),
      walls,
    );

    final route = Paint()
      ..color = AletheiaTheme.cyan.withValues(alpha: .9)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 4
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;
    final path = Path()
      ..moveTo(size.width * .15, size.height * .78)
      ..lineTo(size.width * .27, size.height * .62)
      ..lineTo(size.width * .58, size.height * .62)
      ..lineTo(size.width * .68, size.height * .4)
      ..lineTo(size.width * .88, size.height * .3);
    canvas.drawPath(path, route);

    final marker = Paint()..color = AletheiaTheme.mint;
    canvas.drawCircle(Offset(size.width * .15, size.height * .78), 8, marker);
    canvas.drawCircle(Offset(size.width * .88, size.height * .3), 9, marker);
  }

  @override
  bool shouldRepaint(covariant _GalleryMapPainter oldDelegate) => false;
}

class _MockVideoFrame extends StatelessWidget {
  const _MockVideoFrame();

  @override
  Widget build(BuildContext context) {
    return Stack(
      fit: StackFit.expand,
      children: [
        ColoredBox(color: Color(0xFF172021)),
        Align(
          alignment: Alignment(.28, .18),
          child: Container(
            width: 88,
            height: 88,
            decoration: BoxDecoration(
              color: AletheiaTheme.cyan.withValues(alpha: .2),
              borderRadius: BorderRadius.circular(44),
              border: Border.all(
                color: AletheiaTheme.cyan.withValues(alpha: .7),
              ),
            ),
            child: Icon(
              Icons.smart_toy_outlined,
              color: AletheiaTheme.cyan,
              size: 42,
            ),
          ),
        ),
        const Positioned(left: 12, top: 12, child: _VideoLivePill()),
      ],
    );
  }
}

class _VideoLivePill extends StatelessWidget {
  const _VideoLivePill();

  @override
  Widget build(BuildContext context) => DecoratedBox(
    decoration: BoxDecoration(
      color: Colors.black.withValues(alpha: .48),
      borderRadius: BorderRadius.circular(999),
    ),
    child: const Padding(
      padding: EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      child: Text(
        'LIVE',
        style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700),
      ),
    ),
  );
}

const _gallerySettings = RuntimeSettings(
  taskDirectory: '/opt/ry/data/tasks/origin_tasks',
  commandTimeoutSeconds: 8,
  elevatorWaitTimeoutSeconds: 180,
  taskExecutionTimeoutSeconds: 900,
  monitorNodes: ['MODULES:209-lightning', 'MODULES:211-navigate_todoor_server'],
  dependencyPlan: DependencyPlan(
    enabled: true,
    steps: [
      DependencyStep(nodes: ['MODULES:209-lightning'], waitSeconds: 10),
      DependencyStep(
        nodes: ['MODULES:211-navigate_todoor_server'],
        waitSeconds: 5,
      ),
    ],
  ),
  liveObservation: LiveObservationSettings(
    enabled: true,
    idleStopSeconds: 45,
    activeVehicleModel: 'ry-standard',
    vehicleModels: [
      VehicleModel(
        id: 'ry-standard',
        name: 'RY 标准小车',
        lengthMetres: 1,
        widthMetres: .68,
      ),
    ],
  ),
);

const _gallerySupervisorProcesses = [
  SupervisorProcess(name: 'MODULES:209-lightning', status: 'RUNNING'),
  SupervisorProcess(
    name: 'MODULES:211-navigate_todoor_server',
    status: 'RUNNING',
  ),
  SupervisorProcess(name: 'MODULES:212-task_execute_server', status: 'RUNNING'),
];

const _galleryLogFiles = [
  DiagnosticFile(
    name: 'live_preprocessor_cloud.log',
    label: '实时点云预处理',
    detail: '点云输入与遥测状态',
    sizeBytes: 43820,
    modifiedAt: 1724821200,
  ),
  DiagnosticFile(
    name: 'video-runtime.log',
    label: '视频运行时',
    detail: 'WHEP 与编码器诊断',
    sizeBytes: 18740,
    modifiedAt: 1724821200,
  ),
];

const _galleryScenarioFilePreview = ScenarioFilePreview(
  path: '/opt/ry/launch/fcrp_night.launch.py',
  content: '''from launch import LaunchDescription

def generate_launch_description():
  return LaunchDescription([])
''',
  size: 104,
  sha256: '0f1c5673069ce673a4499db15f603576f3c85d5387369e84ccfd15a8d9d67666',
);

ScenarioSetupStatus _scenarioFor(GalleryScreenSpec spec) {
  const document = ScenarioDocument(
    startupScript: '/opt/ry/scripts/handle_modules.sh',
    searchDirectories: ['/opt/ry'],
    bindings: {},
    caseBindings: {},
    profiles: [
      ScenarioProfile(
        id: 'night-run',
        name: '夜间定位验证',
        fcrpLaunch: '/opt/ry/launch/fcrp_night.launch.py',
        lightningConfig: '/opt/ry/config/lightning_night.yaml',
      ),
    ],
  );
  return ScenarioSetupStatus(
    document: document,
    inspection: const ScenarioInspection(
      path: '/opt/ry/scripts/handle_modules.sh',
      exists: true,
      writable: true,
    ),
    activeBackup: spec.id == 'scenario_setup_pending_restore'
        ? const ScenarioBackup(
            profileName: '夜间定位验证',
            createdAt: '2026-08-28 10:24',
          )
        : null,
  );
}

class _GlobalStatePreview extends StatefulWidget {
  const _GlobalStatePreview({required this.spec});

  final GalleryScreenSpec spec;

  @override
  State<_GlobalStatePreview> createState() => _GlobalStatePreviewState();
}

class _GlobalStatePreviewState extends State<_GlobalStatePreview> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _presentOverlay());
  }

  void _presentOverlay() {
    if (!mounted) {
      return;
    }
    switch (widget.spec.surface) {
      case GallerySurface.dialog:
        unawaited(
          showTestRunConfirmDialog(
            context: context,
            eyebrow: switch (widget.spec.id) {
              'dialog_cancel' => '终止剩余测试',
              'dialog_recovery' => '人工恢复确认',
              _ => '确认自动化测试',
            },
            title: switch (widget.spec.id) {
              'dialog_cancel' => '确认终止尚未开始的轮次？',
              'dialog_recovery' => '机器人已经恢复到测试起点？',
              _ => '开始执行这个测试计划？',
            },
            body: switch (widget.spec.id) {
              'dialog_cancel' => '当前轮结束后将停止后续轮次。',
              'dialog_recovery' => '继续后会从下一轮开始执行，并再次检查测试条件。',
              _ => '将执行“大厅路线”共 3 轮，每轮间隔 3 秒。',
            },
            confirmText: switch (widget.spec.id) {
              'dialog_cancel' => '终止剩余轮次',
              'dialog_recovery' => '确认恢复并继续',
              _ => '确认并创建',
            },
            danger: widget.spec.id == 'dialog_cancel',
          ),
        );
      case GallerySurface.bottomSheet:
        unawaited(
          showModalBottomSheet<void>(
            context: context,
            showDragHandle: true,
            builder: (context) => const _BottomSheetPreview(),
          ),
        );
      case GallerySurface.snackbar:
        ScaffoldMessenger.of(context)
            .showSnackBar(const SnackBar(content: Text('已保存当前设置。')));
      default:
        break;
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('状态预览')),
    body: SafeArea(
      top: false,
      child: Center(child: _GlobalStateCard(spec: widget.spec)),
    ),
  );
}

class _GlobalStateCard extends StatelessWidget {
  const _GlobalStateCard({required this.spec});

  final GalleryScreenSpec spec;

  @override
  Widget build(BuildContext context) {
    final (icon, title, detail, color) = switch (spec.surface) {
      GallerySurface.permission => (
        Icons.lock_outline_rounded,
        '需要访问权限',
        '允许后即可继续使用这一项功能。',
        AletheiaTheme.warning,
      ),
      GallerySurface.offline => (
        Icons.wifi_off_rounded,
        '网络不可用',
        '请检查网络连接后重试。',
        AletheiaTheme.warning,
      ),
      GallerySurface.empty => (
        Icons.inbox_outlined,
        '这里还没有内容',
        '有新的内容时会显示在这里。',
        AletheiaTheme.textSecondary,
      ),
      _ => (
        Icons.tune_rounded,
        '操作状态预览',
        '用于检查 Material 组件在当前主题下的呈现。',
        AletheiaTheme.cyan,
      ),
    };
    return Padding(
      padding: EdgeInsets.all(24),
      child: ConstrainedBox(
        constraints: BoxConstraints(maxWidth: 360),
        child: DecoratedBox(
          decoration: BoxDecoration(
            color: AletheiaTheme.surface,
            border: Border.all(color: AletheiaTheme.border),
            borderRadius: BorderRadius.circular(AletheiaTheme.sectionRadius),
          ),
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(icon, size: 34, color: color),
                const SizedBox(height: 14),
                Text(title, style: Theme.of(context).textTheme.titleMedium),
                SizedBox(height: 7),
                Text(
                  detail,
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    color: AletheiaTheme.textSecondary,
                    height: 1.4,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _BottomSheetPreview extends StatelessWidget {
  const _BottomSheetPreview();

  @override
  Widget build(BuildContext context) => SafeArea(
    top: false,
    child: Padding(
      padding: const EdgeInsets.fromLTRB(24, 8, 24, 28),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text('选择操作', style: Theme.of(context).textTheme.titleLarge),
          SizedBox(height: 8),
          Text(
            '底部操作区用于保持当前页面上下文。',
            style: TextStyle(color: AletheiaTheme.textSecondary),
          ),
          const SizedBox(height: 18),
          FilledButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('完成'),
          ),
        ],
      ),
    ),
  );
}
