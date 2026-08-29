import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/connection/robot_connection_controller.dart';
import '../data/pose_telemetry_client.dart';

final poseTelemetryProvider = StreamProvider.autoDispose<PoseTelemetrySample>((
  ref,
) {
  final connection = ref.watch(
    robotConnectionControllerProvider.select(
      (state) => (
        state.isConnected,
        state.endpoint,
        state.observation?.telemetryOnline,
        state.observation?.telemetryWebSocketPort,
      ),
    ),
  );
  final endpoint = connection.$2;
  final port = connection.$4;
  if (!connection.$1 ||
      connection.$3 != true ||
      endpoint == null ||
      port == null) {
    return const Stream<PoseTelemetrySample>.empty();
  }
  final client = PoseTelemetryClient();
  ref.onDispose(() => unawaited(client.close()));
  return client.frames(endpoint, port);
});
