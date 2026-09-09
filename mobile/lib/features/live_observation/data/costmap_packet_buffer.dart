import 'dart:typed_data';

/// The one-slot handoff between WebSocket I/O and the Flutter frame scheduler.
///
/// Replacing a packet never allocates a queue, so a slow renderer cannot replay
/// stale robot maps after it catches up.
class CostmapPacketBuffer {
  Uint8List? _bytes;
  DateTime? _receivedAt;
  int _receivedPackets = 0;

  void replace(Uint8List bytes, DateTime receivedAt) {
    _bytes = bytes;
    _receivedAt = receivedAt;
    _receivedPackets++;
  }

  CostmapBufferedPacket? takeFresh(
    DateTime now, {
    required Duration maximumAge,
  }) {
    final bytes = _bytes;
    final receivedAt = _receivedAt;
    final receivedPackets = _receivedPackets;
    _bytes = null;
    _receivedAt = null;
    _receivedPackets = 0;
    if (bytes == null || receivedAt == null) {
      return null;
    }
    if (now.difference(receivedAt) > maximumAge) {
      return null;
    }
    return CostmapBufferedPacket(
      bytes: bytes,
      receivedAt: receivedAt,
      receivedPackets: receivedPackets,
    );
  }

  void clear() {
    _bytes = null;
    _receivedAt = null;
    _receivedPackets = 0;
  }
}

class CostmapBufferedPacket {
  const CostmapBufferedPacket({
    required this.bytes,
    required this.receivedAt,
    required this.receivedPackets,
  });

  final Uint8List bytes;
  final DateTime receivedAt;
  final int receivedPackets;
}
