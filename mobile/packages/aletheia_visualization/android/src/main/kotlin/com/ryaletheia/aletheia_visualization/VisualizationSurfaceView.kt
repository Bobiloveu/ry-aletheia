package com.ryaletheia.aletheia_visualization

import android.app.Activity
import android.content.Context
import android.view.View
import android.util.Log
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import io.flutter.plugin.platform.PlatformView
import org.json.JSONObject

/**
 * One embedded Unity surface. Owns the control [MethodChannel] and forwards
 * every message to the active [UnitySurfaceProvider]. Control payloads are
 * small (map descriptor, camera, pose, view-mode). The point cloud does NOT
 * come through here — it is staged into the native `aletheia_viz_bridge`
 * buffer from Dart via FFI and read on Unity's render thread.
 */
internal class VisualizationSurfaceView(
    context: Context,
    viewId: Int,
    messenger: BinaryMessenger,
    private val provider: UnitySurfaceProvider,
) : PlatformView, MethodChannel.MethodCallHandler {

    private val channel = MethodChannel(messenger, "aletheia_visualization/surface_$viewId")
    private val surface: View = provider.createSurface(context) { action ->
        Log.i("AletheiaUnity", "native map chrome action=$action viewId=$viewId")
        channel.invokeMethod("mapAction", action)
    }

    init {
        channel.setMethodCallHandler(this)
        provider.onSurfaceCreated(surface, viewId)
    }

    override fun getView(): View = surface

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        when (call.method) {
            "loadMap" -> {
                @Suppress("UNCHECKED_CAST")
                provider.send(surface, "loadMap", JSONObject(call.arguments as Map<String, Any?>).toString())
                result.success(null)
            }
            "setPose" -> {
                @Suppress("UNCHECKED_CAST")
                provider.send(surface, "setPose", JSONObject(call.arguments as Map<String, Any?>).toString())
                result.success(null)
            }
            "setCamera" -> {
                @Suppress("UNCHECKED_CAST")
                provider.send(surface, "setCamera", JSONObject(call.arguments as Map<String, Any?>).toString())
                result.success(null)
            }
            "setViewMode" -> {
                provider.send(surface, "setViewMode", call.arguments as String)
                result.success(null)
            }
            "setLayer" -> {
                @Suppress("UNCHECKED_CAST")
                provider.send(surface, "setLayer", JSONObject(call.arguments as Map<String, Any?>).toString())
                result.success(null)
            }
            "activateSession" -> {
                @Suppress("UNCHECKED_CAST")
                provider.send(surface, "activateSession", JSONObject(call.arguments as Map<String, Any?>).toString())
                result.success(null)
            }
            "pause" -> { provider.pause(); result.success(null) }
            "resume" -> { provider.resume(); result.success(null) }
            "unload" -> { provider.unload(); result.success(null) }
            "isReady" -> result.success(provider.isReady())
            "readMetrics" -> result.success(provider.readMetrics())
            else -> result.notImplemented()
        }
    }

    override fun dispose() {
        channel.setMethodCallHandler(null)
        provider.onSurfaceDisposed(surface)
    }
}

/** Bound at runtime — the stub or the real Unity implementation. */
internal interface UnitySurfaceProvider {
    fun createSurface(context: Context, onMapAction: (String) -> Unit): View
    fun onSurfaceCreated(surface: View, viewId: Int)
    fun onSurfaceDisposed(surface: View)
    fun attachActivity(activity: Activity)
    fun detachActivity()
    fun send(surface: View, method: String, payload: String)
    fun pause()
    fun resume()
    fun unload()
    fun isReady(): Boolean
    fun readMetrics(): Map<String, Any?>

    companion object {
        private var cached: UnitySurfaceProvider? = null

        fun get(): UnitySurfaceProvider {
            cached?.let { return it }
            // `UnitySurfaceProviderImpl` exists in exactly one of the
            // src/stub or src/unity source sets (selected by the
            // aletheia.unityEnabled gradle flag).
            val impl = Class.forName(
                "com.ryaletheia.aletheia_visualization.UnitySurfaceProviderImpl"
            ).getDeclaredConstructor().newInstance() as UnitySurfaceProvider
            cached = impl
            return impl
        }
    }
}
