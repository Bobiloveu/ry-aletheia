import 'dart:async';
import 'dart:collection';

import 'package:aletheia_mobile/core/connection/robot_connection_controller.dart';
import 'package:aletheia_mobile/core/connection/robot_connection_state.dart';
import 'package:aletheia_mobile/core/connection/robot_endpoint.dart';
import 'package:aletheia_mobile/core/network/aletheia_api_client.dart';
import 'package:aletheia_mobile/core/network/api_exception.dart';
import 'package:aletheia_mobile/features/manual_control/application/manual_control_controller.dart';
import 'package:aletheia_mobile/features/manual_control/data/manual_control_repository.dart';
import 'package:aletheia_mobile/features/manual_control/domain/vehicle_control_state.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/testing.dart';
import 'package:test/test.dart';

void main() {
  test('polls vehicle status while connected before manual entry', () async {
    final repository = _FakeManualControlRepository();
    final container = _container(repository);
    addTearDown(container.dispose);

    container.read(manualControlControllerProvider.notifier);
    await Future<void>.delayed(const Duration(milliseconds: 1200));

    expect(
      repository.calls.where((call) => call == 'status').length,
      greaterThanOrEqualTo(2),
    );
  });

  test(
    'explicit exit requests the backend global navigation transition',
    () async {
      final repository = _FakeManualControlRepository()
        ..nextEnter = _readyState(sessionId: 'session-1');
      final container = _container(repository);
      addTearDown(container.dispose);
      final controller = container.read(
        manualControlControllerProvider.notifier,
      );
      await Future<void>.delayed(Duration.zero);

      await controller.enter();
      await controller.exit();

      expect(repository.calls, ['status', 'enter', 'exit:session-1']);
    },
  );

  test(
    'does not send motion when the newest state is emergency unknown',
    () async {
      final repository = _FakeManualControlRepository()
        ..nextEnter = _state(
          emergency: EmergencyStopState.unknown,
          sessionId: 'session-1',
        );
      final container = _container(repository);
      addTearDown(container.dispose);
      final controller = container.read(
        manualControlControllerProvider.notifier,
      );
      await Future<void>.delayed(Duration.zero);

      await controller.enter();
      await controller.sendCommand(VehicleCommand.forward);

      expect(repository.calls, ['status', 'enter']);
    },
  );

  test(
    'sends a held upper-right vector then stops at the joystick center',
    () async {
      final repository = _FakeManualControlRepository()
        ..nextEnter = _readyState(sessionId: 'session-1');
      final container = _container(repository);
      addTearDown(container.dispose);
      final controller = container.read(
        manualControlControllerProvider.notifier,
      );
      await Future<void>.delayed(Duration.zero);

      await controller.enter();
      await controller.sendVector(const VehicleControlVector(.8, -.6));
      await controller.sendVector(VehicleControlVector.stop);

      expect(repository.calls, [
        'status',
        'enter',
        'vector:session-1:0.8:-0.6',
        'stop:session-1',
      ]);
    },
  );

  test('sends three serialized stop confirmations after the joystick returns to center', () async {
    final repository = _FakeManualControlRepository()
      ..nextEnter = _readyState(sessionId: 'session-1');
    final container = _container(repository);
    addTearDown(container.dispose);
    final controller = container.read(manualControlControllerProvider.notifier);
    await Future<void>.delayed(Duration.zero);

    await controller.enter();
    await controller.sendVector(const VehicleControlVector(.8, -.6));
    await controller.sendVector(VehicleControlVector.stop);
    await Future<void>.delayed(const Duration(milliseconds: 180));

    expect(
      repository.calls.where((call) => call == 'stop:session-1'),
      hasLength(3),
    );
  });

  test(
    'continues the bounded stop confirmation burst after one network failure',
    () async {
      final repository = _FakeManualControlRepository()
        ..nextEnter = _readyState(sessionId: 'session-1')
        ..stopFailuresRemaining = 1;
      final container = _container(repository);
      addTearDown(container.dispose);
      final controller = container.read(
        manualControlControllerProvider.notifier,
      );
      await Future<void>.delayed(Duration.zero);

      await controller.enter();
      await controller.sendVector(const VehicleControlVector(.8, -.6));
      await controller.stop();
      await Future<void>.delayed(const Duration(milliseconds: 180));

      expect(
        repository.calls.where((call) => call == 'stop:session-1'),
        hasLength(3),
      );
    },
  );

  test(
    'cancels unsent stop confirmations before a new joystick direction',
    () async {
      final repository = _FakeManualControlRepository()
        ..nextEnter = _readyState(sessionId: 'session-1');
      final container = _container(repository);
      addTearDown(container.dispose);
      final controller = container.read(
        manualControlControllerProvider.notifier,
      );
      await Future<void>.delayed(Duration.zero);

      await controller.enter();
      await controller.sendVector(const VehicleControlVector(.8, -.6));
      await controller.stop();
      await controller.sendVector(const VehicleControlVector(.3, .2));
      await Future<void>.delayed(const Duration(milliseconds: 180));

      expect(
        repository.calls.where((call) => call == 'stop:session-1'),
        hasLength(1),
      );
      expect(repository.vectorCalls.last, 'vector:session-1:0.3:0.2');
    },
  );

  test(
    'coalesces joystick changes while one vector request is still in flight',
    () async {
      final repository = _FakeManualControlRepository()
        ..holdVectors = true
        ..nextEnter = _readyState(sessionId: 'session-1');
      final container = _container(repository);
      addTearDown(container.dispose);
      final controller = container.read(
        manualControlControllerProvider.notifier,
      );
      await Future<void>.delayed(Duration.zero);

      await controller.enter();
      unawaited(controller.sendVector(const VehicleControlVector(.25, .1)));
      await _flushAsyncWork();
      unawaited(controller.sendVector(const VehicleControlVector(.9, -.7)));
      await _flushAsyncWork();

      expect(repository.vectorCalls, ['vector:session-1:0.25:0.1']);

      repository.completeNextVector();
      await _flushAsyncWork();

      expect(repository.vectorCalls, [
        'vector:session-1:0.25:0.1',
        'vector:session-1:0.9:-0.7',
      ]);
    },
  );

  test('serializes STOP after a vector that is still in flight', () async {
    final repository = _FakeManualControlRepository()
      ..holdVectors = true
      ..nextEnter = _readyState(sessionId: 'session-1');
    final container = _container(repository);
    addTearDown(container.dispose);
    final controller = container.read(manualControlControllerProvider.notifier);
    await Future<void>.delayed(Duration.zero);

    await controller.enter();
    unawaited(controller.sendVector(const VehicleControlVector(.6, 0)));
    await _flushAsyncWork();
    final stop = controller.stop();
    await _flushAsyncWork();

    expect(repository.calls, isNot(contains('stop:session-1')));

    repository.completeNextVector();
    await _flushAsyncWork();

    expect(repository.calls, contains('stop:session-1'));
    await stop;
  });

  test('keeps motion available while showing link delay for a slow vector response', () async {
    final repository = _FakeManualControlRepository()
      ..holdVectors = true
      ..nextEnter = _state(sessionId: 'session-1', inputTimeoutMs: 60);
    final container = _container(repository);
    addTearDown(container.dispose);
    final controller = container.read(manualControlControllerProvider.notifier);
    await Future<void>.delayed(Duration.zero);

    await controller.enter();
    unawaited(controller.sendVector(const VehicleControlVector(.5, 0)));
    await Future<void>.delayed(const Duration(milliseconds: 70));

    expect(
      container.read(manualControlControllerProvider).link,
      ManualControlLink.delayed,
    );
    expect(
      container.read(manualControlControllerProvider).canSendMotion,
      isTrue,
    );
    expect(repository.vectorCalls, hasLength(1));

    repository.completeNextVector();
    await _flushAsyncWork();

    expect(
      container.read(manualControlControllerProvider).link,
      ManualControlLink.healthy,
    );
  });

  test('does not overlap heartbeats with a held vector request', () async {
    final repository = _FakeManualControlRepository()
      ..holdVectors = true
      ..nextEnter = _readyState(sessionId: 'session-1');
    final container = _container(repository);
    addTearDown(container.dispose);
    final controller = container.read(manualControlControllerProvider.notifier);
    await Future<void>.delayed(Duration.zero);

    await controller.enter();
    unawaited(controller.sendVector(const VehicleControlVector(.4, .2)));
    await Future<void>.delayed(const Duration(milliseconds: 550));

    expect(repository.calls, isNot(contains('heartbeat:session-1')));
  });

  test(
    'pausing releases only this session and resuming never re-enters control',
    () async {
      final repository = _FakeManualControlRepository()
        ..nextEnter = _readyState(sessionId: 'session-1');
      final container = _container(repository);
      addTearDown(container.dispose);
      final controller = container.read(
        manualControlControllerProvider.notifier,
      );
      await Future<void>.delayed(Duration.zero);

      await controller.enter();
      await controller.pauseForLifecycle();
      controller.resumeAfterLifecycle();
      await Future<void>.delayed(Duration.zero);

      expect(
        repository.calls,
        containsAllInOrder(['enter', 'release:session-1', 'status']),
      );
      expect(repository.calls.where((call) => call == 'enter'), hasLength(1));
    },
  );
}

