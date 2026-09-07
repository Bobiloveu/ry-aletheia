import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/scheduler.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../../../core/connection/robot_endpoint.dart';
import 'costmap_packet_buffer.dart';
import '../domain/costmap_frame.dart';

/// A validated costmap together with the number of raw packets it replaced.
class CostmapTelemetrySample {
  const CostmapTelemetrySample({
    required this.frame,
    required this.receivedPackets,
    required this.receivedAt,
  });

  final CostmapFrame frame;

  /// A burst produces one rendered map, never a retained history.
  final int receivedPackets;

  /// Handset arrival time; it drives the independent stale-map safety hide.
  final DateTime receivedAt;
}

/// Owns the read-only `/costmap` lane with bounded latest-wins delivery.
class CostmapTelemetryClient {
  static const _packetMaximumAge = Duration(seconds: 5);

  WebSocketChannel? _channel;
  StreamController<CostmapTelemetrySample>? _output;
  final _packetBuffer = CostmapPacketBuffer();
  bool _closed = false;
  bool _flushScheduled = false;
  bool _loggedMalformedPacket = false;

  Stream<CostmapTelemetrySample> frames(RobotEndpoint endpoint, int port) {
    final output = StreamController<CostmapTelemetrySample>();
    _output = output;
    output.onListen = () => unawaited(_run(endpoint, port, output));
    output.onCancel = () => unawaited(close());
    return output.stream;
  }

  Future<void> _run(
    RobotEndpoint endpoint,
    int port,
    StreamController<CostmapTelemetrySample> output,
  ) async {
    var reconnectAttempt = 0;
    while (!_closed && !output.isClosed) {
      final channel = WebSocketChannel.connect(
        endpoint.telemetryUri(port, 'costmap'),
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
      } catch (error) {
        if (kDebugMode) {
          debugPrint(
            '[LiveTelemetry] costmap socket disconnected '
            '(${error.runtimeType})',
          );
        }
      } finally {
        try {
          await channel.sink.close();
        } catch (_) {
          // The WebSocket may already have closed after a transport error.
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
    _packetBuffer.replace(bytes, DateTime.now());
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
    final packet = _packetBuffer.takeFresh(
      DateTime.now(),
      maximumAge: _packetMaximumAge,
    );
    if (_closed || output == null || output.isClosed || packet == null) {
      return;
    }
    try {
      output.add(
        CostmapTelemetrySample(
          frame: CostmapFrameDecoder.decode(packet.bytes),
          receivedPackets: packet.receivedPackets,
          receivedAt: packet.receivedAt,
        ),
      );
    } on FormatException catch (error) {
      if (kDebugMode && !_loggedMalformedPacket) {
        _loggedMalformedPacket = true;
        debugPrint(
          '[LiveTelemetry] costmap rejected binary frame '
          'bytes=${packet.bytes.length} reason=${error.message}',
        );
      }
      // A malformed map never disrupts cloud or pose telemetry.
    }
  }

  Future<void> close() async {
    _closed = true;
    _packetBuffer.clear();
    try {
      await _channel?.sink.close();
    } catch (_) {
      // Closing is best effort during an application lifecycle transition.
    }
    _channel = null;
  }
}
