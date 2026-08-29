import 'dart:typed_data';

const int poseTelemetryKind = 2;
const int poseTelemetryWireVersion = 1;
const int poseTelemetryHeaderBytes = 20;
const int poseTelemetryFrameBytes = poseTelemetryHeaderBytes + 12;

class PoseFrame {
  const PoseFrame({
    required this.sequence,
    required this.sourceTimestampNanoseconds,
    required this.x,
    required this.y,
    required this.yaw,
  });

  final int sequence;
  final int sourceTimestampNanoseconds;
  final double x;
  final double y;
  final double yaw;
}

abstract final class PoseFrameDecoder {
  static PoseFrame decode(Uint8List bytes) {
    if (bytes.lengthInBytes != poseTelemetryFrameBytes) {
      throw const FormatException('实时位置数据格式异常。');
    }
    final data = ByteData.sublistView(bytes);
    if (bytes[0] != 0x41 ||
        bytes[1] != 0x4C ||
        bytes[2] != 0x54 ||
        bytes[3] != 0x4D) {
      throw const FormatException('实时位置数据格式异常。');
    }
    if (data.getUint8(4) != poseTelemetryWireVersion ||
        data.getUint8(5) != poseTelemetryKind ||
        data.getUint16(18, Endian.big) != 1) {
      throw const FormatException('实时位置数据格式异常。');
    }
    final x = data.getFloat32(poseTelemetryHeaderBytes, Endian.big);
    final y = data.getFloat32(poseTelemetryHeaderBytes + 4, Endian.big);
    final yaw = data.getFloat32(poseTelemetryHeaderBytes + 8, Endian.big);
    if (!x.isFinite || !y.isFinite || !yaw.isFinite) {
      throw const FormatException('实时位置数据格式异常。');
    }
    return PoseFrame(
      sequence: data.getUint32(6, Endian.big),
      sourceTimestampNanoseconds: data.getUint64(10, Endian.big),
      x: x,
      y: y,
      yaw: yaw,
    );
  }
}
