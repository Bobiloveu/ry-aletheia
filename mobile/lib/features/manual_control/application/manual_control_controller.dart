import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/connection/robot_connection_controller.dart';
import '../../../core/connection/robot_endpoint.dart';
import '../../../core/network/api_exception.dart';
import '../data/manual_control_repository.dart';
import '../domain/vehicle_control_state.dart';

final manualControlRepositoryProvider = Provider<ManualControlRepository>(
  (ref) => ManualControlRepository(ref.watch(aletheiaApiClientProvider)),
);

final manualControlControllerProvider =
    NotifierProvider<ManualControlController, ManualControlScreenState>(
      ManualControlController.new,
    );

enum ManualControlLink {
  idle,
  healthy,
  delayed,
  locked;

  bool get isLocked => this == ManualControlLink.locked;
}

class ManualControlScreenState {
  const ManualControlScreenState({
    this.status,
    this.isRefreshing = false,
    this.isActionPending = false,
    this.message = '',
    this.isError = false,
    this.hasActiveSession = false,
    this.link = ManualControlLink.idle,
    this.lastControlRoundTrip,
  });

  final VehicleControlState? status;
  final bool isRefreshing;
  final bool isActionPending;
  final String message;
  final bool isError;
  final bool hasActiveSession;
  final ManualControlLink link;
  final Duration? lastControlRoundTrip;

  bool get canSendMotion =>
      hasActiveSession &&
      !link.isLocked &&
      (status?.safety.hasInputTimeout ?? false) &&
      (status?.motionPermittedByBackend ?? false);

  bool get canAdjustMotionSettings =>
      canSendMotion && link != ManualControlLink.delayed;

  bool get isBusy => isRefreshing || isActionPending;

  ManualControlScreenState copyWith({
    VehicleControlState? status,
    bool? isRefreshing,
    bool? isActionPending,
    String? message,
    bool? isError,
    bool? hasActiveSession,
    ManualControlLink? link,
    Duration? lastControlRoundTrip,
  }) => ManualControlScreenState(
    status: status ?? this.status,
    isRefreshing: isRefreshing ?? this.isRefreshing,
    isActionPending: isActionPending ?? this.isActionPending,
    message: message ?? this.message,
    isError: isError ?? this.isError,
    hasActiveSession: hasActiveSession ?? this.hasActiveSession,
    link: link ?? this.link,
    lastControlRoundTrip: lastControlRoundTrip ?? this.lastControlRoundTrip,
  );
}

class ManualControlController extends Notifier<ManualControlScreenState> {
  static const _heartbeatInterval = Duration(milliseconds: 500);
  static const _maximumInputInterval = Duration(milliseconds: 100);
  static const _idleStatusInterval = Duration(seconds: 1);
  static const _activeStatusInterval = Duration(milliseconds: 500);
  static const _stopConfirmationDelays = <Duration>[
    Duration.zero,
    Duration(milliseconds: 60),
    Duration(milliseconds: 80),
  ];

  Timer? _heartbeatTimer;
  Timer? _inputTimer;
  Timer? _statusTimer;
  Timer? _stopConfirmationTimer;
  Timer? _controlWarningTimer;
  late ManualControlRepository _repository;
  RobotEndpoint? _endpoint;
  String? _sessionId;
  VehicleControlVector? _desiredVector;
  int _requestEpoch = 0;
  bool _statusRequestInFlight = false;
  bool _heartbeatRequestInFlight = false;
  bool _vectorRequestInFlight = false;
  bool _stopRequested = false;
  int _remainingStopConfirmations = 0;
  bool _statusPollingPaused = false;

  @override
  ManualControlScreenState build() {
    _repository = ref.read(manualControlRepositoryProvider);
    ref.onDispose(() {
      unawaited(_releaseActiveSession());
    });
    final endpoint = ref.watch(
      robotConnectionControllerProvider.select(
        (connection) => connection.isConnected ? connection.endpoint : null,
      ),
    );
    if (_endpoint != endpoint) {
      final oldEndpoint = _endpoint;
      final oldSessionId = _sessionId;
      _cancelTimers();
      _endpoint = endpoint;
      _sessionId = null;
      _desiredVector = null;
      _statusRequestInFlight = false;
      _heartbeatRequestInFlight = false;
      _vectorRequestInFlight = false;
      _stopRequested = false;
      _remainingStopConfirmations = 0;
      if (oldEndpoint != null && oldSessionId != null) {
        unawaited(_release(oldEndpoint, oldSessionId));
      }
      if (endpoint != null) {
        Future.microtask(() {
          _startStatusPolling();
          unawaited(_load(endpoint));
        });
      }
    }
    return const ManualControlScreenState();
  }

