import '../../../core/connection/robot_endpoint.dart';
import '../../../core/network/aletheia_api_client.dart';
import '../domain/aletheia_report.dart';

class ReportsRepository {
  const ReportsRepository(this._apiClient);

  final AletheiaApiClient _apiClient;

  Future<List<AletheiaReport>> load(RobotEndpoint endpoint) async {
    final payload = await _apiClient.getJson(endpoint, 'api/reports');
    return (payload['reports'] as List<Object?>? ?? const [])
        .whereType<Map>()
        .map(
          (item) => AletheiaReport.fromJson(
            item.map((key, value) => MapEntry(key.toString(), value)),
          ),
        )
        .where((report) => report.isOpenableHtml)
        .toList(growable: false);
  }

  Future<void> delete(RobotEndpoint endpoint, AletheiaReport report) async {
    await _apiClient.deleteJson(endpoint, 'api/reports/${report.filename}');
  }
}
