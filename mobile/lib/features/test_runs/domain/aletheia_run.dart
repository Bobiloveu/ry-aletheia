enum AletheiaRunStatus {
  queued,
  preparing,
  running,
  awaitingRecovery,
  recovering,
  cancelling,
  cancelled,
  completed,
  blocked,
  failed,
  unknown;

  static AletheiaRunStatus fromWire(Object? value) => switch (value) {
    'queued' => AletheiaRunStatus.queued,
    'preparing' => AletheiaRunStatus.preparing,
    'running' => AletheiaRunStatus.running,
    'awaiting_recovery' => AletheiaRunStatus.awaitingRecovery,
    'recovering' => AletheiaRunStatus.recovering,
    'cancelling' => AletheiaRunStatus.cancelling,
    'cancelled' => AletheiaRunStatus.cancelled,
    'completed' => AletheiaRunStatus.completed,
    'blocked' => AletheiaRunStatus.blocked,
    'failed' => AletheiaRunStatus.failed,
    _ => AletheiaRunStatus.unknown,
  };

  String get label => switch (this) {
    AletheiaRunStatus.queued => '排队中',
    AletheiaRunStatus.preparing => '预检中',
    AletheiaRunStatus.running => '执行中',
    AletheiaRunStatus.awaitingRecovery => '等待人工恢复',
    AletheiaRunStatus.recovering => '恢复预检中',
    AletheiaRunStatus.cancelling => '正在终止',
    AletheiaRunStatus.cancelled => '已取消',
    AletheiaRunStatus.completed => '已完成',
    AletheiaRunStatus.blocked => '已拦截',
    AletheiaRunStatus.failed => '运行中断',
    AletheiaRunStatus.unknown => '未知状态',
  };

  bool get isActive => switch (this) {
    AletheiaRunStatus.queued ||
    AletheiaRunStatus.preparing ||
    AletheiaRunStatus.running ||
    AletheiaRunStatus.awaitingRecovery ||
    AletheiaRunStatus.recovering ||
    AletheiaRunStatus.cancelling => true,
    _ => false,
  };

  bool get canCancel => switch (this) {
    AletheiaRunStatus.queued ||
    AletheiaRunStatus.preparing ||
    AletheiaRunStatus.running ||
    AletheiaRunStatus.awaitingRecovery ||
    AletheiaRunStatus.recovering => true,
    _ => false,
  };
}

class TestRunRequest {
  const TestRunRequest({
    required this.caseId,
    required this.count,
    required this.intervalSeconds,
  });

  final String caseId;
  final int count;
  final double intervalSeconds;
  Map<String, dynamic> toJson() => {
    'caseId': caseId,
    'count': count,
    'intervalSeconds': intervalSeconds,
    'prepareTrajectoryMaps': true,
  };
}

class AletheiaRun {
  const AletheiaRun({
    required this.id,
    required this.testCase,
    required this.requestedCount,
    required this.intervalSeconds,
    required this.status,
    required this.error,
    required this.preflight,
    required this.liveProgress,
    required this.cancelRequested,
    required this.activeAttempt,
    required this.summary,
    required this.attempts,
    required this.interventions,
  });

  factory AletheiaRun.fromJson(Map<String, dynamic> json) {
    return AletheiaRun(
      id: _string(json['id']),
      testCase: RunCase.fromJson(_map(json['case'])),
      requestedCount: _integer(json['requestedCount']) ?? 0,
      intervalSeconds: _double(json['intervalSeconds']) ?? 0,
      status: AletheiaRunStatus.fromWire(json['status']),
      error: _nullableString(json['error']),
      preflight: _map(json['preflight']),
      liveProgress: json['liveProgress'] is Map
          ? RunLiveProgress.fromJson(_map(json['liveProgress']))
          : null,
      cancelRequested: json['cancelRequested'] == true,
      activeAttempt: _integer(json['activeAttempt']),
      summary: RunSummary.fromJson(_map(json['summary'])),
      attempts: _maps(json['attempts'])
          .map(RunAttempt.fromJson)
          .toList(growable: false),
      interventions: _maps(json['interventions'])
          .map(RunIntervention.fromJson)
          .toList(growable: false),
    );
  }

