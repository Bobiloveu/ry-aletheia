pluginManagement {
    val flutterSdkPath =
        run {
            val properties = java.util.Properties()
            file("local.properties").inputStream().use { properties.load(it) }
            val flutterSdkPath = properties.getProperty("flutter.sdk")
            require(flutterSdkPath != null) { "flutter.sdk not set in local.properties" }
            flutterSdkPath
        }

    includeBuild("$flutterSdkPath/packages/flutter_tools/gradle")

    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

plugins {
    id("dev.flutter.flutter-plugin-loader") version "1.0.0"
    id("com.android.application") version "9.1.0" apply false
    id("org.jetbrains.kotlin.android") version "2.4.0" apply false
}

include(":app")

// Unity as a Library is deliberately opt-in. The generated module is ignored
// from Git and only exists after the Unity export documented in unity/README.
// Keeping this conditional preserves the normal Flutter renderer build (and
// its emulator compatibility) when no Unity artefact is present.
if (System.getenv("ALETHEIA_UNITY_ENABLED") == "1") {
    val unityLibraryDir = file("../../unity/builds/android/unityLibrary")
    check(unityLibraryDir.isDirectory) {
        "Unity Android library is missing. Export it from unity/aletheia_viz first."
    }
    include(":unityLibrary")
    project(":unityLibrary").projectDir = unityLibraryDir
}
