import '../../../core/connection/robot_endpoint.dart';
import '../../../core/network/aletheia_api_client.dart';
import '../domain/runtime_settings.dart';

class RuntimeSettingsRepository {
  const RuntimeSettingsRepository(this._apiClient);

  final AletheiaApiClient _apiClient;

  Future<RuntimeSettings> load(RobotEndpoint endpoint) async {
    final json = await _apiClient.getJson(endpoint, 'api/settings');
    return RuntimeSettings.fromJson(json);
  }

  Future<RuntimeSettings> save(
    RobotEndpoint endpoint,
    RuntimeSettings settings,
  ) async {
    final json = await _apiClient.postJson(
      endpoint,
      'api/settings',
      body: settings.toJson(),
    );
    return RuntimeSettings.fromJson(json);
  }

  Future<List<SupervisorProcess>> discover(RobotEndpoint endpoint) async {
    final json = await _apiClient.getJson(endpoint, 'api/supervisor/processes');
    return (json['processes'] as List<Object?>? ?? const [])
        .whereType<Map>()
        .map(
          (item) => SupervisorProcess.fromJson(
            item.map((key, value) => MapEntry(key.toString(), value)),
          ),
        )
        .where((item) => item.name.isNotEmpty)
        .toList(growable: false);
  }
}
