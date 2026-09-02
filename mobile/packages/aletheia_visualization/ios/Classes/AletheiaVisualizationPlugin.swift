import Flutter
import UIKit

/// Registers the `aletheia_visualization/surface` platform view. Renderer only:
/// it forwards a map, camera, pose and (via the native FFI bridge, not this
/// channel) a point cloud. Never touches ROS2, the backend, tasks or video.
public class AletheiaVisualizationPlugin: NSObject, FlutterPlugin {
  public static func register(with registrar: FlutterPluginRegistrar) {
    let factory = VisualizationViewFactory(messenger: registrar.messenger())
    registrar.register(factory, withId: "aletheia_visualization/surface")
  }
}

final class VisualizationViewFactory: NSObject, FlutterPlatformViewFactory {
  private let messenger: FlutterBinaryMessenger

  init(messenger: FlutterBinaryMessenger) {
    self.messenger = messenger
    super.init()
  }

  func createArgsCodec() -> FlutterMessageCodec & NSObjectProtocol {
    FlutterStandardMessageCodec.sharedInstance()
  }

  func create(
    withFrame frame: CGRect,
    viewIdentifier viewId: Int64,
    arguments args: Any?
  ) -> FlutterPlatformView {
    VisualizationSurfaceView(frame: frame, viewId: viewId, messenger: messenger)
  }
}

/// Flutter creates platform views before their final layout pass.  Unity's
/// Metal surface cannot be created at 0×0, so forward each real layout change
/// to the shared renderer before it is allowed to start.
private final class VisualizationSurfaceContainerView: UIView {
  var onLayout: ((UIView) -> Void)?

  override func layoutSubviews() {
    super.layoutSubviews()
    onLayout?(self)
  }
}

final class VisualizationSurfaceView: NSObject, FlutterPlatformView {
  private let container: VisualizationSurfaceContainerView
  private let channel: FlutterMethodChannel
  private let provider = UnitySurfaceProvider.shared

  init(frame: CGRect, viewId: Int64, messenger: FlutterBinaryMessenger) {
    container = VisualizationSurfaceContainerView(frame: frame)
    channel = FlutterMethodChannel(
      name: "aletheia_visualization/surface_\(viewId)",
      binaryMessenger: messenger)
    super.init()
    container.backgroundColor = UIColor(white: 0.04, alpha: 1)
    // The native surface is visual output only.  Flutter owns every map
    // gesture, toolbar action and app-navigation tap.  An interactive
    // container would make UIKit consume the entire platform-view rectangle
    // before Flutter can route those events to its widgets.
    container.isUserInteractionEnabled = false
    // Unity's root view is normally window-sized when created by UaaL.  The
    // render surface must be clipped to this Flutter map rectangle while it
    // is being reparented and resized during orientation changes.
    container.clipsToBounds = true
    container.onLayout = { [weak provider] view in
      provider?.layoutDidChange(view)
    }
    provider.attach(to: container, viewId: viewId)
    channel.setMethodCallHandler { [weak self] call, result in
      self?.handle(call, result)
    }
  }

  func view() -> UIView { container }

  private func handle(_ call: FlutterMethodCall, _ result: FlutterResult) {
    switch call.method {
    case "loadMap", "setPose", "setCamera", "setLayer":
      provider.send(call.method, json: call.arguments)
      result(nil)
    case "setViewMode":
      provider.send("setViewMode", json: call.arguments)
      result(nil)
    case "pause": provider.pause(); result(nil)
    case "resume": provider.resume(); result(nil)
    case "unload": provider.unload(); result(nil)
    case "isReady": result(provider.isReady())
    case "readMetrics": result(provider.readMetrics())
    default: result(FlutterMethodNotImplemented)
    }
  }

  deinit {
    channel.setMethodCallHandler(nil)
    provider.detach(from: container)
  }
}
