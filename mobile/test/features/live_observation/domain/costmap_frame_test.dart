import 'dart:typed_data';

import 'package:aletheia_mobile/features/live_observation/domain/costmap_frame.dart';
import 'package:test/test.dart';

void main() {
  test('decodes an exact ALTM v1 map-coordinate costmap frame', () {
    final bytes = _costmapFrame(
      sequence: 42,
      originX: 1.25,
      originY: -2.5,
      originYaw: .75,
      resolution: .05,
      width: 2,
      height: 2,
      cells: const [0, 126, 253, 255],
    );

    final frame = CostmapFrameDecoder.decode(bytes);

    expect(frame.sequence, 42);
    expect(frame.sourceTimestampNanoseconds, 1700000000000000000);
    expect(frame.originX, closeTo(1.25, .0001));
    expect(frame.originY, closeTo(-2.5, .0001));
    expect(frame.originYaw, closeTo(.75, .0001));
    expect(frame.resolution, closeTo(.05, .0001));
    expect(frame.width, 2);
    expect(frame.height, 2);
    expect(frame.cells, [0, 126, 253, 255]);
  });

  test('rejects a costmap whose declared cell count differs from dimensions', () {
    final bytes = _costmapFrame(
      width: 2,
      height: 2,
      cells: const [0, 1, 2],
      declaredCellCount: 3,
    );

    expect(() => CostmapFrameDecoder.decode(bytes), throwsFormatException);
  });

  test('rejects a costmap with a non-finite map origin or resolution', () {
    final bytes = _costmapFrame(
      originX: double.nan,
      width: 1,
      height: 1,
      cells: const [0],
    );

    expect(() => CostmapFrameDecoder.decode(bytes), throwsFormatException);
  });
}

Uint8List _costmapFrame({
  int sequence = 1,
  int timestampNanoseconds = 1700000000000000000,
  double originX = 0,
  double originY = 0,
  double originYaw = 0,
  double resolution = .1,
  required int width,
  required int height,
  required List<int> cells,
  int? declaredCellCount,
}) {
  const headerBytes = 20;
  const metadataBytes = 20;
  final cellCount = declaredCellCount ?? cells.length;
  final bytes = Uint8List(headerBytes + metadataBytes + cells.length);
  ByteData.sublistView(bytes)
    ..setUint32(0, 0x414C544D, Endian.big)
    ..setUint8(4, 1)
    ..setUint8(5, 3)
    ..setUint32(6, sequence, Endian.big)
    ..setUint64(10, timestampNanoseconds, Endian.big)
    ..setUint16(18, cellCount, Endian.big)
    ..setFloat32(headerBytes, originX, Endian.big)
    ..setFloat32(headerBytes + 4, originY, Endian.big)
    ..setFloat32(headerBytes + 8, originYaw, Endian.big)
    ..setFloat32(headerBytes + 12, resolution, Endian.big)
    ..setUint16(headerBytes + 16, width, Endian.big)
    ..setUint16(headerBytes + 18, height, Endian.big);
  bytes.setRange(headerBytes + metadataBytes, bytes.length, cells);
  return bytes;
}
