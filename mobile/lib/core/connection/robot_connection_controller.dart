import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/http.dart' as http;

import '../network/aletheia_api_client.dart';
import '../network/api_exception.dart';
import '../storage/endpoint_store.dart';
import 'robot_connection_state.dart';
import 'robot_endpoint.dart';

final _httpClientProvider = Provider<http.Client>((ref) {
  final client = http.Client();
  ref.onDispose(client.close);
  return client;
});

final aletheiaApiClientProvider = Provider<AletheiaApiClient>((ref) {
  return AletheiaApiClient(ref.watch(_httpClientProvider));
});

final _endpointStoreProvider = Provider<EndpointStore>((ref) {
  return EndpointStore();
});

final robotConnectionControllerProvider =
    NotifierProvider<RobotConnectionController, RobotConnectionState>(
      RobotConnectionController.new,
    );

class RobotConnectionController extends Notifier<RobotConnectionState> {
  Timer? _heartbeatTimer;
  int _operation = 0;

  @override
  RobotConnectionState build() {
    ref.onDispose(() => _heartbeatTimer?.cancel());
    unawaited(_restoreEndpoint());
    return const RobotConnectionState();
  }

  Future<void> connect(String rawAddress) async {
    final operation = ++_operation;
    RobotEndpoint endpoint;
    try {
      endpoint = RobotEndpoint.parse(rawAddress);
    } on FormatException catch (error) {
      state = state.copyWith(
        phase: ConnectionPhase.failure,
        message: error.message,
      );
      return;
    }

    _pauseHeartbeat();
    state = RobotConnectionState(
      phase: ConnectionPhase.checking,
      endpoint: endpoint,
      addressDraft: endpoint.displayAddress,
      message: '正在检查 ${endpoint.displayAddress}…',
    );
    try {
      await ref.read(_endpointStoreProvider).write(endpoint);
      final observation = await ref
          .read(aletheiaApiClientProvider)
          .observation(endpoint);
      if (operation != _operation) {
        return;
      }
      state = RobotConnectionState(
        phase: ConnectionPhase.connected,
        endpoint: endpoint,
        observation: observation,
        lastChecked: DateTime.now(),
        addressDraft: endpoint.displayAddress,
      );
      if (observation.telemetryOnline) {
        _startHeartbeat();
      }
    } on ApiException catch (error) {
      if (operation != _operation) {
        return;
      }
      state = RobotConnectionState(
        phase: ConnectionPhase.failure,
        endpoint: endpoint,
        addressDraft: endpoint.displayAddress,
        message: error.message,
      );
    }
  }

  Future<void> refresh() async {
    final endpoint = state.endpoint;
    if (endpoint == null || state.isBusy) {
      return;
    }
    await connect(endpoint.toString());
  }

  /// Retains the current local text-field value while the operator moves
  /// between top-level HMI sections. It is intentionally not persisted until
  /// a connect attempt validates it as a robot endpoint.
  void updateAddressDraft(String value) {
    if (value == state.addressDraft) return;
    state = state.copyWith(addressDraft: value);
  }

  Future<void> startObservation() async {
    final endpoint = state.endpoint;
    if (endpoint == null || state.isBusy) {
      return;
    }
    state = state.copyWith(isStartingObservation: true, message: '正在启动实时观测…');
    try {
      final observation = await ref
          .read(aletheiaApiClientProvider)
          .startObservation(endpoint);
      state = state.copyWith(
        phase: ConnectionPhase.connected,
        observation: observation,
        lastChecked: DateTime.now(),
        isStartingObservation: false,
        message: '',
      );
      if (observation.telemetryOnline) {
        _startHeartbeat();
      }
    } on ApiException catch (error) {
      state = state.copyWith(
        isStartingObservation: false,
        message: error.message,
      );
    }
  }

  void pauseHeartbeats() => _pauseHeartbeat();

  void resumeHeartbeats() {
    if (state.observation?.telemetryOnline == true) {
      _startHeartbeat(sendImmediately: true);
    }
  }

  Future<void> _restoreEndpoint() async {
    final operation = _operation;
    try {
      final endpoint = await ref.read(_endpointStoreProvider).read();
      if (operation != _operation) {
        return;
      }
      state = RobotConnectionState(
        phase: ConnectionPhase.idle,
        endpoint: endpoint,
        addressDraft: endpoint?.displayAddress ?? '',
      );
    } catch (_) {
      if (operation != _operation) {
        return;
      }
      state = const RobotConnectionState(phase: ConnectionPhase.idle);
    }
  }

  void _startHeartbeat({bool sendImmediately = false}) {
    _heartbeatTimer?.cancel();
    _heartbeatTimer = Timer.periodic(
      const Duration(seconds: 10),
      (_) => unawaited(_heartbeat()),
    );
    if (sendImmediately) {
      unawaited(_heartbeat());
    }
  }

  void _pauseHeartbeat() {
    _heartbeatTimer?.cancel();
    _heartbeatTimer = null;
  }

  Future<void> _heartbeat() async {
    final endpoint = state.endpoint;
    if (endpoint == null) {
      return;
    }
    try {
      final observation = await ref
          .read(aletheiaApiClientProvider)
          .heartbeat(endpoint);
      state = state.copyWith(
        observation: observation,
        lastChecked: DateTime.now(),
        message: '',
      );
    } on ApiException catch (error) {
      state = state.copyWith(message: '观测心跳失败：${error.message}');
    }
  }
}
