import UIKit
import os

/// Bridges the plugin to the embedded Unity instance.
///
/// Guarded by the `ALETHEIA_UNITY_ENABLED` compilation condition. Until the
/// `UnityFramework` is built and the flag is set (see unity/README.md), the
/// stub path compiles and the app uses the Flutter renderer. Point-cloud data
/// never passes through here — Unity reads it from the shared
/// `aletheia_viz_bridge` staging buffer in this plugin framework.
final class UnitySurfaceProvider {
  static let shared = UnitySurfaceProvider()
  private weak var host: UIView?
  private var lastReadyState: Int32 = -1
  private var pendingAttachment: DispatchWorkItem?

  func attach(to container: UIView, viewId: Int64) {
    host = container
    print("[UnityVizNative] attaching platform view id=\(viewId) size=\(container.bounds.size)")
    scheduleAttachment(for: container)
  }

  /// Called by the platform view after UIKit assigns its non-zero frame.  A
  /// Flutter platform view is created at 0×0, which must never reach Unity's
  /// Metal surface creation path.
  func layoutDidChange(_ container: UIView) {
    guard host === container else { return }
    scheduleAttachment(for: container)
  }

  /// A Flutter platform view can receive several layout passes while UIKit is
  /// rotating the window. Reparenting Unity's Metal root view from inside
  /// `layoutSubviews` can recursively invalidate that same layout pass and
  /// leave the application unresponsive. Coalesce the work onto the next main
  /// run-loop turn, after UIKit has committed the container's final bounds.
  private func scheduleAttachment(for container: UIView) {
    guard container.bounds.width > 0, container.bounds.height > 0 else {
      print("[UnityVizNative] deferring Unity start until platform view has a size")
      return
    }
    pendingAttachment?.cancel()
    let work = DispatchWorkItem { [weak self, weak container] in
      guard let self, let container, self.host === container,
            container.bounds.width > 0, container.bounds.height > 0 else {
        return
      }
    #if ALETHEIA_UNITY_ENABLED
      UnityEmbed.shared.attach(to: container)
    #endif
    }
    pendingAttachment = work
    DispatchQueue.main.async(execute: work)
  }

  func detach(from container: UIView) {
    // Flutter may dispose a stale view after a new one has been attached
    // during rotation. Do not pause the live Unity surface in that case.
    guard host === container else { return }
    pendingAttachment?.cancel()
    pendingAttachment = nil
    #if ALETHEIA_UNITY_ENABLED
    UnityEmbed.shared.detach()
    #endif
    host = nil
  }

  func send(_ method: String, json: Any?) {
    #if ALETHEIA_UNITY_ENABLED
    let payload = Self.jsonString(json)
    if method == "loadMap" {
      print("[UnityVizNative] forwarding initial map payload (\(payload.utf8.count) bytes)")
    }
    let message = method + payload
    UnityEmbed.shared.send(gameObject: "VizRoot", method: "OnHostMessage",
                           message: message)
    // `runEmbedded` returns before the first Unity frame creates VizRoot. A
    // Flutter platform view may therefore deliver its one-time map payload at
    // exactly the one point UnitySendMessage is intentionally lossy. Retain
    // only the latest real map and replay it once after startup settles. This
    // is renderer transport reliability, not a mock or a second data source.
    // Do not always replay a large map after two seconds.  Once VizRoot is
    // ready the first send is authoritative; a second full-resolution decode
    // cancels the first coroutine and can keep the embedded renderer busy
    // indefinitely.  A retry is only required for the narrow pre-ready race.
    if method == "loadMap" {
      let mapId = (json as? [String: Any])?["id"] as? String
      // A Gallery/state transition can create a new Flutter platform view
      // while Unity is still starting. Its small placeholder map is retained
      // for the narrow pre-ready race above. Once a later, real map reaches a
      // ready renderer, however, that retained payload must be discarded:
      // replaying it two seconds later can replace (or needlessly decode over)
      // the full-resolution occupancy map that is already on screen.
      if UnityEmbed.shared.isRunning && av_renderer_is_ready_value() == 1 {
        UnityEmbed.shared.acceptMap(id: mapId)
      } else if UnityEmbed.shared.shouldRetryInitialMap(id: mapId) {
        UnityEmbed.shared.retryInitialMap(message)
      }
    }
    #endif
  }

