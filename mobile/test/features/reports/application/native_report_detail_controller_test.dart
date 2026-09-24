import 'package:aletheia_mobile/core/connection/robot_connection_controller.dart';
import 'package:aletheia_mobile/core/connection/robot_connection_state.dart';
import 'package:aletheia_mobile/core/connection/robot_endpoint.dart';
import 'package:aletheia_mobile/core/network/aletheia_api_client.dart';
import 'package:aletheia_mobile/core/network/api_exception.dart';
import 'package:aletheia_mobile/features/reports/application/reports_controller.dart';
import 'package:aletheia_mobile/features/reports/data/reports_repository.dart';
import 'package:aletheia_mobile/features/reports/domain/aletheia_report.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http/testing.dart';
import 'package:test/test.dart';

void main() {
  test('appends the next server page after the existing task order', () async {
    final repository = _FakeReportsRepository()
      ..pages.addAll([
        _page(items: [_item('task_1')], nextCursor: 'cursor_1'),
        _page(items: [_item('task_2')]),
      ]);
    final container = _container(repository);
    addTearDown(container.dispose);

    final initial = await container.read(
      nativeReportDetailProvider('rpt_01J8').future,
    );
    expect(initial.items.map((item) => item.itemId), ['task_1']);

    await container
        .read(nativeReportDetailProvider('rpt_01J8').notifier)
        .loadNextPage();

    final state = container.read(nativeReportDetailProvider('rpt_01J8')).value!;
    expect(state.items.map((item) => item.itemId), ['task_1', 'task_2']);
    expect(repository.cursors, [null, 'cursor_1']);
    expect(state.nextCursor, isNull);
  });

  test(
    'keeps visible tasks and a retryable cursor when append fails',
    () async {
      final repository = _FakeReportsRepository()
        ..pages.add(_page(items: [_item('task_1')], nextCursor: 'cursor_1'))
        ..nextError = const ApiException('分页请求失败。');
      final container = _container(repository);
      addTearDown(container.dispose);

      await container.read(nativeReportDetailProvider('rpt_01J8').future);
      await container
          .read(nativeReportDetailProvider('rpt_01J8').notifier)
          .loadNextPage();

      final state = container
          .read(nativeReportDetailProvider('rpt_01J8'))
          .value!;
      expect(state.items.map((item) => item.itemId), ['task_1']);
      expect(state.nextCursor, 'cursor_1');
      expect(state.loadMoreError, isA<ApiException>());
      expect(state.isLoadingMore, isFalse);
    },
  );
}

ProviderContainer _container(_FakeReportsRepository repository) =>
    ProviderContainer(
      overrides: [
        robotConnectionControllerProvider.overrideWith(
          _ConnectedController.new,
        ),
        reportsRepositoryProvider.overrideWithValue(repository),
      ],
    );

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

  final pages = <NativeReportDetailPage>[];
  final cursors = <String?>[];
  ApiException? nextError;

  @override
  Future<NativeReportDetailPage> loadNativeDetail(
    RobotEndpoint endpoint,
    String reportId, {
    String? cursor,
    int limit = 50,
  }) async {
    cursors.add(cursor);
    final error = nextError;
    if (error != null && cursor != null) {
      throw error;
    }
    return pages.removeAt(0);
  }
}

NativeReportDetailPage _page({
  required List<NativeReportItem> items,
  String? nextCursor,
}) => NativeReportDetailPage(
  report: NativeReportSummary(
    reportId: 'rpt_01J8',
    kind: ReportKind.test,
    title: '路径验证',
    status: ReportStatus.failed,
    createdAt: DateTime.parse('2026-09-23T10:30:00+08:00'),
    duration: const Duration(seconds: 10),
    summary: const NativeReportMetrics(
      total: 2,
      passed: 1,
      failed: 1,
      blocked: 0,
      passRate: 50,
    ),
  ),
  items: items,
  nextCursor: nextCursor,
);

NativeReportItem _item(String id) => NativeReportItem(
  itemId: id,
  title: id,
  status: ReportStatus.passed,
  duration: const Duration(seconds: 1),
);
