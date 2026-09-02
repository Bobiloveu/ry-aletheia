#if UNITY_EDITOR
using System.IO;
using System.Text.RegularExpressions;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEngine;
using UnityEngine.Rendering;

namespace Aletheia.Viz.EditorTools
{
    /// <summary>
    /// Exports the trimmed Unity project as a library for the Flutter host.
    ///
    /// Android  -> <c>unity/builds/android/unityLibrary/</c>
    /// iOS      -> <c>unity/builds/ios/</c> (contains UnityFramework project)
    ///
    /// After exporting, follow <c>unity/README.md</c> to wire the artefact into
    /// the plugin (flip <c>aletheia.unityEnabled</c> / <c>ALETHEIA_UNITY_ENABLED</c>).
    /// </summary>
    public static class UaaLBuild
    {
        private static readonly string[] Scenes = { "Assets/Scenes/Viz.unity" };

        // Flutter 3.47's Android plugins require this SDK-managed NDK. Unity
        // emits its bundled NDK 23 path into the generated Gradle module,
        // which makes a combined build fail before IL2CPP starts. Keep the
        // generated module aligned with the Flutter host after every export.
        private const string FlutterHostNdkVersion = "28.2.13676358";

        [MenuItem("Aletheia/Export Android Library")]
        public static void ExportAndroid()
        {
            ExportAndroidLibrary(BuildOptions.AcceptExternalModificationsToPlayer);
        }

        /// <summary>
        /// Device-only diagnostic export. This enables Unity's runtime log
        /// stream so an Android black surface can be distinguished from a
        /// scene/bootstrap failure. Never use this method for distribution.
        /// </summary>
        [MenuItem("Aletheia/Export Android Library (Development)")]
        public static void ExportAndroidDevelopment()
        {
            ExportAndroidLibrary(
                BuildOptions.AcceptExternalModificationsToPlayer |
                BuildOptions.Development |
                BuildOptions.AllowDebugging);
        }

        private static void ExportAndroidLibrary(BuildOptions options)
        {
            EnsureScene();
            EnsureTarget(BuildTargetGroup.Android, BuildTarget.Android);
            ApplyTrimmedPlayerSettings(BuildTargetGroup.Android);
            EditorUserBuildSettings.exportAsGoogleAndroidProject = true;
            var outDir = ProjectRelative("builds/android");
            Directory.CreateDirectory(outDir);
            BuildAndAssert(new BuildPlayerOptions
            {
                scenes = Scenes,
                locationPathName = outDir,
                target = BuildTarget.Android,
                options = options,
            });
            NormalizeAndroidGradleForFlutter(outDir);
        }

        [MenuItem("Aletheia/Export iOS Framework")]
        public static void ExportIos()
        {
            EnsureScene();
            EnsureTarget(BuildTargetGroup.iOS, BuildTarget.iOS);
            ApplyTrimmedPlayerSettings(BuildTargetGroup.iOS);
            var outDir = ProjectRelative("builds/ios");
            Directory.CreateDirectory(outDir);
            BuildAndAssert(new BuildPlayerOptions
            {
                scenes = Scenes,
                locationPathName = outDir,
                target = BuildTarget.iOS,
                // Xcode projects are already externally editable after an iOS
                // export. Unity rejects AcceptExternalModificationsToPlayer
                // for this target (that option is Android-only).
                options = BuildOptions.None,
            });
        }

