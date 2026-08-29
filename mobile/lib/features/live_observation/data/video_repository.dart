import '../../../core/connection/robot_endpoint.dart';
import '../../../core/network/aletheia_api_client.dart';
import '../domain/video_status.dart';

class VideoRepository {
  const VideoRepository(this._apiClient);

  final AletheiaApiClient _apiClient;

  Future<VideoStatus> status(RobotEndpoint endpoint) async {
    final json = await _apiClient.getJson(endpoint, 'api/video/status');
    return VideoStatus.fromJson(json);
  }

  Future<VideoStatus> setStreamEnabled(
    RobotEndpoint endpoint,
    String streamName,
    bool enabled,
  ) async {
    final json = await _apiClient.postJson(
      endpoint,
      'api/video/control',
      body: {'stream': streamName, 'enabled': enabled},
    );
    return VideoStatus.fromJson(json);
  }
}
