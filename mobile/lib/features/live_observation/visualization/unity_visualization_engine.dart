import 'dart:async';
import 'dart:math' as math;

import 'package:aletheia_visualization/aletheia_visualization.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter/scheduler.dart';

import '../../../app/theme/aletheia_theme.dart';
import '../application/cloud_telemetry_provider.dart';
import '../application/pose_telemetry_provider.dart';
import '../data/cloud_telemetry_client.dart';
import '../data/pose_telemetry_client.dart';
import '../domain/live_map.dart';
import '../domain/pose_frame.dart';
import 'visualization_engine.dart';
import 'unity_viewport.dart';

/// Renders the live scene with an embedded Unity instance.
///
/// PoC engine, opt-in via `--dart-define=AV_ENGINE=unity`. It is a renderer
/// only: it consumes the same Riverpod telemetry streams as the Flutter
/// renderer and forwards a map, a pose, a camera transform and the packed
/// point-cloud buffer to Unity. No robot comms, no business logic, no video.
///
/// If the native module is absent (a build made before the Unity export was
/// wired in), the surface shows a notice and the app should fall back to
/// [FlutterVisualizationEngine].
class UnityVisualizationEngine implements VisualizationEngine {
  const UnityVisualizationEngine();

  @override
  Widget buildMapSurface({
    required LiveMapAsset map,
    required MapCameraFollowController cameraFollowController,
    required MapSurfaceActions actions,
  }) => _UnityMapSurface(
    key: ValueKey('unity-viz-${map.id}'),
    map: map,
    cameraFollowController: cameraFollowController,
    actions: actions,
  );
}

class _UnityMapSurface extends ConsumerStatefulWidget {
  const _UnityMapSurface({
    required this.map,
    required this.cameraFollowController,
    required this.actions,
    super.key,
  });

  final LiveMapAsset map;
  final MapCameraFollowController cameraFollowController;
  final MapSurfaceActions actions;

  @override
  ConsumerState<_UnityMapSurface> createState() => _UnityMapSurfaceState();
}

