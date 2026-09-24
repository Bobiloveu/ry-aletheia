import 'dart:convert';

import 'package:aletheia_mobile/core/connection/robot_endpoint.dart';
import 'package:aletheia_mobile/core/network/aletheia_api_client.dart';
import 'package:aletheia_mobile/core/network/api_exception.dart';
import 'package:aletheia_mobile/features/reports/data/reports_repository.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:test/test.dart';

void main() {
  const endpointAddress = '192.168.1.20';
  final endpoint = RobotEndpoint.parse(endpointAddress);

  test(
    'requests the controlled native detail route with a bounded cursor',
    () async {
      final requests = <http.Request>[];
      final repository = ReportsRepository(
        AletheiaApiClient(
          MockClient((request) async {
            requests.add(request);
            return http.Response(
              jsonEncode(_nativeDetail(cursor: null)),
              200,
              headers: const {
                'content-type': 'application/json; charset=utf-8',
              },
            );
          }),
        ),
      );

      await repository.loadNativeDetail(
        endpoint,
        'rpt_01J8',
        cursor: 'opaque-next',
        limit: 101,
      );

      expect(requests, hasLength(1));
      expect(requests.single.url.path, '/api/reports/rpt_01J8/native');
      expect(requests.single.url.queryParameters, {
        'cursor': 'opaque-next',
        'limit': '100',
      });
    },
  );

  test(
    'rejects an unsafe report identifier before issuing a network request',
    () async {
      var requestCount = 0;
      final repository = ReportsRepository(
        AletheiaApiClient(
          MockClient((_) async {
            requestCount += 1;
            return http.Response('{}', 200);
          }),
        ),
      );

      await expectLater(
        repository.loadNativeDetail(endpoint, '../report'),
        throwsArgumentError,
      );
      expect(requestCount, 0);
    },
  );

  test('preserves the API error when the controlled detail route rejects a request', () async {
    final repository = ReportsRepository(
      AletheiaApiClient(
        MockClient(
          (_) async => http.Response(
            jsonEncode({'error': '报告不存在。'}),
            404,
            headers: const {'content-type': 'application/json; charset=utf-8'},
          ),
        ),
      ),
    );

    await expectLater(
      repository.loadNativeDetail(endpoint, 'rpt_01J8'),
      throwsA(
        isA<ApiException>()
            .having((error) => error.statusCode, 'statusCode', 404)
            .having((error) => error.message, 'message', '报告不存在。'),
      ),
    );
  });

  test(
    'keeps legacy index entries when one optional native summary is malformed',
    () async {
      final repository = ReportsRepository(
        AletheiaApiClient(
          MockClient(
            (_) async => http.Response(
              jsonEncode({
                'reports': [
                  {
                    'filename': 'legacy.html',
                    'size': 1,
                    'modified_at': '2026-09-23T10:30:00+08:00',
                    'native_report': {'schema_version': 99},
                  },
                ],
              }),
              200,
            ),
          ),
        ),
      );

      final reports = await repository.load(endpoint);

      expect(reports, hasLength(1));
      expect(reports.single.filename, 'legacy.html');
      expect(reports.single.nativeReport, isNull);
    },
  );
}

Map<String, dynamic> _nativeDetail({required String? cursor}) => {
  'report': {
    'schema_version': 1,
    'report_id': 'rpt_01J8',
    'kind': 'test',
    'title': '路径验证 · 第 3 次运行',
    'status': 'passed',
    'created_at': '2026-09-23T10:30:00+08:00',
    'duration_ms': 1000,
    'summary': {
      'total': 1,
      'passed': 1,
      'failed': 0,
      'blocked': 0,
      'pass_rate': 100,
    },
  },
  'items': const [],
  'next_cursor': cursor,
};
