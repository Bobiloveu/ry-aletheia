enum NativeTrajectoryAvailability { available, incomplete, unavailable }

enum NativeTrajectoryPathKind { actual, ideal }

class NativeReportTrajectoryRef {
  const NativeReportTrajectoryRef({
    required this.trajectoryId,
    required this.label,
    required this.availability,
    required this.sampleCount,
    this.integrityWarning,
  });

  static NativeReportTrajectoryRef? tryFromJson(Object? value) {
    final json = _map(value);
    if (json == null) return null;
    final trajectoryId = _safeIdentifier(json['trajectory_id']);
    final label = _boundedText(json['label'], maxLength: 200);
    final availability = _availability(json['status']);
    final sampleCount = _nonNegativeInt(json['sample_count']);
    final integrityWarning = _optionalText(
      json['integrity_warning'],
      maxLength: 500,
    );
    if (trajectoryId == null ||
        label == null ||
        availability == null ||
        sampleCount == null ||
        integrityWarning.isInvalid) {
      return null;
    }
    return NativeReportTrajectoryRef(
      trajectoryId: trajectoryId,
      label: label,
      availability: availability,
      sampleCount: sampleCount,
      integrityWarning: integrityWarning.value,
    );
  }

  final String trajectoryId;
  final String label;
  final NativeTrajectoryAvailability availability;
  final int sampleCount;
  final String? integrityWarning;
}

class NativeTrajectoryMap {
  const NativeTrajectoryMap({
    required this.label,
    required this.resolutionM,
    required this.widthCells,
    required this.heightCells,
    required this.originXM,
    required this.originYM,
  });

  static NativeTrajectoryMap? tryFromJson(Object? value) {
    final json = _map(value);
    if (json == null) return null;
    final label = _boundedText(json['label'], maxLength: 200);
    final resolutionM = _positiveFinite(json['resolution_m']);
    final widthCells = _positiveInt(json['width_cells']);
    final heightCells = _positiveInt(json['height_cells']);
    final originXM = _finiteDouble(json['origin_x_m']);
    final originYM = _finiteDouble(json['origin_y_m']);
    if (label == null ||
        resolutionM == null ||
        widthCells == null ||
        heightCells == null ||
        originXM == null ||
        originYM == null) {
      return null;
    }
    return NativeTrajectoryMap(
      label: label,
      resolutionM: resolutionM,
      widthCells: widthCells,
      heightCells: heightCells,
      originXM: originXM,
      originYM: originYM,
    );
  }

  final String label;
  final double resolutionM;
  final int widthCells;
  final int heightCells;
  final double originXM;
  final double originYM;
}

class NativeTrajectoryPoint {
  const NativeTrajectoryPoint({required this.xM, required this.yM});

  static NativeTrajectoryPoint? tryFromJson(Object? value) {
    final json = _map(value);
    if (json == null) return null;
    final xM = _finiteDouble(json['x_m']);
    final yM = _finiteDouble(json['y_m']);
    if (xM == null || yM == null) return null;
    return NativeTrajectoryPoint(xM: xM, yM: yM);
  }

  final double xM;
  final double yM;
}

class NativeTrajectoryPath {
  const NativeTrajectoryPath({
    required this.routeName,
    required this.kind,
    required this.points,
  });

  static NativeTrajectoryPath? tryFromJson(Object? value) {
    final json = _map(value);
    if (json == null) return null;
    final routeName = _boundedText(json['route_name'], maxLength: 200);
    final kind = switch (json['kind']) {
      'actual' => NativeTrajectoryPathKind.actual,
      'ideal' => NativeTrajectoryPathKind.ideal,
      _ => null,
    };
    final rawPoints = json['points'];
    if (routeName == null || kind == null || rawPoints is! List) return null;
    if (rawPoints.isEmpty || rawPoints.length > 2000) return null;
    final points = rawPoints
        .map(NativeTrajectoryPoint.tryFromJson)
        .whereType<NativeTrajectoryPoint>()
        .toList(growable: false);
    if (points.length != rawPoints.length) return null;
    return NativeTrajectoryPath(
      routeName: routeName,
      kind: kind,
      points: points,
    );
  }

