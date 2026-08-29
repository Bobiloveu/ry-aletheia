import 'dart:typed_data';

import '../../../core/connection/robot_endpoint.dart';
import '../../../core/network/aletheia_api_client.dart';
import '../../../core/network/api_exception.dart';
import '../domain/live_map.dart';

class LiveObservationRepository {
  const LiveObservationRepository(this._apiClient);

  final AletheiaApiClient _apiClient;

  Future<LiveMapAsset?> loadActiveMap(
    RobotEndpoint endpoint, {
    String? activeMapId,
  }) async {
    final mapId =
        activeMapId ?? await _apiClient.activeObservationMapId(endpoint);
    if (mapId == null) {
      return null;
    }
    final layers = await _apiClient.observationMapLayers(endpoint, mapId);
    final metadataValue = layers['map'];
    if (metadataValue is! Map) {
      throw const FormatException('车端没有返回完整的地图元数据。');
    }
    final metadata = LiveMapMetadata.fromJson(
      metadataValue.map((key, value) => MapEntry(key.toString(), value)),
    );
    final virtualWalls = LiveMapVirtualWall.parseAll(layers['virtual_walls']);
    final bytesFuture = _apiClient.getBytes(
      endpoint,
      'api/observation/maps/$mapId/preview.png',
    );
    final footprintFuture = _loadVehicleFootprint(endpoint);
    final bytes = await bytesFuture;
    final footprint = await footprintFuture;
    return LiveMapAsset(
      id: mapId,
      metadata: metadata,
      previewBytes: Uint8List.fromList(bytes),
      virtualWalls: virtualWalls,
      vehicleFootprint: footprint,
    );
  }

  Future<VehicleFootprint> _loadVehicleFootprint(RobotEndpoint endpoint) async {
    try {
      return VehicleFootprint.fromSettingsJson(
        await _apiClient.getJson(endpoint, 'api/settings'),
      );
    } on ApiException {
      // A transient settings failure should not take down the independent map
      // workspace. The fallback deliberately matches the PC console.
      return VehicleFootprint.standard;
    } on FormatException {
      return VehicleFootprint.standard;
    }
  }
}
