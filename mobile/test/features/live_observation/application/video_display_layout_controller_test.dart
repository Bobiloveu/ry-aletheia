import 'package:aletheia_mobile/features/live_observation/application/video_display_layout_controller.dart';
import 'package:aletheia_mobile/features/live_observation/domain/video_status.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  VideoStream stream(String name, {bool enabled = true}) => VideoStream(
    name: name,
    enabled: enabled,
    availability: enabled
        ? VideoStreamAvailability.online
        : VideoStreamAvailability.disabled,
    resolution: '1280 × 720',
    fps: 30,
    sourceTopic: '/$name',
    codec: 'H264',
    whepUri: enabled ? Uri.parse('http://robot.local/$name/whep') : null,
  );

  test(
    'keeps a three-slot local layout independent of six source switches',
    () {
      final container = ProviderContainer();
      addTearDown(container.dispose);
      final streams = [
        stream('front_camera'),
        stream('back_camera'),
        stream('left_camera'),
        stream('right_camera'),
        stream('detection_camera'),
        stream('segmentation_overlay'),
      ];
      final controller = container.read(videoDisplayLayoutProvider.notifier);

      expect(controller.resolve(streams, primaryStreamName: 'front_camera'), [
        'front_camera',
        'back_camera',
        'left_camera',
      ]);

      // The operator can keep six robot sources enabled while choosing a
      // non-adjacent source for the third local display slot.
      controller.assign(slot: 2, streamName: 'segmentation_overlay');
      expect(controller.resolve(streams, primaryStreamName: 'front_camera'), [
        'front_camera',
        'back_camera',
        'segmentation_overlay',
      ]);

      // Promoting an auxiliary source is an explicit slot swap, never a fixed
      // API-order fallback that leaves an old camera pinned on the right.
      controller.assign(slot: 0, streamName: 'detection_camera');
      expect(
        controller.resolve(streams, primaryStreamName: 'detection_camera'),
        ['detection_camera', 'front_camera', 'segmentation_overlay'],
      );
    },
  );
}