  Future<void> refresh() async {
    final endpoint = _endpoint;
    if (endpoint == null) {
      state = const ManualControlScreenState(
        message: '请先连接机器人。',
        isError: true,
      );
      return;
    }
    await _load(endpoint, showBusy: true);
  }

  Future<void> enter() async {
    final endpoint = _endpoint;
    if (endpoint == null || state.isBusy || _sessionId != null) return;
    await _perform(
      pendingMessage: '正在请求车端切换至手动控制…',
      action: () => _repository.enter(endpoint),
      onSuccess: (status) {
        _sessionId = status.session.id;
        if (_sessionId == null) {
          state = ManualControlScreenState(
            status: status,
            message: '车端未返回有效手动会话，方向控制保持锁定。',
            isError: true,
          );
          return;
        }
        state = ManualControlScreenState(
          status: status,
          hasActiveSession: true,
          link: ManualControlLink.healthy,
          message: !status.safety.hasInputTimeout
              ? '车端未提供输入看门狗参数，方向控制保持锁定。'
              : status.motionPermittedByBackend
              ? '手动控制已就绪。'
              : '正在等待车端确认控制源…',
          isError: !status.safety.hasInputTimeout,
        );
        _startSessionTimers();
        _restartStatusPolling();
      },
    );
  }

  Future<void> sendCommand(VehicleCommand command) async {
    await sendVector(switch (command) {
      VehicleCommand.forward => const VehicleControlVector(1, 0),
      VehicleCommand.backward => const VehicleControlVector(-1, 0),
      VehicleCommand.left => const VehicleControlVector(0, 1),
      VehicleCommand.right => const VehicleControlVector(0, -1),
    });
  }

  Future<void> sendVector(VehicleControlVector vector) async {
    if (vector.isStop) {
      await stop();
      return;
    }
    final endpoint = _endpoint;
    final sessionId = _sessionId;
    if (endpoint == null || sessionId == null || !state.canSendMotion) return;
    _desiredVector = vector;
    _cancelPendingStopConfirmations();
    _stopRequested = false;
    _startInputTimer();
    await _pumpMotion();
  }

  Future<void> stop() async {
    _desiredVector = null;
    _stopRequested = true;
    _remainingStopConfirmations = _stopConfirmationDelays.length;
    _stopConfirmationTimer?.cancel();
    _stopConfirmationTimer = null;
    _inputTimer?.cancel();
    _inputTimer = null;
    final endpoint = _endpoint;
    final sessionId = _sessionId;
    if (endpoint == null || sessionId == null) return;
    await _pumpMotion();
  }

  Future<void> exit() async {
    final endpoint = _endpoint;
    final sessionId = _sessionId;
    if (endpoint == null || sessionId == null) return;
    _cancelSessionTimers();
    _desiredVector = null;
    _stopRequested = false;
    _sessionId = null;
    _restartStatusPolling();
    await _exitToNavigation(endpoint, sessionId, reportError: true);
  }

  Future<void> setSpeed({
    required double linearMps,
    required double angularRadps,
  }) async {
    final endpoint = _endpoint;
    final sessionId = _sessionId;
    if (endpoint == null ||
        sessionId == null ||
        !state.canAdjustMotionSettings ||
        _desiredVector != null ||
        _vectorRequestInFlight ||
        _stopRequested) {
      return;
    }
    await _perform(
      pendingMessage: '正在更新速度档…',
      action: () => _repository.setSpeed(
        endpoint,
        sessionId,
        linearMps: linearMps,
        angularRadps: angularRadps,
      ),
      onSuccess: _setStatus,
    );
  }

  Future<void> releaseEmergencyStop() async {
    final endpoint = _endpoint;
    if (endpoint == null ||
        state.status?.emergency.state != EmergencyStopState.triggered) {
      return;
    }
    await _perform(
      pendingMessage: '已请求解除急停，正在等待车端确认…',
      action: () => _repository.releaseEmergencyStop(endpoint),
      onSuccess: _setStatus,
    );
  }

