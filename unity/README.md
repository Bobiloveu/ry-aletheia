# Aletheia Unity Visualization — PoC（当前暂停）

> **暂停通知（2026-09-02）**：移动端主线已固定为 Flutter `CustomPaint` 渲染，正式包不加载 Unity runtime，亦不显示 Unity 启动标识。本目录及其 Flutter plugin 仅作为保留的性能 PoC，禁止作为默认构建或直接用于发布。恢复前请先阅读 [`../docs/UNITY_PAUSED_HANDOFF.md`](../docs/UNITY_PAUSED_HANDOFF.md)，并完成其中规定的 Android 模拟器尺寸/全屏压力测试。

Unity is a **renderer only**. It never touches ROS2, the backend API, task
JSON, mission recovery, business logic or the WebRTC video feeds. It receives a
map, a camera transform, a pose (platform channels) and a point-cloud buffer
(FFI) from the Flutter host, and draws them. Flutter owns everything else and
keeps its own renderer (`FlutterVisualizationEngine`) as the permanent
fallback.

```
Flutter (host, unchanged)
  live_observation providers ── pose/cloud/map ──┐
                                                 │
  visualizationEngineProvider                    │  --dart-define=AV_ENGINE=unity
    ├─ FlutterVisualizationEngine  (default, fallback — _MapViewport)
    └─ UnityVisualizationEngine  ──► package: aletheia_visualization
                                       ├─ MethodChannel  loadMap / camera / pose / viewMode / lifecycle
                                       ├─ EventChannel    (metrics back)
                                       └─ dart:ffi ──► libaletheia_viz_bridge  (latest-wins staging buffer)
                                                            ▲
                                       Unity  ──DllImport── ┘   GraphicsBuffer ► GPU point shader
```

This folder holds the Unity **project source only**. The build artefacts
(`unityLibrary` gradle module, `UnityFramework.framework`) are generated and
git-ignored.

## Repeatable map / cloud validation

Run these before creating a Unity device package. They use the supplied,
unchanged `3480 × 10017` occupancy image in
`mobile/assets/debug_ui/sample_map.png`, not a placeholder or a downsampled
copy:

```sh
unity='/Applications/Unity/Hub/Editor/2022.3.62f1/Unity.app/Contents/MacOS/Unity'

# Do not add -nographics to this check: the Metal device capability is part
# of the result. It must report maxTextureSize >= 10017.
"$unity" -batchmode -quit -projectPath "$PWD/unity/aletheia_viz" \
  -executeMethod Aletheia.Viz.EditorTools.VizFixtureValidation.ValidateFullResolutionMapFixture

# Verifies the exact 262,144-point fixed GPU allocation and an oversized XY
# caller. Oversized input must remain capped rather than reaching SetData.
"$unity" -batchmode -quit -projectPath "$PWD/unity/aletheia_viz" \
  -executeMethod Aletheia.Viz.EditorTools.VizFixtureValidation.ValidatePointCloudFrameBounds
```

`-nographics` reports a Null graphics device and commonly a 4096 texture
limit, so it is useful for C# compilation but **not** evidence that this tall
map can render. On the current Apple M2 Metal host the fixture binds at
`3480 × 10017` with `maxTextureSize=16384`; the physical target must still be
checked through Unity's runtime diagnostic after package installation.

For Flutter/HMI pressure review (including iOS Simulator, where Unity's
iPhoneOS framework is intentionally unavailable), launch the production page
with its Debug-only deterministic scenario:

```sh
cd mobile
flutter run --debug -d <iOS-simulator-id> \
  --route '/__debug/ui-gallery?screen=observe_stress'
```

It renders the same full-resolution map while generating bounded, latest-wins
telemetry: 60 Hz pose and 8 Hz / 3,000 XY point-cloud samples. It is not a
replacement for physical-iPhone Unity validation.

---

## One-time setup

**Requirements** (host machine, not this environment):

- Unity **2022.3.62f1** (`4af31df58517`, Apple Silicon), with Android + iOS
  build modules. This is the version pinned in `ProjectSettings/ProjectVersion.txt`.
  Do not use the locally installed 2022.3.73f1 Extended LTS editor for this
  project: Unity Personal reports it as requiring an Industry or Enterprise
  licence.
- Android: Unity's bundled NDK must match Flutter's (`flutter doctor -v` →
  "Android toolchain"). Xcode + a real iOS device for iOS.
