import 'dart:typed_data';

/// A physical vehicle outline used only for the map projection.
///
/// Dimensions come from the existing ``/api/settings`` vehicle-model contract.
/// They do not participate in localisation, navigation or any control path.
class VehicleFootprint {
  const VehicleFootprint({
    required this.lengthMeters,
    required this.widthMeters,
  });

  /// Matches the established PC console fallback when the optional settings
  /// response is temporarily unavailable.
  static const standard = VehicleFootprint(lengthMeters: 1, widthMeters: .68);

  factory VehicleFootprint.fromSettingsJson(Map<String, dynamic> settings) {
    final observation = settings['live_observation'];
    if (observation is! Map) {
      return standard;
    }
    final activeId = observation['active_vehicle_model'];
    final models = observation['vehicle_models'];
    if (models is! List) {
      return standard;
    }
    Map<String, dynamic>? fallback;
    for (final rawModel in models) {
      if (rawModel is! Map) {
        continue;
      }
      final model = rawModel.map(
        (key, value) => MapEntry(key.toString(), value),
      );
      fallback ??= model;
      if (model['id'] == activeId) {
        return _fromModel(model);
      }
    }
    return fallback == null ? standard : _fromModel(fallback);
  }

  final double lengthMeters;
  final double widthMeters;

  static VehicleFootprint _fromModel(Map<String, dynamic> model) {
    final length = model['length_m'];
    final width = model['width_m'];
    return VehicleFootprint(
      lengthMeters: length is num && length.isFinite && length >= .2
          ? length.toDouble()
          : standard.lengthMeters,
      widthMeters: width is num && width.isFinite && width >= .15
          ? width.toDouble()
          : standard.widthMeters,
    );
  }
}

enum VirtualWallCoordinateMode { world, imageRelative }

class VirtualWallPoint {
  const VirtualWallPoint({required this.x, required this.y});

  factory VirtualWallPoint.fromJson(Map<String, dynamic> json) {
    final x = json['x'];
    final y = json['y'];
    if (x is! num || !x.isFinite || y is! num || !y.isFinite) {
      throw const FormatException('虚拟墙坐标无效。');
    }
    return VirtualWallPoint(x: x.toDouble(), y: y.toDouble());
  }

  final double x;
  final double y;
}

class LiveMapVirtualWall {
  const LiveMapVirtualWall({
    required this.points,
    required this.coordinateMode,
  });

  factory LiveMapVirtualWall.fromJson(Map<String, dynamic> json) {
    final rawPoints = json['points'];
    if (rawPoints is! List) {
      throw const FormatException('虚拟墙点列无效。');
    }
    final points = <VirtualWallPoint>[];
    for (final rawPoint in rawPoints) {
      if (rawPoint is Map) {
        points.add(
          VirtualWallPoint.fromJson(
            rawPoint.map((key, value) => MapEntry(key.toString(), value)),
          ),
        );
      }
    }
    if (points.length < 2) {
      throw const FormatException('虚拟墙至少需要两个点。');
    }
    return LiveMapVirtualWall(
      points: List.unmodifiable(points),
      coordinateMode: json['coordinate_mode'] == 'image_relative'
          ? VirtualWallCoordinateMode.imageRelative
          : VirtualWallCoordinateMode.world,
    );
  }

  /// A malformed optional wall must not hide an otherwise valid map.
  static List<LiveMapVirtualWall> parseAll(Object? rawWalls) {
    if (rawWalls is! List) {
      return const [];
    }
    final walls = <LiveMapVirtualWall>[];
    for (final rawWall in rawWalls) {
      if (rawWall is! Map) {
        continue;
      }
      try {
        walls.add(
          LiveMapVirtualWall.fromJson(
            rawWall.map((key, value) => MapEntry(key.toString(), value)),
          ),
        );
      } on FormatException {
        // Keep parsing independent wall segments after one malformed item.
      }
    }
    return List.unmodifiable(walls);
  }

  final List<VirtualWallPoint> points;
  final VirtualWallCoordinateMode coordinateMode;
}

class LiveMapMetadata {
  const LiveMapMetadata({
    required this.width,
    required this.height,
    required this.resolution,
    required this.originX,
    required this.originY,
    required this.frameId,
  });

  factory LiveMapMetadata.fromJson(Map<String, dynamic> json) {
    final width = _positiveInt(json['width'], 'width');
    final height = _positiveInt(json['height'], 'height');
    final resolution = _positiveDouble(json['resolution'], 'resolution');
    final origin = json['origin'];
    if (origin is! List || origin.length < 2) {
      throw const FormatException('地图原点数据无效。');
    }
    final originX = _finiteDouble(origin[0], 'origin[0]');
    final originY = _finiteDouble(origin[1], 'origin[1]');
    final frameId =
        json['frame_id'] is String &&
            (json['frame_id'] as String).trim().isNotEmpty
        ? (json['frame_id'] as String).trim()
        : 'map';
    return LiveMapMetadata(
      width: width,
      height: height,
      resolution: resolution,
      originX: originX,
      originY: originY,
      frameId: frameId,
    );
  }

  final int width;
  final int height;
  final double resolution;
  final double originX;
  final double originY;
  final String frameId;

  double get worldWidth => width * resolution;
  double get worldHeight => height * resolution;

  bool contains(double x, double y) =>
      x >= originX &&
      x <= originX + worldWidth &&
      y >= originY &&
      y <= originY + worldHeight;

  static int _positiveInt(Object? value, String name) {
    if (value is! num || !value.isFinite || value <= 0 || value.toInt() <= 0) {
      throw FormatException('地图 $name 无效。');
    }
    return value.toInt();
  }

  static double _positiveDouble(Object? value, String name) {
    final result = _finiteDouble(value, name);
    if (result <= 0) {
      throw FormatException('地图 $name 无效。');
    }
    return result;
  }

  static double _finiteDouble(Object? value, String name) {
    if (value is! num || !value.isFinite) {
      throw FormatException('地图 $name 无效。');
    }
    return value.toDouble();
  }
}

class LiveMapAsset {
  const LiveMapAsset({
    required this.id,
    required this.metadata,
    required this.previewBytes,
    this.virtualWalls = const [],
    this.vehicleFootprint = VehicleFootprint.standard,
  });

  final String id;
  final LiveMapMetadata metadata;
  final Uint8List previewBytes;
  final List<LiveMapVirtualWall> virtualWalls;
  final VehicleFootprint vehicleFootprint;
}