  Future<void> saveChassisParameters(ChassisParameters parameters) async {
    final endpoint = _endpoint;
    if (endpoint == null) return;
    await _perform(
      pendingMessage: '正在保存底盘参数…',
      action: () => _repository.saveChassisParameters(endpoint, parameters),
      onSuccess: _setStatus,
    );
  }

  Future<void> pauseForLifecycle() async {
    _statusPollingPaused = true;
    _stopStatusPolling();
    await _releaseActiveSession();
  }

  void resumeAfterLifecycle() {
    final endpoint = _endpoint;
    _statusPollingPaused = false;
    _startStatusPolling();
    if (endpoint != null) unawaited(_load(endpoint));
  }

  /// Sends at most one motion request at a time.
  ///
  /// Pointer changes overwrite [_desiredVector] while a request is active.
  /// When it finishes, only the latest intent is sent. This prevents a slow
  /// phone or Wi-Fi link from turning direct manipulation into an old-command
  /// queue. A requested STOP is deliberately sent only after that in-flight
  /// vector settles, so an older vector can never arrive after STOP. Once
  /// stopped, the app sends a finite confirmation burst to make a lost packet
  /// less likely to leave the car moving during a brief Wi-Fi fluctuation.
  Future<void> _pumpMotion() async {
    if (_vectorRequestInFlight) return;
    final endpoint = _endpoint;
    final sessionId = _sessionId;
    if (endpoint == null || sessionId == null) return;

    if (_stopRequested) {
      await _sendStop(endpoint, sessionId);
      return;
    }

    final vector = _desiredVector;
    if (vector == null || !state.canSendMotion) return;

    _vectorRequestInFlight = true;
    final startedAt = DateTime.now();
    var shouldPumpAfterResponse = false;
    _startControlDeadline();
    try {
      final status = await _repository.vector(endpoint, sessionId, vector);
      if (endpoint != _endpoint || sessionId != _sessionId) return;
      _clearControlDeadline();
      _setStatus(
        status,
        link: state.link.isLocked
            ? ManualControlLink.locked
            : ManualControlLink.healthy,
        lastControlRoundTrip: DateTime.now().difference(startedAt),
      );
      shouldPumpAfterResponse =
          _stopRequested ||
          (_desiredVector != null && _desiredVector != vector);
    } on ApiException catch (error) {
      if (endpoint != _endpoint || sessionId != _sessionId) return;
      _clearControlDeadline();
      _desiredVector = null;
      _inputTimer?.cancel();
      _inputTimer = null;
      _stopRequested = true;
      state = state.copyWith(message: error.message, isError: true);
      shouldPumpAfterResponse = true;
    } finally {
      _vectorRequestInFlight = false;
      if (shouldPumpAfterResponse &&
          endpoint == _endpoint &&
          sessionId == _sessionId) {
        unawaited(_pumpMotion());
      }
    }
  }

  Future<void> _sendStop(RobotEndpoint endpoint, String sessionId) async {
    if (_vectorRequestInFlight ||
        !_stopRequested ||
        _remainingStopConfirmations <= 0) {
      return;
    }
    _vectorRequestInFlight = true;
    _remainingStopConfirmations -= 1;
    try {
      final status = await _repository.stop(endpoint, sessionId);
      if (endpoint != _endpoint || sessionId != _sessionId) return;
      _clearControlDeadline();
      _setStatus(
        status,
        link: state.link.isLocked
            ? ManualControlLink.locked
            : ManualControlLink.healthy,
      );
    } on ApiException catch (error) {
      if (endpoint != _endpoint || sessionId != _sessionId) return;
      state = state.copyWith(message: error.message, isError: true);
    } finally {
      _vectorRequestInFlight = false;
      if (endpoint == _endpoint && sessionId == _sessionId) {
        if (_stopRequested && _remainingStopConfirmations > 0) {
          _scheduleStopConfirmation();
        } else {
          _stopRequested = false;
          if (_desiredVector != null) unawaited(_pumpMotion());
        }
      }
    }
  }

  void _scheduleStopConfirmation() {
    _stopConfirmationTimer?.cancel();
    final sentCount =
        _stopConfirmationDelays.length - _remainingStopConfirmations;
    final delay = _stopConfirmationDelays[sentCount];
    _stopConfirmationTimer = Timer(delay, () {
      _stopConfirmationTimer = null;
      unawaited(_pumpMotion());
    });
  }

  void _cancelPendingStopConfirmations() {
    _stopConfirmationTimer?.cancel();
    _stopConfirmationTimer = null;
    _remainingStopConfirmations = 0;
  }

