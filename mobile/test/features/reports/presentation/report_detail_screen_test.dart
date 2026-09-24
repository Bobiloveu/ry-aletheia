import 'package:aletheia_mobile/app/theme/aletheia_theme.dart';
import 'package:aletheia_mobile/core/connection/robot_connection_controller.dart';
import 'package:aletheia_mobile/core/connection/robot_connection_state.dart';
import 'package:aletheia_mobile/core/connection/robot_endpoint.dart';
import 'package:aletheia_mobile/core/network/aletheia_api_client.dart';
import 'package:aletheia_mobile/features/reports/application/reports_controller.dart';
import 'package:aletheia_mobile/features/reports/data/reports_repository.dart';
import 'package:aletheia_mobile/features/reports/domain/aletheia_report.dart';
import 'package:aletheia_mobile/features/reports/presentation/report_detail_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';

void main() {
  testWidgets(
    'shows the native conclusion, metrics and exception-first task list',
    (tester) async {
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            robotConnectionControllerProvider.overrideWith(
              _ConnectedController.new,
            ),
            reportsRepositoryProvider.overrideWithValue(
              _FakeReportsRepository(),
            ),
          ],
          child: MaterialApp(
            theme: AletheiaTheme.light(),
            home: const ReportDetailScreen(reportId: 'rpt_01J8'),
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('定位收敛超时。'), findsOneWidget);
      expect(find.text('任务'), findsOneWidget);
      expect(find.text('通过'), findsOneWidget);
      expect(find.text('异常'), findsOneWidget);
      expect(find.text('2'), findsOneWidget);
      expect(find.text('定位检查'), findsOneWidget);
      expect(find.text('全部任务'), findsOneWidget);
    },
  );

  testWidgets('keeps raw native-detail errors out of the operator UI', (
    tester,
  ) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          robotConnectionControllerProvider.overrideWith(
            _ConnectedController.new,
          ),
          reportsRepositoryProvider.overrideWithValue(
            _FailingReportsRepository(),
          ),
        ],
        child: MaterialApp(
          theme: AletheiaTheme.light(),
          home: const ReportDetailScreen(reportId: 'rpt_01J8'),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('无法读取原生测试报告'), findsOneWidget);
    expect(find.text('车端暂时未返回原生报告详情，请检查连接后重试。'), findsOneWidget);
    expect(find.textContaining('Bad state:'), findsNothing);
  });
}

class _ConnectedController extends RobotConnectionController {
  @override
  RobotConnectionState build() => RobotConnectionState(
    phase: ConnectionPhase.connected,
    endpoint: RobotEndpoint.parse('robot.local'),
  );
}

class _FakeReportsRepository extends ReportsRepository {
  _FakeReportsRepository()
    : super(
        AletheiaApiClient(
          MockClient((_) async => throw StateError('unexpected HTTP request')),
        ),
      );

  @override
  Future<NativeReportDetailPage> loadNativeDetail(
    RobotEndpoint endpoint,
    String reportId, {
    String? cursor,
    int limit = 50,
  }) async => NativeReportDetailPage(
    report: NativeReportSummary(
      reportId: 'rpt_01J8',
      kind: ReportKind.test,
      title: '路径验证 · 第 3 次运行',
      status: ReportStatus.failed,
      createdAt: DateTime.parse('2026-09-23T10:30:00+08:00'),
      duration: const Duration(minutes: 3, seconds: 4),
      summary: const NativeReportMetrics(
        total: 2,
        passed: 1,
        failed: 1,
        blocked: 0,
        passRate: 50,
      ),
      headline: '定位收敛超时。',
    ),
    items: const [
      NativeReportItem(
        itemId: 'task_failure',
        title: '定位检查',
        status: ReportStatus.failed,
        duration: Duration(seconds: 90),
        summary: '定位未在阈值内收敛。',
      ),
      NativeReportItem(
        itemId: 'task_passed',
        title: '到达目标点',
        status: ReportStatus.passed,
        duration: Duration(seconds: 60),
      ),
    ],
    nextCursor: null,
  );
}

class _FailingReportsRepository extends ReportsRepository {
  _FailingReportsRepository()
    : super(
        AletheiaApiClient(
          MockClient((_) async => throw StateError('unexpected HTTP request')),
        ),
      );

  @override
  Future<NativeReportDetailPage> loadNativeDetail(
    RobotEndpoint endpoint,
    String reportId, {
    String? cursor,
    int limit = 50,
  }) async => throw StateError('Bad state: raw vehicle diagnostic');
}
