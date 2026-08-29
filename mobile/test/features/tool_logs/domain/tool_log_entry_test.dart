import 'package:aletheia_mobile/features/tool_logs/domain/tool_log_entry.dart';
import 'package:test/test.dart';

void main() {
  test('decodes the constrained console event contract', () {
    final entry = ToolLogEntry.fromJson({
      'time': '2026-08-27 10:12:00',
      'level': 'ERROR',
      'source': 'observation',
      'message': '遥测网关未就绪',
      'exception': 'stack trace',
    });

    expect(entry.time, '2026-08-27 10:12:00');
    expect(entry.level, ToolLogLevel.error);
    expect(entry.level.label, '错误');
    expect(entry.level.isError, isTrue);
    expect(entry.source, 'observation');
    expect(entry.exception, 'stack trace');
  });

  test('keeps malformed optional fields diagnosable without crashing', () {
    final entry = ToolLogEntry.fromJson({
      'level': 'NEW_LEVEL',
      'time': 42,
      'source': false,
      'message': null,
      'exception': 12,
    });

    expect(entry.level, ToolLogLevel.unknown);
    expect(entry.level.isError, isFalse);
    expect(entry.time, '未知时间');
    expect(entry.source, '系统');
    expect(entry.message, '未提供日志内容。');
    expect(entry.exception, isEmpty);
  });

  test('maps each supported server scope directly', () {
    expect(ToolLogScope.all.apiValue, 'all');
    expect(ToolLogScope.errors.apiValue, 'errors');
  });
}
