package com.ryaletheia.aletheia_visualization

import android.app.Activity
import android.content.Context
import android.util.Log
import android.view.SurfaceHolder
import android.view.SurfaceView
import android.view.View
import android.view.ViewGroup
import android.view.MotionEvent
import android.view.WindowManager
import android.widget.FrameLayout
import com.unity3d.player.UnityPlayer
import java.util.IdentityHashMap

/**
 * Real provider — compiled only when `aletheia.unityEnabled=true` and the host
 * app's settings.gradle includes `:unityLibrary` (see unity/README.md).
 *
 * Uses a single process-wide [UnityPlayer]. Unity as a Library allows only one
 * instance; the observation screen is the only consumer, and `unload()` tears
 * it down so re-entry starts clean. The point cloud is NOT routed here — Unity
 * reads it from the native `aletheia_viz_bridge` staging buffer.
 */
internal class UnitySurfaceProviderImpl : UnitySurfaceProvider {

    private var player: UnityPlayer? = null
    private var activity: Activity? = null
    private var activeHost: View? = null
    private var hostGeneration = 0
    // A fullscreen route can keep the departing card host and the incoming
    // fullscreen host in the Android hierarchy at the same time. Track a
    // generation per View so a delayed callback from the old host cannot
    // start or reparent the process-wide UnityPlayer after replacement.
    private val hostGenerations = IdentityHashMap<View, Int>()
    private val chromeOverlays = IdentityHashMap<View, MapChromeTouchOverlay>()
    private val chromeActionSinks = IdentityHashMap<View, (String) -> Unit>()
    private var scheduledStartGeneration = -1
    private var playerStarted = false
    private var startedHost: View? = null
    private var observedUnitySurface: SurfaceView? = null
    // A Flutter fullscreen route replaces the PlatformView host but does not
    // create a new Android Activity/configuration. UnityPlayerActivity would
    // normally forward both the new bounds and `configurationChanged` to
    // Unity. Keep that equivalent state here so Unity never keeps drawing
    // into the card-sized (or fullscreen-sized) buffer after a host swap.
    private var laidOutHost: View? = null
    private var laidOutWidth = -1
    private var laidOutHeight = -1
    // A SurfaceView has an independent producer buffer.  Host layout can be
    // correct while this buffer remains at the previous card/fullscreen size,
    // which Android then stretches permanently during composition.
    private var requestedBufferWidth = -1
    private var requestedBufferHeight = -1
    // The robot can publish pose telemetry at 60 Hz while Unity is starting.
    // Keep semantic latest values instead of a FIFO: otherwise poses evict
    // the one indispensable loadMap command before the scene is ready.
    private val deferredMessages = LinkedHashMap<String, Pair<String, String>>()
    private var deferredPollScheduled = false
    private var lastRendererReady: Boolean? = null

    override fun attachActivity(activity: Activity) {
        this.activity = activity
    }

    override fun detachActivity() {
        this.activity = null
    }

