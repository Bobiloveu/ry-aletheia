import 'dart:async';

import 'package:aletheia_mobile/core/connection/robot_connection_controller.dart';
import 'package:aletheia_mobile/core/connection/robot_connection_state.dart';
import 'package:aletheia_mobile/core/connection/robot_endpoint.dart';
import 'package:aletheia_mobile/core/network/aletheia_api_client.dart';
import 'package:aletheia_mobile/features/manual_control/application/manual_control_controller.dart';
import 'package:aletheia_mobile/features/manual_control/data/manual_control_repository.dart';
import 'package:aletheia_mobile/features/manual_control/domain/vehicle_control_state.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/testing.dart';
import 'package:test/test.dart';

void main() {
  test('releases an active session in STOP then EXIT order', () async {
    final repository = _FakeManualControlRepository()
      ..nextEnter = _readyState(sessionId: 'session-1');
    final container = _container(repository);
    addTearDown(container.dispose);
    final controller = container.read(manualControlControllerProvider.notifier);
    await Future<void>.delayed(Duration.zero);

    await controller.enter();
    await controller.exit();

    expect(repository.calls, [
      'status',
      'enter',
      'stop:session-1',
      'exit:session-1',
    ]);
  });

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

  test('sends a held upper-right vector then stops at the joystick center', () async {
    final repository = _FakeManualControlRepository()
      ..nextEnter = _readyState(sessionId: 'session-1');
    final container = _container(repository);
    addTearDown(container.dispose);
    final controller = container.read(manualControlControllerProvider.notifier);
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
  });

  test(
    'pausing releases the session and resuming never re-enters control',
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
        containsAllInOrder([
          'enter',
          'stop:session-1',
          'exit:session-1',
          'status',
        ]),
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
  VehicleControlState? nextEnter;

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
    return _readyState(sessionId: sessionId);
  }

  @override
  Future<VehicleControlState> stop(
    RobotEndpoint endpoint,
    String sessionId,
  ) async {
    calls.add('stop:$sessionId');
    return _state();
  }

  @override
  Future<VehicleControlState> exit(
    RobotEndpoint endpoint,
    String sessionId,
  ) async {
    calls.add('exit:$sessionId');
    return _state();
  }
}

VehicleControlState _readyState({required String sessionId}) =>
    _state(sessionId: sessionId);

VehicleControlState _state({
  EmergencyStopState emergency = EmergencyStopState.normal,
  String? sessionId,
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
  'speed': {'linear_mps': .2, 'angular_radps': .3, 'min': .1, 'max': 1.0},
  'emergency_stop': {'state': emergency.wireName, 'release': 'idle'},
  'chassis_parameters': {'press': 1400, 'movement_acc': 1000, 'stop_acc': 1200},
});