ProviderContainer _container(_FakeManualControlRepository repository) =>
    ProviderContainer(
      overrides: [
        robotConnectionControllerProvider.overrideWith(
          _ConnectedController.new,
        ),
        manualControlRepositoryProvider.overrideWithValue(repository),
      ],
    );

Future<void> _flushAsyncWork() async {
  await Future<void>.delayed(Duration.zero);
  await Future<void>.delayed(Duration.zero);
}

class _ConnectedController extends RobotConnectionController {
  @override
  RobotConnectionState build() => RobotConnectionState(
    phase: ConnectionPhase.connected,
    endpoint: RobotEndpoint.parse('robot.local'),
  );
}

class _FakeManualControlRepository extends ManualControlRepository {
  _FakeManualControlRepository()
    : super(
        AletheiaApiClient(
          MockClient((_) async => throw StateError('unexpected HTTP request')),
        ),
      );

  final calls = <String>[];
  final _pendingVectors = Queue<Completer<VehicleControlState>>();
  VehicleControlState? nextEnter;
  bool holdVectors = false;
  int stopFailuresRemaining = 0;

  List<String> get vectorCalls =>
      calls.where((call) => call.startsWith('vector:')).toList();

  void completeNextVector() {
    _pendingVectors.removeFirst().complete(_readyState(sessionId: 'session-1'));
  }

