package com.ryaletheia.aletheia_visualization

import android.util.Log
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

/**
 * Android-Java readiness bridge called directly from Unity's managed scene.
 *
 * Unity-as-a-Library can load native plugins in a linker namespace that is
 * isolated from the host application's JNI library.  A shared-C readiness
 * flag is therefore useful for metrics but cannot be the sole scene-ready
 * handshake on Android.  This class lives in the host app class loader and
 * gives `VizBridge.Start()` an unambiguous, lifecycle-safe acknowledgement.
 */
object UnityLifecycleBridge {
    private val sceneReady = AtomicBoolean(false)
    private val lastDiagnostic = AtomicReference<String>("not-started")

    /**
     * Release Unity builds suppress Debug.Log by default, so native Android
     * logcat is the only reliable way to distinguish a non-running scene from
     * a running scene whose SurfaceView has no visible buffer.  This is a
     * diagnostic seam only; it does not participate in rendering or state.
     */
    @JvmStatic
    fun markDiagnostic(stage: String) {
        lastDiagnostic.set(stage)
        Log.i(logTag, "Unity managed stage=$stage")
    }

    @JvmStatic
    fun markSceneReady() {
        sceneReady.set(true)
        Log.i(logTag, "VizRoot.Start acknowledged by Android host")
    }

    @JvmStatic
    fun markSceneStopped() {
        sceneReady.set(false)
        Log.i(logTag, "VizRoot stopped")
    }

    @JvmStatic
    fun isSceneReady(): Boolean = sceneReady.get()

    @JvmStatic
    fun lastDiagnostic(): String = lastDiagnostic.get()

    private const val logTag = "AletheiaUnity"
}