    override fun createSurface(context: Context, onMapAction: (String) -> Unit): View {
        // Flutter can instantiate a replacement PlatformView before disposing
        // the old one while an orientation/configuration change is in flight.
        // Do not construct UnityPlayer here. Its constructor starts the
        // native main/render thread, and Flutter can replace this provisional
        // host before the first composition is complete. Reparenting a
        // just-starting Unity SurfaceView causes libunity to time out while
        // detaching the primary window, leaving a black Release renderer.
        // First let Flutter settle on a measured host; only then create the
        // process-wide Unity runtime in startInStableHost().
        val host = FrameLayout(context)
        val chromeOverlay = MapChromeTouchOverlay(context, onMapAction)
        host.addView(
            chromeOverlay,
            FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT,
            ),
        )
        chromeOverlays[host] = chromeOverlay
        chromeActionSinks[host] = onMapAction
        val generation = ++hostGeneration
        hostGenerations[host] = generation
        activeHost = host
        // Classic Hybrid Composition can attach and size the Android view
        // *before* Flutter dispatches the platform-view-created callback.
        // Register against the host at creation time as well as in that
        // callback, otherwise the only usable layout pass is missed and Unity
        // never starts even though the card is visible.
        host.addOnLayoutChangeListener { view, _, _, _, _, _, _, _, _ ->
            Log.d(
                logTag,
                "Unity host layout generation=$generation size=${view.width}x${view.height} attached=${view.isAttachedToWindow}",
            )
            synchroniseUnityViewport(view)
            startWhenRenderable(view)
        }
        host.addOnAttachStateChangeListener(object : View.OnAttachStateChangeListener {
            override fun onViewAttachedToWindow(view: View) {
                Log.d(
                    logTag,
                    "Unity host attached generation=$generation size=${view.width}x${view.height}",
                )
                view.post { startWhenRenderable(view) }
            }

            override fun onViewDetachedFromWindow(view: View) = Unit
        })
        Log.i(logTag, "created Flutter Unity host generation=$generation")
        return host
    }

    override fun onSurfaceCreated(surface: View, viewId: Int) {
        // A stale PlatformView may finish its lifecycle after its replacement.
        // Only the host that currently owns Unity may resume and initialise it.
        if (activeHost !== surface) return
        // PlatformView construction happens before Flutter has attached and
        // measured the returned host. Starting Unity against a zero-sized
        // surface leaves a live runtime with a permanently black renderer on
        // some Android devices. Start only after the active host is attached
        // and has a real renderable size; the listener also covers rotation.
        surface.addOnLayoutChangeListener { view, _, _, _, _, _, _, _, _ ->
            synchroniseUnityViewport(view)
            startWhenRenderable(view)
        }
        surface.post { startWhenRenderable(surface) }
    }

    override fun onSurfaceDisposed(surface: View) {
        // Do not synchronously call UnityPlayer.pause() here. Flutter can
        // dispose an initial PlatformView while a measured replacement is
        // already being attached (orientation, fullscreen return, and even
        // the first post-layout composition pass). Unity's pause waits on its
        // render-thread semaphore; doing that on Android's UI thread at this
        // moment can stall before VizRoot.Start and leaves the replacement
        // SurfaceView permanently black in minified Release builds.
        //
        // The player is process-wide and the next host always reasserts its
        // normal resume/focus lifecycle, so keep it alive across view churn.
        val wasActive = activeHost === surface
        hostGenerations.remove(surface)
        chromeOverlays.remove(surface)
        chromeActionSinks.remove(surface)
        if (wasActive) {
            // There is no drawable after disposal. Leaving this detached View
            // active lets late map/camera messages target a dead surface and
            // makes the next fullscreen return nondeterministic.
            activeHost = null
            startedHost = null
            observedUnitySurface = null
            laidOutHost = null
            laidOutWidth = -1
            laidOutHeight = -1
            scheduledStartGeneration = -1
        }
        Log.i(logTag, "disposed Flutter Unity host active=$wasActive")
    }

    override fun send(surface: View, method: String, payload: String) {
        // Flutter keeps the departing and replacement PlatformViews alive
        // together during fullscreen route animations. Only the active host
        // may alter Unity's process-wide renderer state.
        if (activeHost !== surface) {
            Log.d(logTag, "ignored $method from stale Unity host")
            return
        }
        // UnitySendMessage targets a GameObject by name. `VizRoot` hosts
        // `VizBridge` (see unity/aletheia_viz/Assets/Scripts/VizBridge.cs).
        if (!isRendererReady()) {
            // Flutter can deliver the initial map descriptor before Unity has
            // run VizRoot.Start(). UnitySendMessage silently drops that first
            // message, which was the remaining Android black-map failure.
            // Keep a small ordered backlog and flush it as soon as the scene
            // publishes readiness through the shared native bridge.
            deferredMessages[deferredKey(method, payload)] = method to payload
            if (method == "loadMap") {
                Log.i(logTag, "queued loadMap until VizRoot is ready")
            }
            scheduleDeferredFlush(activeHost)
            return
        }
        sendToUnity(method, payload)
    }

    // Unity is a renderer owned by a process-wide PlatformView, not a second
    // Activity. Avoid UnityPlayer.pause() from a Flutter method-channel/UI
    // callback: it waits synchronously for the GL thread and races surface
    // reparenting. The host's real Activity lifecycle remains authoritative.
    override fun pause() = Unit
    override fun resume() { player?.resume() }

    override fun unload() {
        player?.let {
            it.unload() // async; returns once Unity has released GL/native.
        }
        player = null
        activeHost = null
        startedHost = null
        playerStarted = false
        observedUnitySurface = null
        laidOutHost = null
        laidOutWidth = -1
        laidOutHeight = -1
        hostGenerations.clear()
        chromeOverlays.clear()
        chromeActionSinks.clear()
        deferredMessages.clear()
        deferredPollScheduled = false
        lastRendererReady = null
        scheduledStartGeneration = -1
    }

    override fun isReady(): Boolean =
        player != null && activeHost != null && isRendererReady()

    override fun readMetrics(): Map<String, Any?> {
        val m = NativeBridge.readMetrics() ?: return emptyMap()
        return mapOf(
            "fps" to m[0], "p50" to m[1], "p95" to m[2],
            "points" to m[3].toInt(), "seq" to m[4].toLong(),
        )
    }

    private fun startWhenRenderable(host: View) {
        // In Flutter's explicit Hybrid Composition path the native child can
        // have its final measured bounds before Android reports the child as
        // attached. Treat the non-zero layout as the renderability contract;
        // requiring `isAttachedToWindow` here leaves a correctly-positioned
        // card permanently empty on Android 10+.
        if (activeHost !== host || host.width <= 0 || host.height <= 0) {
            if (activeHost === host) {
                Log.d(
                    logTag,
                    "Unity host not renderable generation=$hostGeneration size=${host.width}x${host.height} attached=${host.isAttachedToWindow}",
                )
            }
            return
        }
        // A host may already own a running UnityPlayer when Android reports
        // a second layout during immersive-mode transitions. That is a
        // resize, not a request to boot/reparent Unity again.
        synchroniseUnityViewport(host)
        val generation = hostGenerations[host] ?: return
        if (scheduledStartGeneration == generation || startedHost === host) return
        scheduledStartGeneration = generation
        host.postDelayed({
            if (activeHost !== host || hostGenerations[host] != generation ||
                host.width <= 0 || host.height <= 0) {
                return@postDelayed
            }
            startInStableHost(host)
        }, stableHostDelayMillis)
    }

    private fun startInStableHost(host: View) {
        if (activeHost !== host || host.width <= 0 || host.height <= 0) return
        val hostGroup = host as? ViewGroup ?: return
        // Unity requires a real Activity internally, but its stock player
        // temporarily applies the game fullscreen flag while it constructs.
        // Preserve and restore Flutter's window state in this *same* UI turn
        // so that the system-bar change cannot cause a third PlatformView
        // host to be created after Unity has acquired its primary window.
        val hostActivity = activity
        val originalWindowFlags = hostActivity?.window?.attributes?.flags
        val originalSystemUi = hostActivity?.window?.decorView?.systemUiVisibility
        val unityPlayer = player ?: UnityPlayer(hostActivity ?: host.context).also {
            player = it
            it.requestFocus()
            if (hostActivity != null && originalWindowFlags != null && originalSystemUi != null) {
                val window = hostActivity.window
                if (originalWindowFlags and WindowManager.LayoutParams.FLAG_FULLSCREEN == 0) {
                    window.clearFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN)
                } else {
                    window.addFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN)
                }
                window.decorView.systemUiVisibility = originalSystemUi
            }
            Log.i(logTag, "constructed Unity after stable host layout ${host.width}x${host.height}")
        }
        if (unityPlayer.parent !== host) {
            (unityPlayer.parent as? ViewGroup)?.removeView(unityPlayer)
            hostGroup.addView(
                unityPlayer,
                FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.MATCH_PARENT,
                ),
            )
        }
        // This transparent child remains above Unity's native SurfaceView.
        // It consumes only toolbar button regions and lets map gestures pass
        // through to the normal Flutter/Unity path everywhere else.
        chromeOverlays[host]?.let { hostGroup.bringChildToFront(it) }
        // Flutter's hybrid PlatformView host is measured independently from
        // UnityPlayer's internal SurfaceView. On Android the latter can stay
        // at 0×0 after an early attach even though the host has its final
        // bounds, producing a transparent/black rectangle. Make the nested
        // Unity root consume the exact host bounds before sending lifecycle
        // signals so its GL Surface receives a real buffer.
        synchroniseUnityViewport(host, force = true)
        if (startedHost === host) return
        startedHost = host
        unityPlayer.apply {
            // Unity normally receives these through UnityPlayerActivity. In
            // this application Flutter owns the Activity, so the embedded
            // renderer must receive the equivalent lifecycle/focus signals.
            if (!playerStarted) {
                onStart()
                playerStarted = true
            }
            onResume()
            resume()
            windowFocusChanged(true)
        }
        observeUnityRenderSurface(host)
        Log.i(logTag, "started Unity after stable host layout ${host.width}x${host.height}")
        // UnityPlayer creates its private GL SurfaceView asynchronously after
        // being attached. The first focus event above can precede that
        // Surface's `surfaceCreated` callback; reassert the lifecycle once
        // the child has had a frame to acquire a buffer. Without this Android
        // devices can initialise libunity but never enter the first scene
        // frame, leaving an empty black platform view.
        resumeAfterInternalSurfaceAttach(host, 120L)
        resumeAfterInternalSurfaceAttach(host, 480L)
        // Flutter's Activity was already focused before Unity was lazily
        // constructed. UnityPlayerActivity normally delivers a real
        // focus-loss/focus-gain edge after its GL Surface is present; without
        // that edge libunity can stop after SystemInfo and never initialise
        // graphics or execute VizRoot.Start. Reproduce that one edge after
        // the private SurfaceView has had time to attach.
        host.postDelayed({
            if (activeHost !== host || startedHost !== host) return@postDelayed
            player?.apply {
                windowFocusChanged(false)
                windowFocusChanged(true)
                resume()
            }
            Log.i(logTag, "replayed Unity focus edge after surface attach")
        }, focusEdgeDelayMillis)
        // VizRoot.Start normally follows within the next render frames.
        // Do not send through UnitySendMessage until native readiness proves
        // the target GameObject exists.
        scheduleDeferredFlush(host)
    }

    private fun resumeAfterInternalSurfaceAttach(host: View, delayMillis: Long) {
        host.postDelayed({
            if (activeHost !== host || startedHost !== host) return@postDelayed
            player?.apply {
                synchroniseUnityViewport(host)
                onResume()
                resume()
                windowFocusChanged(true)
            }
            Log.i(logTag, "reasserted Unity lifecycle after ${delayMillis}ms surface attach")
        }, delayMillis)
    }

    /**
     * Unity's first GL surface is created *after* [UnityPlayer.onResume].
     * In a normal UnityPlayerActivity, the Activity owns the window and
     * naturally sends another focus/layout pass. Flutter's PlatformView host
     * does not, which left Android's internal Unity SurfaceView at 0×0 with
     * no buffer despite an otherwise successfully booted libunity.
     *
     * Observe the actual private render SurfaceView and reapply the regular
     * UnityPlayerActivity lifecycle precisely when it becomes drawable. This
     * is intentionally recursive: Unity's internal view structure differs
     * slightly between renderer/Unity patch versions.
     */
    private fun observeUnityRenderSurface(host: View) {
        if (activeHost !== host || startedHost !== host) return
        val unityPlayer = player ?: return
        val renderSurface = findSurfaceView(unityPlayer) ?: run {
            // The child can appear a frame after UnityPlayer is created.
            host.postDelayed({ observeUnityRenderSurface(host) }, 32L)
            return
        }
        if (observedUnitySurface === renderSurface) return
        observedUnitySurface = renderSurface
        // A Unity SurfaceView owns its own input window on several Android
        // GPU stacks, so a transparent sibling above it never receives a
        // touch despite being visually on top. Attach the tiny semantic
        // toolbar listener to the actual render surface instead. It returns
        // false for every canvas point, preserving Unity's normal delivery.
        chromeActionSinks[host]?.let { sink ->
            renderSurface.setOnTouchListener(MapChromeTouchListener(sink))
        }
        renderSurface.holder.addCallback(object : SurfaceHolder.Callback {
            override fun surfaceCreated(holder: SurfaceHolder) =
                resumeForRenderSurface(host, "created")

            override fun surfaceChanged(
                holder: SurfaceHolder,
                format: Int,
                width: Int,
                height: Int,
            ) {
                if (width > 0 && height > 0) {
                    // A buffer resize is asynchronous.  Re-check it after
                    // the callback instead of accepting a stale host-layout
                    // cache from the first traversal.
                    synchroniseUnityViewport(host, force = true)
                    verifyUnityRenderBuffer(host)
                    resumeForRenderSurface(host, "changed ${width}x${height}")
                }
            }

            override fun surfaceDestroyed(holder: SurfaceHolder) = Unit
        })
        // If the callback is registered after SurfaceView creation, the
        // current size is still authoritative and must get the same resume.
        if (renderSurface.width > 0 && renderSurface.height > 0) {
            resumeForRenderSurface(
                host,
                "already-sized ${renderSurface.width}x${renderSurface.height}",
            )
        }
    }

    private fun resumeForRenderSurface(host: View, reason: String) {
        if (activeHost !== host || startedHost !== host) return
        player?.apply {
            synchroniseUnityViewport(host)
            onResume()
            resume()
            windowFocusChanged(true)
        }
        Log.i(logTag, "resumed Unity on internal render surface $reason")
    }

    private fun findSurfaceView(view: View): SurfaceView? {
        if (view is SurfaceView) return view
        if (view !is ViewGroup) return null
        for (index in 0 until view.childCount) {
            findSurfaceView(view.getChildAt(index))?.let { return it }
        }
        return null
    }

    /**
     * Gives Unity's private GL [SurfaceView] the exact current Flutter host
     * bounds. MATCH_PARENT alone is not sufficient after a reparent: the
     * SurfaceView can retain the previous buffer dimensions until an Activity
     * configuration callback occurs, but fullscreen is a route change inside
     * the same Activity. Re-measuring the native subtree and forwarding the
     * configuration restores the normal UnityPlayerActivity resize path.
     */
    private fun synchroniseUnityViewport(host: View, force: Boolean = false) {
        val unityPlayer = player ?: return
        val width = host.width
        val height = host.height
        if (activeHost !== host || unityPlayer.parent !== host ||
            width <= 0 || height <= 0) return
        if (!force && laidOutHost === host &&
            laidOutWidth == width && laidOutHeight == height &&
            !hasStaleRenderBuffer(unityPlayer, width, height)) {
            return
        }
        laidOutHost = host
        laidOutWidth = width
        laidOutHeight = height

        // UnityPlayer itself is MATCH_PARENT in the Flutter host. Its private
        // GL SurfaceView owns a second producer buffer that must be explicitly
        // kept at the same physical-pixel dimensions as that host. Do not call
        // View.measure/layout directly: that bypasses Android's SurfaceControl
        // traversal and is the source of the anisotropic map composition bug.
        var changed = false
        val playerParams = unityPlayer.layoutParams
        if (playerParams.width != ViewGroup.LayoutParams.MATCH_PARENT ||
            playerParams.height != ViewGroup.LayoutParams.MATCH_PARENT) {
            unityPlayer.layoutParams = FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT,
            )
            changed = true
        }
        for (index in 0 until unityPlayer.childCount) {
            val child = unityPlayer.getChildAt(index)
            val params = child.layoutParams
            if (params.width != ViewGroup.LayoutParams.MATCH_PARENT ||
                params.height != ViewGroup.LayoutParams.MATCH_PARENT) {
                child.layoutParams = FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.MATCH_PARENT,
                )
                changed = true
            }
        }
        if (changed) {
            unityPlayer.requestLayout()
            Log.i(logTag, "corrected ${unityPlayer.childCount} Unity child layout params")
        }
        // Do not request layout on [host] here. This method is called from
        // the host's OnLayoutChangeListener, so asking the host to lay itself
        // out creates an unbounded 60 Hz layout -> requestLayout feedback
        // loop. Apart from wasting a frame every traversal, that loop races a
        // fullscreen/rotation SurfaceView buffer resize and is the concrete
        // cause of the persistent stretched map seen on Android.
        val generation = hostGenerations[host] ?: return
        host.post {
            // A host can disappear between this layout pass and the normal
            // Android traversal. Never apply its dimensions to Unity later.
            if (activeHost !== host || hostGenerations[host] != generation ||
                host.width != width || host.height != height ||
                unityPlayer.parent !== host) {
                return@post
            }
            val surface = findSurfaceView(unityPlayer)
            surface?.apply {
                requestLayout()
                val frame = holder.surfaceFrame
                if (frame.width() != width || frame.height() != height) {
                    requestedBufferWidth = width
                    requestedBufferHeight = height
                    // Fixed-size is intentional: the producer buffer must be
                    // identical to the Flutter host, not merely inherit a
                    // previous layout-managed size after a system-ui change.
                    holder.setFixedSize(width, height)
                    Log.i(
                        logTag,
                        "requested Unity render buffer ${width}x${height} " +
                            "from ${frame.width()}x${frame.height()}",
                    )
                }
            }
            unityPlayer.configurationChanged(host.resources.configuration)
            val frame = surface?.holder?.surfaceFrame
            Log.i(
                logTag,
                "synchronised Unity viewport host=${width}x${height} " +
                    "surface=${surface?.width ?: 0}x${surface?.height ?: 0} " +
                    "buffer=${frame?.width() ?: 0}x${frame?.height() ?: 0}",
            )
            verifyUnityRenderBuffer(host)
        }
    }

    private fun hasStaleRenderBuffer(
        unityPlayer: UnityPlayer,
        width: Int,
        height: Int,
    ): Boolean {
        val frame = findSurfaceView(unityPlayer)?.holder?.surfaceFrame ?: return false
        return frame.width() != width || frame.height() != height
    }

    /**
     * SurfaceHolder mutations complete asynchronously. Check after each
     * traversal and retry a bounded number of times while the same host is
     * still active; a stale retry can never target a replacement host.
     */
    private fun verifyUnityRenderBuffer(host: View, attemptsLeft: Int = 6) {
        val expectedWidth = host.width
        val expectedHeight = host.height
        val generation = hostGenerations[host] ?: return
        if (expectedWidth <= 0 || expectedHeight <= 0) return
        host.postDelayed({
            val unityPlayer = player ?: return@postDelayed
            if (activeHost !== host || startedHost !== host ||
                hostGenerations[host] != generation ||
                host.width != expectedWidth || host.height != expectedHeight ||
                unityPlayer.parent !== host) {
                return@postDelayed
            }
            val surface = findSurfaceView(unityPlayer) ?: return@postDelayed
            val frame = surface.holder.surfaceFrame
            if (frame.width() == expectedWidth && frame.height() == expectedHeight) {
                Log.i(logTag, "verified Unity render buffer ${expectedWidth}x${expectedHeight}")
                return@postDelayed
            }
            requestedBufferWidth = expectedWidth
            requestedBufferHeight = expectedHeight
            surface.holder.setFixedSize(expectedWidth, expectedHeight)
            Log.w(
                logTag,
                "Unity render buffer mismatch host=${expectedWidth}x${expectedHeight} " +
                    "buffer=${frame.width()}x${frame.height()} attemptsLeft=$attemptsLeft",
            )
            unityPlayer.configurationChanged(host.resources.configuration)
            if (attemptsLeft > 1) {
                verifyUnityRenderBuffer(host, attemptsLeft - 1)
            }
        }, 48L)
    }

    private fun scheduleDeferredFlush(host: View?, attemptsLeft: Int = 180) {
        if (host == null || activeHost !== host || deferredPollScheduled) return
        deferredPollScheduled = true
        pollDeferredMessages(host, attemptsLeft)
    }

    private fun pollDeferredMessages(host: View, attemptsLeft: Int) {
        host.postDelayed({
            if (activeHost !== host) {
                deferredPollScheduled = false
                return@postDelayed
            }
            if (isRendererReady()) {
                // Notify Unity after Start(), then replay the exact message
                // order Flutter supplied (map, camera, pose and layers).
                sendToUnity("bridgeReady", "{}")
                for ((method, payload) in orderedDeferredMessages()) {
                    sendToUnity(method, payload)
                }
                deferredMessages.clear()
                deferredPollScheduled = false
                Log.i(logTag, "VizRoot acknowledged; initial scene state flushed")
                return@postDelayed
            }
            // Some Unity builds isolate their native plugin namespace from
            // the host bridge. In that case the acknowledgement is absent
            // even though VizRoot has started. Replay a small number of
            // idempotent map/camera messages after the scene is normally
            // available; this is a fallback, not the primary protocol.
            if (attemptsLeft == 140 || attemptsLeft == 90 || attemptsLeft == 30) {
                orderedDeferredMessages().forEach { (method, payload) ->
                    sendToUnity(method, payload)
                }
                Log.i(logTag, "replayed ${deferredMessages.size} initial messages without native acknowledgement")
            }
            if (attemptsLeft <= 1) {
                deferredPollScheduled = false
                return@postDelayed
            }
            pollDeferredMessages(host, attemptsLeft - 1)
        }, rendererPollMillis)
    }

    private fun sendToUnity(method: String, payload: String) {
        UnityPlayer.UnitySendMessage("VizRoot", "OnHostMessage", "$method$payload")
    }

    private fun deferredKey(method: String, payload: String): String {
        if (method != "setLayer") return method
        // Preserve independent visibility states without requiring a JSON
        // dependency in the low-level Android embedding.
        val layer = layerNameRegex.find(payload)?.groupValues?.getOrNull(1)
        return if (layer.isNullOrEmpty()) method else "$method:$layer"
    }

    private fun orderedDeferredMessages(): List<Pair<String, String>> {
        // Static world state must be applied before camera and live pose.
        val priority = listOf("loadMap", "setViewMode", "setLayer", "setCamera", "setPose")
        return deferredMessages.entries.sortedWith(
            compareBy<Map.Entry<String, Pair<String, String>>> {
                val base = it.value.first
                priority.indexOf(base).let { index ->
                    if (index >= 0) index else priority.size
                }
            }.thenBy { it.key },
        ).map { it.value }
    }

    private fun isRendererReady(): Boolean {
        val ready = UnityLifecycleBridge.isSceneReady() || try {
            NativeBridge.isRendererReady()
        } catch (_: UnsatisfiedLinkError) {
            false
        }
        if (lastRendererReady != ready) {
            lastRendererReady = ready
            Log.i(logTag, "native renderer readiness=$ready")
        }
        return ready
    }

    private companion object {
        const val rendererPollMillis = 16L
        const val focusEdgeDelayMillis = 800L
        // Flutter creates its final hybrid-composition host roughly one frame
        // transaction after the provisional one (observed up to ~900 ms on
        // production Android devices). Keep Unity unconstructed through that
        // transaction; booting it earlier makes the following reparent block
        // on libunity's primary-window semaphore for two seconds.
        const val stableHostDelayMillis = 1200L
        const val logTag = "AletheiaUnity"
        val layerNameRegex = Regex("\\\"layer\\\"\\s*:\\s*\\\"([^\\\"]+)\\\"")
    }
}

