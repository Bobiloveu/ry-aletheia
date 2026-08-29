import 'dart:typed_data';

import 'package:aletheia_mobile/features/live_observation/domain/cloud_frame.dart';
import 'package:test/test.dart';

void main() {
  test('decodes an exact ALTM v1 cloud wire frame', () {
    final bytes = Uint8List(cloudTelemetryHeaderBytes + 16);
    ByteData.sublistView(bytes)
      ..setUint32(0, 0x414C544D, Endian.big)
      ..setUint8(4, cloudTelemetryWireVersion)
      ..setUint8(5, cloudTelemetryKind)
      ..setUint32(6, 42, Endian.big)
      ..setUint64(10, 1700000000000000000, Endian.big)
      ..setUint16(18, 2, Endian.big)
      ..setFloat32(cloudTelemetryHeaderBytes, 1.25, Endian.big)
      ..setFloat32(cloudTelemetryHeaderBytes + 4, -2.5, Endian.big)
      ..setFloat32(cloudTelemetryHeaderBytes + 8, 3.75, Endian.big)
      ..setFloat32(cloudTelemetryHeaderBytes + 12, 4.5, Endian.big);

    final frame = CloudFrameDecoder.decode(bytes);

    expect(frame.sequence, 42);
    expect(frame.sourceTimestampNanoseconds, 1700000000000000000);
    expect(frame.pointCount, 2);
    expect(frame.packedMapPoints, [1.25, -2.5, 3.75, 4.5]);
  });

  test('rejects a cloud frame larger than the fixed point budget', () {
    final bytes = Uint8List(cloudTelemetryHeaderBytes);
    ByteData.sublistView(bytes)
      ..setUint32(0, 0x414C544D, Endian.big)
      ..setUint8(4, cloudTelemetryWireVersion)
      ..setUint8(5, cloudTelemetryKind)
      ..setUint16(18, cloudTelemetryPointLimit + 1, Endian.big);

    expect(() => CloudFrameDecoder.decode(bytes), throwsFormatException);
  });

  test('rejects non-finite point coordinates', () {
    final bytes = Uint8List(cloudTelemetryHeaderBytes + 8);
    ByteData.sublistView(bytes)
      ..setUint32(0, 0x414C544D, Endian.big)
      ..setUint8(4, cloudTelemetryWireVersion)
      ..setUint8(5, cloudTelemetryKind)
      ..setUint16(18, 1, Endian.big)
      ..setFloat32(cloudTelemetryHeaderBytes, double.nan, Endian.big)
      ..setFloat32(cloudTelemetryHeaderBytes + 4, 1, Endian.big);

    expect(() => CloudFrameDecoder.decode(bytes), throwsFormatException);
  });
}
