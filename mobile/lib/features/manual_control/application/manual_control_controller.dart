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

class ManualControlScreenState {
  const ManualControlScreenState({
    this.status,
    this.isRefreshing = false,
    this.isActionPending = false,
    this.message = '',
    this.isError = false,
    this.hasActiveSession = false,
  });

  final VehicleControlState? status;
  final bool isRefreshing;
  final bool isActionPending;
  final String message;
  final bool isError;
  final bool hasActiveSession;

  bool get canSendMotion =>
      hasActiveSession && (status?.motionPermittedByBackend ?? false);

  bool get isBusy => isRefreshing || isActionPending;

  ManualControlScreenState copyWith({
    VehicleControlState? status,
    bool? isRefreshing,
    bool? isActionPending,
    String? message,
    bool? isError,
    bool? hasActiveSession,
  }) => ManualControlScreenState(
    status: status ?? this.status,
    isRefreshing: isRefreshing ?? this.isRefreshing,
    isActionPending: isActionPending ?? this.isActionPending,
    message: message ?? this.message,
    isError: isError ?? this.isError,
    hasActiveSession: hasActiveSession ?? this.hasActiveSession,
  );
}

class ManualControlController extends Notifier<ManualControlScreenState> {
  static const _heartbeatInterval = Duration(milliseconds: 500);
  static const _inputInterval = Duration(milliseconds: 200);
  static const _statusInterval = Duration(milliseconds: 500);

  Timer? _heartbeatTimer;
  Timer? _inputTimer;
  Timer? _statusTimer;
  late ManualControlRepository _repository;
  RobotEndpoint? _endpoint;
  String? _sessionId;
  VehicleControlVector? _heldVector;
  int _requestEpoch = 0;

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
      _heldVector = null;
      if (oldEndpoint != null && oldSessionId != null) {
        unawaited(_release(oldEndpoint, oldSessionId));
      }
      if (endpoint != null) {
        Future.microtask(() => _load(endpoint));
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
          message: status.motionPermittedByBackend
              ? '手动控制已就绪。'
              : '正在等待车端确认控制源…',
        );
        _startSessionTimers();
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
    _heldVector = vector;
    await _sendHeldVector(endpoint, sessionId, vector);
    if (_heldVector == vector && state.canSendMotion) {
      _inputTimer ??= Timer.periodic(_inputInterval, (_) {
        final activeEndpoint = _endpoint;
        final activeSession = _sessionId;
        final held = _heldVector;
        if (activeEndpoint != null && activeSession != null && held != null) {
          unawaited(_sendHeldVector(activeEndpoint, activeSession, held));
        }
      });
    }
  }

  Future<void> stop() async {
    _heldVector = null;
    _inputTimer?.cancel();
    _inputTimer = null;
    final endpoint = _endpoint;
    final sessionId = _sessionId;
    if (endpoint == null || sessionId == null) return;
    await _perform(
      pendingMessage: '正在停止车辆…',
      action: () => _repository.stop(endpoint, sessionId),
      onSuccess: _setStatus,
    );
  }

  Future<void> exit() async {
    final endpoint = _endpoint;
    final sessionId = _sessionId;
    if (endpoint == null || sessionId == null) return;
    _cancelTimers();
    _heldVector = null;
    _sessionId = null;
    await _release(endpoint, sessionId, reportError: true);
  }

  Future<void> setSpeed({
    required double linearMps,
    required double angularRadps,
  }) async {
    final endpoint = _endpoint;
    final sessionId = _sessionId;
    if (endpoint == null || sessionId == null || !state.canSendMotion) return;
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

  Future<void> pauseForLifecycle() => exit();

  void resumeAfterLifecycle() {
    final endpoint = _endpoint;
    if (endpoint != null) unawaited(_load(endpoint));
  }

  Future<void> _sendHeldVector(
    RobotEndpoint endpoint,
    String sessionId,
    VehicleControlVector vector,
  ) async {
    if (endpoint != _endpoint ||
        sessionId != _sessionId ||
        !state.canSendMotion) {
      return;
    }
    try {
      final status = await _repository.vector(endpoint, sessionId, vector);
      if (endpoint != _endpoint || sessionId != _sessionId) return;
      _setStatus(status);
    } on ApiException catch (error) {
      if (endpoint != _endpoint || sessionId != _sessionId) return;
      _heldVector = null;
      _inputTimer?.cancel();
      _inputTimer = null;
      state = state.copyWith(message: error.message, isError: true);
      unawaited(stop());
    }
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
    if (state.isActionPending) return;
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
    }
  }

  void _setStatus(VehicleControlState status) {
    final sessionStillPresent = _sessionId != null && status.session.present;
    if (!sessionStillPresent) {
      _sessionId = null;
      _heldVector = null;
      _cancelTimers();
    }
    state = ManualControlScreenState(
      status: status,
      hasActiveSession: sessionStillPresent,
      message: status.transitionError,
      isError: status.transitionError.isNotEmpty,
    );
  }

  void _startSessionTimers() {
    _heartbeatTimer ??= Timer.periodic(_heartbeatInterval, (_) {
      final endpoint = _endpoint;
      final sessionId = _sessionId;
      if (endpoint != null && sessionId != null) {
        unawaited(_heartbeat(endpoint, sessionId));
      }
    });
    _statusTimer ??= Timer.periodic(_statusInterval, (_) {
      final endpoint = _endpoint;
      if (endpoint != null) unawaited(_load(endpoint));
    });
  }

  Future<void> _heartbeat(RobotEndpoint endpoint, String sessionId) async {
    try {
      final status = await _repository.heartbeat(endpoint, sessionId);
      if (endpoint == _endpoint && sessionId == _sessionId) _setStatus(status);
    } on ApiException catch (_) {
      if (endpoint == _endpoint && sessionId == _sessionId) {
        unawaited(exit());
      }
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
      latest = await _repository.stop(endpoint, sessionId);
    } on ApiException catch (error) {
      if (reportError && endpoint == _endpoint) {
        state = state.copyWith(message: error.message, isError: true);
      }
    }
    try {
      latest = await _repository.exit(endpoint, sessionId);
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

  Future<void> _releaseActiveSession() async {
    final endpoint = _endpoint;
    final sessionId = _sessionId;
    _cancelTimers();
    _sessionId = null;
    _heldVector = null;
    if (endpoint != null && sessionId != null) {
      await _release(endpoint, sessionId, updateState: false);
    }
  }

  void _cancelTimers() {
    _heartbeatTimer?.cancel();
    _heartbeatTimer = null;
    _inputTimer?.cancel();
    _inputTimer = null;
    _statusTimer?.cancel();
    _statusTimer = null;
  }
}
