import 'package:flutter/widgets.dart';

import '../domain/live_map.dart';

/// Renders the live spatial scene for [LiveObservationScreen]: occupancy map,
/// metre grid, point cloud, robot pose/footprint — and, in future
/// implementations, 3D point cloud, a 3D robot model and 2D/3D view switching.
///
/// The architecture boundary is fixed:
///
/// * Flutter always owns the app shell, navigation, HMI, business logic,
///   robot connection, HTTP/Binary WebSocket, state management and the six
///   WebRTC video feeds.
/// * A [VisualizationEngine] is *only* a renderer. It never touches ROS2, the
///   backend API, task JSON, mission recovery, business logic or video.
///
/// [FlutterVisualizationEngine] wraps the current `CustomPaint` renderer and is
/// kept as a permanent fallback. A Unity-backed engine is introduced behind
/// this same interface; selecting it is a runtime flag and flipping it back is
/// the entire rollback procedure.
abstract interface class VisualizationEngine {
  /// A widget that renders [map] together with the live pose and point-cloud
  /// overlays. Gesture handling and all HMI chrome (toolbars, readouts, the
  /// scale reference) stay in Flutter, outside this surface.
  Widget buildMapSurface({
    required LiveMapAsset map,
    required MapCameraFollowController cameraFollowController,
    required MapSurfaceActions actions,
  });
}

/// Flutter-owned HMI commands exposed by a map renderer.
@immutable
class MapSurfaceActions {
  const MapSurfaceActions({
    required this.onShowCamera,
    required this.onRecenter,
    required this.onToggleFullscreen,
    required this.onRefresh,
  });

  final VoidCallback onShowCamera;
  final VoidCallback onRecenter;
  final VoidCallback onToggleFullscreen;
  final VoidCallback onRefresh;
}

/// Shared HMI intent for a map renderer's camera.
///
/// The renderer owns its camera transform, but the control belongs to the
/// surrounding Flutter HMI so that Unity and the permanent CustomPaint
/// fallback behave identically. Following begins enabled, a direct map
/// gesture pauses it, and [recenterOnVehicle] is an explicit, repeatable
/// request to return to the latest valid vehicle pose.
class MapCameraFollowController extends ChangeNotifier {
  bool _isFollowing = true;
  MapCameraSnapshot? _unitySnapshot;

  bool get isFollowing => _isFollowing;

  /// Last camera intent produced by the Unity map renderer.  This belongs to
  /// the HMI, not a platform view instance: a fullscreen route replaces the
  /// native Unity host, and must resume the same map-space camera rather than
  /// deriving a new one from its own bounds.
  MapCameraSnapshot? snapshotForMap(String mapId) =>
      _unitySnapshot?.mapId == mapId ? _unitySnapshot : null;

  void saveUnitySnapshot({
    required String mapId,
    required double scale,
    required Offset offset,
    required double overviewScale,
  }) {
    _unitySnapshot = MapCameraSnapshot(
      mapId: mapId,
      zoom: scale / overviewScale,
      offset: offset,
    );
  }

  void pauseForDirectManipulation() {
    if (!_isFollowing) return;
    _isFollowing = false;
    notifyListeners();
  }

  void recenterOnVehicle() {
    _isFollowing = true;
    // A second tap is meaningful: it repeats the re-centre request even when
    // the mode was already active, without hiding the current interaction.
    notifyListeners();
  }
}

@immutable
class MapCameraSnapshot {
  const MapCameraSnapshot({
    required this.mapId,
    required this.zoom,
    required this.offset,
  });

  final String mapId;

  /// The operator's zoom relative to the map-cover overview of the host that
  /// captured it. This is independent of a card/fullscreen viewport.
  final double zoom;
  final Offset offset;

  /// Converts the viewport-independent [zoom] back into Unity's camera
  /// scalar for the receiving host's map-cover overview.
  double scaleForOverview(double overviewScale) => zoom * overviewScale;
}