        private static void ApplyTrimmedPlayerSettings(BuildTargetGroup group)
        {
            PlayerSettings.SetScriptingBackend(group, ScriptingImplementation.IL2CPP);
            // This renderer is reached from Flutter through UnitySendMessage
            // and AndroidJavaClass.  Those are runtime-name based entry
            // points, so high stripping can remove code that has no static
            // C# caller even when link.xml is present.  It was the precise
            // difference between the healthy Development build and a black
            // Release PlatformView on Android.  A small Unity map is not a
            // place to trade correctness for a few megabytes: keep Android
            // at the conservative setting and leave engine code intact.
            // iOS can retain its existing compact setting because its build
            // is embedded through a different native lifecycle.
            PlayerSettings.SetManagedStrippingLevel(
                group,
                group == BuildTargetGroup.Android
                    ? ManagedStrippingLevel.Minimal
                    : ManagedStrippingLevel.High);
            PlayerSettings.stripEngineCode = group != BuildTargetGroup.Android;
            PlayerSettings.SetIl2CppCompilerConfiguration(group, Il2CppCompilerConfiguration.Master);
            PlayerSettings.gpuSkinning = false;
            PlayerSettings.colorSpace = ColorSpace.Gamma;
            PlayerSettings.MTRendering = true;
            PlayerSettings.graphicsJobs = false;
            PlayerSettings.muteOtherAudioSources = false;
            PlayerSettings.accelerometerFrequency = 0;
            PlayerSettings.runInBackground = false;
            // This project is embedded beneath a Flutter HMI, not launched
            // as a standalone game. A Unity-managed splash/fullscreen window
            // can remain over the embedded render target on Android and
            // prevents Flutter from owning system insets/orientation.
            PlayerSettings.SplashScreen.show = false;

            if (group == BuildTargetGroup.Android)
            {
                PlayerSettings.Android.targetArchitectures = AndroidArchitecture.ARM64;
                PlayerSettings.Android.minSdkVersion = AndroidSdkVersions.AndroidApiLevel24;
                PlayerSettings.SetApplicationIdentifier(group, "com.unity3d.framework");
                PlayerSettings.Android.startInFullscreen = false;
                PlayerSettings.Android.renderOutsideSafeArea = false;
                // The map renderer is a small 2D/orthographic workload. Use
                // GLES3 explicitly: it is present on every supported device
                // and avoids a second Vulkan swapchain competing with
                // Flutter Impeller in the same Android process/window.
                PlayerSettings.SetUseDefaultGraphicsAPIs(BuildTarget.Android, false);
                PlayerSettings.SetGraphicsAPIs(
                    BuildTarget.Android,
                    new[] { GraphicsDeviceType.OpenGLES3 });
            }
            if (group == BuildTargetGroup.iOS)
            {
                PlayerSettings.iOS.targetOSVersionString = "13.0";
                PlayerSettings.iOS.appInBackgroundBehavior = iOSAppInBackgroundBehavior.Suspend;
            }

            // Frame pacing: idle when there is no new pose/cloud (VizBridge
            // still needs a heartbeat to poll native, so cap rather than 0).
            QualitySettings.vSyncCount = 0;
            Application.targetFrameRate = 60;
        }

        private static void EnsureScene()
        {
            // The bootstrap is the authoritative scene definition. Rebuild
            // before every export so newly added renderer layers/shader
            // references cannot be silently omitted from an older .unity
            // asset and then stripped from the device player.
            VizSceneBootstrap.Rebuild();
        }

        private static void EnsureTarget(BuildTargetGroup group, BuildTarget target)
        {
            if (!BuildPipeline.IsBuildTargetSupported(group, target))
            {
                throw new System.InvalidOperationException(
                    $"{target} Build Support is not installed for this Unity Editor.");
            }
        }

        private static void BuildAndAssert(BuildPlayerOptions options)
        {
            BuildReport report = BuildPipeline.BuildPlayer(options);
            if (report.summary.result != BuildResult.Succeeded)
            {
                throw new System.InvalidOperationException(
                    $"Unity export failed for {options.target}: {report.summary.result}.");
            }
        }