class _UnityMapSurfaceState extends ConsumerState<_UnityMapSurface>
    with WidgetsBindingObserver, SingleTickerProviderStateMixin {
  VisualizationController? _controller;
  VizCameraState _camera = const VizCameraState();
  bool _receivedFirstCloud = false;
  bool _mapReadyForTelemetry = false;
  bool _hasInitialPoseFocus = false;
  PoseFrame? _latestPose;
  // These snapshots are refreshed synchronously during build/listen. A
  // platform view's `onCreated` may complete after its ProviderScope was
  // replaced by a fullscreen route, so that asynchronous callback must never
  // try to read Riverpod directly.
  PoseTelemetrySample? _cachedPose;
  CloudTelemetrySample? _cachedCloud;
  Size? _viewportSize;
  int _viewportRevision = 0;
  // This drives only the fixed Flutter HUD scale reference. The Unity scene
  // remains the sole map renderer; keeping the label outside the Metal view
  // means a pan cannot make the operator lose the distance reference.
  final ValueNotifier<double> _cameraScale = ValueNotifier<double>(1);

  // Keep gesture state on the Flutter side.  Unity is deliberately a pure
  // renderer: it receives a single camera intent for a whole MapCanvas rather
  // than trying to arbitrate iOS touches inside an embedded surface.
  final Map<int, Offset> _pointerPositions = <int, Offset>{};
  int? _singlePanPointer;
  Offset _singlePanStart = Offset.zero;
  VizCameraState _singlePanCameraStart = const VizCameraState();
  double _scaleAtGestureStart = 1;
  double _pinchSpanAtGestureStart = 0;
  Offset _mapOffsetAtGestureAnchor = Offset.zero;
  bool _cameraSyncScheduled = false;
  late final AnimationController _followAnimation;
  Offset _followAnimationStart = Offset.zero;
  Offset _followAnimationTarget = Offset.zero;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    widget.cameraFollowController.addListener(_handleFollowControlChanged);
    _followAnimation = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 240),
    )..addListener(_applyFollowAnimationFrame);
  }

  @override
  void didUpdateWidget(covariant _UnityMapSurface oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.map.id != widget.map.id) {
      _hasInitialPoseFocus = false;
      _latestPose = null;
      _followAnimation.stop();
      unawaited(_pushMap());
    }
    if (oldWidget.cameraFollowController != widget.cameraFollowController) {
      oldWidget.cameraFollowController.removeListener(
        _handleFollowControlChanged,
      );
      widget.cameraFollowController.addListener(_handleFollowControlChanged);
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    widget.cameraFollowController.removeListener(_handleFollowControlChanged);
    _followAnimation
      ..removeListener(_applyFollowAnimationFrame)
      ..dispose();
    _controller?.setMapActionHandler(null);
    _controller?.dispose();
    _cameraScale.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _controller?.resume();
    } else {
      _controller?.pause();
    }
  }

  Future<void> _onCreated(VisualizationController controller) async {
    _controller = controller;
    controller.setMapActionHandler(_handleNativeMapAction);
    final ready = await controller.waitUntilReady();
    if (!mounted ||
        controller.isDisposed ||
        !identical(_controller, controller)) {
      return;
    }
    controller.startMetricsPolling();
    // The readiness bridge is advisory. On iOS Unity runs inside a separately
    // linked framework, so a bridge symbol can be unavailable even when the
    // `VizRoot` scene is already running. Never let that diagnostic handshake
    // suppress the actual map payload: by the bounded wait above Unity has had
    // time to construct its scene, and the native receiver also owns a small
    // retry for the first map message.
    //
    // Both the ready and timed-out paths must render the same real robot map.
    if (kDebugMode) {
      debugPrint('[UnityViz] surface ready=$ready; sending initial map');
    }
    await _pushMap();
    if (!mounted ||
        controller.isDisposed ||
        !identical(_controller, controller)) {
      return;
    }
    _replayLatestTelemetry(controller);
  }

  void _handleNativeMapAction(VisualizationMapAction action) {
    if (!mounted) return;
    switch (action) {
      case VisualizationMapAction.camera:
        widget.actions.onShowCamera();
      case VisualizationMapAction.recenter:
        widget.actions.onRecenter();
      case VisualizationMapAction.fullscreen:
        widget.actions.onToggleFullscreen();
      case VisualizationMapAction.refresh:
        widget.actions.onRefresh();
    }
  }

  /// The stream listeners intentionally do not use `fireImmediately`: this
  /// avoids repeatedly uploading stale scans during ordinary rebuilds. Unity
  /// itself, however, is created after this widget's first build and could
  /// otherwise miss the one latest-wins frame already held by Riverpod. Replay
  /// that bounded cached state exactly once after the native surface is ready.
  void _replayLatestTelemetry(VisualizationController controller) {
    final pose = _cachedPose;
    if (pose != null) {
      unawaited(_forwardPose(controller, pose.frame));
    }

    final cloud = _cachedCloud;
    if (cloud == null) {
      if (kDebugMode) {
        debugPrint(
          '[UnityViz] no cached cloud yet; nativeBridge='
          '${controller.hasCloudBridge}',
        );
      }
      return;
    }
    final nativeSequence = controller.pushCloud(cloud.frame.packedMapPoints);
    if (kDebugMode) {
      debugPrint(
        '[UnityViz] replayed cached cloud points=${cloud.frame.pointCount} '
        'sourceSeq=${cloud.frame.sequence} nativeSeq=$nativeSequence '
        'nativeBridge=${controller.hasCloudBridge}',
      );
    }
  }

  Future<void> _pushMap() async {
    final map = widget.map;
    _mapReadyForTelemetry = false;
    _hasInitialPoseFocus = false;
    _latestPose = null;
    _followAnimation.stop();
    // This must start from exactly the same visible world width as the
    // CustomPaint map.  A fixed 16 m "working" view looked acceptable on a
    // wide desktop surface, but cropped tall maps on phones and made a card
    // <-> fullscreen transition appear to stretch the raster.
    final savedCamera = widget.cameraFollowController.snapshotForMap(map.id);
    final overviewScale = _overviewScaleFor(_viewportSize);
    _camera = savedCamera == null
        ? VizCameraState(scale: overviewScale)
        : VizCameraState(
            // A card and its fullscreen route have different map-cover
            // overviews. Restore the operator's relative zoom into this
            // host's overview rather than replaying the old host's absolute
            // Unity scalar.
            scale: savedCamera.scaleForOverview(overviewScale),
            offset: savedCamera.offset,
          );
    _cameraScale.value = _camera.scale;
    if (kDebugMode) {
      debugPrint(
        '[UnityViz] loadMap id=${map.id} png=${map.previewBytes.length}B '
        '${map.metadata.width}x${map.metadata.height} '
        'resolution=${map.metadata.resolution}',
      );
    }
    final controller = _controller;
    if (controller == null || controller.isDisposed) return;
    await controller.loadMap(
      VizMapDescriptor(
        id: map.id,
        pngBytes: map.previewBytes,
        widthPx: map.metadata.width,
        heightPx: map.metadata.height,
        resolution: map.metadata.resolution,
        originX: map.metadata.originX,
        originY: map.metadata.originY,
        vehicleLengthM: map.vehicleFootprint.lengthMeters,
        vehicleWidthM: map.vehicleFootprint.widthMeters,
        virtualWalls: _wallsToWorld(map),
      ),
    );
    // Camera state is Flutter-owned. Sending it immediately after the static
    // map lets a newly attached/fullscreen Unity surface restore the same
    // CustomPaint-equivalent overview before live pose data arrives.
    if (!mounted ||
        controller.isDisposed ||
        !identical(_controller, controller)) {
      return;
    }
    await _sendCamera(controller);
    _persistCamera();
    _mapReadyForTelemetry = true;
  }

  /// Place the first real pose at the centre of Flutter's camera model before
  /// forwarding it to Unity.  Without this, Unity's temporary pose focus and
  /// Flutter's zero map-centre offset disagree; the first drag then appears to
  /// jump back to a map overview instead of moving the current canvas.
  Future<void> _forwardPose(
    VisualizationController controller,
    PoseFrame frame,
  ) async {
    if (!mounted ||
        controller.isDisposed ||
        !identical(_controller, controller) ||
        !_mapReadyForTelemetry) {
      return;
    }
    _latestPose = frame;
    if (!_hasInitialPoseFocus) {
      _hasInitialPoseFocus = true;
      _camera = _cameraForPose(frame);
      _persistCamera();
      await _sendCamera(controller);
      if (!mounted ||
          controller.isDisposed ||
          !identical(_controller, controller)) {
        return;
      }
    } else if (widget.cameraFollowController.isFollowing) {
      _animateFollowTo(frame);
    }
    await controller.setPose(frame.x, frame.y, frame.yaw, seq: frame.sequence);
  }

  VizCameraState _cameraForPose(PoseFrame frame) {
    final metadata = widget.map.metadata;
    return VizCameraState(
      scale: _camera.scale,
      offset: Offset(
        frame.x - metadata.originX - metadata.worldWidth / 2,
        frame.y - metadata.originY - metadata.worldHeight / 2,
      ),
    );
  }

  void _handleFollowControlChanged() {
    if (!widget.cameraFollowController.isFollowing) {
      _followAnimation.stop();
      return;
    }
    final pose = _latestPose;
    if (pose != null) _animateFollowTo(pose);
  }

  void _animateFollowTo(PoseFrame pose) {
    if (!mounted || !_mapReadyForTelemetry) return;
    _followAnimationStart = _camera.offset;
    _followAnimationTarget = _cameraForPose(pose).offset;
    if ((_followAnimationTarget - _followAnimationStart).distance < .002) {
      return;
    }
    _followAnimation.forward(from: 0);
  }

  void _applyFollowAnimationFrame() {
    if (!mounted || !widget.cameraFollowController.isFollowing) return;
    final t = Curves.easeOutCubic.transform(_followAnimation.value);
    _camera = VizCameraState(
      scale: _camera.scale,
      offset: Offset.lerp(_followAnimationStart, _followAnimationTarget, t)!,
    );
    _persistCamera();
    _scheduleCameraSync();
  }

  List<Float32List> _wallsToWorld(LiveMapAsset map) {
    final meta = map.metadata;
    return map.virtualWalls
        .map((wall) {
          final flat = Float32List(wall.points.length * 2);
          for (var i = 0; i < wall.points.length; i++) {
            final p = wall.points[i];
            final worldX =
                wall.coordinateMode == VirtualWallCoordinateMode.world
                ? p.x
                : meta.originX + p.x;
            final worldY =
                wall.coordinateMode == VirtualWallCoordinateMode.world
                ? p.y
                : meta.originY + p.y;
            flat[i * 2] = worldX;
            flat[i * 2 + 1] = worldY;
          }
          return flat;
        })
        .toList(growable: false);
  }

  @override
  Widget build(BuildContext context) {
    // Same telemetry streams the Flutter renderer uses; forwarded to Unity.
    // Do not `watch` either stream here: a 60 Hz pose update would rebuild the
    // whole Android PlatformView and force a SurfaceView layout transaction
    // every frame. A long-lived listener keeps auto-dispose providers alive
    // while routing each latest sample directly into Unity instead.
    _cachedPose = ref
        .read(poseTelemetryProvider)
        .maybeWhen(data: (value) => value, orElse: () => null);
    _cachedCloud = ref
        .read(cloudTelemetryProvider)
        .maybeWhen(data: (value) => value, orElse: () => null);
    ref.listen(poseTelemetryProvider, (_, next) {
      next.whenData((sample) {
        _cachedPose = sample;
        final controller = _controller;
        if (controller != null) {
          unawaited(_forwardPose(controller, sample.frame));
        }
      });
    });
    ref.listen(cloudTelemetryProvider, (_, next) {
      next.whenData((sample) {
        _cachedCloud = sample;
        final nativeSequence =
            _controller?.pushCloud(sample.frame.packedMapPoints) ?? -1;
        if (kDebugMode && !_receivedFirstCloud) {
          _receivedFirstCloud = true;
          debugPrint(
            '[UnityViz] received cloud points=${sample.frame.pointCount} '
            'sourceSeq=${sample.frame.sequence} nativeSeq=$nativeSequence',
          );
        }
      });
    });

    return LayoutBuilder(
      builder: (context, constraints) {
        _captureViewport(constraints.biggest);
        return Stack(
          fit: StackFit.expand,
          children: [
            AletheiaVisualizationView(
              onCreated: (controller) => unawaited(_onCreated(controller)),
              onPlaceholder: (context) => ColoredBox(
                color: AletheiaTheme.surfaceSunken,
                child: Center(
                  child: Padding(
                    padding: const EdgeInsets.all(20),
                    child: Text(
                      'Unity 渲染器未构建。\n请按 unity/README.md 导出后重试，或回退 Flutter 渲染器。',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        color: AletheiaTheme.textSecondary,
                        fontSize: 12,
                        height: 1.4,
                      ),
                    ),
                  ),
                ),
              ),
            ),
            // A UIKit platform view can win iOS hit testing before a parent
            // Listener receives its move samples, even when the Unity root view
            // has interaction disabled. Keep a transparent Flutter hit target
            // physically *above* the Metal surface so pan/pinch follows the
            // same gesture arena as the proven CustomPaint map. Unity remains a
            // renderer and never handles HMI gestures itself.
            Positioned.fill(
              child: RawGestureDetector(
                key: const ValueKey('unity-map-gesture-surface'),
                behavior: HitTestBehavior.opaque,
                // Claim the pointer sequence before the page's ListView. This
                // means a vertical pan is always a canvas pan, never a partial
                // scroll of the page.
                gestures: <Type, GestureRecognizerFactory>{
                  EagerGestureRecognizer:
                      GestureRecognizerFactoryWithHandlers<
                        EagerGestureRecognizer
                      >(EagerGestureRecognizer.new, (recognizer) {}),
                },
                child: Listener(
                  behavior: HitTestBehavior.opaque,
                  onPointerDown: (event) =>
                      _recordPointerDown(event, constraints),
                  onPointerMove: (event) =>
                      _recordPointerMove(event, constraints),
                  onPointerUp: _recordPointerEnd,
                  onPointerCancel: _recordPointerEnd,
                  child: const SizedBox.expand(),
                ),
              ),
            ),
            Positioned(
              left: 8,
              bottom: 8,
              child: IgnorePointer(
                child: ValueListenableBuilder<double>(
                  valueListenable: _cameraScale,
                  builder: (context, scale, _) {
                    final pixelsPerMetre = _pixelsPerMetre(scale, constraints);
                    final metresPerGrid = _gridStepFor(pixelsPerMetre);
                    return _UnityMapScaleReference(
                      metresPerGrid: metresPerGrid,
                      pixelsPerMetre: pixelsPerMetre,
                    );
                  },
                ),
              ),
            ),
          ],
        );
      },
    );
  }

  double _overviewScaleFor(Size? viewport) {
    final metadata = widget.map.metadata;
    final worldWidth = metadata.worldWidth;
    final worldHeight = metadata.worldHeight;
    if (viewport == null ||
        viewport.isEmpty ||
        worldWidth <= 0 ||
        worldHeight <= 0) {
      return 1;
    }

    // Mirrors _MapViewportState._mapSizeFor in live_observation_screen.dart.
    // It deliberately covers the view without altering the map aspect ratio.
    final mapAspect = worldWidth / worldHeight;
    final viewportAspect = viewport.width / viewport.height;
    final mapPixelWidth = mapAspect > viewportAspect
        ? viewport.height * mapAspect
        : viewport.width;
    final pixelsPerMetre = mapPixelWidth / worldWidth;
    final visibleWorldWidth = viewport.width / pixelsPerMetre;
    final baseViewMetres = math.max(worldWidth, worldHeight) * 1.1;
    return (baseViewMetres / visibleWorldWidth).clamp(0.01, 48.0);
  }

  void _recordPointerDown(PointerDownEvent event, BoxConstraints constraints) {
    _pointerPositions[event.pointer] = event.localPosition;
    if (_pointerPositions.length == 1) {
      _singlePanPointer = event.pointer;
      _singlePanStart = event.localPosition;
      _singlePanCameraStart = _camera;
      return;
    }
    if (_pointerPositions.length == 2) {
      _pauseFollowForDirectManipulation();
      _singlePanPointer = null;
      _setPinchAnchor(constraints);
    }
  }

  void _recordPointerMove(PointerMoveEvent event, BoxConstraints constraints) {
    if (!_pointerPositions.containsKey(event.pointer)) return;
    _pointerPositions[event.pointer] = event.localPosition;
    if (_pointerPositions.length == 1 && _singlePanPointer == event.pointer) {
      final delta = event.localPosition - _singlePanStart;
      if (delta.distanceSquared > 16) {
        _pauseFollowForDirectManipulation();
      }
      final metresPerPixel = _metresPerPixel(
        _singlePanCameraStart.scale,
        constraints,
      );
      _camera = VizCameraState(
        scale: _singlePanCameraStart.scale,
        offset: Offset(
          _singlePanCameraStart.offset.dx - delta.dx * metresPerPixel,
          _singlePanCameraStart.offset.dy + delta.dy * metresPerPixel,
        ),
      );
      _persistCamera();
      _scheduleCameraSync();
      return;
    }
    if (_pointerPositions.length < 2 || _pinchSpanAtGestureStart <= 0) return;

    final scale =
        (_scaleAtGestureStart * (_pointerSpan / _pinchSpanAtGestureStart))
            .clamp(1.0, 48.0);
    final focal = _pointerCentroid;
    final viewportCentre = Offset(
      constraints.maxWidth / 2,
      constraints.maxHeight / 2,
    );
    final metresPerPixel = _metresPerPixel(scale, constraints);
    // Hold the map-world point below the centroid fixed while zooming. This
    // avoids the recognizer's moving focal point producing the common “rubber
    // band” feel and mirrors the original Flutter canvas implementation.
    _camera = VizCameraState(
      scale: scale,
      offset: Offset(
        _mapOffsetAtGestureAnchor.dx -
            (focal.dx - viewportCentre.dx) * metresPerPixel,
        _mapOffsetAtGestureAnchor.dy +
            (focal.dy - viewportCentre.dy) * metresPerPixel,
      ),
    );
    _cameraScale.value = scale;
    _persistCamera();
    _scheduleCameraSync();
  }

  void _recordPointerEnd(PointerEvent event) {
    _pointerPositions.remove(event.pointer);
    if (_pointerPositions.length == 1) {
      final remaining = _pointerPositions.entries.single;
      _singlePanPointer = remaining.key;
      _singlePanStart = remaining.value;
      _singlePanCameraStart = _camera;
    } else {
      _singlePanPointer = null;
      _pinchSpanAtGestureStart = 0;
    }
  }

  void _pauseFollowForDirectManipulation() {
    widget.cameraFollowController.pauseForDirectManipulation();
  }

  Offset get _pointerCentroid {
    var x = 0.0;
    var y = 0.0;
    for (final position in _pointerPositions.values) {
      x += position.dx;
      y += position.dy;
    }
    return Offset(x / _pointerPositions.length, y / _pointerPositions.length);
  }

  double get _pointerSpan {
    final positions = _pointerPositions.values.take(2).toList(growable: false);
    return (positions.first - positions.last).distance;
  }

  void _setPinchAnchor(BoxConstraints constraints) {
    _scaleAtGestureStart = _camera.scale;
    _pinchSpanAtGestureStart = _pointerSpan;
    final focal = _pointerCentroid;
    final viewportCentre = Offset(
      constraints.maxWidth / 2,
      constraints.maxHeight / 2,
    );
    final metresPerPixel = _metresPerPixel(_scaleAtGestureStart, constraints);
    _mapOffsetAtGestureAnchor = Offset(
      _camera.offset.dx + (focal.dx - viewportCentre.dx) * metresPerPixel,
      _camera.offset.dy - (focal.dy - viewportCentre.dy) * metresPerPixel,
    );
  }

  double _metresPerPixel(double scale, BoxConstraints constraints) {
    final metadata = widget.map.metadata;
    final baseViewMetres =
        math.max(metadata.worldWidth, metadata.worldHeight) * 1.1;
    // `scale` is relative to the Unity map's stable base view.  Its initial
    // value comes from _overviewScaleFor, so this uses the same viewport
    // geometry as Flutter's CustomPaint renderer in portrait and fullscreen.
    return baseViewMetres / scale / math.max(1.0, constraints.maxWidth);
  }

  double _pixelsPerMetre(double scale, BoxConstraints constraints) =>
      1 / _metresPerPixel(scale, constraints);

  void _captureViewport(Size size) {
    if (size.isEmpty || _viewportSize == size) return;
    _viewportSize = size;
    _viewportRevision++;
    // Layout is the source of truth. Publish a fresh *complete* camera packet
    // after the current frame rather than allowing Unity to infer a projection
    // from a transient Android SurfaceView size during route/fullscreen swaps.
    final revision = _viewportRevision;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted && revision == _viewportRevision) _scheduleCameraSync();
    });
  }

  VizViewport? get _currentViewport {
    final size = _viewportSize;
    if (size == null || size.isEmpty) return null;
    return UnityViewport.fromFlutter(
      map: widget.map.metadata,
      camera: _camera,
      size: size,
      revision: _viewportRevision,
    );
  }

  Future<void> _sendCamera(VisualizationController controller) {
    final viewport = _currentViewport;
    if (viewport == null) return Future<void>.value();
    return controller.setCamera(_camera, viewport: viewport);
  }

  /// Native camera staging is a latest-wins scalar write and can safely accept
  /// each touch sample. Older framework builds retain the MethodChannel
  /// fallback, which stays coalesced to a single Flutter frame.
  void _scheduleCameraSync() {
    final controller = _controller;
    if (mounted &&
        controller != null &&
        !controller.isDisposed &&
        controller.hasCameraBridge) {
      unawaited(_sendCamera(controller));
      return;
    }
    if (_cameraSyncScheduled) return;
    _cameraSyncScheduled = true;
    SchedulerBinding.instance.scheduleFrame();
    SchedulerBinding.instance.scheduleFrameCallback((_) {
      _cameraSyncScheduled = false;
      final controller = _controller;
      if (mounted && controller != null && !controller.isDisposed) {
        unawaited(_sendCamera(controller));
      }
    });
  }

  void _persistCamera() {
    final overviewScale = _overviewScaleFor(_viewportSize);
    if (overviewScale <= 0) return;
    widget.cameraFollowController.saveUnitySnapshot(
      mapId: widget.map.id,
      scale: _camera.scale,
      offset: _camera.offset,
      overviewScale: overviewScale,
    );
  }
}

