import '../../../core/connection/robot_endpoint.dart';
import '../../../core/network/aletheia_api_client.dart';
import '../domain/vehicle_control_state.dart';

class ManualControlRepository {
  const ManualControlRepository(this._apiClient);

  final AletheiaApiClient _apiClient;

  Future<VehicleControlState> status(RobotEndpoint endpoint) =>
      _get(endpoint, 'api/vehicle-control');

  Future<VehicleControlState> enter(RobotEndpoint endpoint) =>
      _post(endpoint, 'api/vehicle-control/enter', const {});

  Future<VehicleControlState> heartbeat(
    RobotEndpoint endpoint,
    String sessionId,
  ) => _post(endpoint, 'api/vehicle-control/heartbeat', {
    'session_id': sessionId,
  });

  Future<VehicleControlState> command(
    RobotEndpoint endpoint,
    String sessionId,
    VehicleCommand command,
  ) => _post(endpoint, 'api/vehicle-control/command', {
    'session_id': sessionId,
    'command': command.wireName,
  });

  Future<VehicleControlState> vector(
    RobotEndpoint endpoint,
    String sessionId,
    VehicleControlVector vector,
  ) => _post(endpoint, 'api/vehicle-control/vector', {
    'session_id': sessionId,
    ...vector.toJson(),
  });

  Future<VehicleControlState> setSpeed(
    RobotEndpoint endpoint,
    String sessionId, {
    required double linearMps,
    required double angularRadps,
  }) => _post(endpoint, 'api/vehicle-control/speed', {
    'session_id': sessionId,
    'linear_speed': linearMps,
    'angular_speed': angularRadps,
  });

  Future<VehicleControlState> stop(RobotEndpoint endpoint, String sessionId) =>
      _post(endpoint, 'api/vehicle-control/stop', {'session_id': sessionId});

  Future<VehicleControlState> exit(RobotEndpoint endpoint, String sessionId) =>
      _post(endpoint, 'api/vehicle-control/exit', {'session_id': sessionId});

  Future<VehicleControlState> releaseEmergencyStop(RobotEndpoint endpoint) =>
      _post(endpoint, 'api/vehicle-control/release-emergency-stop', const {});

  Future<VehicleControlState> saveChassisParameters(
    RobotEndpoint endpoint,
    ChassisParameters parameters,
  ) => _post(
    endpoint,
    'api/vehicle-control/chassis-parameters',
    parameters.toJson(),
  );

  Future<VehicleControlState> _get(RobotEndpoint endpoint, String path) async {
    final payload = await _apiClient.getJson(endpoint, path);
    return VehicleControlState.fromJson(payload);
  }

  Future<VehicleControlState> _post(
    RobotEndpoint endpoint,
    String path,
    Map<String, dynamic> body,
  ) async {
    final payload = await _apiClient.postJson(endpoint, path, body: body);
    return VehicleControlState.fromJson(payload);
  }
}
