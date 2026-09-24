enum ReportStatus { passed, failed, blocked, cancelled, incomplete, unknown }

enum ReportKind { test, acceptance, unknown }

class AletheiaReport {
  const AletheiaReport({
    required this.filename,
    required this.sizeBytes,
    required this.modifiedAt,
    required this.csvFilename,
    this.reportType,
    this.title,
    this.nativeReport,
  });

  factory AletheiaReport.fromJson(Map<String, dynamic> json) {
    return AletheiaReport(
      filename: json['filename'] is String ? json['filename'] as String : '',
      sizeBytes: _nonNegativeInt(json['size']) ?? 0,
      modifiedAt: _dateTimeOrNull(json['modified_at']),
      csvFilename: json['csv_filename'] is String
          ? json['csv_filename'] as String
          : null,
      reportType: _reportKindOrNull(json['report_type']),
      title: _boundedTextOrNull(json['title'], maxLength: 200),
      nativeReport: NativeReportSummary.tryFromJson(json['native_report']),
    );
  }

  final String filename;
  final int sizeBytes;
  final DateTime? modifiedAt;
  final String? csvFilename;
  final ReportKind? reportType;
  final String? title;
  final NativeReportSummary? nativeReport;

  /// The reports index is supplied by the car console. Keep its filename
  /// confined to the report-files endpoint even if that response is malformed.
  bool get isOpenableHtml =>
      filename.toLowerCase().endsWith('.html') &&
      !filename.contains('/') &&
      !filename.contains('\\') &&
      !filename.contains('..') &&
      !filename.contains('\u0000');

  String get sizeLabel {
    if (sizeBytes < 1024) {
      return '$sizeBytes B';
    }
    if (sizeBytes < 1024 * 1024) {
      return '${(sizeBytes / 1024).toStringAsFixed(1)} KiB';
    }
    return '${(sizeBytes / (1024 * 1024)).toStringAsFixed(2)} MiB';
  }

  String get modifiedLabel {
    final value = modifiedAt?.toLocal();
    if (value == null) {
      return '生成时间未知';
    }
    String two(int input) => input.toString().padLeft(2, '0');
    return '${value.year}-${two(value.month)}-${two(value.day)} '
        '${two(value.hour)}:${two(value.minute)}';
  }
}

class NativeReportSummary {
  const NativeReportSummary({
    required this.reportId,
    required this.kind,
    required this.title,
    required this.status,
    required this.createdAt,
    required this.duration,
    required this.summary,
    this.headline,
  });

  static NativeReportSummary? tryFromJson(Object? value) {
    if (value is! Map) return null;
    final json = value.map((key, item) => MapEntry(key.toString(), item));
    if (json['schema_version'] != 1) return null;

    final reportId = _safeIdentifier(json['report_id']);
    final kind = _reportKindOrNull(json['kind']);
    final status = _knownReportStatusOrNull(json['status']);
    final title = _boundedTextOrNull(json['title'], maxLength: 200);
    final createdAt = _dateTimeOrNull(json['created_at']);
    final duration = _nonNegativeInt(json['duration_ms']);
    final summary = NativeReportMetrics.tryFromJson(json['summary']);
    final headline = _optionalBoundedText(json['headline'], maxLength: 400);

    if (reportId == null ||
        kind == null ||
        status == null ||
        title == null ||
        createdAt == null ||
        duration == null ||
        summary == null ||
        headline.isInvalid) {
      return null;
    }

    return NativeReportSummary(
      reportId: reportId,
      kind: kind,
      title: title,
      status: status,
      createdAt: createdAt,
      duration: Duration(milliseconds: duration),
      summary: summary,
      headline: headline.value,
    );
  }

  final String reportId;
  final ReportKind kind;
  final String title;
  final ReportStatus status;
  final DateTime createdAt;
  final Duration duration;
  final NativeReportMetrics summary;
  final String? headline;
}

class NativeReportMetrics {
  const NativeReportMetrics({
    required this.total,
    required this.passed,
    required this.failed,
    required this.blocked,
    required this.passRate,
  });

  static NativeReportMetrics? tryFromJson(Object? value) {
    if (value is! Map) return null;
    final json = value.map((key, item) => MapEntry(key.toString(), item));
    final total = _nonNegativeInt(json['total']);
    final passed = _nonNegativeInt(json['passed']);
    final failed = _nonNegativeInt(json['failed']);
    final blocked = _nonNegativeInt(json['blocked']);
    final passRate = _percentageOrNull(json['pass_rate']);
    if (total == null ||
        passed == null ||
        failed == null ||
        blocked == null ||
        passRate == null ||
        passed + failed + blocked > total) {
      return null;
    }
    return NativeReportMetrics(
      total: total,
      passed: passed,
      failed: failed,
      blocked: blocked,
      passRate: passRate,
    );
  }

  final int total;
  final int passed;
  final int failed;
  final int blocked;
  final double passRate;