double _gridStepFor(double pixelsPerMetre) {
  for (final metres in const [0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0]) {
    if (pixelsPerMetre * metres >= 26) return metres;
  }
  return 20;
}

String _formatUnityDistance(double metres) {
  if (metres < 1) return '${(metres * 100).round()} cm';
  return metres == metres.roundToDouble()
      ? '${metres.toInt()} m'
      : '${metres.toStringAsFixed(1)} m';
}

/// Fixed-HUD distance reference for the Unity renderer. Its value and bar
/// width follow the exact same zoom state used to choose Unity's metre grid,
/// so pinch is continuous and a grid-step threshold changes both together.
class _UnityMapScaleReference extends StatelessWidget {
  const _UnityMapScaleReference({
    required this.metresPerGrid,
    required this.pixelsPerMetre,
  });

  final double metresPerGrid;
  final double pixelsPerMetre;

  @override
  Widget build(BuildContext context) {
    final barWidth = (metresPerGrid * pixelsPerMetre)
        .clamp(30.0, 104.0)
        .toDouble();
    return Semantics(
      label: '${_formatUnityDistance(metresPerGrid)} 每格',
      child: DecoratedBox(
        key: const ValueKey('unity-map-scale-reference'),
        decoration: BoxDecoration(
          color: AletheiaTheme.canvas.withValues(alpha: .88),
          border: Border.all(
            color: AletheiaTheme.divider.withValues(alpha: .88),
          ),
          borderRadius: BorderRadius.circular(6),
        ),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(7, 5, 7, 6),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '${_formatUnityDistance(metresPerGrid)} / 格',
                style: Theme.of(context).textTheme.labelSmall
                    ?.copyWith(color: AletheiaTheme.textSecondary),
              ),
              const SizedBox(height: 4),
              SizedBox(
                width: barWidth,
                height: 6,
                child: const CustomPaint(painter: _UnityScaleBarPainter()),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _UnityScaleBarPainter extends CustomPainter {
  const _UnityScaleBarPainter();

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = AletheiaTheme.textSecondary
      ..strokeWidth = 1;
    final y = size.height - .5;
    canvas.drawLine(Offset.zero, Offset(size.width, y), paint);
    canvas.drawLine(Offset(0, 0), Offset(0, y), paint);
    canvas.drawLine(Offset(size.width, 0), Offset(size.width, y), paint);
  }

  @override
  bool shouldRepaint(covariant _UnityScaleBarPainter oldDelegate) => false;
}
