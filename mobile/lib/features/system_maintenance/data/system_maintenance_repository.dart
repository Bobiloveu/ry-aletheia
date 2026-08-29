import '../../../core/connection/robot_endpoint.dart';
import '../../../core/network/aletheia_api_client.dart';

class SystemMaintenanceRepository {
  const SystemMaintenanceRepository(this._apiClient);
  final AletheiaApiClient _apiClient;

  Future<void> shutdown(RobotEndpoint endpoint) async {
    await _apiClient.postJson(endpoint, 'api/system/shutdown');
  }
}
