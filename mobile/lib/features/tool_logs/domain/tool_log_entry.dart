enum ToolLogScope {
  all,
  errors;

  String get apiValue => switch (this) {
    ToolLogScope.all => 'all',
    ToolLogScope.errors => 'errors',
  };

  String get label => switch (this) {
    ToolLogScope.all => '全部',
    ToolLogScope.errors => '错误',
  };
}

enum ToolLogLevel {
  info,
  warning,
  error,
  critical,
  unknown;

  factory ToolLogLevel.fromWire(Object? value) => switch (value) {
    'INFO' => ToolLogLevel.info,
    'WARNING' => ToolLogLevel.warning,
    'ERROR' => ToolLogLevel.error,
    'CRITICAL' => ToolLogLevel.critical,
    _ => ToolLogLevel.unknown,
  };

  String get label => switch (this) {
    ToolLogLevel.info => '信息',
    ToolLogLevel.warning => '警告',
    ToolLogLevel.error => '错误',
    ToolLogLevel.critical => '严重错误',
    ToolLogLevel.unknown => '未知',
  };

  bool get isError =>
      this == ToolLogLevel.error || this == ToolLogLevel.critical;
}

class ToolLogEntry {
  const ToolLogEntry({
    required this.time,
    required this.level,
    required this.source,
    required this.message,
    required this.exception,
  });

  factory ToolLogEntry.fromJson(Map<String, dynamic> json) {
    return ToolLogEntry(
      time: json['time'] is String ? json['time'] as String : '未知时间',
      level: ToolLogLevel.fromWire(json['level']),
      source: json['source'] is String ? json['source'] as String : '系统',
      message: json['message'] is String
          ? json['message'] as String
          : '未提供日志内容。',
      exception: json['exception'] is String ? json['exception'] as String : '',
    );
  }

  final String time;
  final ToolLogLevel level;
  final String source;
  final String message;
  final String exception;
}

class DiagnosticFile {
  const DiagnosticFile({
    required this.name,
    required this.label,
    required this.detail,
    required this.sizeBytes,
    required this.modifiedAt,
  });

  factory DiagnosticFile.fromJson(Map<String, dynamic> json) => DiagnosticFile(
    name: json['name'] is String ? json['name'] as String : '',
    label: json['label'] is String ? json['label'] as String : '诊断文件',
    detail: json['detail'] is String ? json['detail'] as String : '',
    sizeBytes: json['size_bytes'] is num
        ? (json['size_bytes'] as num).toInt()
        : 0,
    modifiedAt: json['modified_at'] is num
        ? (json['modified_at'] as num).toInt()
        : 0,
  );
  final String name;
  final String label;
  final String detail;
  final int sizeBytes;
  final int modifiedAt;
  bool get isDownloadable =>
      name.isNotEmpty && !name.contains('/') && !name.contains('..');
  String get sizeLabel => sizeBytes < 1024
      ? '$sizeBytes B'
      : sizeBytes < 1024 * 1024
      ? '${(sizeBytes / 1024).toStringAsFixed(1)} KiB'
      : '${(sizeBytes / 1024 / 1024).toStringAsFixed(2)} MiB';
}
