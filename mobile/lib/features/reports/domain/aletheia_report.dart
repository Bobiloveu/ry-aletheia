class AletheiaReport {
  const AletheiaReport({
    required this.filename,
    required this.sizeBytes,
    required this.modifiedAt,
    required this.csvFilename,
  });

  factory AletheiaReport.fromJson(Map<String, dynamic> json) {
    return AletheiaReport(
      filename: json['filename'] is String ? json['filename'] as String : '',
      sizeBytes: json['size'] is num ? (json['size'] as num).toInt() : 0,
      modifiedAt: json['modified_at'] is String
          ? DateTime.tryParse(json['modified_at'] as String)
          : null,
      csvFilename: json['csv_filename'] is String
          ? json['csv_filename'] as String
          : null,
    );
  }

  final String filename;
  final int sizeBytes;
  final DateTime? modifiedAt;
  final String? csvFilename;

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
