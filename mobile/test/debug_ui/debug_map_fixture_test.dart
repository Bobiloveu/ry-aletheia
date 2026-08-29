import 'package:aletheia_mobile/debug_ui/debug_map_fixture.dart';
import 'package:aletheia_mobile/features/live_observation/domain/live_map.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test(
    'loads the supplied map metadata, image and virtual-wall segments',
    () async {
      final fixture = await DebugMapFixture.load();
      final map = fixture.map;

      expect(map.id, 'debug-sample-map');
      expect(map.metadata.width, 3480);
      expect(map.metadata.height, 10017);
      expect(map.metadata.resolution, .05);
      expect(map.metadata.originX, -111.57);
      expect(map.metadata.originY, -248.79);
      expect(map.previewBytes.lengthInBytes, greaterThan(80000));
      expect(map.virtualWalls, hasLength(453));
      expect(fixture.previewImage.width, 3480);
      expect(fixture.previewImage.height, 10017);
      expect(
        map.virtualWalls.every(
          (wall) =>
              wall.coordinateMode == VirtualWallCoordinateMode.imageRelative,
        ),
        isTrue,
      );
    },
  );
}