  func pause() {
    #if ALETHEIA_UNITY_ENABLED
    UnityEmbed.shared.pause()
    #endif
  }

  func resume() {
    #if ALETHEIA_UNITY_ENABLED
    UnityEmbed.shared.resume()
    #endif
  }

  func unload() {
    #if ALETHEIA_UNITY_ENABLED
    UnityEmbed.shared.unload()
    #endif
  }

  func isReady() -> Bool {
    #if ALETHEIA_UNITY_ENABLED
    // Flutter starts its bounded readiness probe as soon as the UIKit platform
    // view is created. UIKit has not necessarily completed the later layout
    // pass that starts Unity at that point. Do not touch the C ABI until this
    // process-wide runtime has actually been embedded: an unresolved lazy
    // bridge binding in a release IPA otherwise jumps to address zero.
    guard UnityEmbed.shared.isRunning else { return false }
    let ready = av_renderer_is_ready_value()
    if ready != lastReadyState {
      lastReadyState = ready
      print("[UnityVizNative] renderer ready=\(ready)")
    }
    return ready == 1
    #else
    return false
    #endif
  }

  func readMetrics() -> [String: Any] {
    #if ALETHEIA_UNITY_ENABLED
    // Metrics are diagnostic-only and share the same host bridge as readiness.
    // Returning no metrics before Unity starts is correct; invoking a lazy C
    // binding before the host export is available is not.
    guard UnityEmbed.shared.isRunning else { return [:] }
    #endif
    var fps: Float = 0
    var p50: Float = 0
    var p95: Float = 0
    var points: Int32 = 0
    var sequence: Int64 = 0
    guard av_metrics_read_values(&fps, &p50, &p95, &points, &sequence) == 0
    else { return [:] }
    return [
      "fps": fps, "p50": p50, "p95": p95,
      "points": Int(points), "seq": Int(sequence),
    ]
  }

  private static func jsonString(_ value: Any?) -> String {
    if let s = value as? String { return s }
    guard let value = value,
          let data = try? JSONSerialization.data(withJSONObject: value),
          let s = String(data: data, encoding: .utf8) else { return "{}" }
    return s
  }
}

#if ALETHEIA_UNITY_ENABLED
import UnityFramework

/// Thin wrapper over UnityFramework. One process-wide instance (UaaL rule).
final class UnityEmbed: UIResponder, UnityFrameworkListener {
  static let shared = UnityEmbed()
  private let logger = Logger(
    subsystem: "com.ryaletheia.aletheiaMobile",
    category: "UnityEmbed")
  private var framework: UnityFramework?
  private weak var unityView: UIView?
  private var hasStarted = false
  private var hasRegisteredListener = false
  private var initialMapRetry: DispatchWorkItem?
  private var pendingInitialMap: String?
  private var acceptedMapIdentifiers = Set<String>()
  private weak var attachedContainer: UIView?
  private var lastAttachedBounds = CGRect.null
  private var isPaused = true

  /// A synchronous main-thread lifecycle fact. This is intentionally not a
  /// second "renderer ready" signal: it only gates host-bridge access until
  /// `runEmbedded` has completed its initial setup.
  var isRunning: Bool { hasStarted && framework != nil }

