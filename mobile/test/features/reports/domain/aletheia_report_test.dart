import 'package:aletheia_mobile/features/reports/domain/aletheia_report.dart';
import 'package:test/test.dart';

void main() {
  test('decodes the read-only report index returned by the console', () {
    final report = AletheiaReport.fromJson({
      'filename': 'validation_5f1e2d3c4b5a.html',
      'size': 3584,
      'modified_at': '2026-08-27T10:12:00+08:00',
      'csv_filename': 'validation_5f1e2d3c4b5a.csv',
    });

    expect(report.filename, 'validation_5f1e2d3c4b5a.html');
    expect(report.sizeBytes, 3584);
    expect(report.sizeLabel, '3.5 KiB');
    expect(report.modifiedAt, isNotNull);
    expect(report.csvFilename, 'validation_5f1e2d3c4b5a.csv');
    expect(report.isOpenableHtml, isTrue);
  });

  test('keeps malformed report metadata displayable', () {
    final report = AletheiaReport.fromJson({
      'filename': null,
      'size': 'unknown',
      'modified_at': 'invalid',
      'csv_filename': false,
    });

    expect(report.filename, isEmpty);
    expect(report.sizeBytes, 0);
    expect(report.sizeLabel, '0 B');
    expect(report.modifiedLabel, '生成时间未知');
    expect(report.csvFilename, isNull);
    expect(report.isOpenableHtml, isFalse);
  });

  test('does not turn malformed report names into external browser paths', () {
    for (final filename in [
      '../report.html',
      'reports/report.html',
      r'reports\\report.html',
      'report.html?download=true',
      'report.csv',
      'report..html',
    ]) {
      final report = AletheiaReport.fromJson({'filename': filename});
      expect(report.isOpenableHtml, isFalse, reason: filename);
    }
  });
}
