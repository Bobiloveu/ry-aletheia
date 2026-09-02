import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import 'camera_bridge.dart';
import 'cloud_bridge.dart';

/// 2D vs 3D scene mode.
enum VizViewMode { twoD, threeD }

/// Optional scene layers. Only the ones needed for the current milestone are
/// rendered; the rest are architecture hooks.
enum VizLayer {
  occupancyMap,
  grid,
  pointCloud,
  robot,
  trajectory,
  path,
  obstacle,
  costmap,
}

/// Actions emitted by the Android native map-chrome hit layer.
///
/// Hybrid composition keeps Unity's real SurfaceView correctly clipped to the
/// Flutter card, but the native view owns hit testing in that rectangle. Map
/// chrome therefore forwards these small HMI intents back to Flutter.
enum VisualizationMapAction { camera, recenter, fullscreen, refresh }

/// Complete logical viewport for a 2D Unity map projection.
///
/// Flutter owns these values because it owns the layout and the gesture
/// transform.  Supplying the dimensions, pixels-per-metre and centre in one
/// immutable packet prevents a native SurfaceView resize from mixing a new
/// render buffer with a camera calculated for an old card/fullscreen host.
@immutable
class VizViewport {
  const VizViewport({
    required this.width,
    required this.height,
    required this.pixelsPerMetre,
    required this.centerX,
    required this.centerY,
    required this.revision,
  });

  final double width;
  final double height;
  final double pixelsPerMetre;
  final double centerX;
  final double centerY;
  final int revision;

  bool get isValid =>
      width.isFinite &&
      width > 0 &&
      height.isFinite &&
      height > 0 &&
      pixelsPerMetre.isFinite &&
      pixelsPerMetre > 0 &&
      centerX.isFinite &&
      centerY.isFinite &&
      revision >= 0;

  Map<String, dynamic> toJson() => {
    'viewportWidth': width,
    'viewportHeight': height,
    'pixelsPerMetre': pixelsPerMetre,
    'centerX': centerX,
    'centerY': centerY,
    'viewportRevision': revision,
  };
}

/// Camera transform, owned by Flutter. In 2D only [scale] and [offset] are
/// used; in 3D [orbitYaw]/[orbitPitch]/[distance] drive an orbit rig around
/// [target].
@immutable
class VizCameraState {
  const VizCameraState({
    this.scale = 1.0,
    this.offset = Offset.zero,
    this.orbitYaw = 0.0,
    this.orbitPitch = 0.6,
    this.distance = 20.0,
    this.target = Offset.zero,
  });

  final double scale;
  final Offset offset;
  final double orbitYaw;
  final double orbitPitch;
  final double distance;
  final Offset target;

  /// Legacy in-message representation. Keep this for the explicit fallback
  /// path and wire-contract compatibility, but do not use it for normal live
  /// maps: a production occupancy raster can be many megabytes and must not
  /// become one giant UnitySendMessage string on the iOS main thread.
  Map<String, dynamic> toJson() => {
    'scale': scale,
    'ox': offset.dx,
    'oy': offset.dy,
    'yaw': orbitYaw,
    'pitch': orbitPitch,
    'distance': distance,
    'tx': target.dx,
    'ty': target.dy,
  };
}

/// Everything Unity needs to place the occupancy raster in world metres.
/// Derived from the existing `LiveMapMetadata` on the Flutter side so Unity
/// never parses robot payloads.
@immutable
class VizMapDescriptor {
  const VizMapDescriptor({
    required this.id,
    required this.pngBytes,
    required this.widthPx,
    required this.heightPx,
    required this.resolution,
    required this.originX,
    required this.originY,
    required this.vehicleLengthM,
    required this.vehicleWidthM,
    this.virtualWalls = const [],
  });

  final String id;
  final Uint8List pngBytes;
  final int widthPx;
  final int heightPx;
  final double resolution;
  final double originX;
  final double originY;
  final double vehicleLengthM;
  final double vehicleWidthM;

  /// Each wall is a flat `[x0,y0,x1,y1,...]` list in world metres.
  final List<Float32List> virtualWalls;

  Map<String, dynamic> toJson() => {
    'id': id,
    // Raster rides as base64 so the Unity JsonUtility envelope stays flat.
    // Sent once per map switch only — never on the pose/cloud hot path.
    'png': base64Encode(pngBytes),
    'w': widthPx,
    'h': heightPx,
    'res': resolution,
    'ox': originX,
    'oy': originY,
    'vlen': vehicleLengthM,
    'vwid': vehicleWidthM,
    'walls': _wallsJson(),
  };

  /// Normal renderer message. The original PNG stays byte-for-byte intact in
  /// [pngPath]; Unity loads it asynchronously from the shared app sandbox.
  Map<String, dynamic> toPathJson(String pngPath) => {
    'id': id,
    'pngPath': pngPath,
    'w': widthPx,
    'h': heightPx,
    'res': resolution,
    'ox': originX,
    'oy': originY,
    'vlen': vehicleLengthM,
    'vwid': vehicleWidthM,
    'walls': _wallsJson(),
  };

