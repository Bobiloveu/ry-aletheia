import 'dart:convert';

import 'package:aletheia_mobile/core/connection/robot_endpoint.dart';
import 'package:aletheia_mobile/core/network/aletheia_api_client.dart';
import 'package:aletheia_mobile/features/manual_control/data/manual_control_repository.dart';
import 'package:aletheia_mobile/features/manual_control/domain/vehicle_control_state.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:test/test.dart';

void main() {
  test(
    'sends only an opaque session and supported command to the backend',
    () async {
      final requests = <http.Request>[];
      final repository = ManualControlRepository(
        AletheiaApiClient(
          MockClient((request) async {
            requests.add(request);
            return http.Response(jsonEncode(_snapshot()), 200);
          }),
        ),
      );

      await repository.command(
        RobotEndpoint.parse('192.168.1.20'),
        'session-1',
        VehicleCommand.forward,
      );

      expect(requests, hasLength(1));
      expect(requests.single.method, 'POST');
      expect(requests.single.url.path, '/api/vehicle-control/command');
      expect(jsonDecode(requests.single.body), {
        'session_id': 'session-1',
        'command': 'forward',
      });
    },
  );

  test('sends normalized vector ratios only through the controlled endpoint', () async {
    final requests = <http.Request>[];
    final repository = ManualControlRepository(
      AletheiaApiClient(
        MockClient((request) async {
          requests.add(request);
          return http.Response(jsonEncode(_snapshot()), 200);
        }),
      ),
    );

    await repository.vector(
      RobotEndpoint.parse('192.168.1.20'),
      'session-1',
      const VehicleControlVector(.8, -.6),
    );

    expect(requests.single.url.path, '/api/vehicle-control/vector');
    expect(jsonDecode(requests.single.body), {
      'session_id': 'session-1',
      'linear_ratio': .8,
      'angular_ratio': -.6,
    });
  });

  test(
    'uses the fixed release endpoint without session or path input',
    () async {
      final requests = <http.Request>[];
      final repository = ManualControlRepository(
        AletheiaApiClient(
          MockClient((request) async {
            requests.add(request);
            return http.Response(jsonEncode(_snapshot()), 202);
          }),
        ),
      );

      await repository.releaseEmergencyStop(RobotEndpoint.parse('robot.local'));

      expect(
        requests.single.url.path,
        '/api/vehicle-control/release-emergency-stop',
      );
      expect(jsonDecode(requests.single.body), isEmpty);
    },
  );

  test('saves only the three server-defined chassis parameters', () async {
    final requests = <http.Request>[];
    final repository = ManualControlRepository(
      AletheiaApiClient(
        MockClient((request) async {
          requests.add(request);
          return http.Response(jsonEncode(_snapshot()), 200);
        }),
      ),
    );

    await repository.saveChassisParameters(
      RobotEndpoint.parse('robot.local'),
      const ChassisParameters(
        press: 1400,
        movementAcceleration: 1000,
        stopAcceleration: 1200,
      ),
    );

    expect(requests.single.url.path, '/api/vehicle-control/chassis-parameters');
    expect(jsonDecode(requests.single.body), {
      'press': 1400,
      'movement_acc': 1000,
      'stop_acc': 1200,
    });
  });
}

Map<String, dynamic> _snapshot() => {
  'runtime': 'ready',
  'actual_source': 'navigation',
  'manual_ready': false,
  'can_begin_manual': true,
  'session': {'present': false, 'state': 'none'},
  'speed': {'linear_mps': .2, 'angular_radps': .3, 'min': .1, 'max': 1.0},
  'emergency_stop': {'state': 'normal', 'release': 'idle'},
  'chassis_parameters': {'press': 1400, 'movement_acc': 1000, 'stop_acc': 1200},
};
