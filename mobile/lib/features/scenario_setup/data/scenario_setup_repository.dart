import '../../../core/connection/robot_endpoint.dart';
import '../../../core/network/aletheia_api_client.dart';
import '../domain/scenario_setup.dart';

class ScenarioSetupRepository {
  const ScenarioSetupRepository(this._apiClient);
  final AletheiaApiClient _apiClient;

  Future<ScenarioSetupStatus> load(RobotEndpoint endpoint) async =>
      ScenarioSetupStatus.fromJson(
        await _apiClient.getJson(endpoint, 'api/scenario-setup'),
      );

  Future<ScenarioSetupStatus> save(
    RobotEndpoint endpoint,
    ScenarioDocument document,
  ) async {
    final json = await _apiClient.postJson(
      endpoint,
      'api/scenario-setup',
      body: {'action': 'save', 'document': document.toJson()},
    );
    return ScenarioSetupStatus.fromJson(_map(json['status']));
  }

  Future<ScenarioPreview> preview(
    RobotEndpoint endpoint,
    ScenarioDocument document,
    String profileId,
  ) async => ScenarioPreview.fromJson(
    await _apiClient.postJson(
      endpoint,
      'api/scenario-setup',
      body: {
        'action': 'preview',
        'document': document.toJson(),
        'profile_id': profileId,
      },
    ),
  );

  Future<ScenarioSetupStatus> apply(RobotEndpoint endpoint, String profileId) =>
      _action(endpoint, {'action': 'apply', 'profile_id': profileId});
  Future<ScenarioSetupStatus> restore(RobotEndpoint endpoint) =>
      _action(endpoint, const {'action': 'restore'});

  Future<ScenarioSetupStatus> bindCase(
    RobotEndpoint endpoint,
    String caseId,
    String profileId,
  ) => _action(endpoint, {
    'action': 'bind-case',
    'case_id': caseId,
    'profile_id': profileId,
  });

  Future<ScenarioFileBrowser> browse(
    RobotEndpoint endpoint, {
    required String kind,
    String path = '',
  }) async => ScenarioFileBrowser.fromJson(
    await _apiClient.getJson(
      endpoint,
      'api/scenario-setup/browse',
      queryParameters: {'kind': kind, 'path': path},
    ),
  );

  Future<ScenarioFilePreview> readFile(
    RobotEndpoint endpoint,
    String path,
  ) async => ScenarioFilePreview.fromJson(
    await _apiClient.getJson(
      endpoint,
      'api/scenario-setup/file',
      queryParameters: {'path': path},
    ),
  );

  Future<ScenarioSetupStatus> _action(
    RobotEndpoint endpoint,
    Map<String, dynamic> body,
  ) async {
    final json = await _apiClient.postJson(
      endpoint,
      'api/scenario-setup',
      body: body,
    );
    return ScenarioSetupStatus.fromJson(_map(json['status']));
  }
}

Map<String, dynamic> _map(Object? value) => value is Map
    ? value.map((key, item) => MapEntry(key.toString(), item))
    : const {};
