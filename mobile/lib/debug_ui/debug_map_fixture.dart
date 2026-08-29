import 'dart:ui' as ui;

import 'package:flutter/services.dart';
import 'package:yaml/yaml.dart';

import '../features/live_observation/domain/live_map.dart';

/// A real, local map fixture for Debug UI Gallery reviews.
///
/// The PNG is a lossless, full-resolution conversion of the supplied PGM.
/// World metadata and every virtual-wall segment come directly from the paired YAML files,
/// so the production map, Grid and wall painters exercise their real
/// coordinate path without contacting a robot.
abstract final class DebugMapFixture {
  static const previewPath = 'assets/debug_ui/sample_map.png';
  static const _mapYamlPath = 'assets/debug_ui/sample_map.yaml';
  static const _wallsYamlPath = 'assets/debug_ui/sample_map_walls.yaml';

  // These are both the original PGM and PNG dimensions. Keeping the full
  // raster preserves the exact review resolution and metre coordinate system.
  static const _sourceWidth = 3480;
  static const _sourceHeight = 10017;

  static Future<DebugMapFixtureData> load() async {
    // Keep the types explicit. The Flutter test bundle provides `ByteData`
    // and `String` through different asynchronous paths.
    final previewData = await rootBundle.load(previewPath);
    final mapYaml = await rootBundle.loadString(_mapYamlPath);
    final wallsYaml = await rootBundle.loadString(_wallsYamlPath);
    final mapDocument = _asMap(loadYaml(mapYaml), '地图 YAML');
    final wallsDocument = _asMap(loadYaml(wallsYaml), '虚拟墙 YAML');
    final metadata = _metadataFrom(mapDocument);
    final walls = _wallsFrom(wallsDocument, metadata: metadata);
    final previewBytes = previewData.buffer.asUint8List(
      previewData.offsetInBytes,
      previewData.lengthInBytes,
    );
    final codec = await ui.instantiateImageCodec(previewBytes);
    final frame = await codec.getNextFrame();
    codec.dispose();
    return DebugMapFixtureData(
      map: LiveMapAsset(
        id: 'debug-sample-map',
        metadata: metadata,
        previewBytes: previewBytes,
        virtualWalls: walls,
      ),
      previewImage: frame.image,
    );
  }

  static LiveMapMetadata _metadataFrom(Map<Object?, Object?> document) {
    final origin = _asList(document['origin'], '地图 origin');
    if (origin.length < 2) {
      throw const FormatException('地图 origin 至少需要两个坐标。');
    }
    return LiveMapMetadata(
      width: _sourceWidth,
      height: _sourceHeight,
      resolution: _number(document['resolution'], '地图 resolution'),
      originX: _number(origin[0], '地图 origin x'),
      originY: _number(origin[1], '地图 origin y'),
      frameId: 'map',
    );
  }

  static List<LiveMapVirtualWall> _wallsFrom(
    Map<Object?, Object?> document, {
    required LiveMapMetadata metadata,
  }) {
    final rawWalls = _asMap(document['virtual_walls'], '虚拟墙根节点');
    final mode = rawWalls['coordinate_mode'] == 'image_relative'
        ? VirtualWallCoordinateMode.imageRelative
        : VirtualWallCoordinateMode.world;
    final origin = _asList(rawWalls['map_origin'], '虚拟墙 map_origin');
    if (origin.length < 2 ||
        _number(origin[0], '虚拟墙 origin x') != metadata.originX ||
        _number(origin[1], '虚拟墙 origin y') != metadata.originY) {
      throw const FormatException('虚拟墙与地图原点不一致。');
    }
    final segments = _asList(rawWalls['segments'], '虚拟墙 segments');
    return List.unmodifiable(
      segments.map((rawSegment) {
        final segment = _asMap(rawSegment, '虚拟墙 segment');
        return LiveMapVirtualWall(
          coordinateMode: mode,
          points: [
            _pointFrom(segment['start'], '虚拟墙 start'),
            _pointFrom(segment['end'], '虚拟墙 end'),
          ],
        );
      }),
    );
  }

  static VirtualWallPoint _pointFrom(Object? raw, String name) {
    final values = _asList(raw, name);
    if (values.length < 2) {
      throw FormatException('$name 至少需要两个坐标。');
    }
    return VirtualWallPoint(
      x: _number(values[0], '$name x'),
      y: _number(values[1], '$name y'),
    );
  }

  static Map<Object?, Object?> _asMap(Object? value, String name) {
    if (value is! Map) {
      throw FormatException('$name 格式无效。');
    }
    return value.map((key, item) => MapEntry(key, item));
  }

  static List<Object?> _asList(Object? value, String name) {
    if (value is! List) {
      throw FormatException('$name 格式无效。');
    }
    return List<Object?>.from(value);
  }

  static double _number(Object? value, String name) {
    if (value is! num || !value.isFinite) {
      throw FormatException('$name 必须是有限数值。');
    }
    return value.toDouble();
  }
}

class DebugMapFixtureData {
  const DebugMapFixtureData({required this.map, required this.previewImage});

  final LiveMapAsset map;
  final ui.Image previewImage;
}
