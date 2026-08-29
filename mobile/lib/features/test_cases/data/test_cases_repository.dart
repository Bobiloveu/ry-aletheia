import '../../../core/connection/robot_endpoint.dart';
import '../../../core/network/aletheia_api_client.dart';
import '../domain/aletheia_test_case.dart';

class CaseCatalog {
  const CaseCatalog({required this.cases, required this.validationIssues});

  const CaseCatalog.empty() : cases = const [], validationIssues = const [];

  final List<AletheiaTestCase> cases;
  final List<CaseValidationIssue> validationIssues;
}

class CaseValidationIssue {
  const CaseValidationIssue({required this.filename, required this.message});

  factory CaseValidationIssue.fromJson(Map<String, dynamic> json) {
    return CaseValidationIssue(
      filename: json['filename'] is String
          ? json['filename'] as String
          : '未知文件',
      message: json['message'] is String ? json['message'] as String : '用例校验失败',
    );
  }

  final String filename;
  final String message;
}

class TestCasesRepository {
  const TestCasesRepository(this._apiClient);

  final AletheiaApiClient _apiClient;

  Future<CaseCatalog> load(RobotEndpoint endpoint) async {
    final payload = await _apiClient.getJson(endpoint, 'api/cases');
    final cases = (payload['cases'] as List<Object?>? ?? const [])
        .whereType<Map>()
        .map(
          (item) => AletheiaTestCase.fromJson(
            item.map((key, value) => MapEntry(key.toString(), value)),
          ),
        )
        .toList(growable: false);
    final issues = (payload['validationIssues'] as List<Object?>? ?? const [])
        .whereType<Map>()
        .map(
          (item) => CaseValidationIssue.fromJson(
            item.map((key, value) => MapEntry(key.toString(), value)),
          ),
        )
        .toList(growable: false);
    return CaseCatalog(cases: cases, validationIssues: issues);
  }

  Future<void> saveManagement(
    RobotEndpoint endpoint,
    AletheiaTestCase testCase, {
    required String alias,
    required String version,
    required String lifecycle,
    required List<String> tags,
    required String summary,
  }) async {
    // Aliases are part of the existing global settings document. Read-modify-
    // write preserves all unrelated server-owned configuration fields.
    final settings = await _apiClient.getJson(endpoint, 'api/settings');
    final aliases = (settings['case_aliases'] as Map? ?? const {}).map(
      (key, value) => MapEntry(key.toString(), value.toString()),
    );
    if (alias.trim().isEmpty) {
      aliases.remove(testCase.id);
    } else {
      aliases[testCase.id] = alias.trim();
    }
    await _apiClient.postJson(
      endpoint,
      'api/settings',
      body: {'case_aliases': aliases},
    );
    await _apiClient.postJson(
      endpoint,
      'api/cases/${testCase.id}/management',
      body: {
        'version': version.trim(),
        'lifecycle': lifecycle,
        'tags': tags,
        'summary': summary.trim(),
      },
    );
  }

  Future<String> importFile(
    RobotEndpoint endpoint, {
    required List<int> bytes,
    required String filename,
    required bool isPackage,
  }) async {
    final payload = await _apiClient.postBytes(
      endpoint,
      isPackage ? 'api/case-packages/import' : 'api/cases/upload',
      bytes: bytes,
      contentType: isPackage
          ? 'application/zip'
          : 'application/json; charset=utf-8',
      headers: isPackage
          ? const {}
          : {'X-Case-Filename': Uri.encodeComponent(filename)},
    );
    return payload['message'] is String
        ? payload['message'] as String
        : '用例已导入。';
  }
}