  /// Keep virtual walls in the same world-metre coordinate system as the
  /// raster, cloud and robot.  They are a small static map layer, so they can
  /// travel with the one-time map descriptor without touching the telemetry
  /// hot path.
  List<Map<String, List<double>>> _wallsJson() => virtualWalls
      // Unity's JsonUtility reliably supports an array of serializable
      // objects. Avoid a jagged primitive-array contract here: it works in
      // some editor versions but is not dependable in stripped iOS players.
      .map(
        (wall) => {
          'p': wall.map((coordinate) => coordinate.toDouble()).toList(),
        },
      )
      .toList(growable: false);
}

/// Render telemetry polled back from Unity for the diagnostics HTTP post that
/// Flutter already owns. Unity never calls the network.
@immutable
class VizRenderMetrics {
  const VizRenderMetrics({
    required this.fps,
    required this.frameMsP50,
    required this.frameMsP95,
    required this.lastPointCount,
    required this.cloudSeq,
  });

  final double fps;
  final double frameMsP50;
  final double frameMsP95;
  final int lastPointCount;
  final int cloudSeq;

  static const zero = VizRenderMetrics(
    fps: 0,
    frameMsP50: 0,
    frameMsP95: 0,
    lastPointCount: 0,
    cloudSeq: 0,
  );
}

/// Drives one embedded Unity surface. Created by [AletheiaVisualizationView]
/// once the platform view exists. All control traffic is small and goes over a
/// [MethodChannel]; the point cloud goes over FFI via [CloudBridge].
class VisualizationController {
  VisualizationController(int viewId)
    : _viewId = viewId,
      _channel = MethodChannel('aletheia_visualization/surface_$viewId'),
      _cloud = CloudBridge.instanceOrNull(),
      _camera = CameraBridge.instanceOrNull() {
    _channel.setMethodCallHandler(_handleNativeMethodCall);
  }

  final int _viewId;
  final MethodChannel _channel;
  final CloudBridge? _cloud;
  final CameraBridge? _camera;

  Timer? _metricsTimer;
  final _metrics = ValueNotifier<VizRenderMetrics>(VizRenderMetrics.zero);
  bool _isDisposed = false;
  String? _lastDebugMetricsSummary;
  void Function(VisualizationMapAction action)? _mapActionHandler;
  ValueListenable<VizRenderMetrics> get metrics => _metrics;
  bool get isDisposed => _isDisposed;

  /// Installs the current Flutter HMI handler for native map chrome.
  void setMapActionHandler(
    void Function(VisualizationMapAction action)? handler,
  ) {
    _mapActionHandler = handler;
  }

  Future<void> _handleNativeMethodCall(MethodCall call) async {
    if (_isDisposed || call.method != 'mapAction') return;
    final action = switch (call.arguments) {
      'camera' => VisualizationMapAction.camera,
      'recenter' => VisualizationMapAction.recenter,
      'fullscreen' => VisualizationMapAction.fullscreen,
      'refresh' => VisualizationMapAction.refresh,
      _ => null,
    };
    if (action != null) _mapActionHandler?.call(action);
  }

  /// True when the FFI cloud path is available in this build.
  bool get hasCloudBridge => _cloud != null;

  /// True when high-frequency pan/pinch bypasses the platform channel.
  bool get hasCameraBridge => _camera != null;

  /// Sends the raster by path rather than base64 whenever the app sandbox is
  /// writable. This preserves the exact map supplied by the robot while
  /// keeping JSON parsing and UnitySendMessage bounded on the UI thread.
  Future<void> loadMap(VizMapDescriptor map) async {
    try {
      // The Unity runtime is process-wide while Flutter temporarily keeps the
      // card and fullscreen PlatformViews alive together. Claim the native
      // camera slot before sending any scene state so an outgoing surface can
      // never apply its last pan/pinch intent to this view.
      await _invoke('activateSession', {'owner': _viewId});
      final path = await _stageMapRaster(map);
      await _invoke('loadMap', map.toPathJson(path));
    } on FileSystemException {
      // Renderer transport must not make the otherwise valid map unavailable
      // on a restrictive host. The native receiver keeps the pre-existing
      // base64 route solely for this uncommon fallback.
      await _invoke('loadMap', map.toJson());
    }
  }

  Future<String> _stageMapRaster(VizMapDescriptor map) async {
    // Map IDs are backend-provided strings, so encode them before using a
    // filename. Include the byte length to prevent an old raster with the same
    // ID being reused while the robot updates a map in place.
    final safeId = base64Url
        .encode(utf8.encode('${map.id}:${map.pngBytes.length}'))
        .replaceAll('=', '');
    final file = File('${Directory.systemTemp.path}/aletheia-viz-$safeId.png');
    await file.writeAsBytes(map.pngBytes, flush: true);
    return file.path;
  }

  Future<void> setPose(double x, double y, double yaw, {int seq = 0}) =>
      _invoke('setPose', {'x': x, 'y': y, 'yaw': yaw, 'seq': seq});

