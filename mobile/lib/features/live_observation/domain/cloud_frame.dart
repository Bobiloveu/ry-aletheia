import 'dart:typed_data';

const int cloudTelemetryKind = 1;
const int cloudTelemetryWireVersion = 1;
const int cloudTelemetryHeaderBytes = 20;
const int cloudTelemetryPointLimit = 3000;

/// One validated, map-coordinate point-cloud frame from Aletheia's private
/// telemetry lane. Points stay packed to avoid allocating 3000 point objects
/// for every incoming scan.
class CloudFrame {
  const CloudFrame({
    required this.sequence,
    required this.sourceTimestampNanoseconds,
    required this.packedMapPoints,
  });

  final int sequence;
  final int sourceTimestampNanoseconds;
  final Float32List packedMapPoints;

  int get pointCount => packedMapPoints.length ~/ 2;

  /// Mirrors the browser implementation: source clocks that cannot be safely
  /// compared to the handset clock are reported as zero rather than stale.
  int sourceAgeMillisecondsAt(DateTime now) {
    const nanosecondsPerMillisecond = 1000000;
    final sourceMilliseconds =
        sourceTimestampNanoseconds ~/ nanosecondsPerMillisecond;
    final age = now.millisecondsSinceEpoch - sourceMilliseconds;
    return age >= 0 && age <= 5000 ? age : 0;
  }
}

abstract final class CloudFrameDecoder {
  static CloudFrame decode(Uint8List bytes) {
    if (bytes.lengthInBytes < cloudTelemetryHeaderBytes) {
      throw const FormatException('点云数据格式异常。');
    }
    final data = ByteData.sublistView(bytes);
    if (bytes[0] != 0x41 ||
        bytes[1] != 0x4C ||
        bytes[2] != 0x54 ||
        bytes[3] != 0x4D) {
      throw const FormatException('点云数据格式异常。');
    }
    if (data.getUint8(4) != cloudTelemetryWireVersion ||
        data.getUint8(5) != cloudTelemetryKind) {
      throw const FormatException('点云数据格式异常。');
    }
    final pointCount = data.getUint16(18, Endian.big);
    if (pointCount > cloudTelemetryPointLimit ||
        bytes.lengthInBytes != cloudTelemetryHeaderBytes + pointCount * 8) {
      throw const FormatException('点云数据格式异常。');
    }

    final points = Float32List(pointCount * 2);
    for (var index = 0; index < pointCount; index++) {
      final offset = cloudTelemetryHeaderBytes + index * 8;
      final x = data.getFloat32(offset, Endian.big);
      final y = data.getFloat32(offset + 4, Endian.big);
      if (!x.isFinite || !y.isFinite) {
        throw const FormatException('点云数据格式异常。');
      }
      points[index * 2] = x;
      points[index * 2 + 1] = y;
    }
    return CloudFrame(
      sequence: data.getUint32(6, Endian.big),
      sourceTimestampNanoseconds: data.getUint64(10, Endian.big),
      packedMapPoints: points,
    );
  }
}
