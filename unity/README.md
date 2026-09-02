# Aletheia Unity 可视化 PoC（当前暂停）

> **暂停状态（2026-09-02）**：移动端正式主线已固定为 Flutter `CustomPaint`；正式包不加载 Unity runtime，也不显示 Unity 启动标识。本目录和 `mobile/packages/aletheia_visualization/` 仅保留为性能 PoC，不能作为默认构建或发布路径。恢复前必须先阅读 [`../docs/UNITY_PAUSED_HANDOFF.md`](../docs/UNITY_PAUSED_HANDOFF.md)，并完成其中规定的 Android 模拟器尺寸与全屏压力测试。

## 作用与硬边界

Unity 是**纯渲染器**：Flutter Host 通过 platform channel 传入地图、相机变换和位姿，通过 FFI 传入点云缓冲；Unity 只负责绘制。它绝不接触 ROS2、Backend API、任务 JSON、任务恢复、业务逻辑或 WebRTC 视频流。Flutter 保有所有业务所有权，并始终保留 `FlutterVisualizationEngine` 作为默认渲染器和回退路径。

```text
Flutter Host（业务、地图数据、生命周期）
  └─ visualizationEngineProvider
       ├─ FlutterVisualizationEngine（默认，_MapViewport）
       └─ UnityVisualizationEngine（仅显式 PoC 开关）
            └─ package:aletheia_visualization
                 ├─ MethodChannel：loadMap / camera / pose / viewMode / lifecycle
                 ├─ EventChannel：回传 metrics
                 └─ dart:ffi：libaletheia_viz_bridge（latest-wins 暂存缓冲）
                      └─ Unity DllImport → GraphicsBuffer → GPU 点着色器
```

本目录只保存 Unity **项目源码**。`unityLibrary` Gradle module 和 `UnityFramework.framework` 都是生成物，必须保持 git-ignored。

## 恢复前的必做验证

以下验证使用 `mobile/assets/debug_ui/sample_map.png` 中原始的 `3480 × 10017` 占据栅格，不能改用占位图或下采样副本：

```sh
unity='/Applications/Unity/Hub/Editor/2022.3.62f1/Unity.app/Contents/MacOS/Unity'

# 不得加入 -nographics：必须验证 Metal 设备能力，结果应报告 maxTextureSize >= 10017。
"$unity" -batchmode -quit -projectPath "$PWD/unity/aletheia_viz" \
  -executeMethod Aletheia.Viz.EditorTools.VizFixtureValidation.ValidateFullResolutionMapFixture

# 验证固定的 262,144 点 GPU 分配；超限 XY 输入必须被限流，不能进入 SetData。
"$unity" -batchmode -quit -projectPath "$PWD/unity/aletheia_viz" \
  -executeMethod Aletheia.Viz.EditorTools.VizFixtureValidation.ValidatePointCloudFrameBounds
```

`-nographics` 使用 Null graphics device，通常只会报告 4096 纹理上限；它可用于 C# 编译检查，却不能证明这张高图能够渲染。当前 Apple M2 Metal 主机曾以 `maxTextureSize=16384` 绑定该夹具，恢复后仍必须在目标真机通过 Unity runtime diagnostic 验证。

Flutter/HMI 压力检查（含无法链接 Unity iPhoneOS framework 的 iOS Simulator）可使用生产页面的 Debug 确定性场景：

```sh
cd mobile
fvm flutter run --debug -d <iOS-simulator-id> \
  --route '/__debug/ui-gallery?screen=observe_stress'
```

该场景使用同一张全分辨率地图，并生成有界 latest-wins 遥测：60 Hz 位姿、8 Hz / 3,000 个 XY 点。它不能替代 iPhone 上的 Unity 真机验证。

## 固定工具链与项目打开方式

- Unity 固定为 **2022.3.62f1**（`4af31df58517`，Apple Silicon），版本以 `ProjectSettings/ProjectVersion.txt` 为准，并需安装 Android 与 iOS Build Support。不得使用本机可能安装的 2022.3.73f1 Extended LTS：Unity Personal 会要求 Industry 或 Enterprise 许可证。
- Android 中 Unity 附带 NDK 必须与 Flutter Android toolchain 匹配。iOS 需要 Xcode 和真实 iPhone。
- 使用 Unity Hub：**Add project from disk** → `unity/aletheia_viz`。首次打开执行 `Aletheia ▸ Rebuild Viz Scene`，它从 `Assets/Editor/VizSceneBootstrap.cs` 生成 `Assets/Scenes/Viz.unity`；生成的 `.unity` 和 `.meta` 文件应提交。
- Package Manager 的 In Project 仅应保留 URP 和必要核心模块；禁用 XR、Audio 和 analytics。

## 渲染管线不变量

项目有意使用 Unity **Built-in Render Pipeline**：`GraphicsSettings.asset` 没有指定 custom pipeline。渲染器 shader 因此必须是基于 `UnityCG.cginc` 的 Built-in `CGPROGRAM` shader；除非整个项目迁移到真实 URP asset，否则不得加入 `RenderPipeline = UniversalPipeline` tag 或 URP `Core.hlsl` include。iOS 上不兼容的 pass 会退回品红色错误材质，并可能让大工作区格栅遮蔽地图。

## 导出与接入（仅恢复 PoC 时）

### Android

```text
Unity 菜单：Aletheia ▸ Export Android Library
输出：unity/builds/android/（包含 ./unityLibrary）
```