        private static void NormalizeAndroidGradleForFlutter(string outputDirectory)
        {
            var gradlePath = Path.Combine(outputDirectory, "unityLibrary/build.gradle");
            var source = File.ReadAllText(gradlePath);
            var patched = Regex.Replace(
                source,
                @"^\s*ndkPath\s+.*$",
                $"    ndkVersion '{FlutterHostNdkVersion}'",
                RegexOptions.Multiline);
            patched = patched.Replace(
                "\n}\n\nandroid {\n    task BuildIl2CppTask",
                "\n}\n\next.aletheiaBuildIl2Cpp = this.&BuildIl2Cpp\n\nandroid {\n    task BuildIl2CppTask");
            patched = patched.Replace(
                "              BuildIl2Cpp(projectDir.toString()",
                "              project.ext.aletheiaBuildIl2Cpp.call(projectDir.toString()");
            patched = patched.Replace(
                "    exec {\n        executable workingDir",
                "    project.providers.exec {\n        executable workingDir");
            patched = patched.Replace(
                "    project.providers.exec {\n        executable workingDir",
                "    def aletheiaIl2CppExecution = project.providers.exec {\n        executable workingDir");
            patched = patched.Replace(
                "    }\n    delete workingDir + \"/src/main/jniLibs/\" + abi + \"/libil2cpp.sym.so\"",
                "    }\n    aletheiaIl2CppExecution.result.get()\n    delete workingDir + \"/src/main/jniLibs/\" + abi + \"/libil2cpp.sym.so\"");
            // Flutter creates a `profile` variant for every Android plugin.
            // Unity exports only `debug` and `release`, so an embedded Unity
            // build otherwise fails before compilation with "No matching
            // variant ... profileCompileClasspath". Give the generated
            // library a profile configuration cloned from debug; this is a
            // host integration variant, not a Unity profiling feature.
            const string profileBuildType =
                "    // Aletheia: required by Flutter plugin profile resolution.\n" +
                "    buildTypes {\n" +
                "        profile {\n" +
                "            initWith debug\n" +
                "            matchingFallbacks = ['debug']\n" +
                "        }\n" +
                "    }\n\n";
            if (!patched.Contains("Aletheia: required by Flutter plugin profile resolution."))
            {
                patched = patched.Replace("    lintOptions {", profileBuildType + "    lintOptions {");
            }
            // The Flutter release pipeline minifies the final APK. Unity's
            // native runtime registers UnityPlayer JNI methods by their
            // original names, so the generated library must export a safe
            // consumer rule to its host. Unity's stock rule also includes a
            // global -ignorewarnings directive, which AGP 9 rejects for an
            // AAR consumer rule. Generate the minimal JNI-safe subset instead
            // and declare it on the generated Unity module.
            const string embeddedConsumerRules = "proguard-unity-embedded.txt";
            var embeddedConsumerRulesPath = Path.Combine(
                outputDirectory,
                "unityLibrary",
                embeddedConsumerRules);
            File.WriteAllText(
                embeddedConsumerRulesPath,
                "# Generated by Aletheia UaaLBuild.\n" +
                "# Keep Unity JNI entry points stable in a minified host APK.\n" +
                "-keep class com.unity3d.player.** { *; }\n" +
                "-keep interface com.unity3d.player.IUnityPlayerLifecycleEvents { *; }\n" +
                "# Android Game SDK frame-pacing callbacks are invoked by libunity.\n" +
                "-keep class com.google.androidgamesdk.** { *; }\n" +
                "-dontwarn com.google.android.play.core.assetpacks.**\n" +
                "-dontwarn com.google.android.gms.tasks.**\n");
            patched = patched.Replace(
                "        consumerProguardFiles 'proguard-unity.txt'\n",
                $"        consumerProguardFiles '{embeddedConsumerRules}'\n");
            if (!patched.Contains($"consumerProguardFiles '{embeddedConsumerRules}'"))
            {
                patched = patched.Replace(
                    "    defaultConfig {",
                    $"    defaultConfig {{\n        consumerProguardFiles '{embeddedConsumerRules}'");
            }
            // Unity can retain an already-normalized Gradle file on a
            // subsequent export. Validate the final result instead of
            // requiring a textual change, so exporting is idempotent.
            if (!patched.Contains($"ndkVersion '{FlutterHostNdkVersion}'") ||
                !patched.Contains("project.ext.aletheiaBuildIl2Cpp.call") ||
                !patched.Contains("aletheiaIl2CppExecution.result.get()") ||
                !patched.Contains("Aletheia: required by Flutter plugin profile resolution.") ||
                !patched.Contains($"consumerProguardFiles '{embeddedConsumerRules}'"))
            {
                throw new System.InvalidOperationException(
                    "Unity Android export did not contain the expected NDK or IL2CPP task settings.");
            }
            File.WriteAllText(gradlePath, patched);
        }

        private static string ProjectRelative(string sub)
        {
            // Application.dataPath is <repo>/unity/aletheia_viz/Assets. The
            // export root is its parent Unity folder, not <repo>/unity/unity.
            var projectRoot = Directory.GetParent(Application.dataPath)!.FullName;
            var unityRoot = Directory.GetParent(projectRoot)!.FullName;
            return Path.Combine(unityRoot, sub);
        }
    }
}
#endif