  void _startInputTimer() {
    if (_inputTimer != null) return;
    final inputTimeout = state.status?.safety.inputTimeout;
    if (inputTimeout == null) {
      _lockControlLink('车端未提供输入看门狗参数，方向控制已安全锁定。');
      return;
    }
    // Keep enough headroom for one full request/response cycle before the
    // backend watchdog expires. This is a cadence cap, not a queue: an
    // outstanding request still prevents another one from starting.
    final intervalMs = (inputTimeout.inMilliseconds / 4)
        .round()
        .clamp(50, _maximumInputInterval.inMilliseconds)
        .toInt();
    _inputTimer = Timer.periodic(Duration(milliseconds: intervalMs), (_) {
      unawaited(_pumpMotion());
    });
  }

  void _startControlDeadline() {
    _clearControlDeadline();
    final inputTimeout = state.status?.safety.inputTimeout;
    if (inputTimeout == null) {
      _lockControlLink('车端未提供输入看门狗参数，方向控制已安全锁定。');
      return;
    }
    final totalUs = inputTimeout.inMicroseconds;
    final warning = Duration(microseconds: (totalUs * .6).round());
    _controlWarningTimer = Timer(warning, () {
      if (_vectorRequestInFlight && !state.link.isLocked) {
        state = state.copyWith(
          link: ManualControlLink.delayed,
          message: '控制链路延迟偏高，正在等待车端响应。',
          isError: false,
        );
      }
    });
  }

  void _clearControlDeadline() {
    _controlWarningTimer?.cancel();
    _controlWarningTimer = null;
  }

  void _lockControlLink(String message) {
    _clearControlDeadline();
    _desiredVector = null;
    _stopRequested = true;
    _remainingStopConfirmations = _stopConfirmationDelays.length;
    _stopConfirmationTimer?.cancel();
    _stopConfirmationTimer = null;
    _inputTimer?.cancel();
    _inputTimer = null;
    state = state.copyWith(
      link: ManualControlLink.locked,
      message: message,
      isError: true,
    );
    unawaited(_pumpMotion());
  }

  Future<void> _perform({
    required String pendingMessage,
    required Future<VehicleControlState> Function() action,
    required void Function(VehicleControlState status) onSuccess,
  }) async {
    final endpoint = _endpoint;
    if (endpoint == null || state.isActionPending) return;
    final requestEpoch = ++_requestEpoch;
    state = state.copyWith(
      isActionPending: true,
      message: pendingMessage,
      isError: false,
    );
    try {
      final status = await action();
      if (endpoint != _endpoint || requestEpoch != _requestEpoch) return;
      onSuccess(status);
    } on ApiException catch (error) {
      if (endpoint != _endpoint || requestEpoch != _requestEpoch) return;
      state = state.copyWith(
        isActionPending: false,
        message: error.message,
        isError: true,
      );
    }
  }

  Future<void> _load(RobotEndpoint endpoint, {bool showBusy = false}) async {
    if (state.isActionPending || _statusRequestInFlight) return;
    _statusRequestInFlight = true;
    final requestEpoch = ++_requestEpoch;
    if (showBusy) {
      state = state.copyWith(isRefreshing: true, message: '', isError: false);
    }
    try {
      final status = await _repository.status(endpoint);
      if (endpoint != _endpoint || requestEpoch != _requestEpoch) return;
      _setStatus(status);
    } on ApiException catch (error) {
      if (endpoint != _endpoint || requestEpoch != _requestEpoch) return;
      state = state.copyWith(
        isRefreshing: false,
        message: '无法更新手动控制状态：${error.message}',
        isError: true,
      );
    } finally {
      if (endpoint == _endpoint) _statusRequestInFlight = false;
    }
  }

  void _setStatus(
    VehicleControlState status, {
    ManualControlLink? link,
    Duration? lastControlRoundTrip,
  }) {
    final hadActiveSession = _sessionId != null;
    final sessionStillPresent = _sessionId != null && status.session.present;
    if (!sessionStillPresent) {
      _sessionId = null;
      _desiredVector = null;
      _stopRequested = false;
      _cancelPendingStopConfirmations();
      _cancelSessionTimers();
      if (hadActiveSession) _restartStatusPolling();
    }
    state = ManualControlScreenState(
      status: status,
      hasActiveSession: sessionStillPresent,
      link: sessionStillPresent ? (link ?? state.link) : ManualControlLink.idle,
      lastControlRoundTrip: lastControlRoundTrip ?? state.lastControlRoundTrip,
      message: status.transitionError,
      isError: status.transitionError.isNotEmpty,
    );
  }