  final String id;
  final RunCase testCase;
  final int requestedCount;
  final double intervalSeconds;
  final AletheiaRunStatus status;
  final String? error;
  final Map<String, dynamic> preflight;
  final RunLiveProgress? liveProgress;
  final bool cancelRequested;
  final int? activeAttempt;
  final RunSummary summary;
  final List<RunAttempt> attempts;
  final List<RunIntervention> interventions;

  String? get preflightMessage {
    final taskSync = preflight['task_sync'];
    if (taskSync is String && taskSync.isNotEmpty) {
      return taskSync;
    }
    final service = _map(preflight['ros_service']);
    final message = service['message'];
    return message is String && message.isNotEmpty ? message : null;
  }

  /// Snapshot supplied by the existing run preflight API. These are read-only
  /// Supervisor observations; the mobile client must not imply that it can
  /// start, stop, or restart the robot's local processes.
  List<RunSupervisorNode> get supervisorNodes =>
      _maps(preflight['node_states'])
          .map(RunSupervisorNode.fromJson)
          .toList(growable: false);

  /// Stable across the controller's one-second polling cadence unless the
  /// actual Supervisor snapshot changes. Presentation uses this to explain a
  /// real state change without animating every poll.
  String get supervisorStateSignature => supervisorNodes
      .map((node) => '${node.id}:${node.status}:${node.required}')
      .join('|');

  static Map<String, dynamic> _map(Object? value) => value is Map
      ? value.map((key, item) => MapEntry(key.toString(), item))
      : const {};

  static List<Map<String, dynamic>> _maps(Object? value) =>
      (value as List<Object?>? ?? const [])
          .whereType<Map>()
          .map(_map)
          .toList(growable: false);

  static String _string(Object? value) => value is String ? value : '';

  static String? _nullableString(Object? value) =>
      value is String ? value : null;

  static int? _integer(Object? value) => value is num ? value.toInt() : null;

  static double? _double(Object? value) =>
      value is num ? value.toDouble() : null;
}

class RunSupervisorNode {
  const RunSupervisorNode({
    required this.id,
    required this.label,
    required this.supervisor,
    required this.required,
    required this.status,
  });

  factory RunSupervisorNode.fromJson(Map<String, dynamic> json) {
    final supervisor = _string(json['supervisor']);
    final id = _string(json['id']);
    final label = _string(json['label']);
    return RunSupervisorNode(
      id: id.isNotEmpty ? id : supervisor,
      label: label.isNotEmpty
          ? label
          : (supervisor.isNotEmpty ? supervisor : '未命名节点'),
      supervisor: supervisor,
      required: json['required'] != false,
      status: _string(json['status']).toUpperCase(),
    );
  }

  final String id;
  final String label;
  final String supervisor;
  final bool required;
  final String status;

  bool get isRunning => status == 'RUNNING';

  String get statusLabel => switch (status) {
    'RUNNING' => '运行中',
    'STARTING' => '启动中',
    'STOPPING' => '停止中',
    'STOPPED' => '已停止',
    'FATAL' => '异常退出',
    'BACKOFF' => '正在重试',
    'EXITED' => '已退出',
    'MISSING' || '' => '未发现',
    _ => status,
  };

  static String _string(Object? value) => value is String ? value : '';
}

class RunCase {
  const RunCase({required this.id, required this.filename, required this.name});

  factory RunCase.fromJson(Map<String, dynamic> json) => RunCase(
    id: json['id'] is String ? json['id'] as String : '',
    filename: json['filename'] is String ? json['filename'] as String : '',
    name: json['name'] is String ? json['name'] as String : '',
  );

  final String id;
  final String filename;
  final String name;
}

class RunSummary {
  const RunSummary({
    required this.completed,
    required this.passed,
    required this.failed,
    required this.cancelled,
    required this.passRate,
  });

