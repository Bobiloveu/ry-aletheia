enum VideoStreamAvailability { disabled, offline, waiting, online, unknown }

class VideoGateway {
  const VideoGateway({required this.online, required this.detail});

  final bool online;
  final String detail;
}

class VideoStream {
  const VideoStream({
    required this.name,
    required this.enabled,
    required this.availability,
    required this.resolution,
    required this.fps,
    required this.sourceTopic,
    required this.codec,
    required this.whepUri,
  });

  factory VideoStream.fromJson(Map<String, dynamic> json) {
    final name = json['name'];
    if (name is! String || name.trim().isEmpty) {
      throw const FormatException('视频流名称无效。');
    }
    return VideoStream(
      name: name,
      enabled: json['enabled'] == true,
      availability: _availabilityOf(json['status']),
      resolution: _stringOr(json['resolution'], '未知分辨率'),
      fps: _positiveIntOr(json['fps'], 0),
      sourceTopic: _stringOr(json['source_topic'], '未知图像话题'),
      codec: _stringOr(json['codec'], '未知编码'),
      whepUri: _whepUriOf(json['url']),
    );
  }

  final String name;
  final bool enabled;
  final VideoStreamAvailability availability;
  final String resolution;
  final int fps;
  final String sourceTopic;
  final String codec;
  final Uri? whepUri;

  bool get isReadyForPlayback =>
      enabled &&
      availability == VideoStreamAvailability.online &&
      whepUri != null;

  static VideoStreamAvailability _availabilityOf(Object? value) =>
      switch (value) {
        'disabled' => VideoStreamAvailability.disabled,
        'offline' => VideoStreamAvailability.offline,
        'waiting' => VideoStreamAvailability.waiting,
        'online' => VideoStreamAvailability.online,
        _ => VideoStreamAvailability.unknown,
      };

  static Uri? _whepUriOf(Object? value) {
    if (value is! String || value.trim().isEmpty) {
      return null;
    }
    final uri = Uri.tryParse(value);
    return uri != null && uri.scheme == 'http' && uri.host.isNotEmpty
        ? uri
        : null;
  }

  static String _stringOr(Object? value, String fallback) =>
      value is String && value.trim().isNotEmpty ? value : fallback;

  static int _positiveIntOr(Object? value, int fallback) =>
      value is num && value.isFinite && value > 0 ? value.toInt() : fallback;
}

class VideoStatus {
  const VideoStatus({
    required this.enabled,
    required this.gateway,
    required this.streams,
  });

  factory VideoStatus.fromJson(Map<String, dynamic> json) {
    final streams = json['streams'];
    if (streams is! List) {
      throw const FormatException('车端没有返回视频流列表。');
    }
    final gateway = json['gateway'];
    final gatewayMap = gateway is Map
        ? gateway.map((key, value) => MapEntry(key.toString(), value))
        : const <String, dynamic>{};
    return VideoStatus(
      enabled: json['enabled'] == true,
      gateway: VideoGateway(
        online: gatewayMap['online'] == true,
        detail: VideoStream._stringOr(gatewayMap['detail'], 'MediaMTX 状态未知。'),
      ),
      streams: streams
          .whereType<Map>()
          .map(
            (item) => VideoStream.fromJson(
              item.map((key, value) => MapEntry(key.toString(), value)),
            ),
          )
          .toList(growable: false),
    );
  }

  final bool enabled;
  final VideoGateway gateway;
  final List<VideoStream> streams;

  VideoStream? streamNamed(String? name) {
    if (name == null) {
      return null;
    }
    for (final stream in streams) {
      if (stream.name == name) {
        return stream;
      }
    }
    return null;
  }

  /// The default selection before an operator picks one of the configured
  /// streams. Keep this compatibility helper for existing callers/tests.
  VideoStream? get primaryStream {
    for (final stream in streams) {
      if (stream.name == 'front_camera') {
        return stream;
      }
    }
    return streams.isEmpty ? null : streams.first;
  }
}
