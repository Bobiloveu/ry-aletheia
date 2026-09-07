import 'dart:typed_data';

import 'package:aletheia_mobile/features/live_observation/data/costmap_packet_buffer.dart';
import 'package:aletheia_mobile/features/live_observation/domain/costmap_frame.dart';
import 'package:test/test.dart';

void main() {
  test('keeps only the newest costmap packet in a burst', () {
    final buffer = CostmapPacketBuffer();
    final receivedAt = DateTime.utc(2026, 9, 7, 12);

    buffer.replace(_frame(sequence: 4), receivedAt);
    buffer.replace(
      _frame(sequence: 5),
      receivedAt.add(const Duration(milliseconds: 4)),
    );

    final sample = buffer.takeFresh(
      receivedAt.add(const Duration(milliseconds: 5)),
      maximumAge: const Duration(seconds: 5),
    );

    expect(sample, isNotNull);
    expect(CostmapFrameDecoder.decode(sample!.bytes).sequence, 5);
    expect(sample.receivedPackets, 2);
    expect(
      buffer.takeFresh(
        receivedAt.add(const Duration(milliseconds: 5)),
        maximumAge: const Duration(seconds: 5),
      ),
      isNull,
    );
  });

  test('drops a costmap packet after its safety freshness window', () {
    final buffer = CostmapPacketBuffer();
    final receivedAt = DateTime.utc(2026, 9, 7, 12);
    buffer.replace(_frame(sequence: 9), receivedAt);

    expect(
      buffer.takeFresh(
        receivedAt.add(const Duration(seconds: 6)),
        maximumAge: const Duration(seconds: 5),
      ),
      isNull,
    );
  });
}

Uint8List _frame({required int sequence}) {
  const headerBytes = 20;
  const metadataBytes = 20;
  final bytes = Uint8List(headerBytes + metadataBytes + 1);
  ByteData.sublistView(bytes)
    ..setUint32(0, 0x414C544D, Endian.big)
    ..setUint8(4, 1)
    ..setUint8(5, 3)
    ..setUint32(6, sequence, Endian.big)
    ..setUint64(10, 1700000000000000000, Endian.big)
    ..setUint16(18, 1, Endian.big)
    ..setFloat32(headerBytes, 0, Endian.big)
    ..setFloat32(headerBytes + 4, 0, Endian.big)
    ..setFloat32(headerBytes + 8, 0, Endian.big)
    ..setFloat32(headerBytes + 12, .1, Endian.big)
    ..setUint16(headerBytes + 16, 1, Endian.big)
    ..setUint16(headerBytes + 18, 1, Endian.big);
  bytes[headerBytes + metadataBytes] = 254;
  return bytes;
}
