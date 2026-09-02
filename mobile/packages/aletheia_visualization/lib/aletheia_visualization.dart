/// Embeds a lightweight Unity renderer as a Flutter platform view.
///
/// Boundary (fixed): Flutter owns the app, navigation, HMI, business logic,
/// networking, state and the WebRTC video feeds. This package is a *renderer
/// transport* only — it forwards a map, a camera transform, a pose and a
/// point-cloud buffer to Unity and nothing else. It never calls ROS2, the
/// robot backend, task services or video.
library;

export 'src/visualization_view.dart' show AletheiaVisualizationView;
export 'src/visualization_controller.dart'
    show
        VisualizationController,
        VisualizationMapAction,
        VizViewMode,
        VizLayer,
        VizCameraState,
        VizViewport,
        VizMapDescriptor,
        VizRenderMetrics;
export 'src/cloud_bridge.dart' show CloudBridge, CloudLayout;
