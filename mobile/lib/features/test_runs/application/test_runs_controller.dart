import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/connection/robot_connection_controller.dart';
import '../../../core/connection/robot_endpoint.dart';
import '../../../core/network/api_exception.dart';
import '../data/test_runs_repository.dart';
import '../domain/aletheia_run.dart';

final testRunsRepositoryProvider = Provider<TestRunsRepository>((ref) {
  return TestRunsRepository(ref.watch(aletheiaApiClientProvider));
});

final testRunsControllerProvider =
    NotifierProvider<TestRunsController, TestRunsScreenState>(
      TestRunsController.new,
    );

class TestRunsScreenState {
  const TestRunsScreenState({
    this.run,
    this.isRefreshing = false,
    this.isActionPending = false,
    this.message = '',
    this.isError = false,
  });

  final AletheiaRun? run;
  final bool isRefreshing;
  final bool isActionPending;
  final String message;
  final bool isError;

  bool get isBusy => isRefreshing || isActionPending;

  TestRunsScreenState copyWith({
    AletheiaRun? run,
    bool? isRefreshing,
    bool? isActionPending,
    String? message,
    bool? isError,
  }) {
    return TestRunsScreenState(
      run: run ?? this.run,
      isRefreshing: isRefreshing ?? this.isRefreshing,
      isActionPending: isActionPending ?? this.isActionPending,
      message: message ?? this.message,
      isError: isError ?? this.isError,
    );
  }
}

class TestRunsController extends Notifier<TestRunsScreenState> {
  Timer? _pollTimer;
  RobotEndpoint? _endpoint;
  int _requestEpoch = 0;

  @override
  TestRunsScreenState build() {
    ref.onDispose(() => _pollTimer?.cancel());
    final endpoint = ref.watch(
      robotConnectionControllerProvider.select(
        (connection) => connection.isConnected ? connection.endpoint : null,
      ),
    );
    _endpoint = endpoint;
    if (endpoint != null) {
      // State becomes writable only after build returns. Defer the first
      // status request so a responsive robot console cannot race Notifier
      // initialization when the testing workspace opens.
      Future.microtask(() => _load(endpoint));
    } else {
      _pausePolling();
    }
    return const TestRunsScreenState();
  }

  Future<void> refresh() async {
    final endpoint = _endpoint;
    if (endpoint == null) {
      state = const TestRunsScreenState(message: '请先连接机器人。', isError: true);
      return;
    }
    await _load(endpoint, showBusy: true);
  }

  Future<void> create(TestRunRequest request) => _perform(
    pendingMessage: '正在创建测试计划…',
    action: (endpoint) =>
        ref.read(testRunsRepositoryProvider).create(endpoint, request),
  );

  Future<void> cancel() {
    final run = state.run;
    if (run == null) {
      return Future.value();
    }
    return _perform(
      pendingMessage: '正在请求终止剩余轮次…',
      action: (endpoint) =>
          ref.read(testRunsRepositoryProvider).cancel(endpoint, run.id),
    );
  }

  Future<void> resume() {
    final run = state.run;
    if (run == null) {
      return Future.value();
    }
    return _perform(
      pendingMessage: '正在提交人工恢复确认…',
      action: (endpoint) =>
          ref.read(testRunsRepositoryProvider).resume(endpoint, run.id),
    );
  }

  Future<void> stallAction(String action) {
    final run = state.run;
    if (run == null) return Future.value();
    return _perform(
      pendingMessage: '正在记录人工处置…',
      action: (endpoint) => ref
          .read(testRunsRepositoryProvider)
          .stallAction(endpoint, run.id, action),
    );
  }

  void pausePolling() => _pausePolling();

  void resumePolling() {
    final run = state.run;
    if (run?.status.isActive == true) {
      _schedulePolling(run!);
    } else {
      unawaited(refresh());
    }
  }

  Future<void> _perform({
    required String pendingMessage,
    required Future<AletheiaRun> Function(RobotEndpoint endpoint) action,
  }) async {
    final endpoint = _endpoint;
    if (endpoint == null || state.isBusy) {
      return;
    }
    final requestEpoch = ++_requestEpoch;
    state = state.copyWith(
      isActionPending: true,
      message: pendingMessage,
      isError: false,
    );
    try {
      final run = await action(endpoint);
      if (_endpoint != endpoint || requestEpoch != _requestEpoch) {
        return;
      }
      state = TestRunsScreenState(run: run);
      _schedulePolling(run);
    } on ApiException catch (error) {
      if (_endpoint != endpoint || requestEpoch != _requestEpoch) {
        return;
      }
      state = state.copyWith(
        isActionPending: false,
        message: error.message,
        isError: true,
      );
    }
  }

  Future<void> _load(RobotEndpoint endpoint, {bool showBusy = false}) async {
    if (state.isActionPending) {
      return;
    }
    final requestEpoch = ++_requestEpoch;
    if (showBusy) {
      state = state.copyWith(isRefreshing: true, message: '', isError: false);
    }
    try {
      final run = await ref.read(testRunsRepositoryProvider).latest(endpoint);
      if (_endpoint != endpoint || requestEpoch != _requestEpoch) {
        return;
      }
      state = TestRunsScreenState(run: run);
      _schedulePolling(run);
    } on ApiException catch (error) {
      if (_endpoint != endpoint || requestEpoch != _requestEpoch) {
        return;
      }
      state = state.copyWith(
        isRefreshing: false,
        message: '无法更新运行状态：${error.message}',
        isError: true,
      );
      if (state.run?.status.isActive == true) {
        _schedulePolling(state.run);
      }
    }
  }

  void _schedulePolling(AletheiaRun? run) {
    _pollTimer?.cancel();
    if (run?.status.isActive != true || _endpoint == null) {
      _pollTimer = null;
      return;
    }
    _pollTimer = Timer(const Duration(seconds: 1), () {
      final endpoint = _endpoint;
      if (endpoint != null) {
        unawaited(_load(endpoint));
      }
    });
  }

  void _pausePolling() {
    _pollTimer?.cancel();
    _pollTimer = null;
  }
}