  func attach(to container: UIView) {
    guard container.bounds.width > 0, container.bounds.height > 0 else {
      print("[UnityVizNative] ignoring zero-sized Unity attachment")
      return
    }
    guard let ufw = loadFramework() else { return }
    framework = ufw
    // CocoaPods copies the Unity `Data` directory into this plugin framework
    // (rather than into Runner.app).  Point Unity at the bundle that actually
    // owns those resources.  Using UnityFramework's own identifier here makes
    // a device build start with no Data folder available and terminate during
    // initialization.
    if !hasStarted {
      let dataBundleId = Bundle(for: UnitySurfaceProvider.self).bundleIdentifier
        ?? "org.cocoapods.aletheia-visualization"
      print("[UnityVizNative] starting Unity dataBundleId=\(dataBundleId)")
      ufw.setDataBundleId(dataBundleId)
      if !hasRegisteredListener {
        ufw.register(self)
        hasRegisteredListener = true
      }
      ufw.runEmbedded(withArgc: CommandLine.argc,
                      argv: CommandLine.unsafeArgv,
                      appLaunchOpts: nil)
      hasStarted = true
      print("[UnityVizNative] runEmbedded returned")
      logger.notice("Unity embedded runtime started")
    }
    guard let rootView = ufw.appController()?.rootView else {
      print("[UnityVizNative] Unity root view unavailable")
      logger.error("Unity root view was unavailable after attach")
      return
    }
    let isNewContainer = attachedContainer !== container
    let boundsChanged = lastAttachedBounds != container.bounds
    let needsReparent = rootView.superview !== container
    if !isNewContainer && !boundsChanged && !needsReparent {
      resume()
      return
    }

    rootView.autoresizingMask = [.flexibleWidth, .flexibleHeight]
    // Unity is a pure renderer in this app. Flutter owns the map gesture
    // arena and translates its pan/pinch state into camera messages, so the
    // embedded Metal view must never consume UIKit touches.  An interactive
    // Unity root was paired with an eager platform-view recognizer, making the
    // map workspace appear frozen as soon as Unity had started.
    rootView.isUserInteractionEnabled = false
    if needsReparent {
      // This now runs after the platform view's layout pass; see
      // `scheduleAttachment(for:)` above.
      rootView.removeFromSuperview()
      container.addSubview(rootView)
      print("[UnityVizNative] Unity root view attached size=\(container.bounds.size)")
    }
    rootView.frame = container.bounds
    unityView = rootView
    attachedContainer = container
    lastAttachedBounds = container.bounds
    // `runEmbedded` creates a second UIWindow and binds the Metal swap chain
    // to it. Merely moving `rootView` into Flutter (then hiding that window)
    // leaves Unity presenting to a hidden layer on a device. Rebind Unity's
    // private DisplayConnection to the *Flutter-owned* host window first,
    // then hide only the now-unused bootstrap window. A fullscreen route uses
    // a different Flutter platform-view size without necessarily changing the
    // container identity. Rebind once for that committed bounds transition as
    // well; otherwise Unity keeps presenting to the stale Metal drawable and
    // the map appears blank after exiting fullscreen. `scheduleAttachment`
    // coalesces UIKit's intermediate rotation layouts, so this is not a
    // per-frame surface recreation.
    if (isNewContainer || needsReparent || boundsChanged),
       let controller = ufw.appController(),
       let hostWindow = container.window {
      av_unity_rebind_surface(
        Unmanaged.passUnretained(controller).toOpaque(),
        Unmanaged.passUnretained(rootView).toOpaque(),
        Unmanaged.passUnretained(hostWindow).toOpaque(),
      )
      if let unityWindow = controller.window, unityWindow !== hostWindow {
        // Keep Unity's original controller alive. It owns the Metal app
        // lifecycle that `recreateRenderingSurface` uses on the next Flutter
        // bounds change. Clearing it can appear to work for the first embed,
        // then leave the drawable black after returning from fullscreen.
        // Reparenting rootView plus the explicit host-window rebind above is
        // sufficient; only hide Unity's no-longer-visible bootstrap window.
        unityWindow.isHidden = true
      }
      hostWindow.makeKey()
      print("[UnityVizNative] Unity surface now uses Flutter host window")
    }
    resume()
    if isNewContainer || needsReparent || boundsChanged {
      scheduleInitialMapReplay()
    }
  }

  func detach() {
    guard unityView?.superview != nil else { return }
    pause()
    unityView?.removeFromSuperview()
    attachedContainer = nil
    lastAttachedBounds = .null
  }

