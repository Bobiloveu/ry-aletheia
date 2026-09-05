import 'package:aletheia_mobile/features/manual_control/domain/vehicle_control_state.dart';
import 'package:test/test.dart';

void main() {
  test('decodes a backend-confirmed manual-ready state', () {
    final state = VehicleControlState.fromJson(
      _readyPayload(sessionId: 'a' * 32),
    );

    expect(state.manualReady, isTrue);
    expect(state.session.id, 'a' * 32);
    expect(state.emergency.state, EmergencyStopState.normal);
    expect(state.motionPermittedByBackend, isTrue);
  });

  test('fails closed when the emergency status is absent or unknown', () {
    final state = VehicleControlState.fromJson({'manual_ready': true});

    expect(state.emergency.state, EmergencyStopState.unknown);
    expect(state.motionPermittedByBackend, isFalse);
  });

  test('exposes only the four backend motion commands', () {
    expect(VehicleCommand.values, {
      VehicleCommand.forward,
      VehicleCommand.backward,
      VehicleCommand.left,
      VehicleCommand.right,
    });
  });

  test('maps an upper-right joystick position to forward and right turn', () {
    final vector = VehicleControlVector.fromJoystick(
      horizontal: .8,
      vertical: -.6,
    );

    expect(vector.linearRatio, .6);
    expect(vector.angularRatio, -.8);
    expect(vector.isStop, isFalse);
  });

  test('maps the joystick center to the explicit stop vector', () {
    final vector = VehicleControlVector.fromJoystick(
      horizontal: .03,
      vertical: -.02,
    );

    expect(vector, VehicleControlVector.stop);
  });
}

Map<String, dynamic> _readyPayload({required String sessionId}) => {
  'runtime': 'ready',
  'actual_source': 'miniapp',
  'transition': null,
  'manual_ready': true,
  'can_begin_manual': false,
  'session': {'present': true, 'state': 'active', 'id': sessionId},
  'speed': {'linear_mps': .2, 'angular_radps': .3, 'min': .1, 'max': 1.0},
  'emergency_stop': {'state': 'normal', 'release': 'idle'},
  'chassis_parameters': {'press': 1400, 'movement_acc': 1000, 'stop_acc': 1200},
};
