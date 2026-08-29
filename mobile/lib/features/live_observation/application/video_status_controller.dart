import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/connection/robot_connection_controller.dart';
import '../../../core/connection/robot_endpoint.dart';
import '../../../core/network/api_exception.dart';
import '../data/video_repository.dart';
import '../domain/video_status.dart';

final videoRepositoryProvider = Provider<VideoRepository>(
  (ref) => VideoRepository(ref.watch(aletheiaApiClientProvider)),
);

final videoStatusControllerProvider =
    NotifierProvider.autoDispose<VideoStatusController, VideoStatusState>(
      VideoStatusController.new,
    );

enum VideoStatusPhase { loading, ready, unavailable, failure }

class VideoStatusState {
  const VideoStatusState({
    this.phase = VideoStatusPhase.loading,
    this.status,
    this.message = '',
    this.isChangingStream = false,
    this.selectedStreamName,
  });

  final VideoStatusPhase phase;
  final VideoStatus? status;
  final String message;
  final bool isChangingStream;
  final String? selectedStreamName;

  VideoStream? get selectedStream =>
      status?.streamNamed(selectedStreamName) ?? status?.primaryStream;

  VideoStatusState copyWith({
    VideoStatusPhase? phase,
    VideoStatus? status,
    String? message,
    bool? isChangingStream,
    String? selectedStreamName,
  }) => VideoStatusState(
    phase: phase ?? this.phase,
    status: status ?? this.status,
    message: message ?? this.message,
    isChangingStream: isChangingStream ?? this.isChangingStream,
    selectedStreamName: selectedStreamName ?? this.selectedStreamName,
  );
}

class VideoStatusController extends Notifier<VideoStatusState> {
  static const _pollInterval = Duration(seconds: 3);

  Timer? _pollTimer;
  RobotEndpoint? _endpoint;
  VideoStatusState _current = const VideoStatusState();
  int _requestEpoch = 0;

  @override
  VideoStatusState build() {
    ref.onDispose(() => _pollTimer?.cancel());
    final endpoint = ref.watch(
      robotConnectionControllerProvider.select(
        (connection) => connection.isConnected ? connection.endpoint : null,
      ),
    );
    if (endpoint != _endpoint) {
      _endpoint = endpoint;
      _pollTimer?.cancel();
      _pollTimer = null;
      _current = endpoint == null
          ? const VideoStatusState(
              phase: VideoStatusPhase.unavailable,
              message: '请先连接机器人后再查看相机。',
            )
          : const VideoStatusState();
      if (endpoint != null) {
        // A Notifier's state is not writable until build returns. Defer the
        // initial request so first-opening the camera cannot race provider
        // initialization on a fast local response.
        Future.microtask(() => _load(endpoint));
      }
    }
    return _current;
  }

  void activate() {
    final endpoint = _endpoint;
    if (endpoint == null) {
      return;
    }
    _schedulePolling(endpoint);
    unawaited(_load(endpoint));
  }

  void pause() {
    _pollTimer?.cancel();
    _pollTimer = null;
  }

  Future<void> refresh() async {
    final endpoint = _endpoint;
    if (endpoint != null) {
      await _load(endpoint, showLoading: true);
    }
  }

  Future<void> setPrimaryStreamEnabled(bool enabled) async {
    await setSelectedStreamEnabled(enabled);
  }

  void selectStream(String streamName) {
    if (state.status?.streamNamed(streamName) == null) {
      return;
    }
    _setState(state.copyWith(selectedStreamName: streamName, message: ''));
  }

  Future<void> setSelectedStreamEnabled(bool enabled) async {
    final stream = state.selectedStream;
    if (stream == null) {
      return;
    }
    await setStreamEnabled(stream.name, enabled);
  }

  /// Changes a configured stream without changing the selected decoder.
  /// This keeps the operator's active WHEP surface stable while allowing the
  /// HMI control rail to prepare or stop another source on the robot.
  Future<void> setStreamEnabled(String streamName, bool enabled) async {
    final endpoint = _endpoint;
    final stream = state.status?.streamNamed(streamName);
    if (endpoint == null || stream == null || state.isChangingStream) {
      return;
    }
    final requestEpoch = ++_requestEpoch;
    _setState(
      state.copyWith(
        isChangingStream: true,
        message: enabled ? '正在启动 ${stream.name}…' : '正在停止 ${stream.name}…',
      ),
    );
    try {
      final status = await ref
          .read(videoRepositoryProvider)
          .setStreamEnabled(endpoint, stream.name, enabled);
      if (!_isCurrent(endpoint, requestEpoch)) {
        return;
      }
      _setState(
        _readyState(
          status,
          preferredStreamName: state.selectedStreamName ?? stream.name,
        ),
      );
    } on ApiException catch (error) {
      if (_isCurrent(endpoint, requestEpoch)) {
        _setState(
          state.copyWith(
            isChangingStream: false,
            message: '无法切换视频流：${error.message}',
          ),
        );
      }
    } on FormatException catch (error) {
      if (_isCurrent(endpoint, requestEpoch)) {
        _setState(
          state.copyWith(isChangingStream: false, message: error.message),
        );
      }
    }
  }

  Future<void> _load(RobotEndpoint endpoint, {bool showLoading = false}) async {
    if (state.isChangingStream) {
      return;
    }
    final requestEpoch = ++_requestEpoch;
    if (showLoading || state.status == null) {
      _setState(state.copyWith(message: '正在读取视频状态…'));
    }
    try {
      final status = await ref.read(videoRepositoryProvider).status(endpoint);
      if (!_isCurrent(endpoint, requestEpoch)) {
        return;
      }
      _setState(_readyState(status));
    } on ApiException catch (error) {
      if (_isCurrent(endpoint, requestEpoch)) {
        _setState(
          VideoStatusState(
            phase: VideoStatusPhase.failure,
            status: state.status,
            message: '无法读取视频状态：${error.message}',
          ),
        );
      }
    } on FormatException catch (error) {
      if (_isCurrent(endpoint, requestEpoch)) {
        _setState(
          VideoStatusState(
            phase: VideoStatusPhase.failure,
            status: state.status,
            message: error.message,
          ),
        );
      }
    }
  }

  void _schedulePolling(RobotEndpoint endpoint) {
    _pollTimer?.cancel();
    _pollTimer = Timer.periodic(_pollInterval, (_) {
      if (_endpoint == endpoint) {
        unawaited(_load(endpoint));
      }
    });
  }

  bool _isCurrent(RobotEndpoint endpoint, int requestEpoch) =>
      _endpoint == endpoint && _requestEpoch == requestEpoch;

  VideoStatusState _readyState(
    VideoStatus status, {
    String? preferredStreamName,
  }) {
    final selected =
        status.streamNamed(preferredStreamName ?? state.selectedStreamName) ??
        status.primaryStream;
    return VideoStatusState(
      phase: VideoStatusPhase.ready,
      status: status,
      selectedStreamName: selected?.name,
    );
  }

  void _setState(VideoStatusState value) {
    _current = value;
    state = value;
  }
}
