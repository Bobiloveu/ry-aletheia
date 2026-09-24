import 'package:aletheia_mobile/features/reports/domain/aletheia_report.dart';
import 'package:test/test.dart';

void main() {
  test('accepts a complete version one native report summary', () {
    final report = AletheiaReport.fromJson({
      'filename': 'validation_20260923.html',
      'size': 3584,
      'modified_at': '2026-09-23T10:30:00+08:00',
      'native_report': {
        'schema_version': 1,
        'report_id': 'rpt_01J8',
        'kind': 'test',
        'title': '路径验证 · 第 3 次运行',
        'status': 'failed',
        'created_at': '2026-09-23T10:30:00+08:00',
        'duration_ms': 184000,
        'summary': {
          'total': 12,
          'passed': 10,
          'failed': 1,
          'blocked': 1,
          'pass_rate': 83.3,
        },
        'headline': '定位收敛超时。',
      },
    });

    expect(report.nativeReport, isNotNull);
    expect(report.nativeReport!.reportId, 'rpt_01J8');
    expect(report.nativeReport!.status, ReportStatus.failed);
    expect(report.nativeReport!.kind, ReportKind.test);
    expect(report.nativeReport!.summary.exceptionCount, 2);
  });

  test(
    'rejects an unsafe or internally inconsistent native report summary',
    () {
      for (final nativeReport in [
        {
          'schema_version': 2,
          'report_id': 'rpt_01J8',
          'kind': 'test',
          'title': '版本不支持',
          'status': 'passed',
          'created_at': '2026-09-23T10:30:00+08:00',
          'duration_ms': 1,
          'summary': {
            'total': 1,
            'passed': 1,
            'failed': 0,
            'blocked': 0,
            'pass_rate': 100,
          },
        },
        {
          'schema_version': 1,
          'report_id': '../unsafe',
          'kind': 'test',
          'title': '不安全标识',
          'status': 'passed',
          'created_at': '2026-09-23T10:30:00+08:00',
          'duration_ms': 1,
          'summary': {
            'total': 1,
            'passed': 1,
            'failed': 0,
            'blocked': 0,
            'pass_rate': 100,
          },
        },
        {
          'schema_version': 1,
          'report_id': 'rpt_01J8',
          'kind': 'test',
          'title': '未知状态',
          'status': 'running',
          'created_at': '2026-09-23T10:30:00+08:00',
          'duration_ms': 1,
          'summary': {
            'total': 1,
            'passed': 1,
            'failed': 0,
            'blocked': 0,
            'pass_rate': 100,
          },
        },
        {
          'schema_version': 1,
          'report_id': 'rpt_01J8',
          'kind': 'test',
          'title': '计数越界',
          'status': 'failed',
          'created_at': '2026-09-23T10:30:00+08:00',
          'duration_ms': -1,
          'summary': {
            'total': 1,
            'passed': 1,
            'failed': 1,
            'blocked': 0,
            'pass_rate': 100,
          },
        },
      ]) {
        final report = AletheiaReport.fromJson({'native_report': nativeReport});
        expect(report.nativeReport, isNull, reason: '$nativeReport');
      }
    },
  );

  test(
    'keeps an unknown future item status readable and terminal cursor null',
    () {
      final page = NativeReportDetailPage.fromJson({
        'report': {
          'schema_version': 1,
          'report_id': 'rpt_01J8',
          'kind': 'test',
          'title': '路径验证 · 第 3 次运行',
          'status': 'failed',
          'created_at': '2026-09-23T10:30:00+08:00',
          'duration_ms': 184000,
          'summary': {
            'total': 1,
            'passed': 0,
            'failed': 1,
            'blocked': 0,
            'pass_rate': 0,
          },
        },
        'items': [
          {
            'item_id': 'task_01',
            'title': '兼容未来状态',
            'status': 'future_state',
            'duration_ms': 180,
            'summary': '服务端给出了新状态。',
            'detail': '客户端应安全保留该任务。',
          },
        ],
        'next_cursor': null,
      });

      expect(page.nextCursor, isNull);
      expect(page.items, hasLength(1));
      expect(page.items.single.status, ReportStatus.unknown);
    },
  );
}