  void _startSessionTimers() {
    _heartbeatTimer ??= Timer.periodic(_heartbeatInterval, (_) {
      final endpoint = _endpoint;
      final sessionId = _sessionId;
      if (endpoint != null &&
          sessionId != null &&
          _desiredVector == null &&
          !_vectorRequestInFlight &&
          !_stopRequested &&
          !_heartbeatRequestInFlight) {
        unawaited(_heartbeat(endpoint, sessionId));
      }
    });
  }

  void _startStatusPolling() {
    if (_statusPollingPaused || _endpoint == null || _statusTimer != null) {
      return;
    }
    final interval = _sessionId == null
        ? _idleStatusInterval
        : _activeStatusInterval;
    _statusTimer = Timer.periodic(interval, (_) {
      final endpoint = _endpoint;
      // Vector responses already contain an authoritative state snapshot while
      // the joystick is held. A competing GET could otherwise arrive later
      // and incorrectly lock the direct-manipulation surface mid-gesture.
      if (endpoint == null ||
          _desiredVector != null ||
          _vectorRequestInFlight ||
          _stopRequested ||
          state.isActionPending) {
        return;
      }
      unawaited(_load(endpoint));
    });
  }

  void _restartStatusPolling() {
    _stopStatusPolling();
    _startStatusPolling();
  }

  void _stopStatusPolling() {
    _statusTimer?.cancel();
    _statusTimer = null;
  }

  Future<void> _heartbeat(RobotEndpoint endpoint, String sessionId) async {
    if (_heartbeatRequestInFlight ||
        _desiredVector != null ||
        _vectorRequestInFlight ||
        _stopRequested) {
      return;
    }
    _heartbeatRequestInFlight = true;
    try {
      final status = await _repository.heartbeat(endpoint, sessionId);
      if (endpoint == _endpoint && sessionId == _sessionId) _setStatus(status);
    } on ApiException catch (_) {
      if (endpoint == _endpoint && sessionId == _sessionId) {
        _cancelSessionTimers();
        _sessionId = null;
        _desiredVector = null;
        _stopRequested = false;
        _cancelPendingStopConfirmations();
        _restartStatusPolling();
        unawaited(_release(endpoint, sessionId));
      }
    } finally {
      if (endpoint == _endpoint) _heartbeatRequestInFlight = false;
    }
  }

  Future<void> _release(
    RobotEndpoint endpoint,
    String sessionId, {
    bool reportError = false,
    bool updateState = true,
  }) async {
    VehicleControlState? latest;
    try {
      latest = await _repository.release(endpoint, sessionId);
    } on ApiException catch (error) {
      if (reportError && endpoint == _endpoint) {
        state = state.copyWith(message: error.message, isError: true);
      }
    }
    if (updateState &&
        endpoint == _endpoint &&
        _sessionId == null &&
        latest != null) {
      state = ManualControlScreenState(status: latest);
    }
  }

  Future<void> _exitToNavigation(
    RobotEndpoint endpoint,
    String sessionId, {
    bool reportError = false,
  }) async {
    VehicleControlState? latest;
    try {
      latest = await _repository.exit(endpoint, sessionId);
    } on ApiException catch (error) {
      if (reportError && endpoint == _endpoint) {
        state = state.copyWith(message: error.message, isError: true);
      }
    }
    if (endpoint == _endpoint && _sessionId == null && latest != null) {
      state = ManualControlScreenState(status: latest);
    }
  }

  Future<void> _releaseActiveSession() async {
    final endpoint = _endpoint;
    final sessionId = _sessionId;
    _cancelTimers();
    _sessionId = null;
    _desiredVector = null;
    _stopRequested = false;
    _cancelPendingStopConfirmations();
    if (endpoint != null && sessionId != null) {
      await _release(endpoint, sessionId, updateState: false);
    }
  }

  void _cancelTimers() {
    _cancelSessionTimers();
    _stopStatusPolling();
  }

  void _cancelSessionTimers() {
    _heartbeatTimer?.cancel();
    _heartbeatTimer = null;
    _inputTimer?.cancel();
    _inputTimer = null;
    _cancelPendingStopConfirmations();
    _clearControlDeadline();
  }
}
