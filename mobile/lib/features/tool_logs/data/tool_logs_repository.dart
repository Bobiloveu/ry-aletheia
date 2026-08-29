import '../../../core/connection/robot_endpoint.dart';
import '../../../core/network/aletheia_api_client.dart';
import '../domain/tool_log_entry.dart';

class ToolLogsRepository {
  const ToolLogsRepository(this._apiClient);

  final AletheiaApiClient _apiClient;

  Future<List<ToolLogEntry>> load(
    RobotEndpoint endpoint,
    ToolLogScope scope,
  ) async {
    final payload = await _apiClient.getJson(
      endpoint,
      'api/tool-logs',
      queryParameters: {'scope': scope.apiValue},
    );
    return (payload['entries'] as List<Object?>? ?? const [])
        .whereType<Map>()
        .map(
          (item) => ToolLogEntry.fromJson(
            item.map((key, value) => MapEntry(key.toString(), value)),
          ),
        )
        .toList(growable: false);
  }

  Future<List<DiagnosticFile>> files(RobotEndpoint endpoint) async {
    final payload = await _apiClient.getJson(endpoint, 'api/tool-logs/files');
    return (payload['files'] as List<Object?>? ?? const [])
        .whereType<Map>()
        .map(
          (item) => DiagnosticFile.fromJson(
            item.map((key, value) => MapEntry(key.toString(), value)),
          ),
        )
        .where((item) => item.isDownloadable)
        .toList(growable: false);
  }
}
