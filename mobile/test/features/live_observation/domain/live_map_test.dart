import 'package:aletheia_mobile/features/live_observation/domain/live_map.dart';
import 'package:test/test.dart';

void main() {
  test('maps world coordinates into the cached map bounds', () {
    final metadata = LiveMapMetadata.fromJson(const {
      'width': 200,
      'height': 100,
      'resolution': 0.05,
      'origin': [-3.0, 4.0],
      'frame_id': 'map',
    });

    expect(metadata.worldWidth, 10);
    expect(metadata.worldHeight, 5);
    expect(metadata.contains(-3, 4), isTrue);
    expect(metadata.contains(7, 9), isTrue);
    expect(metadata.contains(7.01, 9), isFalse);
  });

  test('rejects malformed cached map metadata', () {
    expect(
      () => LiveMapMetadata.fromJson(const {
        'width': 200,
        'height': 100,
        'resolution': 0,
        'origin': [0, 0],
      }),
      throwsFormatException,
    );
  });

  test(
    'keeps virtual-wall coordinate modes and ignores malformed segments',
    () {
      final walls = LiveMapVirtualWall.parseAll(const [
        {
          'coordinate_mode': 'world',
          'points': [
            {'x': -1.5, 'y': 2.0},
            {'x': -1.0, 'y': 2.5},
          ],
        },
        {
          'coordinate_mode': 'image_relative',
          'points': [
            {'x': .5, 'y': .25},
            {'x': 1.0, 'y': .25},
          ],
        },
        {
          'points': [
            {'x': 0.0},
          ],
        },
      ]);

      expect(walls, hasLength(2));
      expect(walls.first.coordinateMode, VirtualWallCoordinateMode.world);
      expect(
        walls.last.coordinateMode,
        VirtualWallCoordinateMode.imageRelative,
      );
    },
  );

  test('uses the active configured vehicle footprint for map projection', () {
    final footprint = VehicleFootprint.fromSettingsJson(const {
      'live_observation': {
        'active_vehicle_model': 'narrow',
        'vehicle_models': [
          {'id': 'standard', 'length_m': 1.0, 'width_m': .68},
          {'id': 'narrow', 'length_m': .82, 'width_m': .52},
        ],
      },
    });

    expect(footprint.lengthMeters, .82);
    expect(footprint.widthMeters, .52);
  });
}
