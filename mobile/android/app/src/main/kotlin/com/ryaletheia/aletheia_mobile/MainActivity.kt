package com.ryaletheia.aletheia_mobile

import android.os.Bundle
import android.view.KeyEvent
import io.flutter.embedding.android.FlutterActivity

class MainActivity : FlutterActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // UnityPlayer looks these host resources up by *name* during PlatformView
        // construction.  AGP's release resource optimizer cannot see that
        // dynamic lookup, so retain concrete references from the host Activity.
        // A keyed tag is intentionally invisible and does not affect Flutter's
        // content or accessibility tree.
        window.decorView.setTag(
            R.id.unitySurfaceView,
            getString(R.string.game_view_content_description),
        )
    }

    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        // An embedded UnityPlayer may hold native focus while the map is in
        // fullscreen mode.  In that state it consumes BACK before Flutter's
        // navigator sees it, leaving the fullscreen SurfaceView alive over a
        // black route.  BACK belongs to the HMI shell, so route it through the
        // Activity dispatcher (which Flutter registers with) instead.
        if (event.keyCode == KeyEvent.KEYCODE_BACK) {
            if (event.action == KeyEvent.ACTION_UP) {
                // FlutterActivity is based on Activity rather than
                // ComponentActivity, so it has no AndroidX back dispatcher.
                // Send the route pop straight to Flutter's navigation channel
                // instead of finishing this Activity while Unity owns focus.
                getFlutterEngine()?.navigationChannel?.popRoute()
            }
            return true
        }
        return super.dispatchKeyEvent(event)
    }
}
