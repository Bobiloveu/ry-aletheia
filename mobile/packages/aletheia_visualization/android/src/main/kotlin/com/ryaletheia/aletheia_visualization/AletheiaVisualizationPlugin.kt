package com.ryaletheia.aletheia_visualization

import android.content.Context
import io.flutter.embedding.engine.plugins.FlutterPlugin
import io.flutter.embedding.engine.plugins.activity.ActivityAware
import io.flutter.embedding.engine.plugins.activity.ActivityPluginBinding
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.StandardMessageCodec
import io.flutter.plugin.platform.PlatformView
import io.flutter.plugin.platform.PlatformViewFactory

/**
 * Registers the `aletheia_visualization/surface` platform view. The view is a
 * renderer only — it receives a map, camera, pose and (via the native FFI
 * bridge, not this channel) a point cloud. It never touches ROS2, the backend,
 * task services or video.
 */
class AletheiaVisualizationPlugin : FlutterPlugin, ActivityAware {

    private var messenger: BinaryMessenger? = null

    override fun onAttachedToEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        messenger = binding.binaryMessenger
        binding.platformViewRegistry.registerViewFactory(
            "aletheia_visualization/surface",
            UnityViewFactory(binding.binaryMessenger, binding.applicationContext),
        )
    }

    override fun onDetachedFromEngine(binding: FlutterPlugin.FlutterPluginBinding) {
        messenger = null
    }

    override fun onAttachedToActivity(binding: ActivityPluginBinding) {
        UnitySurfaceProvider.get().attachActivity(binding.activity)
    }

    override fun onDetachedFromActivity() {
        UnitySurfaceProvider.get().detachActivity()
    }

    override fun onReattachedToActivityForConfigChanges(binding: ActivityPluginBinding) =
        onAttachedToActivity(binding)

    override fun onDetachedFromActivityForConfigChanges() = onDetachedFromActivity()
}

private class UnityViewFactory(
    private val messenger: BinaryMessenger,
    private val appContext: Context,
) : PlatformViewFactory(StandardMessageCodec.INSTANCE) {

    override fun create(context: Context?, viewId: Int, args: Any?): PlatformView {
        return VisualizationSurfaceView(
            context ?: appContext,
            viewId,
            messenger,
            UnitySurfaceProvider.get(),
        )
    }
}