- The `mobile/` Flutter app builds already.

**Open the project**

1. Unity Hub → *Add project from disk* → `unity/aletheia_viz`.
2. First open: `Aletheia ▸ Rebuild Viz Scene` (menu). This generates
   `Assets/Scenes/Viz.unity` from `Assets/Editor/VizSceneBootstrap.cs` so the
   scene graph stays reviewable. Commit the generated `.unity` + `.meta` files.
3. Confirm the trimmed package set: **Window ▸ Package Manager ▸ In Project**
   should show only URP + a few core modules. Remove anything else. Project
   Settings: no XR, Audio disabled, no analytics.

---

## Build the library (per platform, after any script/shader/scene change)

### Render-pipeline invariant

This project deliberately runs Unity's **Built-in Render Pipeline**
(`GraphicsSettings.asset` has no assigned custom pipeline). Renderer shaders
must therefore be pipeline-neutral Built-in `CGPROGRAM` shaders using
`UnityCG.cginc`; do not add a `RenderPipeline = UniversalPipeline` tag or URP
`Core.hlsl` include unless the entire project is migrated to a real URP asset.
On iOS an incompatible pass falls back to Unity's magenta error material, and
the large workspace grid then hides the map.

### Android

```
Unity menu:  Aletheia ▸ Export Android Library
# output → unity/builds/android/   (contains ./unityLibrary)
```

Wire it into the app **once**:

1. Do not manually include `:unityLibrary` or edit the plugin flag. The host
   includes the generated module only when `ALETHEIA_UNITY_ENABLED=1` is set.
