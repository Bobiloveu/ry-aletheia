import 'dart:typed_data';

import 'package:aletheia_visualization/aletheia_visualization.dart';
import 'package:flutter_test/flutter_test.dart';

/// Locks the Flutter->Unity wire field names. Unity's `VizTypes.cs` /
/// `VizBridge.MapEnvelope` deserialize these exact keys with JsonUtility, so a
/// rename here without a matching change there silently breaks rendering.
void main() {
  test('camera payload keys match VizCameraMsg', () {
    const camera = VizCameraState(
      scale: 2,
      offset: Offset(3, 4),
      orbitYaw: 0.5,
      orbitPitch: 0.7,
      distance: 12,
      target: Offset(1, 2),
    );
    expect(camera.toJson().keys.toSet(), {
      'scale',
      'ox',
      'oy',
      'yaw',
      'pitch',
      'distance',
      'tx',
      'ty',
    });
  });

  test('map descriptor payload keys match VizBridge.MapEnvelope', () {
    final map = VizMapDescriptor(
      id: 'm1',
      pngBytes: Uint8List.fromList([1, 2, 3]),
      widthPx: 10,
      heightPx: 20,
      resolution: 0.05,
      originX: -1,
      originY: -2,
      vehicleLengthM: 1.0,
      vehicleWidthM: 0.68,
      virtualWalls: [
        Float32List.fromList([1, 2, 3, 4]),
      ],
    );
    final json = map.toJson();
    expect(json.keys.toSet(), {
      'id',
      'png',
      'w',
      'h',
      'res',
      'ox',
      'oy',
      'vlen',
      'vwid',
      'walls',
    });
    // Raster is base64 and only sent on map switch.
    expect(json['png'], 'AQID');
    expect(json['walls'], [
      {
        'p': [1.0, 2.0, 3.0, 4.0],
      },
    ]);

    final pathJson = map.toPathJson('/tmp/aletheia-map.png');
    expect(pathJson['pngPath'], '/tmp/aletheia-map.png');
    expect(pathJson.containsKey('png'), isFalse);
    expect(pathJson['walls'], json['walls']);
  });

  test('cloud layout float counts', () {
    expect(CloudLayout.xy.floatsPerPoint, 2);
    expect(CloudLayout.xyz.floatsPerPoint, 3);
  });
}
