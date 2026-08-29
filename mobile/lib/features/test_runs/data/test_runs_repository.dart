import '../../../core/connection/robot_endpoint.dart';
import '../../../core/network/aletheia_api_client.dart';
import '../../../core/network/api_exception.dart';
import '../domain/aletheia_run.dart';

class TestRunsRepository {
  const TestRunsRepository(this._apiClient);

  final AletheiaApiClient _apiClient;

  Future<AletheiaRun?> latest(RobotEndpoint endpoint) async {
    final payload = await _apiClient.getJson(endpoint, 'api/runs/latest');
    return _optionalRun(payload['run']);
  }

  Future<AletheiaRun> create(
    RobotEndpoint endpoint,
    TestRunRequest request,
  ) async {
    final payload = await _apiClient.postJson(
      endpoint,
      'api/runs',
      body: request.toJson(),
    );
    return _requiredRun(payload);
  }

  Future<AletheiaRun> cancel(RobotEndpoint endpoint, String runId) async {
    final payload = await _apiClient.postJson(
      endpoint,
      'api/runs/$runId/cancel',
    );
    return _requiredRun(payload);
  }

  Future<AletheiaRun> resume(RobotEndpoint endpoint, String runId) async {
    final payload = await _apiClient.postJson(
      endpoint,
      'api/runs/$runId/resume',
    );
    return _requiredRun(payload);
  }

  Future<AletheiaRun> stallAction(
    RobotEndpoint endpoint,
    String runId,
    String action,
  ) async {
    final payload = await _apiClient.postJson(
      endpoint,
      'api/runs/$runId/stall-action',
      body: {'action': action},
    );
    return _requiredRun(payload);
  }

  AletheiaRun? _optionalRun(Object? value) {
    if (value is! Map) {
      return null;
    }
    return AletheiaRun.fromJson(
      value.map((key, item) => MapEntry(key.toString(), item)),
    );
  }

  AletheiaRun _requiredRun(Map<String, dynamic> payload) {
    final run = _optionalRun(payload['run']);
    if (run == null) {
      throw const ApiException('没有可读取的测试记录。');
    }
    return run;
  }
}
