import 'package:aletheia_mobile/features/live_observation/domain/live_map.dart';
import 'package:aletheia_mobile/features/live_observation/visualization/unity_viewport.dart';
import 'package:aletheia_visualization/aletheia_visualization.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('camera and Flutter layout produce one complete Unity projection', () {
    const map = LiveMapMetadata(
      width: 100,
      height: 50,
      resolution: .1,
      originX: -4,
      originY: 3,
      frameId: 'map',
    );
    const camera = VizCameraState(scale: 2, offset: Offset(1.5, -0.5));

    final viewport = UnityViewport.fromFlutter(
      map: map,
      camera: camera,
      size: const Size(220, 110),
      revision: 7,
    );

    // world: x=[-4,6], y=[3,8], so the base centre is (1,5.5).
    expect(viewport.width, 220);
    expect(viewport.height, 110);
    expect(viewport.pixelsPerMetre, 40);
    expect(viewport.centerX, 2.5);
    expect(viewport.centerY, 5);
    expect(viewport.revision, 7);
  });
}
