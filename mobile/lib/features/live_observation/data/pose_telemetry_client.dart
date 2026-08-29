import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/scheduler.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../../../core/connection/robot_endpoint.dart';
import '../domain/pose_frame.dart';

class _PendingPosePacket {
  const _PendingPosePacket(this.bytes, this.receivedAt);

  final Uint8List bytes;
  final DateTime receivedAt;
}

class PoseTelemetrySample {
  const PoseTelemetrySample({
    required this.frame,
    required this.receivedPackets,
  });

  final PoseFrame frame;

  /// All packets received since the preceding decoded sample. A burst can be
  /// coalesced into one rendered pose without hiding the transport rate from
  /// the diagnostic metrics endpoint.
  final int receivedPackets;
}

/// Owns the read-only `/pose` lane.
///
/// Pose follows the same bounded latest-wins rule as point clouds. Rendering a
/// temporarily busy frame must never cause historical robot positions to be
/// replayed later. The 250 ms age bound matches the observation diagnostic
/// contract documented for the PC console.
class PoseTelemetryClient {
  static const _packetMaximumAge = Duration(milliseconds: 250);

  WebSocketChannel? _channel;
  StreamController<PoseTelemetrySample>? _output;
  _PendingPosePacket? _pendingPacket;
  bool _closed = false;
  bool _flushScheduled = false;
  int _packetsSinceLastSample = 0;

  Stream<PoseTelemetrySample> frames(RobotEndpoint endpoint, int port) {
    final output = StreamController<PoseTelemetrySample>();
    _output = output;
    output.onListen = () => unawaited(_run(endpoint, port, output));
    output.onCancel = () => unawaited(close());
    return output.stream;
  }

  Future<void> _run(
    RobotEndpoint endpoint,
    int port,
    StreamController<PoseTelemetrySample> output,
  ) async {
    var reconnectAttempt = 0;
    while (!_closed && !output.isClosed) {
      final channel = WebSocketChannel.connect(
        endpoint.telemetryUri(port, 'pose'),
      );
      _channel = channel;
      try {
        await channel.ready.timeout(const Duration(seconds: 5));
        reconnectAttempt = 0;
        await for (final message in channel.stream) {
          if (_closed || output.isClosed) {
            return;
          }
          if (message is List<int>) {
            _queueLatestPacket(
              message is Uint8List ? message : Uint8List.fromList(message),
            );
          }
        }
      } catch (_) {
        // A Wi-Fi interruption is isolated to this read-only lane. The
        // bounded reconnect loop never retains a historical pose queue.
      } finally {
        try {
          await channel.sink.close();
        } catch (_) {
          // A socket can already be gone after a Wi-Fi interruption.
        }
        if (identical(_channel, channel)) {
          _channel = null;
        }
      }
      if (_closed || output.isClosed) {
        return;
      }
      final exponent = reconnectAttempt.clamp(0, 3);
      final delay = Duration(milliseconds: 250 * (1 << exponent));
      reconnectAttempt = (reconnectAttempt + 1).clamp(0, 4);
      await Future<void>.delayed(delay);
    }
  }

  void _queueLatestPacket(Uint8List bytes) {
    _packetsSinceLastSample++;
    _pendingPacket = _PendingPosePacket(bytes, DateTime.now());
    if (_flushScheduled) {
      return;
    }
    _flushScheduled = true;
    SchedulerBinding.instance.scheduleFrameCallback((_) {
      _flushScheduled = false;
      _flushLatestPacket();
    });
    SchedulerBinding.instance.scheduleFrame();
  }

  void _flushLatestPacket() {
    final output = _output;
    final packet = _pendingPacket;
    _pendingPacket = null;
    if (_closed || output == null || output.isClosed || packet == null) {
      return;
    }
    if (DateTime.now().difference(packet.receivedAt) > _packetMaximumAge) {
      return;
    }
    try {
      output.add(
        PoseTelemetrySample(
          frame: PoseFrameDecoder.decode(packet.bytes),
          receivedPackets: _packetsSinceLastSample,
        ),
      );
      _packetsSinceLastSample = 0;
    } on FormatException {
      // Invalid or stale-protocol frames are isolated to this packet.
    }
  }

  Future<void> close() async {
    _closed = true;
    _pendingPacket = null;
    try {
      await _channel?.sink.close();
    } catch (_) {
      // Closing is best effort during a platform lifecycle transition.
    }
    _channel = null;
  }
}