  final String routeName;
  final NativeTrajectoryPathKind kind;
  final List<NativeTrajectoryPoint> points;
}

class NativeTrajectorySample extends NativeTrajectoryPoint {
  const NativeTrajectorySample({
    required super.xM,
    required super.yM,
    required this.timestampNs,
    required this.routeName,
    required this.sampleIndex,
  });

  static NativeTrajectorySample? tryFromJson(Object? value) {
    final json = _map(value);
    final point = NativeTrajectoryPoint.tryFromJson(value);
    final timestampNs = json == null
        ? null
        : _nonNegativeInt(json['timestamp_ns']);
    final routeName = json == null
        ? null
        : _boundedText(json['route_name'], maxLength: 200);
    final sampleIndex = json == null
        ? null
        : _nonNegativeInt(json['sample_index']);
    if (point == null ||
        timestampNs == null ||
        routeName == null ||
        sampleIndex == null) {
      return null;
    }
    return NativeTrajectorySample(
      xM: point.xM,
      yM: point.yM,
      timestampNs: timestampNs,
      routeName: routeName,
      sampleIndex: sampleIndex,
    );
  }

  final int timestampNs;
  final String routeName;
  final int sampleIndex;
}

class NativeReportTrajectory {
  const NativeReportTrajectory({
    required this.trajectoryId,
    required this.itemId,
    required this.label,
    required this.map,
    required this.displayPaths,
    required this.virtualWalls,
    required this.sampleCount,
    this.integrityWarning,
    this.samplesNextCursor,
  });

  factory NativeReportTrajectory.fromJson(Map<String, dynamic> json) {
    final trajectory = tryFromJson(json);
    if (trajectory == null) {
      throw const FormatException('原生报告轨迹数据不完整。');
    }
    return trajectory;
  }

  static NativeReportTrajectory? tryFromJson(Object? value) {
    final json = _map(value);
    if (json == null || json['schema_version'] != 1) return null;
    final trajectoryId = _safeIdentifier(json['trajectory_id']);
    final itemId = _safeIdentifier(json['item_id']);
    final label = _boundedText(json['label'], maxLength: 200);
    final map = NativeTrajectoryMap.tryFromJson(json['map']);
    final displayPaths = _paths(json['display_paths']);
    final virtualWalls = _walls(json['virtual_walls']);
    final sampleCount = _nonNegativeInt(json['sample_count']);
    final integrityWarning = _optionalText(
      json['integrity_warning'],
      maxLength: 500,
    );
    final nextCursor = _optionalCursor(json['samples_next_cursor']);
    if (trajectoryId == null ||
        itemId == null ||
        label == null ||
        map == null ||
        displayPaths == null ||
        virtualWalls == null ||
        sampleCount == null ||
        integrityWarning.isInvalid ||
        nextCursor.isInvalid) {
      return null;
    }
    return NativeReportTrajectory(
      trajectoryId: trajectoryId,
      itemId: itemId,
      label: label,
      map: map,
      displayPaths: displayPaths,
      virtualWalls: virtualWalls,
      sampleCount: sampleCount,
      integrityWarning: integrityWarning.value,
      samplesNextCursor: nextCursor.value,
    );
  }

  final String trajectoryId;
  final String itemId;
  final String label;
  final NativeTrajectoryMap map;
  final List<NativeTrajectoryPath> displayPaths;
  final List<List<NativeTrajectoryPoint>> virtualWalls;
  final int sampleCount;
  final String? integrityWarning;
  final String? samplesNextCursor;
}

class NativeTrajectorySamplePage {
  const NativeTrajectorySamplePage({
    required this.samples,
    required this.nextCursor,
  });