  @override
  Future<VehicleControlState> status(RobotEndpoint endpoint) async {
    calls.add('status');
    return _state();
  }

  @override
  Future<VehicleControlState> enter(RobotEndpoint endpoint) async {
    calls.add('enter');
    return nextEnter ?? _state();
  }

  @override
  Future<VehicleControlState> command(
    RobotEndpoint endpoint,
    String sessionId,
    VehicleCommand command,
  ) async {
    calls.add('command:${command.wireName}');
    return _readyState(sessionId: sessionId);
  }

  @override
  Future<VehicleControlState> vector(
    RobotEndpoint endpoint,
    String sessionId,
    VehicleControlVector vector,
  ) async {
    calls.add('vector:$sessionId:${vector.linearRatio}:${vector.angularRatio}');
    if (holdVectors) {
      final pending = Completer<VehicleControlState>();
      _pendingVectors.add(pending);
      return pending.future;
    }
    return _readyState(sessionId: sessionId);
  }

  @override
  Future<VehicleControlState> heartbeat(
    RobotEndpoint endpoint,
    String sessionId,
  ) async {
    calls.add('heartbeat:$sessionId');
    return _readyState(sessionId: sessionId);
  }

  @override
  Future<VehicleControlState> stop(
    RobotEndpoint endpoint,
    String sessionId,
  ) async {
    calls.add('stop:$sessionId');
    if (stopFailuresRemaining > 0) {
      stopFailuresRemaining -= 1;
      throw ApiException('simulated stop network failure');
    }
    return _readyState(sessionId: sessionId);
  }

  @override
  Future<VehicleControlState> exit(
    RobotEndpoint endpoint,
    String sessionId,
  ) async {
    calls.add('exit:$sessionId');
    return _state();
  }

  @override
  Future<VehicleControlState> release(
    RobotEndpoint endpoint,
    String sessionId,
  ) async {
    calls.add('release:$sessionId');
    return _state();
  }
}

VehicleControlState _readyState({required String sessionId}) =>
    _state(sessionId: sessionId);

VehicleControlState _state({
  EmergencyStopState emergency = EmergencyStopState.normal,
  String? sessionId,
  int inputTimeoutMs = 350,
}) => VehicleControlState.fromJson({
  'runtime': 'ready',
  'actual_source': sessionId == null ? 'navigation' : 'miniapp',
  'manual_ready': sessionId != null,
  'can_begin_manual': sessionId == null,
  'session': {
    'present': sessionId != null,
    'state': sessionId == null ? 'none' : 'active',
    ...(sessionId == null ? const <String, Object?>{} : {'id': sessionId}),
  },
  'safety': {
    'publish_hz': 20,
    'input_timeout_ms': inputTimeoutMs,
    'heartbeat_timeout_ms': 1200,
  },
  'speed': {'linear_mps': .2, 'angular_radps': .3, 'min': .1, 'max': 1.0},
  'emergency_stop': {'state': emergency.wireName, 'release': 'idle'},
  'chassis_parameters': {'press': 1400, 'movement_acc': 1000, 'stop_acc': 1200},
});
