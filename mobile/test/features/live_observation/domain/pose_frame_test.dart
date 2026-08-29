import 'dart:typed_data';

import 'package:aletheia_mobile/features/live_observation/domain/pose_frame.dart';
import 'package:test/test.dart';

void main() {
  test('decodes the exact ALTM v1 pose wire frame', () {
    final bytes = Uint8List(poseTelemetryFrameBytes);
    ByteData.sublistView(bytes)
      ..setUint32(0, 0x414C544D, Endian.big)
      ..setUint8(4, poseTelemetryWireVersion)
      ..setUint8(5, poseTelemetryKind)
      ..setUint32(6, 42, Endian.big)
      ..setUint64(10, 1234567890, Endian.big)
      ..setUint16(18, 1, Endian.big)
      ..setFloat32(poseTelemetryHeaderBytes, 1.25, Endian.big)
      ..setFloat32(poseTelemetryHeaderBytes + 4, -2.5, Endian.big)
      ..setFloat32(poseTelemetryHeaderBytes + 8, 0.75, Endian.big);

    final frame = PoseFrameDecoder.decode(bytes);

    expect(frame.sequence, 42);
    expect(frame.sourceTimestampNanoseconds, 1234567890);
    expect(frame.x, closeTo(1.25, 0.0001));
    expect(frame.y, closeTo(-2.5, 0.0001));
    expect(frame.yaw, closeTo(0.75, 0.0001));
  });

  test('rejects a frame from the wrong telemetry lane', () {
    final bytes = Uint8List(poseTelemetryFrameBytes);
    ByteData.sublistView(bytes)
      ..setUint32(0, 0x414C544D, Endian.big)
      ..setUint8(4, poseTelemetryWireVersion)
      ..setUint8(5, 1)
      ..setUint16(18, 1, Endian.big);

    expect(() => PoseFrameDecoder.decode(bytes), throwsFormatException);
  });
}