  int get exceptionCount => failed + blocked;
}

class NativeReportDetailPage {
  const NativeReportDetailPage({
    required this.report,
    required this.items,
    required this.nextCursor,
  });

  factory NativeReportDetailPage.fromJson(Map<String, dynamic> json) {
    final report = NativeReportSummary.tryFromJson(json['report']);
    final rawItems = json['items'];
    final nextCursor = _optionalCursor(json['next_cursor']);
    if (report == null || rawItems is! List || nextCursor.isInvalid) {
      throw const FormatException('原生测试报告数据不完整。');
    }

    final items = rawItems
        .whereType<Map>()
        .map(
          (item) => NativeReportItem.tryFromJson(
            item.map((key, value) => MapEntry(key.toString(), value)),
          ),
        )
        .whereType<NativeReportItem>()
        .toList(growable: false);
    if (items.length != rawItems.length) {
      throw const FormatException('原生测试报告任务数据不完整。');
    }
    return NativeReportDetailPage(
      report: report,
      items: items,
      nextCursor: nextCursor.value,
    );
  }

  final NativeReportSummary report;
  final List<NativeReportItem> items;
  final String? nextCursor;
}

class NativeReportItem {
  const NativeReportItem({
    required this.itemId,
    required this.title,
    required this.status,
    required this.duration,
    this.summary,
    this.detail,
  });

  static NativeReportItem? tryFromJson(Map<String, dynamic> json) {
    final itemId = _safeIdentifier(json['item_id']);
    final title = _boundedTextOrNull(json['title'], maxLength: 200);
    final duration = _nonNegativeInt(json['duration_ms']);
    final summary = _optionalBoundedText(json['summary'], maxLength: 500);
    final detail = _optionalBoundedText(json['detail'], maxLength: 2000);
    if (itemId == null ||
        title == null ||
        duration == null ||
        summary.isInvalid ||
        detail.isInvalid) {
      return null;
    }
    return NativeReportItem(
      itemId: itemId,
      title: title,
      status: _reportStatusOrUnknown(json['status']),
      duration: Duration(milliseconds: duration),
      summary: summary.value,
      detail: detail.value,
    );
  }

  final String itemId;
  final String title;
  final ReportStatus status;
  final Duration duration;
  final String? summary;
  final String? detail;
}

final _identifierExpression = RegExp(r'^[A-Za-z0-9_-]{1,128}$');
final _iso8601WithTimezoneExpression = RegExp(
  r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$',
);
final _controlCharacterExpression = RegExp(r'[\u0000-\u001F\u007F]');

String? _safeIdentifier(Object? value) {
  if (value is! String || !_identifierExpression.hasMatch(value)) return null;
  return value;
}

ReportKind? _reportKindOrNull(Object? value) => switch (value) {
  'test' => ReportKind.test,
  'acceptance' => ReportKind.acceptance,
  _ => null,
};

ReportStatus? _knownReportStatusOrNull(Object? value) => switch (value) {
  'passed' => ReportStatus.passed,
  'failed' => ReportStatus.failed,
  'blocked' => ReportStatus.blocked,
  'cancelled' => ReportStatus.cancelled,
  'incomplete' => ReportStatus.incomplete,
  'unknown' => ReportStatus.unknown,
  _ => null,
};

ReportStatus _reportStatusOrUnknown(Object? value) =>
    _knownReportStatusOrNull(value) ?? ReportStatus.unknown;

DateTime? _dateTimeOrNull(Object? value) {
  if (value is! String || !_iso8601WithTimezoneExpression.hasMatch(value)) {
    return null;
  }
  return DateTime.tryParse(value);
}

int? _nonNegativeInt(Object? value) {
  if (value is! num ||
      !value.isFinite ||
      value < 0 ||
      value != value.truncate()) {
    return null;
  }
  return value.toInt();
}

double? _percentageOrNull(Object? value) {
  if (value is! num || !value.isFinite || value < 0 || value > 100) return null;
  return value.toDouble();
}

String? _boundedTextOrNull(Object? value, {required int maxLength}) {
  if (value is! String || value.trim().isEmpty || value.length > maxLength) {
    return null;
  }
  if (_controlCharacterExpression.hasMatch(value)) return null;
  return value;
}

_OptionalString _optionalBoundedText(Object? value, {required int maxLength}) {
  if (value == null) return const _OptionalString();
  final text = _boundedTextOrNull(value, maxLength: maxLength);
  return _OptionalString(value: text, isInvalid: text == null);
}

_OptionalString _optionalCursor(Object? value) {
  if (value == null) return const _OptionalString();
  if (value is! String ||
      value.isEmpty ||
      value.length > 512 ||
      _controlCharacterExpression.hasMatch(value)) {
    return const _OptionalString(isInvalid: true);
  }
  return _OptionalString(value: value);
}

class _OptionalString {
  const _OptionalString({this.value, this.isInvalid = false});

  final String? value;
  final bool isInvalid;
}
