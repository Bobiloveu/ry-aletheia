package com.ryaletheia.aletheia_visualization

import android.app.Activity
import android.content.Context
import android.graphics.Color
import android.view.View

/**
 * Stub provider used until the Unity module is exported
 * (`aletheia.unityEnabled=false`). Renders a flat surface so the plugin loads
 * cleanly; the app falls back to the Flutter renderer.
 */
internal class UnitySurfaceProviderImpl : UnitySurfaceProvider {
    override fun createSurface(context: Context, onMapAction: (String) -> Unit): View =
        View(context).apply { setBackgroundColor(Color.parseColor("#0C1011")) }

    override fun onSurfaceCreated(surface: View, viewId: Int) {}
    override fun onSurfaceDisposed(surface: View) {}
    override fun attachActivity(activity: Activity) {}
    override fun detachActivity() {}
    override fun send(surface: View, method: String, payload: String) {}
    override fun pause() {}
    override fun resume() {}
    override fun unload() {}
    override fun isReady(): Boolean = false
    override fun readMetrics(): Map<String, Any?> = emptyMap()
}
