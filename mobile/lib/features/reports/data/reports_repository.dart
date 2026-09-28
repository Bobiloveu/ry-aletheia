import '../../../core/connection/robot_endpoint.dart';
import '../../../core/network/aletheia_api_client.dart';
import '../domain/aletheia_report.dart';
import '../domain/native_report_trajectory.dart';

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

  Future<NativeReportTrajectory> loadNativeTrajectory(
    RobotEndpoint endpoint,
    String reportId,
    String trajectoryId,
  ) async {
    _validateIdentifier(reportId, field: 'reportId', label: '报告标识');
    _validateIdentifier(trajectoryId, field: 'trajectoryId', label: '轨迹标识');
    final payload = await _apiClient.getJson(
      endpoint,
      'api/reports/$reportId/native/trajectories/$trajectoryId',
    );
    return NativeReportTrajectory.fromJson(payload);
  }

  Future<NativeTrajectorySamplePage> loadNativeTrajectorySamples(
    RobotEndpoint endpoint,
    String reportId,
    String trajectoryId, {
    required String cursor,
    int limit = 200,
  }) async {
    _validateIdentifier(reportId, field: 'reportId', label: '报告标识');
    _validateIdentifier(trajectoryId, field: 'trajectoryId', label: '轨迹标识');
    if (cursor.isEmpty ||
        cursor.length > 512 ||
        _controlCharacterExpression.hasMatch(cursor)) {
      throw ArgumentError.value(cursor, 'cursor', '报告分页标识无效。');
    }
    final boundedLimit = limit.clamp(1, 1000);
    final payload = await _apiClient.getJson(
      endpoint,
      'api/reports/$reportId/native/trajectories/$trajectoryId/samples',
      queryParameters: {'cursor': cursor, 'limit': '$boundedLimit'},
    );
    return NativeTrajectorySamplePage.fromJson(payload);
  }

  Uri nativeTrajectoryMapUri(
    RobotEndpoint endpoint,
    String reportId,
    String trajectoryId,
  ) {
    _validateIdentifier(reportId, field: 'reportId', label: '报告标识');
    _validateIdentifier(trajectoryId, field: 'trajectoryId', label: '轨迹标识');
    return endpoint.apiUri(
      'api/reports/$reportId/native/trajectories/$trajectoryId/map.png',
    );
  }

  Future<void> delete(RobotEndpoint endpoint, AletheiaReport report) async {
    await _apiClient.deleteJson(endpoint, 'api/reports/${report.filename}');
  }
}

final _identifierExpression = RegExp(r'^[A-Za-z0-9_-]{1,128}$');
final _controlCharacterExpression = RegExp(r'[\u0000-\u001F\u007F]');

void _validateIdentifier(
  String value, {
  required String field,
  required String label,
}) {
  if (!_identifierExpression.hasMatch(value)) {
    throw ArgumentError.value(value, field, '$label无效。');
  }
}
