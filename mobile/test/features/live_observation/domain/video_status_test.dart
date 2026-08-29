import 'package:aletheia_mobile/features/live_observation/domain/video_status.dart';
import 'package:test/test.dart';

void main() {
  test(
    'prefers the configured forward camera until an operator selects a stream',
    () {
      final status = VideoStatus.fromJson({
        'enabled': true,
        'gateway': {'online': true, 'detail': 'MediaMTX API 在线'},
        'streams': [
          {
            'name': 'back_camera',
            'enabled': true,
            'status': 'online',
            'resolution': '640x480',
            'fps': 10,
            'source_topic': '/back_camera/image_raw',
            'codec': 'h264',
            'url': 'http://192.168.1.2:8889/back_camera/whep',
          },
          {
            'name': 'front_camera',
            'enabled': true,
            'status': 'online',
            'resolution': '1280x720',
            'fps': 15,
            'source_topic': '/front_camera/image_raw',
            'codec': 'h264',
            'url': 'http://192.168.1.2:8889/front_camera/whep',
          },
        ],
      });

      final stream = status.primaryStream;

      expect(stream?.name, 'front_camera');
      expect(stream?.isReadyForPlayback, isTrue);
      expect(stream?.whepUri?.path, '/front_camera/whep');
      expect(status.streamNamed('back_camera')?.name, 'back_camera');
      expect(status.streamNamed('unknown'), isNull);
    },
  );

  test('keeps an enabled stream waiting until MediaMTX marks it online', () {
    final stream = VideoStream.fromJson({
      'name': 'front_camera',
      'enabled': true,
      'status': 'waiting',
      'resolution': '1280x720',
      'fps': 15,
      'source_topic': '/front_camera/image_raw',
      'codec': 'h264',
      'url': 'http://robot.local:8889/front_camera/whep',
    });

    expect(stream.availability, VideoStreamAvailability.waiting);
    expect(stream.isReadyForPlayback, isFalse);
  });

  test('rejects a video stream without a configured name', () {
    expect(
      () => VideoStream.fromJson({'enabled': false, 'status': 'disabled'}),
      throwsFormatException,
    );
  });
}
