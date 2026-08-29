class ObservationStatus {
  const ObservationStatus({
    required this.enabledInConfiguration,
    required this.telemetryOnline,
    required this.telemetryWebSocketPort,
    required this.telemetryDetail,
    required this.preprocessorAvailable,
    required this.preprocessorManaged,
    required this.activeMapId,
    required this.idleStopSeconds,
  });

  factory ObservationStatus.fromJson(Map<String, dynamic> json) {
    final telemetry = _map(json['telemetry']);
    final preprocessor = _map(json['preprocessor']);
    return ObservationStatus(
      enabledInConfiguration: json['enabled'] == true,
      telemetryOnline: telemetry['online'] == true,
      telemetryWebSocketPort: telemetry['websocket_port'] is num
          ? (telemetry['websocket_port'] as num).toInt()
          : null,
      telemetryDetail: telemetry['detail'] is String
          ? telemetry['detail'] as String
          : 'Aletheia 专用实时遥测',
      preprocessorAvailable: preprocessor['available'] == true,
      preprocessorManaged: preprocessor['managed'] == true,
      activeMapId: json['active_map_id'] is String
          ? json['active_map_id'] as String
          : null,
      idleStopSeconds: json['idle_stop_seconds'] is num
          ? (json['idle_stop_seconds'] as num).round()
          : null,
    );
  }

  final bool enabledInConfiguration;
  final bool telemetryOnline;
  final int? telemetryWebSocketPort;
  final String telemetryDetail;
  final bool preprocessorAvailable;
  final bool preprocessorManaged;
  final String? activeMapId;
  final int? idleStopSeconds;

  static Map<String, dynamic> _map(Object? value) => value is Map
      ? value.map((key, item) => MapEntry(key.toString(), item))
      : const {};
}