  func pause() {
    guard !isPaused else { return }
    framework?.pause(true)
    isPaused = true
  }

  func resume() {
    guard isPaused else { return }
    framework?.pause(false)
    isPaused = false
  }

  func unload() {
    // A platform-view disposal is common during rotation. Keep the UaaL
    // process alive and reattach it later; iOS will reclaim it at app exit.
    detach()
  }

  func send(gameObject: String, method: String, message: String) {
    framework?.sendMessageToGO(withName: gameObject, functionName: method,
                               message: message)
  }

  func retryInitialMap(_ message: String) {
    pendingInitialMap = message
    scheduleInitialMapReplay()
  }

  /// The live Unity scene survives Flutter platform-view recreation. A map
  /// already delivered to that scene must not be retained for another delayed
  /// bootstrap replay merely because a replacement UIKit view briefly reports
  /// not-ready during fullscreen/orientation layout.
  func shouldRetryInitialMap(id: String?) -> Bool {
    guard let id else { return true }
    return !acceptedMapIdentifiers.contains(id)
  }

  /// A ready renderer has accepted a newer authoritative map. Any delayed
  /// bootstrap payload belongs to an old platform view and must not mutate the
  /// active scene later in the same process-wide Unity runtime.
  func discardInitialMapRetry() {
    initialMapRetry?.cancel()
    initialMapRetry = nil
    pendingInitialMap = nil
  }

  func acceptMap(id: String?) {
    if let id { acceptedMapIdentifiers.insert(id) }
    discardInitialMapRetry()
  }

  private func scheduleInitialMapReplay() {
    initialMapRetry?.cancel()
    let retry = DispatchWorkItem { [weak self] in
      guard let self, self.framework != nil,
            let message = self.pendingInitialMap else { return }
      self.logger.debug("Replaying initial Unity map payload after startup")
      self.send(gameObject: "VizRoot", method: "OnHostMessage", message: message)
      self.pendingInitialMap = nil
    }
    initialMapRetry = retry
    DispatchQueue.main.asyncAfter(deadline: .now() + .seconds(2), execute: retry)
  }

  func unityDidUnload(_ notification: Notification) {
    initialMapRetry?.cancel()
    initialMapRetry = nil
    pendingInitialMap = nil
    acceptedMapIdentifiers.removeAll(keepingCapacity: false)
    unityView = nil
    attachedContainer = nil
    lastAttachedBounds = .null
    framework = nil
    hasStarted = false
    hasRegisteredListener = false
    isPaused = true
    print("[UnityVizNative] Unity runtime unloaded")
    logger.notice("Unity runtime unloaded")
  }

  private func loadFramework() -> UnityFramework? {
    if let ufw = framework { return ufw }
    let bundlePath = Bundle.main.bundlePath + "/Frameworks/UnityFramework.framework"
    guard let bundle = Bundle(path: bundlePath) else {
      print("[UnityVizNative] Unity framework bundle missing at \(bundlePath)")
      logger.error("Unity framework bundle is missing")
      return nil
    }
    if !bundle.isLoaded && !bundle.load() {
      print("[UnityVizNative] Unity framework bundle failed to load")
      logger.error("Unity framework bundle could not load")
      return nil
    }
    guard let ufw = bundle.principalClass?.getInstance() else {
      print("[UnityVizNative] Unity framework principal class unavailable")
      logger.error("Unity framework principal class is unavailable")
      return nil
    }
    if ufw.appController() == nil, let executeHeader = _dyld_get_image_header(0) {
      // Unity's Swift overlay expects its MachHeader alias (mach_header_64 on
      // arm64). dyld exposes the architecture-neutral C pointer, so bind it
      // explicitly at this FFI boundary rather than relying on an implicit cast.
      let unityHeader = UnsafeRawPointer(executeHeader)
        .assumingMemoryBound(to: MachHeader.self)
      ufw.setExecuteHeader(unityHeader)
      print("[UnityVizNative] configured Unity execute header")
    }
    return ufw
  }
}
#endif
