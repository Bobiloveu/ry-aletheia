import 'package:flutter/foundation.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';

import 'visualization_controller.dart';

/// Hosts the embedded Unity render surface as a Flutter platform view and
/// hands back a [VisualizationController] once it exists.
///
/// The surface renders only. Gestures are captured by Flutter around it (the
/// caller wires them to [VisualizationController.setCamera]); Unity receives a
/// camera transform, never raw touches.
class AletheiaVisualizationView extends StatefulWidget {
  const AletheiaVisualizationView({
    required this.onCreated,
    this.onPlaceholder,
    super.key,
  });

  /// Called once with a live controller. May never fire on an unsupported
  /// platform — [onPlaceholder] renders instead.
  final void Function(VisualizationController controller) onCreated;

  /// Shown on platforms without the native view, or before it is ready.
  final WidgetBuilder? onPlaceholder;

  static const String viewType = 'aletheia_visualization/surface';

  @override
  State<AletheiaVisualizationView> createState() =>
      _AletheiaVisualizationViewState();
}

class _AletheiaVisualizationViewState extends State<AletheiaVisualizationView> {
  VisualizationController? _controller;

  bool get _supported =>
      defaultTargetPlatform == TargetPlatform.android ||
      defaultTargetPlatform == TargetPlatform.iOS;

  void _handleCreated(int id) {
    final controller = VisualizationController(id);
    _controller = controller;
    widget.onCreated(controller);
  }

  @override
  void dispose() {
    _controller?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (!_supported) {
      return widget.onPlaceholder?.call(context) ?? const _DefaultPlaceholder();
    }
    // The platform renderer owns no interaction in this app.  An explicit
    // empty set is required by AndroidViewSurface and lets Flutter's parent
    // GestureDetector retain pan/pinch ownership on both platforms.
    const rendererGestures = <Factory<OneSequenceGestureRecognizer>>{};
    switch (defaultTargetPlatform) {
      case TargetPlatform.android:
        // Unity owns a real Android SurfaceView. Texture/virtual-display
        // composition moves that surface to the Activity origin, ignoring the
        // Flutter card's offset and clip. Keep it in the Android hierarchy;
        // Android-native hit targets in the same host handle map chrome.
        return PlatformViewLink(
          viewType: AletheiaVisualizationView.viewType,
          surfaceFactory: (context, controller) => AndroidViewSurface(
            controller: controller as AndroidViewController,
            gestureRecognizers: rendererGestures,
            hitTestBehavior: PlatformViewHitTestBehavior.transparent,
          ),
          onCreatePlatformView: (params) {
            final controller = PlatformViewsService.initExpensiveAndroidView(
              id: params.id,
              viewType: AletheiaVisualizationView.viewType,
              layoutDirection: TextDirection.ltr,
              creationParams: const <String, dynamic>{},
              creationParamsCodec: const StandardMessageCodec(),
              onFocus: () => params.onFocusChanged(true),
            );
            // PlatformViewLink must receive its own creation callback before
            // it replaces the placeholder with the Android hybrid-composition
            // host.  Only notifying our consumer leaves the native FrameLayout
            // detached: Unity may be created, but its SurfaceView is then
            // either invisible or composited at the activity origin.
            controller.addOnPlatformViewCreatedListener((id) {
              params.onPlatformViewCreated(id);
              _handleCreated(id);
            });
            controller.create();
            return controller;
          },
        );
      case TargetPlatform.iOS:
        return UiKitView(
          viewType: AletheiaVisualizationView.viewType,
          layoutDirection: TextDirection.ltr,
          creationParams: const <String, dynamic>{},
          creationParamsCodec: const StandardMessageCodec(),
          // Unity is display-only.  On iOS a platform view otherwise becomes
          // an opaque UIKit hit-test island and steals taps from Flutter
          // controls layered above it (and, with Unity's root view, can make
          // navigation appear frozen).  The parent GestureDetector still
          // receives map pan/pinch and forwards the resulting camera state.
          gestureRecognizers: rendererGestures,
          hitTestBehavior: PlatformViewHitTestBehavior.transparent,
          onPlatformViewCreated: _handleCreated,
        );
      default:
        return widget.onPlaceholder?.call(context) ??
            const _DefaultPlaceholder();
    }
  }
}

class _DefaultPlaceholder extends StatelessWidget {
  const _DefaultPlaceholder();

  @override
  Widget build(BuildContext context) => const ColoredBox(
    color: Color(0xFF0C1011),
    child: Center(
      child: Text(
        'Unity 渲染器不可用',
        style: TextStyle(color: Color(0xFF82918F), fontSize: 12),
      ),
    ),
  );
}
