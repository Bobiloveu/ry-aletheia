import 'dart:typed_data';

import 'package:aletheia_mobile/features/live_observation/domain/costmap_frame.dart';
import 'package:aletheia_mobile/features/live_observation/domain/costmap_raster.dart';
import 'package:test/test.dart';

void main() {
  test('uses PC-equivalent colours and flips ROS rows for map rendering', () {
    final rgba = costmapRgbaBytes(
      CostmapFrame(
        sequence: 1,
        sourceTimestampNanoseconds: 1,
        originX: 0,
        originY: 0,
        originYaw: 0,
        resolution: .1,
        width: 2,
        height: 2,
        cells: Uint8List.fromList(const [0, 126, 253, 255]),
      ),
    );

    expect(rgba, <int>[
      249,
      115,
      22,
      176,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      0,
      250,
      204,
      21,
      128,
    ]);
  });
}