/**
 * Transparent native hit layer for the Flutter-drawn map toolbar.
 *
 * Hybrid composition is required for Unity's SurfaceView to honour Flutter's
 * card bounds and clips. The tradeoff is that the native surface receives the
 * touch before Flutter does. This view consumes only the small, stable button
 * regions and sends their semantic action over the existing MethodChannel;
 * all canvas pixels return false and remain available for normal map input.
 */
private class MapChromeTouchOverlay(
    context: Context,
    private val onAction: (String) -> Unit,
) : View(context) {
    private var pressedAction: String? = null

    override fun onTouchEvent(event: MotionEvent): Boolean {
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                pressedAction = actionAt(event.x, event.y)
                Log.d(
                    "AletheiaUnity",
                    "native chrome down x=${event.x.toInt()}/${width} y=${event.y.toInt()}/${height} action=$pressedAction",
                )
                return pressedAction != null
            }
            MotionEvent.ACTION_UP -> {
                val action = pressedAction
                pressedAction = null
                if (action != null && action == actionAt(event.x, event.y)) {
                    onAction(action)
                    performClick()
                }
                return action != null
            }
            MotionEvent.ACTION_CANCEL -> {
                val handled = pressedAction != null
                pressedAction = null
                return handled
            }
        }
        return pressedAction != null
    }

    override fun performClick(): Boolean {
        super.performClick()
        return true
    }

    private fun actionAt(x: Float, y: Float): String? {
        if (width <= 0 || height <= 0) return null
        val horizontal = x / width
        val vertical = y / height
        // Portrait cards and every fullscreen presentation use Flutter's
        // horizontal toolbar. The action zones intentionally include the
        // complete 48dp targets plus a small slop margin, not the canvas.
        if (vertical <= 0.16f && horizontal >= 0.50f) {
            return when {
                horizontal < 0.64f -> "camera"
                horizontal < 0.76f -> "recenter"
                horizontal < 0.88f -> "fullscreen"
                else -> "refresh"
            }
        }
        // Normal landscape cards use a vertical tool rail at the left. Keep
        // this separate from the map canvas so panning never becomes a tap.
        if (width > height && horizontal <= 0.18f && vertical in 0.06f..0.62f) {
            return when {
                vertical < 0.20f -> "camera"
                vertical < 0.34f -> "recenter"
                vertical < 0.48f -> "fullscreen"
                else -> "refresh"
            }
        }
        return null
    }
}

