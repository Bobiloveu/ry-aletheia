class AletheiaTestCase {
  const AletheiaTestCase({
    required this.id,
    required this.filename,
    required this.name,
    required this.alias,
    required this.parameters,
    required this.management,
  });

  factory AletheiaTestCase.fromJson(Map<String, dynamic> json) {
    return AletheiaTestCase(
      id: _string(json['id']),
      filename: _string(json['filename']),
      name: _string(json['name']),
      alias: _string(json['alias']),
      parameters: TestCaseParameters.fromJson(_map(json['parameters'])),
      management: TestCaseManagement.fromJson(_map(json['management'])),
    );
  }

  final String id;
  final String filename;
  final String name;
  final String alias;
  final TestCaseParameters parameters;
  final TestCaseManagement management;

  String get displayName => alias.isNotEmpty ? alias : name;

  static String _string(Object? value) => value is String ? value : '';

  static Map<String, dynamic> _map(Object? value) => value is Map
      ? value.map((key, item) => MapEntry(key.toString(), item))
      : const {};
}

class TestCaseParameters {
  const TestCaseParameters({
    required this.community,
    required this.building,
    required this.unit,
    required this.floor,
    required this.door,
  });

  factory TestCaseParameters.fromJson(Map<String, dynamic> json) {
    return TestCaseParameters(
      community: json['community'] is String ? json['community'] as String : '',
      building: _integer(json['building']),
      unit: _integer(json['unit']),
      floor: _integer(json['floor']),
      door: _integer(json['door']),
    );
  }

  final String community;
  final int? building;
  final int? unit;
  final int? floor;
  final int? door;

  String get locationLabel {
    final buildingText = building == null ? '—' : '$building栋';
    final unitText = unit == null ? '—' : '$unit单元';
    final floorText = floor == null ? '—' : '$floor层';
    final doorText = door == null ? '—' : '$door室';
    return [
      community,
      buildingText,
      unitText,
      floorText,
      doorText,
    ].where((item) => item.isNotEmpty).join(' · ');
  }

  static int? _integer(Object? value) => value is num ? value.toInt() : null;
}

class TestCaseManagement {
  const TestCaseManagement({
    required this.lifecycle,
    required this.version,
    required this.summary,
    required this.tags,
  });

  factory TestCaseManagement.fromJson(Map<String, dynamic> json) {
    return TestCaseManagement(
      lifecycle: json['lifecycle'] is String
          ? json['lifecycle'] as String
          : 'draft',
      version: json['version'] is String ? json['version'] as String : '0.1.0',
      summary: json['summary'] is String ? json['summary'] as String : '',
      tags: (json['tags'] as List<Object?>? ?? const [])
          .whereType<String>()
          .toList(growable: false),
    );
  }

  final String lifecycle;
  final String version;
  final String summary;
  final List<String> tags;
}
