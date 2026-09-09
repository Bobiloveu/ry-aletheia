import 'dart:typed_data';

const int costmapTelemetryKind = 3;
const int costmapTelemetryWireVersion = 1;
const int costmapTelemetryHeaderBytes = 20;
const int costmapTelemetryMetadataBytes = 20;
const int costmapCellLimit = 65535;

/// One validated local occupancy grid whose origin has already been projected
/// into the active `map` frame by the robot-side preprocessor.
class CostmapFrame {
  const CostmapFrame({
    required this.sequence,
    required this.sourceTimestampNanoseconds,
    required this.originX,
    required this.originY,
    required this.originYaw,
    required this.resolution,
    required this.width,
    required this.height,
    required this.cells,
  });

  final int sequence;
  final int sourceTimestampNanoseconds;
  final double originX;
  final double originY;
  final double originYaw;
  final double resolution;
  final int width;
  final int height;

  /// Raw ROS OccupancyGrid bytes. The original `-1` unknown value is `255`.
  final Uint8List cells;
}

abstract final class CostmapFrameDecoder {
  static CostmapFrame decode(Uint8List bytes) {
    if (bytes.lengthInBytes <
        costmapTelemetryHeaderBytes + costmapTelemetryMetadataBytes) {
      throw const FormatException('局部代价地图数据格式异常。');
    }
    final data = ByteData.sublistView(bytes);
    if (bytes[0] != 0x41 ||
        bytes[1] != 0x4C ||
        bytes[2] != 0x54 ||
        bytes[3] != 0x4D ||
        data.getUint8(4) != costmapTelemetryWireVersion ||
        data.getUint8(5) != costmapTelemetryKind) {
      throw const FormatException('局部代价地图数据格式异常。');
    }

    final cellCount = data.getUint16(18, Endian.big);
    final expectedLength =
        costmapTelemetryHeaderBytes + costmapTelemetryMetadataBytes + cellCount;
    if (cellCount == 0 ||
        cellCount > costmapCellLimit ||
        bytes.lengthInBytes != expectedLength) {
      throw const FormatException('局部代价地图数据格式异常。');
    }

    final metadataOffset = costmapTelemetryHeaderBytes;
    final originX = data.getFloat32(metadataOffset, Endian.big);
    final originY = data.getFloat32(metadataOffset + 4, Endian.big);
    final originYaw = data.getFloat32(metadataOffset + 8, Endian.big);
    final resolution = data.getFloat32(metadataOffset + 12, Endian.big);
    final width = data.getUint16(metadataOffset + 16, Endian.big);
    final height = data.getUint16(metadataOffset + 18, Endian.big);
    if (width == 0 ||
        height == 0 ||
        width * height != cellCount ||
        !originX.isFinite ||
        !originY.isFinite ||
        !originYaw.isFinite ||
        !resolution.isFinite ||
        resolution <= 0) {
      throw const FormatException('局部代价地图数据格式异常。');
    }

    return CostmapFrame(
      sequence: data.getUint32(6, Endian.big),
      sourceTimestampNanoseconds: data.getUint64(10, Endian.big),
      originX: originX,
      originY: originY,
      originYaw: originYaw,
      resolution: resolution,
      width: width,
      height: height,
      cells: Uint8List.sublistView(
        bytes,
        costmapTelemetryHeaderBytes + costmapTelemetryMetadataBytes,
      ),
    );
  }
}