1. 不得手动 `include ':unityLibrary'` 或修改插件开关。Host 仅在 `ALETHEIA_UNITY_ENABLED=1` 时包含生成模块。
2. `UaaLBuild.ExportAndroid` 会将 Unity 生成的 Gradle 文件适配 Flutter Host 的 NDK、Gradle 9 task API 和 Flutter 所需 `profile` build variant（映射为 Unity debug 配置）。每次 scene/script/shader 变化后重新导出；不得手工维护被忽略的输出。
3. Unity 输出仅为 **arm64-v8a**，只支持实体 Android 设备，不支持 Emulator 或 32 位硬件。

### iOS

```text
Unity 菜单：Aletheia ▸ Export iOS Framework
输出：unity/builds/ios/（Xcode 项目会生成 UnityFramework.framework）
```

1. 在导出 Xcode 项目中构建 Release `UnityFramework.framework`。它从已加载的 `aletheia_visualization.framework` 解析共享渲染桥；不得加入第二份桥接库或 `-undefined dynamic_lookup` linker setting。
2. 将 framework 与**同一导出根目录**的 `Data` 同时复制到插件目录：

   ```sh
   rsync -a --delete \
     "$PWD/unity/builds/ios/build/Release-iphoneos/UnityFramework.framework/" \
     "$PWD/mobile/packages/aletheia_visualization/ios/UnityLibrary/UnityFramework.framework/"
   rsync -a --delete "$PWD/unity/builds/ios/Data/" \
     "$PWD/mobile/packages/aletheia_visualization/ios/UnityLibrary/Data/"
   ```

   不得复制 `unity/builds/ios/Unity-iPhone/Data`；它不是当前权威导出，可能让旧 IL2CPP metadata 与新 framework 混用，并在 Unity 启动、地图加载前导致 iOS 崩溃。若本地存在导出，`build_mobile_packages.sh --engine unity` 会拒绝该陈旧配对。

3. 只在**实体 iPhone**启用生成物：

   ```sh
   cd mobile/ios
   ALETHEIA_UNITY_ENABLED=1 pod install
   cd ..
   ALETHEIA_UNITY_ENABLED=1 fvm flutter run \
     --dart-define=AV_ENGINE=unity \
     --dart-define=AV_UNITY_RUNTIME=true -d <physical-ios-device-id>
   ```

   plugin podspec 嵌入 framework 并将 `Data` 复制到插件 resource bundle；`UnitySurfaceProvider` 在运行时解析此 bundle，不需要编辑 Runner Xcode project。
4. 返回 Simulator/Flutter 路径前，重新执行普通 `pod install`，再使用普通 `fvm flutter run`。Unity 2022 的 iPhoneOS framework 有意不链接到 Simulator build。

## 代理与运行约束

若 macOS 导出了 `HTTP_PROXY` 或 `HTTPS_PROXY`，运行依附 Simulator 或真机的 Flutter 命令前必须清除所有 proxy 变量；否则 Dart VM Service 的本地 WebSocket 可能被代理转发并报 `Connection closed before full header was received`：

```sh
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
  -u http_proxy -u https_proxy -u all_proxy \
  ALETHEIA_UNITY_ENABLED=1 fvm flutter run --debug \
  --dart-define=AV_ENGINE=unity \
  --dart-define=AV_UNITY_RUNTIME=true -d <physical-ios-device-id>
```

`AV_ENGINE=unity` 单独存在时，在原生导出不可用（包括 iOS Simulator）时有意保留 Flutter `CustomPaint`。真实 Unity 设备包还必须设置 `AV_UNITY_RUNTIME=true`；没有导出时这种包配置无效，应重新构建，绝不能发布空白地图界面。

## 里程碑与恢复范围

| 里程碑 | 范围 | 当前保留状态 |
| --- | --- | --- |
| M1 | 最小 Unity + bridge、占据地图、正交相机自适应格栅、干净 create/unload | scene generation、Android `unityLibrary` 和 iOS UnityFramework/Data 的导出代码保留；真机 surface attach/detach/pause/resume/unload 仍需验证。 |
| M2 | 位姿 EventChannel、2D 点云（FFI → `GraphicsBuffer` → 点 shader）、车体 footprint、Flutter 所有的相机 | 代码存在，受 M1 前置条件限制。 |
| M3 | 3D 点云、3D 机器人 primitive、orbit camera、2D/3D 切换 | camera 与 shader 支持存在，未作为当前功能验证。 |
| M4 | 有界点云压力、A/B harness、真机指标 | Editor 固定上限验证和 Flutter Simulator 3,000 点场景可用；真机指标仍必需。 |

当前恢复工作不得额外加入虚拟墙、轨迹、导航路径、costmap、digital twin 或手动重定位。`VisualizationController.setLayerVisible` 与 `VizBridge` 图层处理只是预留钩子。未来若做重定位，场景应能容纳 `map + local cloud + candidate pose + interactive x/y/yaw align`，但当前不得实现功能。

## 裁剪清单

`Assets/Editor/UaaLBuild.cs` 应用 Player Settings。移除或保持禁用：XR & AR、Audio、Timeline、Cinemachine、Terrain、AI/NavMesh、Physics & Physics2D、ParticleSystem、Analytics、Ads、Purchasing、Remote Config、Video、未使用 Animation、TextMeshPro 示例和所有 sample assets。

保留：URP core（一个 forward renderer、无 renderer feature）、IL2CPP + arm64、managed + engine code stripping High、incremental GC、MSAA off、HDR off、无阴影、无 depth/opaque texture、Gamma color space 与受限 `targetFrameRate`。
