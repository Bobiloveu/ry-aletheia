import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/scheduler.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../../../core/connection/robot_endpoint.dart';
import '../domain/cloud_frame.dart';

/// A decoded cloud frame together with its local receive accounting.
class CloudTelemetrySample {
  const CloudTelemetrySample({
    required this.frame,
    required this.receivedPackets,
  });

  final CloudFrame frame;

  /// All binary packets received since the preceding decoded sample. A burst
  /// may therefore produce one sample while still preserving its true rate.
  final int receivedPackets;
}

class _PendingCloudPacket {
  const _PendingCloudPacket(this.bytes, this.receivedAt);

  final Uint8List bytes;
  final DateTime receivedAt;
}

/// Owns the read-only `/cloud` lane. Incoming packets replace a single local
/// slot and are decoded on the next Flutter frame, so a busy renderer never
/// builds a historical cloud backlog.
class CloudTelemetryClient {
  static const _packetMaximumAge = Duration(milliseconds: 100);

  WebSocketChannel? _channel;
  StreamController<CloudTelemetrySample>? _output;
  _PendingCloudPacket? _pendingPacket;
  bool _closed = false;
  bool _flushScheduled = false;
  int _packetsSinceLastSample = 0;
  bool _loggedFirstMessage = false;
  bool _loggedMalformedPacket = false;

  Stream<CloudTelemetrySample> frames(RobotEndpoint endpoint, int port) {
    final output = StreamController<CloudTelemetrySample>();
    _output = output;
    output.onListen = () => unawaited(_run(endpoint, port, output));
    output.onCancel = () => unawaited(close());
    return output.stream;
  }

  Future<void> _run(
    RobotEndpoint endpoint,
    int port,
    StreamController<CloudTelemetrySample> output,
  ) async {
    var reconnectAttempt = 0;
    while (!_closed && !output.isClosed) {
      final channel = WebSocketChannel.connect(
        endpoint.telemetryUri(port, 'cloud'),
      );
      _channel = channel;
      try {
        await channel.ready.timeout(const Duration(seconds: 5));
        if (kDebugMode) {
          debugPrint('[LiveTelemetry] cloud socket connected');
        }
        reconnectAttempt = 0;
        await for (final message in channel.stream) {
          if (_closed || output.isClosed) {
            return;
          }
          if (message is List<int>) {
            if (kDebugMode && !_loggedFirstMessage) {
              _loggedFirstMessage = true;
              debugPrint(
                '[LiveTelemetry] cloud first binary frame '
                'type=${message.runtimeType} bytes=${message.length}',
              );
            }
            _queueLatestPacket(
              message is Uint8List ? message : Uint8List.fromList(message),
            );
          } else if (kDebugMode && !_loggedFirstMessage) {
            _loggedFirstMessage = true;
            debugPrint(
              '[LiveTelemetry] cloud ignored non-binary frame '
              'type=${message.runtimeType}',
            );
          }
        }
      } catch (error) {
        if (kDebugMode) {
          debugPrint(
            '[LiveTelemetry] cloud socket disconnected '
            '(${error.runtimeType})',
          );
        }
        // A Wi-Fi interruption is isolated to this lane. The bounded retry
        // loop deliberately does not retain data while the socket is down.
      } finally {
        try {
          await channel.sink.close();
        } catch (_) {
          // The WebSocket may already be closed after a transport error.
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
    _pendingPacket = _PendingCloudPacket(bytes, DateTime.now());
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
        CloudTelemetrySample(
          frame: CloudFrameDecoder.decode(packet.bytes),
          receivedPackets: _packetsSinceLastSample,
        ),
      );
      _packetsSinceLastSample = 0;
    } on FormatException catch (error) {
      if (kDebugMode && !_loggedMalformedPacket) {
        _loggedMalformedPacket = true;
        debugPrint(
          '[LiveTelemetry] cloud rejected binary frame '
          'bytes=${packet.bytes.length} reason=${error.message}',
        );
      }
      // One malformed packet must not take down the independent cloud lane.
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
