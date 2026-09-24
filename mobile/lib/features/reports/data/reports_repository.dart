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

  Future<NativeReportDetailPage> loadNativeDetail(
    RobotEndpoint endpoint,
    String reportId, {
    String? cursor,
    int limit = 50,
  }) async {
    if (!_identifierExpression.hasMatch(reportId)) {
      throw ArgumentError.value(reportId, 'reportId', '报告标识无效。');
    }
    if (cursor != null &&
        (cursor.isEmpty ||
            cursor.length > 512 ||
            _controlCharacterExpression.hasMatch(cursor))) {
      throw ArgumentError.value(cursor, 'cursor', '报告分页标识无效。');
    }
    final boundedLimit = limit.clamp(1, 100);
    final payload = await _apiClient.getJson(
      endpoint,
      'api/reports/$reportId/native',
      queryParameters: {'cursor': ?cursor, 'limit': '$boundedLimit'},
    );
    return NativeReportDetailPage.fromJson(payload);
  }

  Future<void> delete(RobotEndpoint endpoint, AletheiaReport report) async {
    await _apiClient.deleteJson(endpoint, 'api/reports/${report.filename}');
  }
}

final _identifierExpression = RegExp(r'^[A-Za-z0-9_-]{1,128}$');
final _controlCharacterExpression = RegExp(r'[\u0000-\u001F\u007F]');
