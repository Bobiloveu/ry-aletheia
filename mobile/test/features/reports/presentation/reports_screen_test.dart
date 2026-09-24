import 'package:aletheia_mobile/app/theme/aletheia_theme.dart';
import 'package:aletheia_mobile/core/connection/robot_connection_controller.dart';
import 'package:aletheia_mobile/core/connection/robot_connection_state.dart';
import 'package:aletheia_mobile/core/connection/robot_endpoint.dart';
import 'package:aletheia_mobile/features/reports/application/reports_controller.dart';
import 'package:aletheia_mobile/features/reports/domain/aletheia_report.dart';
import 'package:aletheia_mobile/features/reports/presentation/reports_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

void main() {
  testWidgets(
    'renders native report facts and keeps a legacy report in migration state',
    (tester) async {
      await tester.pumpWidget(_testApp());
      await tester.pump();

      expect(find.text('路径验证 · 第 3 次运行'), findsOneWidget);
      expect(find.text('通过 10'), findsOneWidget);
      expect(find.text('异常 2'), findsOneWidget);
      expect(find.text('车端尚未提供原生报告数据'), findsOneWidget);
      expect(find.text('在浏览器打开'), findsNothing);
      expect(find.text('下载 HTML'), findsNothing);
      expect(find.text('下载 CSV'), findsNothing);
    },
  );

  testWidgets('opens only a native report into its app detail route', (
    tester,
  ) async {
    await tester.pumpWidget(_testApp());
    await tester.pump();

    await tester.tap(find.byKey(const ValueKey('native-report-rpt_01J8')));
    await tester.pumpAndSettle();

    expect(find.text('detail:rpt_01J8'), findsOneWidget);
  });
}

Widget _testApp() {
  final router = GoRouter(
    initialLocation: ReportsScreen.routePath,
    routes: [
      GoRoute(
        path: ReportsScreen.routePath,
        builder: (_, _) => const ReportsScreen(),
      ),
      GoRoute(
        path: '${ReportsScreen.routePath}/:reportId',
        builder: (_, state) =>
            Scaffold(body: Text('detail:${state.pathParameters['reportId']}')),
      ),
    ],
  );
  return ProviderScope(
    overrides: [
      robotConnectionControllerProvider.overrideWith(_ConnectedController.new),
      reportsProvider.overrideWith((_) async => _reports),
    ],
    child: MaterialApp.router(
      theme: AletheiaTheme.light(),
      routerConfig: router,
    ),
  );
}

class _ConnectedController extends RobotConnectionController {
  @override
  RobotConnectionState build() => RobotConnectionState(
    phase: ConnectionPhase.connected,
    endpoint: RobotEndpoint.parse('robot.local'),
  );
}

final _reports = [
  AletheiaReport(
    filename: 'validation.html',
    sizeBytes: 3584,
    modifiedAt: DateTime.parse('2026-09-23T10:30:00+08:00'),
    csvFilename: 'validation.csv',
    nativeReport: NativeReportSummary(
      reportId: 'rpt_01J8',
      kind: ReportKind.test,
      title: '路径验证 · 第 3 次运行',
      status: ReportStatus.failed,
      createdAt: DateTime.parse('2026-09-23T10:30:00+08:00'),
      duration: const Duration(minutes: 3, seconds: 4),
      summary: const NativeReportMetrics(
        total: 12,
        passed: 10,
        failed: 1,
        blocked: 1,
        passRate: 83.3,
      ),
      headline: '定位收敛超时。',
    ),
  ),
  AletheiaReport(
    filename: 'legacy.html',
    sizeBytes: 1,
    modifiedAt: DateTime.parse('2026-09-23T10:30:00+08:00'),
    csvFilename: null,
  ),
];
