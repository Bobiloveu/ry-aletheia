import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test(
    'stale Unity creation callbacks never read a disposed ProviderScope',
    () {
      final source = File(
        'lib/features/live_observation/visualization/unity_visualization_engine.dart',
      ).readAsStringSync();
      final replayStart = source.indexOf(
        'void _replayLatestTelemetry(VisualizationController controller)',
      );
      final replayEnd = source.indexOf(
        '\n  Future<void> _pushMap()',
        replayStart,
      );
      final replayMethod = source.substring(replayStart, replayEnd);

      // A platform view can report readiness after Flutter replaced the
      // ProviderScope during a fullscreen route transition. Replaying telemetry
      // must consume values cached during build/listen, never access `ref` from
      // that asynchronous callback.
      expect(replayMethod, isNot(contains('ref.read(')));
      expect(source, contains('PoseTelemetrySample? _cachedPose;'));
      expect(source, contains('CloudTelemetrySample? _cachedCloud;'));
    },
  );

  test(
    'Unity camera bridge attributes staged intents to their platform view',
    () {
      final controller = File(
        'packages/aletheia_visualization/lib/src/visualization_controller.dart',
      ).readAsStringSync();
      final dartBridge = File(
        'packages/aletheia_visualization/lib/src/camera_bridge.dart',
      ).readAsStringSync();
      final nativeBridge = File(
        'packages/aletheia_visualization/shared/aletheia_viz_bridge.h',
      ).readAsStringSync();
      final unityBridge = File(
        '../unity/aletheia_viz/Assets/Scripts/NativeCloudBridge.cs',
      ).readAsStringSync();

      // Card and fullscreen platform views coexist briefly during a route
      // swap. Their latest-wins FFI camera intents must carry an owner so a
      // departing fullscreen view cannot alter the replacement card camera.
      expect(controller, contains('final int _viewId;'));
      expect(controller, contains('owner: _viewId'));
      expect(dartBridge, contains('required int owner'));
      expect(dartBridge, contains('required VizViewport viewport'));
      expect(nativeBridge, contains('int64_t owner;'));
      expect(nativeBridge, contains('float pixels_per_metre;'));
      expect(nativeBridge, contains('int64_t viewport_revision;'));
      expect(unityBridge, contains('public long owner;'));
      expect(unityBridge, contains('public float pixels_per_metre;'));
      expect(unityBridge, contains('public long viewport_revision;'));
    },
  );

  test('disposing one PlatformView does not reset the shared Unity bridge', () {
    final source = File(
      'packages/aletheia_visualization/lib/src/visualization_controller.dart',
    ).readAsStringSync();
    final disposeStart = source.indexOf('Future<void> dispose() async');
    final disposeEnd = source.indexOf('\n  Future<void> _invoke', disposeStart);
    final disposeMethod = source.substring(disposeStart, disposeEnd);

    // A fullscreen route disposes its PlatformView after the card replacement
    // begins construction. `av_bridge_reset` is process-wide, so it belongs to
    // a true Unity runtime unload only, never to an individual view dispose.
    expect(disposeMethod, isNot(contains('_cloud?.reset()')));
  });

  test('Unity fullscreen never creates a second native map host', () {
    final source = File(
      'lib/features/live_observation/presentation/live_observation_screen.dart',
    ).readAsStringSync();

    // Unity as a Library supports one UnityPlayer.  A fullscreen interaction
    // may resize that player, but it must not push a route that builds another
    // map workspace/PlatformView while the compact workspace is still alive.
    expect(source, isNot(contains('class _MapFullscreenScreen')));
    expect(source, isNot(contains('MaterialPageRoute(')));
    expect(source, contains('void _setMapFullscreen(bool fullscreen)'));
    expect(source, contains("'unity-map-fullscreen-surface'"));
  });

  test(
    'Android renderer verifies the real Surface buffer after every resize',
    () {
      final source = File(
        'packages/aletheia_visualization/android/src/unity/kotlin/'
        'com/ryaletheia/aletheia_visualization/UnitySurfaceProviderImpl.kt',
      ).readAsStringSync();

      // `SurfaceView` owns a second size (SurfaceHolder.surfaceFrame) in
      // addition to the Flutter host layout. It must be brought back to the
      // exact host dimensions after every configuration/layout transition.
      expect(source, contains('holder.setFixedSize(width, height)'));
      expect(source, contains('verifyUnityRenderBuffer'));
      expect(source, contains('surfaceChanged'));
    },
  );

}
