# Unity as a Library is initialized through RegisterNatives in libunity.so.
# Its Java entry points are addressed by their original names, not through
# ordinary Java call sites.  Keep the complete Unity player API intact in a
# minified Flutter release; otherwise JNI_OnLoad aborts as soon as an embedded
# UnityPlayer view is constructed.
-keep class com.unity3d.player.** { *; }
-keep interface com.unity3d.player.IUnityPlayerLifecycleEvents { *; }

# libunity invokes this bridge from native code while bringing up IL2CPP's
# managed runtime.  There is no ordinary Java call site, so it is invisible
# to R8 unless it is explicitly retained.  Removing it makes Unity log
# `JNI:FilesDir: ClassNotFoundException: bitter.jnibridge.JNIBridge`, after
# which the managed data extraction path is empty and the embedded scene
# remains black.
-keep class bitter.jnibridge.** { *; }

# Unity's Android frame-pacing bridge is also registered from native code.
# It has no ordinary host-side Java call sites, so R8 otherwise removes it.
-keep class com.google.androidgamesdk.** { *; }
# Called by Unity through AndroidJavaClass; the reference is not visible to R8.
-keep class com.ryaletheia.aletheia_visualization.UnityLifecycleBridge { *; }

# This trimmed renderer does not ship Unity Play Asset Delivery.  The Unity
# Java wrapper references it opportunistically, so tell R8 these optional
# integrations are intentionally absent rather than restoring Unity's broad
# (and invalid as a consumer rule) -ignorewarnings setting.
-dontwarn com.google.android.play.core.assetpacks.**
-dontwarn com.google.android.gms.tasks.**