/** Same button classifier, attached to Unity's actual input-owning Surface. */
private class MapChromeTouchListener(
    private val onAction: (String) -> Unit,
) : View.OnTouchListener {
    private var pressedAction: String? = null

    override fun onTouch(view: View, event: MotionEvent): Boolean {
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                pressedAction = mapActionAt(view, event.x, event.y)
                Log.d(
                    "AletheiaUnity",
                    "Unity render touch x=${event.x.toInt()}/${view.width} y=${event.y.toInt()}/${view.height} action=$pressedAction",
                )
                return pressedAction != null
            }
            MotionEvent.ACTION_UP -> {
                val action = pressedAction
                pressedAction = null
                if (action != null && action == mapActionAt(view, event.x, event.y)) {
                    onAction(action)
                }
                return action != null
            }
            MotionEvent.ACTION_CANCEL -> {
                val handled = pressedAction != null
                pressedAction = null
                return handled
            }
        }
        return pressedAction != null
    }
}

private fun mapActionAt(view: View, x: Float, y: Float): String? {
    if (view.width <= 0 || view.height <= 0) return null
    val horizontal = x / view.width
    val vertical = y / view.height
    if (vertical <= 0.16f && horizontal >= 0.50f) {
        return when {
            horizontal < 0.64f -> "camera"
            horizontal < 0.76f -> "recenter"
            horizontal < 0.88f -> "fullscreen"
            else -> "refresh"
        }
    }
    if (view.width > view.height && horizontal <= 0.18f && vertical in 0.06f..0.62f) {
        return when {
            vertical < 0.20f -> "camera"
            vertical < 0.34f -> "recenter"
            vertical < 0.48f -> "fullscreen"
            else -> "refresh"
        }
    }
    return null
}

/** JNI view of the shared `aletheia_viz_bridge` metrics, for readMetrics(). */
private object NativeBridge {
    init { System.loadLibrary("aletheia_viz_bridge") }
    external fun readMetrics(): DoubleArray?
    external fun isRendererReady(): Boolean
}
