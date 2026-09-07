import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/connection/robot_connection_controller.dart';
import '../data/costmap_telemetry_client.dart';

/// The independent, read-only local-costmap lane.
///
/// It is deliberately isolated from pose and cloud delivery: a stale or
/// malformed costmap cannot delay the vehicle indicator or point cloud.
final costmapTelemetryProvider =
    StreamProvider.autoDispose<CostmapTelemetrySample>((ref) {
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
        return const Stream<CostmapTelemetrySample>.empty();
      }
      final client = CostmapTelemetryClient();
      ref.onDispose(() => unawaited(client.close()));
      return client.frames(endpoint, port);
    });