  Future<void> setCamera(
    VizCameraState camera, {
    required VizViewport viewport,
  }) {
    final staged = _camera?.stage(
      owner: _viewId,
      scale: camera.scale,
      offset: camera.offset,
      orbitYaw: camera.orbitYaw,
      orbitPitch: camera.orbitPitch,
      distance: camera.distance,
      target: camera.target,
      viewport: viewport,
    );
    if (staged == true) return Future<void>.value();
    // Keep the existing low-frequency message path for hosts built before the
    // new bridge ABI, including unit-test and Flutter-only configurations.
    return _invoke('setCamera', {...camera.toJson(), ...viewport.toJson()});
  }

  Future<void> setViewMode(VizViewMode mode) =>
      _invoke('setViewMode', mode == VizViewMode.threeD ? '3d' : '2d');

  Future<void> setLayerVisible(VizLayer layer, bool visible) =>
      _invoke('setLayer', {'layer': layer.name, 'v': visible});

  /// Waits until Unity's `VizRoot` has run `Start`. Sending a map before this
  /// point loses it because UnitySendMessage intentionally drops calls to a
  /// scene object that has not been instantiated yet.
  Future<bool> waitUntilReady({
    Duration timeout = const Duration(seconds: 3),
  }) async {
    final deadline = DateTime.timestamp().add(timeout);
    while (!_isDisposed && DateTime.timestamp().isBefore(deadline)) {
      try {
        final ready = await _channel.invokeMethod<bool>('isReady') ?? false;
        if (ready) return true;
      } on PlatformException {
        return false;
      } on MissingPluginException {
        // A stale platform-view channel can disappear during an Android
        // rotation. The replacement view owns its own readiness probe.
        return false;
      }
      await Future<void>.delayed(const Duration(milliseconds: 50));
    }
    return false;
  }

  /// Stages a decoded cloud frame for Unity. Zero-copy beyond one bulk fill of
  /// the reused native scratch buffer. Silently a no-op when the FFI bridge is
  /// unavailable (Flutter keeps its own renderer as fallback).
  /// Stages the latest cloud and returns its native sequence. A negative
  /// return value means this build has no native bridge or rejected the frame.
  int pushCloud(Float32List packedMapPoints, {bool threeD = false}) {
    return _cloud?.stage(
          packedMapPoints,
          layout: threeD ? CloudLayout.xyz : CloudLayout.xy,
        ) ??
        -1;
  }

  Future<void> pause() => _channel.invokeMethod('pause');
  Future<void> resume() => _channel.invokeMethod('resume');

  void startMetricsPolling({Duration interval = const Duration(seconds: 1)}) {
    if (_isDisposed) return;
    _metricsTimer?.cancel();
    _metricsTimer = Timer.periodic(interval, (_) async {
      try {
        final raw = await _channel.invokeMapMethod<String, dynamic>(
          'readMetrics',
        );
        if (raw == null) return;
        _metrics.value = VizRenderMetrics(
          fps: (raw['fps'] as num?)?.toDouble() ?? 0,
          frameMsP50: (raw['p50'] as num?)?.toDouble() ?? 0,
          frameMsP95: (raw['p95'] as num?)?.toDouble() ?? 0,
          lastPointCount: (raw['points'] as num?)?.toInt() ?? 0,
          cloudSeq: (raw['seq'] as num?)?.toInt() ?? 0,
        );
        final debugSummary =
            '${_metrics.value.fps.toStringAsFixed(1)}|'
            '${_metrics.value.frameMsP50.toStringAsFixed(1)}|'
            '${_metrics.value.lastPointCount}|${_metrics.value.cloudSeq}';
        if (kDebugMode && _lastDebugMetricsSummary != debugSummary) {
          _lastDebugMetricsSummary = debugSummary;
          debugPrint(
            '[UnityViz] renderer metrics '
            'fps=${_metrics.value.fps.toStringAsFixed(1)} '
            'p50=${_metrics.value.frameMsP50.toStringAsFixed(1)}ms '
            'points=${_metrics.value.lastPointCount} '
            'cloudSeq=${_metrics.value.cloudSeq}',
          );
        }
      } on PlatformException {
        // Metrics are diagnostic only.
      }
    });
  }

  Future<void> dispose() async {
    if (_isDisposed) return;
    _isDisposed = true;
    _metricsTimer?.cancel();
    _metricsTimer = null;
    _mapActionHandler = null;
    _channel.setMethodCallHandler(null);
    try {
      // A Flutter platform view can be recreated while rotating or switching
      // between map and video. Keep the process-wide Unity instance alive and
      // let the next view reattach it; unloading or resetting the shared FFI
      // bridge here races that replacement and makes its map camera unstable.
      await _channel.invokeMethod('pause');
    } on PlatformException {
      // The surface may already be gone during a lifecycle transition.
    }
    _metrics.dispose();
  }

  Future<void> _invoke(String method, [Object? arguments]) {
    if (_isDisposed) return Future<void>.value();
    return _channel.invokeMethod<void>(method, arguments);
  }
}
