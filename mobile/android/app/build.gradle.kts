plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// Unity 2022 export for this project contains arm64-v8a runtime libraries
// only. Limit an opt-in Unity build to that ABI so the resulting APK cannot be
// installed on an emulator/32-bit device and fail at runtime.
val unityRendererEnabled = System.getenv("ALETHEIA_UNITY_ENABLED") == "1"

// A formal Android release key is intentionally supplied only by the build
// environment.  Keeping its location and passwords out of source control lets
// the same project produce either an installable internal package or a
// distributable, update-compatible release package.
val androidReleaseKeystorePath = System.getenv("ALETHEIA_ANDROID_KEYSTORE")
val androidReleaseStorePassword = System.getenv("ALETHEIA_ANDROID_KEYSTORE_PASSWORD")
val androidReleaseKeyAlias = System.getenv("ALETHEIA_ANDROID_KEY_ALIAS")
val androidReleaseKeyPassword = System.getenv("ALETHEIA_ANDROID_KEY_PASSWORD")
val hasAndroidReleaseSigning = listOf(
    androidReleaseKeystorePath,
    androidReleaseStorePassword,
    androidReleaseKeyAlias,
    androidReleaseKeyPassword,
).all { !it.isNullOrBlank() }

android {
    namespace = "com.ryaletheia.aletheia_mobile"
    compileSdk = flutter.compileSdkVersion
    // All Flutter plugins require this SDK-managed NDK. The Unity export is
    // normalized to the same version by UaaLBuild after every export.
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "com.ryaletheia.aletheia_mobile"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        // Uses the version code from pubspec.yaml. When using split APKs, 1000 * ABI_VERSION
        // is added automatically by Flutter. (https://developer.android.com/studio/build/configure-apk-splits#configure-APK-versions)
        // You can force using the value of versionCode by specifying the `-P force-version-code-ignoring-abi=true`
        // flag during build.
        versionCode = flutter.versionCode
        versionName = flutter.versionName
        if (unityRendererEnabled) {
            ndk {
                abiFilters += "arm64-v8a"
            }
        }
    }

    // Unity 2022's Android player resolves `libmain.so` and `libunity.so`
    // through the application's native-library directory during startup.
    // Flutter/AGP otherwise defaults to non-extracted native libraries, which
    // produces an APK whose merged manifest says `extractNativeLibs=false`.
    // That contract is valid for ordinary Flutter plugins but can abort the
    // Unity player the instant its embedded PlatformView is created. Keep the
    // setting opt-in with the Unity renderer so the regular Flutter APK keeps
    // its normal packaging behaviour.
    if (unityRendererEnabled) {
        packaging {
            jniLibs {
                useLegacyPackaging = true
            }
        }
    }

    signingConfigs {
        if (hasAndroidReleaseSigning) {
            create("aletheiaRelease") {
                storeFile = file(requireNotNull(androidReleaseKeystorePath))
                storePassword = requireNotNull(androidReleaseStorePassword)
                keyAlias = requireNotNull(androidReleaseKeyAlias)
                keyPassword = requireNotNull(androidReleaseKeyPassword)
            }
        }
    }

    buildTypes {
        release {
            // Unity registers the methods on UnityPlayer directly from its
            // native runtime. Flutter's release build enables R8, so this
            // rule must be applied by the final application (not merely kept
            // next to the generated Unity library) or JNI_OnLoad aborts when
            // the embedded PlatformView is first created.
            if (unityRendererEnabled) {
                proguardFiles("proguard-rules.pro")
            }
            // Without all four environment values above, retain the existing
            // internal-test behavior.  The package script labels it clearly as
            // debug-signed; it must not be distributed as a formal release.
            signingConfig = if (hasAndroidReleaseSigning) {
                signingConfigs.getByName("aletheiaRelease")
            } else {
                signingConfigs.getByName("debug")
            }
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}