2. `UaaLBuild.ExportAndroid` normalizes Unity's generated Gradle file to the
   Flutter host's NDK, Gradle 9 task APIs, and Flutter's required `profile`
   build variant (mapped to Unity's debug configuration). Re-export Unity whenever a
   scene/script/shader changes; do not hand-maintain ignored output.
3. Unity output is **arm64-v8a only**. Unity APKs are for physical Android
   devices, not emulators or 32-bit hardware.

### iOS

```
Unity menu:  Aletheia ▸ Export iOS Framework
# output → unity/builds/ios/   (Xcode project producing UnityFramework.framework)
```

1. Build `UnityFramework.framework` from that Xcode project (Release). The
   framework resolves the shared renderer bridge from the already-loaded
   `aletheia_visualization.framework`; do not add a second bridge library or
   `-undefined dynamic_lookup` linker setting to the generated Xcode project.
2. Copy `UnityFramework.framework` **and the matching export-root `Data`
   directory** into `mobile/packages/aletheia_visualization/ios/UnityLibrary/`:
   ```sh
   rsync -a --delete \
     "$PWD/unity/builds/ios/build/Release-iphoneos/UnityFramework.framework/" \
     "$PWD/mobile/packages/aletheia_visualization/ios/UnityLibrary/UnityFramework.framework/"
   rsync -a --delete "$PWD/unity/builds/ios/Data/" \
     "$PWD/mobile/packages/aletheia_visualization/ios/UnityLibrary/Data/"
   ```
   Do **not** copy `unity/builds/ios/Unity-iPhone/Data`: it is not the
   authoritative current export and can leave an old IL2CPP metadata file next
   to a new framework. That mismatch crashes iOS during Unity startup, before
   the map is loaded. `build_mobile_packages.sh --engine unity` rejects this
   stale pairing when the local export is present.
3. Enable the generated artefacts for a **physical iPhone** only:
   ```sh
   cd mobile/ios
   ALETHEIA_UNITY_ENABLED=1 pod install
   cd ..
   ALETHEIA_UNITY_ENABLED=1 flutter run \
     --dart-define=AV_ENGINE=unity \
     --dart-define=AV_UNITY_RUNTIME=true -d <physical-ios-device-id>
   ```
   The plugin podspec embeds the framework and copies `Data` into the plugin
   resource bundle; `UnitySurfaceProvider` resolves that bundle at runtime.
   No Runner Xcode project edit is required.
4. To return to simulator/Flutter rendering, rerun plain `pod install` then
   use ordinary `flutter run`. Unity 2022's iPhoneOS framework deliberately
   is not linked into simulator builds.

### macOS development proxy note

If the development Mac exports `HTTP_PROXY` / `HTTPS_PROXY`, remove all proxy
variables for Flutter commands that attach to a Simulator or physical device.
Otherwise Dart VM Service's local WebSocket can be routed through the proxy and
fail with `Connection closed before full header was received`, even though the
App and Unity runtime are healthy:

```sh
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
  -u http_proxy -u https_proxy -u all_proxy \
  ALETHEIA_UNITY_ENABLED=1 flutter run --debug \
  --dart-define=AV_ENGINE=unity \
  --dart-define=AV_UNITY_RUNTIME=true -d <physical-ios-device-id>
```

---

## Run the PoC engine

```sh
cd mobile

# Recommended reusable packaging entrypoint. It validates the required Unity
# exports, produces timestamped artifacts plus SHA-256 files in build/artifacts,
# and keeps signing secrets in environment variables only.
./tool/build_mobile_packages.sh --engine unity --platform all

# Android real Unity renderer (arm64-v8a physical device only)
ALETHEIA_UNITY_ENABLED=1 flutter build apk --release \
  --dart-define=AV_ENGINE=unity \
  --dart-define=AV_UNITY_RUNTIME=true

# iOS real Unity renderer (physical iPhone only)
cd ios && ALETHEIA_UNITY_ENABLED=1 pod install && cd ..
ALETHEIA_UNITY_ENABLED=1 flutter build ipa --release \
  --export-method development \
  --dart-define=AV_ENGINE=unity \
  --dart-define=AV_UNITY_RUNTIME=true

# Interactive iPhone verification (Debug Gallery supplies a real mock map,
# pose and cloud without robot/ROS access)
ALETHEIA_UNITY_ENABLED=1 flutter run --debug \
  --route '/__debug/ui-gallery?screen=observe_live' \
  --dart-define=AV_ENGINE=unity \
  --dart-define=AV_UNITY_RUNTIME=true -d <physical-ios-device-id>

# Flutter renderer (default, including iOS Simulator)
flutter run
```

After an iOS Unity build, run a plain `cd ios && pod install` before returning
to iOS Simulator/Flutter renderer work. The two renderer packages currently
share one bundle identifier; installing one replaces the other on a device.

`AV_ENGINE=unity` alone deliberately retains Flutter `CustomPaint` when the
native export is unavailable (including the iOS Simulator). A real Unity
device package additionally sets `AV_UNITY_RUNTIME=true`; without the export,
that package configuration is invalid and should be rebuilt rather than
shipping a blank map surface.

---

## Milestone status

| Milestone | Scope | State |
| --- | --- | --- |
| **M1** | Min Unity + bridge, occupancy map + adaptive grid via Unity ortho camera; clean create/unload | scene generation, Android `unityLibrary` is embedded into a successful arm64 Unity APK; iOS UnityFramework/Data are embedded into a successful device IPA. Full on-device surface attach/detach/pause/resume/unload remains a physical-device check. |
| **M2** | Pose (EventChannel) + 2D cloud (FFI → `GraphicsBuffer` → point shader) + footprint; Flutter-owned camera | code present, gated behind M1 |
| **M3** | 3D cloud, 3D robot primitive, orbit camera, 2D/3D toggle | camera + shader support present; not exercised |
| **M4** | bounded point-cloud stress + A/B harness + on-device metrics | Editor fixed-cap validation and Flutter Simulator 3,000-point scenario are available; physical-device metrics remain required. |

Do **not** add virtual walls, trajectory, nav path, costmap, digital twin or
manual relocalization this round. `VisualizationController.setLayerVisible` and
`VizBridge` layer handling are hooks only. Relocalization: the scene must be
able to host `map + local cloud + candidate pose + interactive x/y/yaw align`
later — no functional work now.

---

## Trimming checklist (`Assets/Editor/UaaLBuild.cs` applies the player settings)

Remove / keep disabled: XR & AR, Audio, Timeline, Cinemachine, Terrain,
AI/NavMesh, Physics & Physics2D, ParticleSystem, Analytics, Ads, Purchasing,
Remote Config, Video, Animation (if unused), TextMeshPro examples, all sample
assets.

Keep: URP core (one forward renderer, no renderer features), IL2CPP + arm64,
managed + engine code stripping High, incremental GC, MSAA off, HDR off, no
shadows, no depth/opaque texture, Gamma color space, `targetFrameRate` capped.