  factory RunSummary.fromJson(Map<String, dynamic> json) => RunSummary(
    completed: (json['completed'] as num?)?.toInt() ?? 0,
    passed: (json['passed'] as num?)?.toInt() ?? 0,
    failed: (json['failed'] as num?)?.toInt() ?? 0,
    cancelled: (json['cancelled'] as num?)?.toInt() ?? 0,
    passRate: (json['passRate'] as num?)?.toDouble() ?? 0,
  );

  final int completed;
  final int passed;
  final int failed;
  final int cancelled;
  final double passRate;
}

class RunAttempt {
  const RunAttempt({
    required this.index,
    required this.status,
    required this.message,
    required this.durationSeconds,
    required this.startedAt,
    required this.trajectoryViews,
  });

  factory RunAttempt.fromJson(Map<String, dynamic> json) {
    final trajectory = _map(json['trajectory']);
    return RunAttempt(
      index: (json['index'] as num?)?.toInt() ?? 0,
      status: json['status'] is String ? json['status'] as String : 'unknown',
      message: json['message'] is String ? json['message'] as String : '',
      durationSeconds: (json['duration_s'] as num?)?.toDouble() ?? 0,
      startedAt: json['started_at'] is String
          ? json['started_at'] as String
          : '',
      trajectoryViews: _maps(trajectory['visualizations'])
          .map(RunTrajectoryView.fromJson)
          .where((item) => item.mapId.isNotEmpty)
          .toList(growable: false),
    );
  }

  final int index;
  final String status;
  final String message;
  final double durationSeconds;
  final String startedAt;
  final List<RunTrajectoryView> trajectoryViews;

  static Map<String, dynamic> _map(Object? value) => value is Map
      ? value.map((key, item) => MapEntry(key.toString(), item))
      : const {};

  static List<Map<String, dynamic>> _maps(Object? value) =>
      (value as List<Object?>? ?? const [])
          .whereType<Map>()
          .map(_map)
          .toList(growable: false);
}

/// A per-map SVG evidence view generated by the existing test service.
/// The mobile client only opens this immutable evidence; it never generates
/// paths, alters map data, or sends motion commands.
class RunTrajectoryView {
  const RunTrajectoryView({required this.mapId, required this.label});

  factory RunTrajectoryView.fromJson(Map<String, dynamic> json) =>
      RunTrajectoryView(
        mapId: json['map_id'] is String ? json['map_id'] as String : '',
        label: json['label'] is String ? json['label'] as String : '',
      );

  final String mapId;
  final String label;
}

class RunLiveProgress {
  const RunLiveProgress({
    required this.visible,
    required this.attempt,
    required this.attemptTotal,
    required this.state,
    required this.progressAvailable,
    required this.percent,
    required this.alert,
    required this.alertReason,
    required this.stalledSeconds,
  });

  factory RunLiveProgress.fromJson(Map<String, dynamic> json) =>
      RunLiveProgress(
        visible: json['visible'] == true,
        attempt: (json['attempt'] as num?)?.toInt(),
        attemptTotal: (json['attempt_total'] as num?)?.toInt(),
        state: json['state'] is String ? json['state'] as String : '',
        progressAvailable: json['progress_available'] == true,
        percent: (json['percent'] as num?)?.toDouble(),
        alert: json['alert'] == true,
        alertReason: json['alert_reason'] is String
            ? json['alert_reason'] as String
            : '',
        stalledSeconds: (json['stalled_seconds'] as num?)?.toDouble(),
      );

  final bool visible;
  final int? attempt;
  final int? attemptTotal;
  final String state;
  final bool progressAvailable;
  final double? percent;
  final bool alert;
  final String alertReason;
  final double? stalledSeconds;
}

class RunIntervention {
  const RunIntervention({
    required this.at,
    required this.attempt,
    required this.action,
    required this.detail,
  });

  factory RunIntervention.fromJson(Map<String, dynamic> json) =>
      RunIntervention(
        at: json['at'] is String ? json['at'] as String : '',
        attempt: (json['attempt'] as num?)?.toInt(),
        action: json['action'] is String ? json['action'] as String : '',
        detail: json['detail'] is String ? json['detail'] as String : '',
      );

  final String at;
  final int? attempt;
  final String action;
  final String detail;
}
