import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/connection/robot_connection_controller.dart';
import '../../../core/connection/robot_endpoint.dart';
import '../../../core/network/api_exception.dart';
import '../data/live_observation_repository.dart';
import '../domain/live_map.dart';

final liveObservationRepositoryProvider = Provider<LiveObservationRepository>(
  (ref) => LiveObservationRepository(ref.watch(aletheiaApiClientProvider)),
);

final liveObservationControllerProvider =
    NotifierProvider<LiveObservationController, LiveObservationState>(
      LiveObservationController.new,
    );

enum LiveObservationPhase { loading, ready, unavailable, failure }

class LiveObservationState {
  const LiveObservationState({
    this.phase = LiveObservationPhase.loading,
    this.map,
    this.message = '正在准备实时观测…',
    this.isRefreshing = false,
  });

  final LiveObservationPhase phase;
  final LiveMapAsset? map;
  final String message;
  final bool isRefreshing;

  LiveObservationState copyWith({
    LiveObservationPhase? phase,
    LiveMapAsset? map,
    String? message,
    bool? isRefreshing,
  }) => LiveObservationState(
    phase: phase ?? this.phase,
    map: map ?? this.map,
    message: message ?? this.message,
    isRefreshing: isRefreshing ?? this.isRefreshing,
  );
}

class LiveObservationController extends Notifier<LiveObservationState> {
  Timer? _mapTimer;
  RobotEndpoint? _endpoint;
  int _requestEpoch = 0;

  @override
  LiveObservationState build() {
    ref.onDispose(() => _mapTimer?.cancel());
    final endpoint = ref.watch(
      robotConnectionControllerProvider.select(
        (connection) => connection.isConnected ? connection.endpoint : null,
      ),
    );
    if (endpoint != _endpoint) {
      _endpoint = endpoint;
      _mapTimer?.cancel();
      if (endpoint != null) {
        // Avoid assigning state while this Notifier is still building. A
        // local robot can answer fast enough for that race to be observable.
        Future.microtask(() => _prepare(endpoint));
      }
    }
    return endpoint == null
        ? const LiveObservationState(
            phase: LiveObservationPhase.unavailable,
            message: '请先连接机器人后再打开实时观测。',
          )
        : const LiveObservationState();
  }

  Future<void> refresh() async {
    final endpoint = _endpoint;
    if (endpoint == null) {
      return;
    }
    await _prepare(endpoint, showRefreshing: true);
  }

  void activate() {
    final endpoint = _endpoint;
    if (endpoint != null) {
      unawaited(_prepare(endpoint));
    }
  }

  void pauseMapPolling() {
    _mapTimer?.cancel();
    _mapTimer = null;
  }

  void resumeMapPolling() {
    final endpoint = _endpoint;
    if (endpoint == null) {
      return;
    }
    _scheduleMapPolling(endpoint);
    unawaited(_syncActiveMap(endpoint));
  }

  Future<void> _prepare(
    RobotEndpoint endpoint, {
    bool showRefreshing = false,
  }) async {
    final requestEpoch = ++_requestEpoch;
    if (showRefreshing) {
      state = state.copyWith(isRefreshing: true, message: '正在刷新地图…');
    } else {
      state = const LiveObservationState();
    }

    final connection = ref.read(robotConnectionControllerProvider);
    if (connection.observation?.enabledInConfiguration != true) {
      if (_isCurrent(endpoint, requestEpoch)) {
        state = const LiveObservationState(
          phase: LiveObservationPhase.unavailable,
          message: '实时观测尚未启用。请先在机器人管理端开启后再试。',
        );
      }
      return;
    }

    if (connection.observation?.telemetryOnline != true) {
      await ref
          .read(robotConnectionControllerProvider.notifier)
          .startObservation();
    }
    final ready = ref.read(robotConnectionControllerProvider);
    final observation = ready.observation;
    if (!_isCurrent(endpoint, requestEpoch)) {
      return;
    }
    if (observation?.telemetryOnline != true ||
        observation?.telemetryWebSocketPort == null) {
      state = LiveObservationState(
        phase: LiveObservationPhase.unavailable,
        message: ready.message.isNotEmpty
            ? ready.message
            : '实时数据尚未准备好，请稍后重试或查看诊断日志。',
      );
      return;
    }

    await _loadMap(
      endpoint,
      requestEpoch,
      activeMapId: observation!.activeMapId,
      keepExistingMap: showRefreshing,
    );
    if (_isCurrent(endpoint, requestEpoch)) {
      _scheduleMapPolling(endpoint);
    }
  }

  Future<void> _syncActiveMap(RobotEndpoint endpoint) async {
    final requestEpoch = _requestEpoch;
    try {
      final mapId = await ref
          .read(aletheiaApiClientProvider)
          .activeObservationMapId(endpoint);
      if (!_isCurrent(endpoint, requestEpoch)) {
        return;
      }
      if (mapId != state.map?.id) {
        await _loadMap(
          endpoint,
          requestEpoch,
          activeMapId: mapId,
          keepExistingMap: true,
        );
      }
    } on ApiException catch (error) {
      if (_isCurrent(endpoint, requestEpoch) && state.map == null) {
        state = LiveObservationState(
          phase: LiveObservationPhase.failure,
          message: '无法更新地图：${error.message}',
        );
      }
    } on FormatException catch (error) {
      if (_isCurrent(endpoint, requestEpoch) && state.map == null) {
        state = LiveObservationState(
          phase: LiveObservationPhase.failure,
          message: error.message,
        );
      }
    }
  }

  Future<void> _loadMap(
    RobotEndpoint endpoint,
    int requestEpoch, {
    required String? activeMapId,
    required bool keepExistingMap,
  }) async {
    try {
      final map = await ref
          .read(liveObservationRepositoryProvider)
          .loadActiveMap(endpoint, activeMapId: activeMapId);
      if (!_isCurrent(endpoint, requestEpoch)) {
        return;
      }
      state = LiveObservationState(
        phase: LiveObservationPhase.ready,
        map: map,
        message: map == null ? '暂未找到活动地图，实时位置仍会继续更新。' : '',
      );
    } on ApiException catch (error) {
      if (_isCurrent(endpoint, requestEpoch)) {
        state = LiveObservationState(
          phase: keepExistingMap && state.map != null
              ? LiveObservationPhase.ready
              : LiveObservationPhase.failure,
          map: keepExistingMap ? state.map : null,
          message: '无法读取地图：${error.message}',
        );
      }
    } on FormatException catch (error) {
      if (_isCurrent(endpoint, requestEpoch)) {
        state = LiveObservationState(
          phase: keepExistingMap && state.map != null
              ? LiveObservationPhase.ready
              : LiveObservationPhase.failure,
          map: keepExistingMap ? state.map : null,
          message: error.message,
        );
      }
    }
  }

  void _scheduleMapPolling(RobotEndpoint endpoint) {
    _mapTimer?.cancel();
    _mapTimer = Timer.periodic(const Duration(seconds: 5), (_) {
      if (_endpoint == endpoint) {
        unawaited(_syncActiveMap(endpoint));
      }
    });
  }

  bool _isCurrent(RobotEndpoint endpoint, int requestEpoch) =>
      _endpoint == endpoint && _requestEpoch == requestEpoch;
}