  factory NativeTrajectorySamplePage.fromJson(Map<String, dynamic> json) {
    final rawSamples = json['samples'];
    final nextCursor = _optionalCursor(json['next_cursor']);
    if (rawSamples is! List || nextCursor.isInvalid) {
      throw const FormatException('原生轨迹样本数据不完整。');
    }
    final samples = rawSamples
        .map(NativeTrajectorySample.tryFromJson)
        .whereType<NativeTrajectorySample>()
        .toList(growable: false);
    if (samples.length != rawSamples.length || !_strictlyIncreasing(samples)) {
      throw const FormatException('原生轨迹样本顺序无效。');
    }
    return NativeTrajectorySamplePage(
      samples: samples,
      nextCursor: nextCursor.value,
    );
  }

  final List<NativeTrajectorySample> samples;
  final String? nextCursor;
}

final _identifierExpression = RegExp(r'^[A-Za-z0-9_-]{1,128}$');
final _controlCharacterExpression = RegExp(r'[\u0000-\u001F\u007F]');

Map<String, dynamic>? _map(Object? value) {
  if (value is! Map) return null;
  return value.map((key, item) => MapEntry(key.toString(), item));
}

String? _safeIdentifier(Object? value) =>
    value is String && _identifierExpression.hasMatch(value) ? value : null;

NativeTrajectoryAvailability? _availability(Object? value) => switch (value) {
  'available' => NativeTrajectoryAvailability.available,
  'incomplete' => NativeTrajectoryAvailability.incomplete,
  'unavailable' => NativeTrajectoryAvailability.unavailable,
  _ => null,
};

int? _nonNegativeInt(Object? value) =>
    value is num && value.isFinite && value >= 0 && value == value.truncate()
    ? value.toInt()
    : null;

int? _positiveInt(Object? value) {
  final parsed = _nonNegativeInt(value);
  return parsed != null && parsed > 0 ? parsed : null;
}

double? _finiteDouble(Object? value) =>
    value is num && value.isFinite ? value.toDouble() : null;

double? _positiveFinite(Object? value) {
  final parsed = _finiteDouble(value);
  return parsed != null && parsed > 0 ? parsed : null;
}

String? _boundedText(Object? value, {required int maxLength}) {
  if (value is! String || value.trim().isEmpty || value.length > maxLength) {
    return null;
  }
  return _controlCharacterExpression.hasMatch(value) ? null : value;
}

_OptionalString _optionalText(Object? value, {required int maxLength}) {
  if (value == null) return const _OptionalString();
  final text = _boundedText(value, maxLength: maxLength);
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

List<NativeTrajectoryPath>? _paths(Object? value) {
  if (value is! List || value.isEmpty) return null;
  final paths = value
      .map(NativeTrajectoryPath.tryFromJson)
      .whereType<NativeTrajectoryPath>()
      .toList(growable: false);
  return paths.length == value.length ? paths : null;
}

List<List<NativeTrajectoryPoint>>? _walls(Object? value) {
  if (value is! List) return null;
  final walls = <List<NativeTrajectoryPoint>>[];
  for (final rawWall in value) {
    if (rawWall is! List || rawWall.length < 2) return null;
    final points = rawWall
        .map(NativeTrajectoryPoint.tryFromJson)
        .whereType<NativeTrajectoryPoint>()
        .toList(growable: false);
    if (points.length != rawWall.length) return null;
    walls.add(points);
  }
  return walls;
}

bool _strictlyIncreasing(List<NativeTrajectorySample> samples) {
  for (var index = 1; index < samples.length; index += 1) {
    if (samples[index - 1].sampleIndex >= samples[index].sampleIndex) {
      return false;
    }
  }
  return true;
}

class _OptionalString {
  const _OptionalString({this.value, this.isInvalid = false});

  final String? value;
  final bool isInvalid;
}
