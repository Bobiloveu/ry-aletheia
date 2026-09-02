# 当前开发断点

## 2026-09-02：主线切回 Flutter 渲染，Unity 嵌入暂停

### 当前决策

- 正式运行路径固定使用 Flutter `CustomPaint` 地图渲染；`visualizationEngineProvider` 不再读取 Unity 的运行时开关。
- App 启动直接进入 Flutter，正式包不再展示 Unity 标识或 Unity 启动页。
- Unity 导出、原生桥接与 PlatformView 代码作为后续性能原型保留，但不参与当前主线构建、启动或地图界面。
- `tool/build_mobile_packages.sh` 的默认引擎已改为 `flutter`；显式传入 `--engine unity` 才会构建暂停中的原型。
- Unity 的恢复前置条件、保留入口与已知 PlatformView 风险集中记录在
  [`UNITY_PAUSED_HANDOFF.md`](UNITY_PAUSED_HANDOFF.md)；恢复工作必须从该文档的模拟器压力测试开始。

### 本轮验证与交付

- 定向 Flutter 组件测试通过：地图横屏/拖拽缩放、全屏工作区和渲染引擎回退契约。
- `flutter analyze lib/app/app.dart lib/features/live_observation/presentation/live_observation_screen.dart` 通过，`git diff --check` 通过。
- 已将旧 Android/iOS 编译输出移出 `mobile/build/`；新构建仅保留
  `aletheia-flutter-internal-debug-signed-20260902-2025.apk` 与
  `aletheia-flutter-release-development-20260902-2025.ipa`，以及各自的 SHA-256 文件。
- APK 使用现有 debug key 的 Release 构建（v2 签名已验证）；由于环境未提供正式 Android keystore，不能把它标记为商店/正式签名。
  IPA 使用 Xcode 当前 Development 导出配置。

### 相关文件

- `mobile/lib/app/app.dart`
- `mobile/lib/features/live_observation/presentation/live_observation_screen.dart`
- `mobile/tool/build_mobile_packages.sh`


## 2026-09-02：Android Unity 全屏返回的跨宿主相机竞态修复（最新）

### 当前目标

消除 Android Unity 地图在“卡片 → 全屏 → 返回卡片”后被旧宿主相机状态覆盖、出现错误缩放/视觉畸变的问题。

### 已完成

- 根因已由真机日志确认：全屏与卡片 PlatformView 短暂并存，但相机 FFI 缓存是进程级且没有来源；同时，离开的
  `VisualizationController.dispose()` 会调用进程级 `av_bridge_reset()`，清掉新卡片正在接管的相机、点云和 readiness。
- 新增 PlatformView session ownership：Dart 相机 FFI 写入 `viewId`，原生 ABI 的 `av_camera` 传递 owner，Unity 仅接受
  当前 `activateSession` 认领的 owner 的相机意图。
- Android 原生转发层现在拒绝非 active PlatformView 的地图、姿态、相机和图层消息；旧全屏页面不再影响新卡片。
- 每个 PlatformView dispose 不再重置共享 FFI bridge；`bridgeReady` 也不再清除已被新页面暂存的相机/点云状态。
- 新增回归契约测试，覆盖 owner 贯穿 Dart/C/Unity 与“单个 PlatformView dispose 不得 reset 共享 bridge”。
- 已以 Unity 2022.3.62f1 重新导出 Android Development `unityLibrary`，并构建新的 Unity Debug APK。

### 已验证

- 定向回归测试：`flutter test test/features/live_observation/visualization/unity_camera_restore_contract_test.dart` 通过（3 项）。
- `clang -std=c11 -fsyntax-only` shared bridge、`flutter analyze`、`flutter test --concurrency=1 -r compact`（149 项）均通过。
- Android Unity Debug APK 构建成功，内含 `libaletheia_viz_bridge.so`、`libil2cpp.so`、`libunity.so`。
- Android ARM64 模拟器自动生命周期测试通过：33 秒。
- 已连接 Android 真机 `PERM10` 自动生命周期测试通过：37 秒；日志持续显示 3000 点云和约 30 FPS，并经过多次全屏往返。

### 当前涉及文件

- `mobile/packages/aletheia_visualization/lib/src/{visualization_controller,camera_bridge}.dart`
- `mobile/packages/aletheia_visualization/shared/aletheia_viz_bridge.h`
- `mobile/packages/aletheia_visualization/android/src/**/UnitySurfaceProviderImpl.kt`
- `mobile/packages/aletheia_visualization/android/src/main/**/VisualizationSurfaceView.kt`
- `unity/aletheia_viz/Assets/Scripts/{NativeCloudBridge,VizBridge,VizTypes}.cs`
- `mobile/test/features/live_observation/visualization/unity_camera_restore_contract_test.dart`

### 后续真机手工复验

用刚构建的 Unity APK 连续执行至少三轮“进入地图 → 放大/拖动 → 全屏 → 返回卡片”，确认地图比例、格栅、虚拟墙、点云与车辆保持同一坐标变换。

## 2026-09-01：Unity 地图回退黑屏、车辆标记与随图格栅/比例尺修复

### 本轮完成

- 新增统一的“跟随小车”地图意图：Unity 与永久 `CustomPaint` 回退均默认以最新有效位姿为中心；单指拖动或双指
  地图操作立即暂停跟随，工具栏的定位按钮可从当前画面以 240 ms、无过冲的动画平滑回到小车。该状态由 Flutter
  HMI 持有，Unity 仍只接收最终相机 transform，不接管手势或机器人协议。
- 跟随保持地图北向上，不随小车航向旋转；这保留了占据图、虚拟墙和现场空间的稳定参照，避免 HMI 在行驶时旋转
  整张地图。小车图标自身仍显示实时朝向。
- 修复 Unity 全屏回退后的黑色地图：全屏 route 关闭后，紧凑地图工作区会重建自己的 platform view，并回放当前
  地图与最新遥测。这样 Unity 的单个 Metal drawable 不会仍挂在已经销毁的全屏容器中；不引入第二个 Unity runtime。
- Unity 格栅改为 **MapCanvas 本地坐标**：`WorldGrid.shader` 不再以会随画布平移而改变相位的 world 坐标计算线条；
  地图栅格、占据图、虚拟墙、点云和车辆现在跟随同一 map-space transform 拖动。
- Unity 地图左下增加与 Flutter 版本同语义的固定 HUD 比例尺（例如 `5 m / 格`）。双指缩放时，它与 Unity 的
  格栅步长共用同一相机 scale，宽度连续更新、跨步长阈值时标签同步变化；单指平移不会触发 Flutter rebuild。
- 车辆标记从单个黑色 Quad 改为真实车型尺寸的分层 HMI 符号：深色倒角轮廓、暖色车身甲板与前向 chevron；
  新增并序列化 `RobotMarkerUnlit` shader 和三个材质，避免 iOS IL2CPP stripping 后退回黑块/缺标记。
- Unity 场景已由 `VizSceneBootstrap.Rebuild` 重建；iOS export 与 arm64 `UnityFramework` Release 编译都确认包含
  `WorldGrid` 和 `RobotMarkerUnlit` 两个 shader。

### 已验证

- `dart format`（本轮两个 Dart 文件）、`flutter analyze`：通过。
- `flutter test --concurrency=1 -r compact`：全量通过；地图横屏手势/全屏 Widget 测试单独通过（3 项）。
- Unity 2022.3.62f1：完整 3480×10017 地图与 262,144 点云上限 fixture 均通过；iOS export 与
  `xcodebuild -target UnityFramework -configuration Release -sdk iphoneos` 均成功。
- 包含小车跟随功能的最新归档：`mobile/build/artifacts/aletheia-unity-release-development-20260901-1604.ipa`；
  `unzip -t`、SHA-256、Payload 的 UnityFramework/Data/global-metadata 与
  `codesign --verify --deep --strict` 均通过。签名为 Team `7W824PZNYM` 的 Apple Development 签名。
- Android Unity export 与 Release APK 构建也通过；产物为
  `mobile/build/artifacts/aletheia-unity-internal-debug-signed-20260901-1633.apk`，包含小车跟随功能与 Android
  Unity 启动修复；SHA-256、APK 结构、Android v2 签名、`libunity.so`、`libil2cpp.so` 和 Unity Data 均已校验。
- 修复 Android Unity 进入观测即退出的启动契约：Unity 导出要求 native library 从应用 native-library 目录加载，
  但 Flutter/AGP 的默认 APK 合并为 `android:extractNativeLibs=false`。在 Unity opt-in 构建中显式启用
  `packaging.jniLibs.useLegacyPackaging = true`；新 APK 的最终 Manifest 已验证为
  `android:extractNativeLibs=true`，并包含 `libmain.so`、`libunity.so`、`libil2cpp.so`。

### 真机回归重点

1. 进入地图 → 双指缩放，确认左下角“m / 格”与格栅密度同步且动画无跳变。
2. 连续单指拖动画布，确认格栅与占据图、虚拟墙、点云、车辆没有相对滑移。
3. 全屏进入/退出至少三次；回退后应立即重建并显示地图，不应出现黑色 Unity surface。

真机自动化仍依赖 macOS 让执行 `flutter test integration_test/unity_map_lifecycle_test.dart` 的宿主获得
Xcode 自动化/VM Service 授权；本轮该集成测试仍未返回可采信断言，已停止挂起进程。交付前已重新执行
`flutter analyze` 与完整 `flutter test --concurrency=1 -r compact`（145 项通过）；新 IPA 已可直接手工安装验证。

### 本轮文件

- `mobile/lib/features/live_observation/presentation/live_observation_screen.dart`
- `mobile/lib/features/live_observation/visualization/unity_visualization_engine.dart`
- `unity/aletheia_viz/Assets/Scripts/VizBridge.cs`
- `unity/aletheia_viz/Assets/Scripts/RobotMarker.cs`
- `unity/aletheia_viz/Assets/Shaders/WorldGrid.shader`
- `unity/aletheia_viz/Assets/Shaders/RobotMarkerUnlit.shader`
- `unity/aletheia_viz/Assets/Editor/VizSceneBootstrap.cs`

### 使用的 Skill

- `apple-design`：以“地图为单一直接操作坐标系、比例尺作为稳定参照、全屏可连续返回”的原则决定本轮交互和
  视觉层级；没有加入会干扰 HMI 操作的装饰性动效。

## 2026-09-01：Android 全屏、连接地址恢复与三路视频工作区修复

### 本轮完成

- 地图全屏改为经 `rootNavigator` 打开，避开 Shell 的嵌套 Navigator；全屏页进入时使用
  `SystemUiMode.immersiveSticky`，退出时恢复 `edgeToEdge`。Android 现在不会再保留一级导航栏或上层 App
  壳，地图获得完整的横屏工作区。
- 连接地址不再只存在首页的 `TextEditingController` 中。`RobotConnectionState.addressDraft` 保存当前输入和
  已验证 endpoint 的显示地址；首页重新创建时会从状态同步，因此切换一级节目后仍显示
  `192.168.1.20:8087`，但不会把未验证草稿写入持久化 endpoint。
- 视频工作区明确区分两类状态：左侧六个开关仅请求机器人启停对应视频源；本机最多同时解码并显示三路。
  新增“配置显示画面”入口，提供主画面、辅助画面 1、辅助画面 2 三个明确槽位，可从六路源中任选三路；
  选主画面时会保持三路唯一，原主画面自动换入空出的辅助槽位。横屏右侧不再按接口返回顺序固定截取两路。
- 该配置面板在短横屏按可用高度滚动，避免遮挡或 `RenderFlex overflow`。

### 已验证

```bash
cd /Users/bob/Desktop/code/ry-aletheia/mobile
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \\
  flutter test -j 1 \\
  test/features/live_observation/landscape_observation_layout_test.dart \\
  test/features/live_observation/application/video_display_layout_controller_test.dart \\
  test/features/robot_connection/presentation/robot_connection_screen_test.dart
```

定向测试共 5 项通过；随后 `flutter analyze`、全量 `flutter test --concurrency=1 -r compact`（144 项）和
`flutter build apk --debug` 均通过，APK 位于 `mobile/build/app/outputs/flutter-apk/app-debug.apk`。当前
`flutter devices` 只发现 iOS 真机/模拟器，没有可部署的 Android 设备；Android 真机接入后优先验证：地图全屏、
返回首页地址恢复、六路开关下任意三路槽位选择与横竖屏切换。

另外，Unity Android Debug 首次复核暴露 stock `unityLibrary` 缺失 Flutter 插件所需 `profile` Gradle 变体；已由
`UaaLBuild.NormalizeAndroidGradleForFlutter` 自动添加 `profile { initWith debug }`，Unity Debug APK 也已通过
`ALETHEIA_UNITY_ENABLED=1 ... --dart-define=AV_ENGINE=unity --dart-define=AV_UNITY_RUNTIME=true` 构建。重新导出 Unity
时会自动重做该兼容处理。

### iOS USB Unity 全流程重跑（2026-09-01）

- 真机 `00008110-001154A90AC3401E` 已识别；带 Unity runtime 的 iPhoneOS Debug build 自动签名并在 Xcode
  构建阶段通过。`devicectl` 已确认 `Aletheia Mobile`（`com.ryaletheia.aletheiaMobile`）安装成功，随后启动的
  `Runner` 进程处于 `running-active`；没有设备侧崩溃报告。
- 自动化用例 `integration_test/unity_map_lifecycle_test.dart` 覆盖固定地图/虚拟墙/连续点云、拖动画布、进入全屏、
  全屏后二次拖动与退出后的地图保留。该用例此次**未获得最终断言结果**：Flutter 无法发现设备 Dart VM Service，
  即使 App 已安装、前台运行且 USB 可用。手动 `flutter attach` 也停在 `Waiting for a connection from Flutter`。
- 该现象属于 macOS 主机的调试服务/Apple Events 授权通道，不是 Unity 安装或 App 进程失败。当前运行命令来自
  Codex/VS Code 的子进程，和用户在“终端 → Xcode”中已授予的权限不是同一 TCC 身份；需在“系统设置 → 隐私与
  安全性 → 自动化”允许 **Visual Studio Code（以及 Codex，如出现）控制 Xcode**，再从已授权宿主重新执行下方命令。

```bash
cd /Users/bob/Desktop/code/ry-aletheia/mobile
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \\
  ALETHEIA_UNITY_ENABLED=1 flutter test integration_test/unity_map_lifecycle_test.dart \\
  -d 00008110-001154A90AC3401E \\
  --dart-define=AV_ENGINE=unity \\
  --dart-define=AV_UNITY_RUNTIME=true
```

### Unity iOS Development IPA（2026-09-01 14:42）

- 已使用 `tool/build_mobile_packages.sh --engine unity --platform ios --ios-export development` 生成真机可安装包：
  `mobile/build/artifacts/aletheia-unity-release-development-20260901-1440.ipa`。
- `unzip -t` 和附带 SHA-256 校验均通过；Payload 同时包含 `UnityFramework.framework`、插件框架中的 Unity `Data` 和
  `global-metadata.dat`。本包采用当前 Xcode 开发团队的 Development profile，只能安装到已登记/受信任的开发设备。

### 本轮文件

- `mobile/lib/features/live_observation/presentation/live_observation_screen.dart`
- `mobile/lib/features/live_observation/application/video_display_layout_controller.dart`
- `mobile/lib/core/connection/robot_connection_state.dart`
- `mobile/lib/core/connection/robot_connection_controller.dart`
- `mobile/lib/features/robot_connection/presentation/robot_connection_screen.dart`
- `mobile/test/features/live_observation/landscape_observation_layout_test.dart`
- `mobile/test/features/live_observation/application/video_display_layout_controller_test.dart`
- `mobile/test/features/robot_connection/presentation/robot_connection_screen_test.dart`
- `unity/aletheia_viz/Assets/Editor/UaaLBuild.cs`

### 使用的 Skill

- `apple-design`：全屏上下文切换与三路可见工作槽位遵循“保持用户掌控、直接且不遮挡”的交互原则；未引入多余动效。

## 2026-09-01：Unity 地图生命周期最终自检（可继续真机自动化回归）

### 本轮结论

- 已确认 macOS 上配置的 `HTTP_PROXY` / `HTTPS_PROXY` 会截获 Flutter 到本机 Dart VM Service 的
  WebSocket；它会表现为 `Connection closed before full header was received`，但不是 App、地图或 Unity
  的连接失败。所有 Flutter 调试、测试和构建命令必须移除六个代理环境变量，见下方命令。
- Unity 版现在有明确构建契约：只有同时使用
  `--dart-define=AV_ENGINE=unity --dart-define=AV_UNITY_RUNTIME=true` 的、且原生 Unity runtime 已编入的
  iOS/Android 包才会创建 Unity surface。仅设置 `AV_ENGINE=unity`（例如 Simulator/Flutter-only host）会安全
  回退到原有 Flutter `CustomPaint`，不会再出现没有 UnityFramework 时的黑色/空白 platform view。
- 修复了 fullscreen / 横竖屏平台视图重建时的地图重放竞态：同一 `mapId` 已被 ready 的 Unity 场景接受后，
  只会继续接收正常实时 `loadMap`，不会因为旧 Flutter platform view 短暂 not-ready 而在两秒后把同一份
  3480×10017 原图重新解码、抢占渲染线程。Unity controller/Metal 生命周期仍保持，不会为此清空 root controller。

### 已实际验证

- iPhone Simulator：Debug Gallery `observe_stress` 的 Flutter 回退地图已手工验证完整地图、格栅、虚拟墙、
  点云、拖动画布、进入全屏、拖动、退出全屏后地图仍存在；没有黑屏或残影。新增
  `unity_map_lifecycle_test.dart` 已在同一 Simulator 自动通过该闭环（13 秒）。测试刻意以
  `DebugGalleryPreview` 注入真实生产页面与确定性数据，避免 XCTest runner 的 default route 覆盖 Debug Gallery
  路由而产生假阴性。
- 真机日志此前已验证 Unity 正确读取 `Data`、加载真实 3480×10017 地图、453 条虚拟墙和 3000 个点云，并稳定
  输出约 30 FPS。`UnitySurfaceProvider.swift` 的本轮修改已通过 Unity-enabled iPhoneOS Xcode build。
- 本轮命令均通过：`dart format`、`clang -std=c11 -fsyntax-only`（shared bridge）、`flutter analyze`、
  全量 `flutter test --concurrency=1 -r compact`（142 passed）、`git diff --check`，以及：

```bash
cd /Users/bob/Desktop/code/ry-aletheia/mobile
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
  ALETHEIA_UNITY_ENABLED=1 flutter build ios --debug --no-codesign \
  --dart-define=AV_ENGINE=unity --dart-define=AV_UNITY_RUNTIME=true
```

### 尚待的唯一设备门槛

新增 `mobile/integration_test/unity_map_lifecycle_test.dart` 会在真机自动执行“等待真实地图 → 拖画布 → 全屏
→ 再拖画布 → 退出全屏 → 地图仍在”的闭环。Simulator 已通过。最近一次 USB 真机已完成自动签名、构建和
安装启动，但 Flutter 在 120 秒内未发现 Dart VM Service，因此未进入断言；终端提示需要在 macOS“隐私与安全性
→ 自动化”允许终端控制 Xcode。此前也曾出现 `Developer App Certificate is not trusted`，所以设备侧仍应在
“设置 → 通用 → VPN 与设备管理”信任当前 Xcode 开发者证书。两项授权完成后执行：

```bash
cd /Users/bob/Desktop/code/ry-aletheia/mobile
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
  ALETHEIA_UNITY_ENABLED=1 flutter test integration_test/unity_map_lifecycle_test.dart \
  -d 00008110-001154A90AC3401E \
  --dart-define=AV_ENGINE=unity \
  --dart-define=AV_UNITY_RUNTIME=true \
  --dart-define=AV_DEBUG_ROUTE='/__debug/ui-gallery?screen=observe_stress'
```

### 本轮文件

- `mobile/lib/features/live_observation/presentation/live_observation_screen.dart`
- `mobile/integration_test/unity_map_lifecycle_test.dart`
- `mobile/packages/aletheia_visualization/ios/Classes/UnitySurfaceProvider.swift`
- `mobile/tool/build_mobile_packages.sh`
- `unity/README.md`

### 使用的 Skill

- `write-swift`：用于确保 UIKit/Unity Metal surface 重绑仍遵守 root controller 生命周期与主线程约束。
- `computer-use`：用于在 iPhone Simulator 逐项实测地图画布拖动及全屏进入/退出闭环。

## 2026-09-01：Unity 地图手势与全屏黑屏修复（USB 真机 Debug 已重启）

### 用户反馈与确认的根因

- Unity 地图拖动“不动/非常卡”并非地图或点云传输性能问题。原实现把 Flutter `Listener` 包在
  `UiKitView` 外层：在 iOS 上原生 platform view 可以先赢得 hit test，使连续 pointer move 不能稳定交给
  Flutter；即使事件进入 Flutter，每一条 camera 更新仍经 `MethodChannel → Swift → UnitySendMessage → JSON`，
  会在 120 Hz 触控时排队到 UIKit/Unity 主线程。
- 全屏退出后的黑画面来自 `UnitySurfaceProvider` 在重绑 Metal surface 后清空了 Unity bootstrap window 的
  `rootViewController`。首屏有时正常，但下一次 bounds/recreate rendering surface 失去 Unity controller 所有的
  Metal 生命周期。

### 本轮实现

- `unity_visualization_engine.dart` 现在将透明的 `RawGestureDetector + Listener` **叠放在**
  `AletheiaVisualizationView` 之上。地图触控物理上先进入 Flutter；Eager recognizer 保证纵向拖动也是画布
  pan，不会被页面 `ListView` 抢走。Unity root view 继续保持非交互，仅渲染。
- 新增 `av_camera_stage/acquire` 的 8-float latest-wins ABI，与现有点云 bridge 一样共享同一进程内 native
  buffer。Flutter 在每个触控采样只写入最新相机标量，Unity 的 `LateUpdate` 每帧最多读取一份并更新同一个
  `MapCanvas`。旧 framework 或 Flutter-only host 自动保留原 MethodChannel 低频后备路径。
- `UnitySurfaceProvider` 仍会对全屏/尺寸变化重绑 Flutter-owned Metal surface，但不再清空 Unity 的
  `rootViewController`，只隐藏失去展示职责的 bootstrap window，避免返回原窗口后的黑屏。

### 已完成验证与部署

- `dart format`、`clang -std=c11 -fsyntax-only`（shared bridge）、`flutter analyze`、定向
  `visualization_engine_test.dart`（4 passed）以及 `git diff --check` 均通过。
- Unity 2022.3.62f1 iOS export 与 arm64 Release `UnityFramework` build 成功；framework 和 `Data` 已同步到
  `mobile/packages/aletheia_visualization/ios/UnityLibrary/`。
- iPhoneOS Debug host build 已核对 plugin framework 导出 `_av_camera_stage` 与 `_av_camera_acquire`，并已通过 USB
  真机启动：`--dart-define=AV_ENGINE=unity --route '/__debug/ui-gallery?screen=observe_stress'`。
- 当前真机人工回归顺序：单指连续拖动、双指缩放、全屏进入/退出至少三次、地图/相机来回切换。应检查手指与
  canvas 无明显延迟、页面不滚动、退出全屏后不黑屏；若仍异常，先保留屏幕录像和该时刻 Unity 日志，禁止以降采
  原图作为规避手段。

### 本轮涉及文件

- `mobile/lib/features/live_observation/visualization/unity_visualization_engine.dart`
- `mobile/packages/aletheia_visualization/lib/src/{camera_bridge,visualization_controller}.dart`
- `mobile/packages/aletheia_visualization/shared/aletheia_viz_bridge.{h,c}`
- `unity/aletheia_viz/Assets/Scripts/{NativeCloudBridge,VizBridge}.cs`
- `mobile/packages/aletheia_visualization/ios/Classes/UnitySurfaceProvider.swift`

### Skill

- `write-swift`：用于复核 Unity-as-a-Library 在 UIKit/Metal surface 重绑时必须保留 controller 的生命周期边界。

## 2026-09-01：双渲染器正式测试包（已完成）

旧 `mobile/build/artifacts/` 的历史 APK、IPA 与校验文件已按用户要求清空，随后从当前源码重新生成两套
release-mode 测试包：

| 渲染器 | Android APK | iOS development IPA |
| --- | --- | --- |
| Flutter `CustomPaint` | `aletheia-flutter-internal-debug-signed-20260901-1043.apk` | `aletheia-flutter-release-development-20260901-1043.ipa` |
| Unity | `aletheia-unity-internal-debug-signed-20260901-1047.apk` | `aletheia-unity-release-development-20260901-1047.ipa` |

- 所有产物和对应 `.sha256` 文件均位于 `mobile/build/artifacts/`；SHA-256 已逐个复算通过。
- 两个 APK 均通过 `apksigner` v2 签名验证。未提供 Android 正式 keystore，故 Android 文件名明确标注
  `internal-debug-signed`，只能作为内部测试包而非上架/正式更新包。
- 两个 IPA 均通过 `codesign --verify --deep --strict`。Flutter IPA 不含 Unity runtime；Unity IPA 已验证包含
  `UnityFramework.framework` 和 `aletheia_visualization.framework/Data`。
- `tool/build_mobile_packages.sh` 修复了 macOS Bash 3.2 在 Flutter 版空 `dart_defines` 数组配合 `set -u` 时
  报 `unbound variable` 的问题。以后可直接执行 `--engine flutter|unity --platform all` 重复生成两版。

## 2026-09-01：Unity 画布直接操控（USB 真机回归中）

### 本轮目标与实现

- Unity 仍只负责渲染；手势由 Flutter 完整拥有，并同步给同一个 `MapCanvas` 的 camera intent。
  `unity_visualization_engine.dart` 已由 `GestureDetector.onScaleUpdate` 改为与原 Flutter 地图一致的
  `RawGestureDetector + EagerGestureRecognizer + Listener`：地图优先取得 pointer sequence，纵向拖动不会被
  外层页面滚动抢走。
- 单指平移以首次落点的 camera 状态为基准，按地图米制 1:1 移动整个 canvas；两指缩放保存两指中心下方的
  世界坐标，因此手指移动和缩放不会跳动或“橡皮筋”。触控硬件的高频事件会合并为每 Flutter frame 至多一个
  camera message，避免 Dart → Swift → Unity 连续跨端调用造成触感落后。
- 首个实时位姿在 Flutter camera state 中先转换为相对于地图中心的 offset，再传 Unity。此举修复 Unity
  先以小车聚焦、Flutter 却仍持有 `(0, 0)` 的不一致，避免用户第一次拖动把画面跳回地图中心。
- Unity 2D camera 的最大缩放与 Flutter 一致：`1×…48×`，不再在 20× 提前停止。

### 本轮自检与部署状态

- `dart format`、`flutter analyze`、定向 `visualization_engine_test.dart` 均通过；`git diff --check` 通过。
- 全量 `flutter test` 当前被本机 Flutter tester 的 `127.0.0.1` HTTP server 意外断连阻断（所有 test loading
  同时报 `Connection closed before full header`，没有测试断言失败）；已用无代理环境复测定向测试通过，待
  tester 环境恢复后再执行全量回归。
- Unity 2022.3.62f1 iOS 导出、Release arm64 `UnityFramework` 编译均通过，新的 framework 和 `Data` 已同步到
  `mobile/packages/aletheia_visualization/ios/Frameworks/`。下一步直接通过 USB `flutter run` 覆盖部署并验收。

## 2026-09-01：Unity 白色画布、格栅、虚拟墙与随车初始视角（待真机回归）

### 用户可见目标

- 地图不再只是白色栅格图本身；它落在比原图略大的**白色米制画布**上。拖到地图边缘时，仍能看到
  连续、留白的工作区，而不会露出 Unity 黑色清屏背景。
- 格栅必须如 Flutter/mobile Web：覆盖地图与留白画布、具有深浅两级线条、随缩放选择合适米制间距，不能被
  occupancy PNG 遮住。
- 虚拟墙在 Unity 中是同一 `MapCanvas` 的静态层，使用 Flutter 已解析的世界米制坐标；不新建任何数据接口。
- 初始视图以第一条实时位姿（小车）为中心，采用与 `frontend/src/liveObservation.js` 相同的 16 m 工作视野；
  用户随后 pan/zoom 不会被后续位姿强行拉回。
- 进入全屏、退出全屏后，Unity 对 Flutter 平台视图最终 bounds 再绑定 Metal drawable，避免显示旧尺寸的
  空白/丢失地图画面。

### 本轮实现

- `VizBridge` 新增 `VirtualWallRenderer`；Flutter `VizMapDescriptor` 的 `walls` 字段采用
  `[{"p":[x0,y0,x1,y1,...]}]` 显式对象数组，规避 iOS IL2CPP 下 jagged primitive JSON 的兼容风险。
  新墙体 mesh 只在切图时构建，线宽 `0.075 m`，不进入点云/位姿热路径。
- `WorldGrid` 从地图底层移至 occupancy 上方、virtual wall 下方；透明深灰 minor/major 格栅覆盖整个
  `MapCanvas`，其宽高在原图四周增加至少 8 m 的白色工作区余量。相机清屏改为 `#F6F9F8`。
- `VizCamera` 默认工作视图为 16 m，并在首次 `setPose` 仅聚焦一次；Flutter 同步发送等效 scale（允许
  `1×…48×` 缩放），先 `loadMap` 再发送 camera/pose，杜绝异步 staging 让位姿早于地图而被重置。
- `UnitySurfaceProvider` 的 surface rebind 条件扩展为最终 bounds 改变，且布局已在下一 MainActor run-loop
  合并，不会为每帧 layout 重建。解决全屏 push/pop 容器相同但 drawable 尺寸已变化的情况。
- `UaaLBuild.EnsureScene()` 每次导出均重建权威 scene，直接序列化新着色器引用，防止 iOS High stripping
  遗漏 `VirtualWallUnlit`。导出的 Unity `Data` 与 framework 已同步至
  `mobile/packages/aletheia_visualization/ios/Frameworks/`。

### 已完成自检

- Unity headless：`ValidateVirtualWallGeometry` 通过（2 个世界坐标线段 → 8 vertices / 12 indices）；
  scene 已包含 `VirtualWalls` 和 shader 直接依赖。
- Flutter wire-contract test：通过，锁定 `walls` 字段及 path/base64 两条 map transport 均携带墙体。
- Flutter 全量 `flutter test`：142 passed；`flutter analyze`：无问题；`git diff --check`：通过。
- Unity 2022.3.62f1 iOS export 与 arm64 `UnityFramework` Release build：通过；Flutter
  `flutter build ios --debug --no-codesign --dart-define=AV_ENGINE=unity`：通过。

### 真机验收顺序

1. 使用新 framework 的 Unity Debug 构建进入 `observe_stress`；应首先看到小车附近约 16 m 的白色画布、格栅、
   原始栅格地图、红色虚拟墙、点云和机器人。
2. 单指拖动、双指缩放；格栅、地图、虚拟墙、点云、机器人必须始终同速同向移动，页面不能滚动。
3. 进入全屏再退出、地图/相机切换、横竖屏切换各至少三次；地图不得消失、不得重置成黑底窄条。
4. 若异常，保留截图与同一时刻 `[UnityVizNative]` / `[UnityViz]` 日志；不要降低 `3480×10017` 原图分辨率。

## 2026-09-01：Unity 地图世界画布与真机横条修复（当前真机 Debug 已部署）

### 当前目标

让 Unity 只作为观测地图工作区内的渲染器：Flutter 继续拥有页面、导航、状态、数据接入与
pan/pinch；Unity 只在同一个地图世界画布中绘制底图、米制格栅、点云和机器人。不得让 Unity
创建或接管第二个 HMI 页面、机器人连接或视频链路。

### 已确认根因与修复

- 用户真机截图 `IMG_5067.heic` 中的“黑色格栅 + 中间一条白色地图”并不是地图 PNG 未下载。
  原始地图是完整的 `3480 × 10017` PNG，Unity 已能以原分辨率解码和绑定。根因是
  `PrimitiveType.Quad` 的顶点在其**局部 XY 平面**；场景把 Quad 绕 X 轴旋转到 XZ 地图平面后，
  `OccupancyMap.ApplyLayout` 却把地图高度缩放到了没有顶点的局部 Z 轴。结果 500.85m 的地图高度
  只有约 1m，刚好表现为截图中的水平白色窄带。
- `OccupancyMap` 现以 `localScale = (worldWidth, worldHeight, 1)` 布局；旋转后正确覆盖 XZ
  平面。`VizFixtureValidation` 新增同一几何断言，防止再次把高地图压扁。
- 新增 `MapCanvas`（对应 Web `world-stage`）：occupancy、grid、point cloud 与 robot 都是其子层。
  Flutter 手势将屏幕增量换算为地图米制偏移；Unity `VizCamera` 只平移 `MapCanvas`，不单独拖动
  图片。点云 procedural draw 显式接收同一 canvas offset。
- `UnitySurfaceProvider` 仍保留设备专用的 Flutter UIWindow / Unity Metal surface rebind，避免
  UaaL bootstrap 的全屏 drawable 被 Flutter 平台视图裁成片段；attach 只在容器或容器归属变化时
  重建，不在每次 layout / rotation 重建，以避免主线程卡顿。

### 本次实际验证

- Unity 2022.3.62f1 iOS export：通过。
- `UnityFramework` Release (arm64 iPhoneOS)：通过；新 framework 与 `Data` 已复制到
  `mobile/packages/aletheia_visualization/ios/UnityLibrary/`。
- 完整原图 fixture：通过，确认 `3480×10017`、133.0 MiB RGBA、`maxTextureSize=16384`，且世界画布
  geometry 断言通过。
- iPhoneOS host Debug build：通过。Flutter 全量 `flutter test --concurrency=1 -r compact` 和
  `flutter analyze`：通过；`git diff --check`：通过。
- 当前无线真机 Debug 会话运行于
  `--dart-define=AV_ENGINE=unity --route '/__debug/ui-gallery?screen=observe_stress'`，其 Flutter
  `UiKitView` 已确认尺寸为 `326×429` logical pixels；这个场景使用生产 `LiveObservationScreen`、原图、
  60Hz pose 与 8Hz / 3000 点 latest-wins cloud，不依赖机器人。

### 当前真机验收顺序

1. 在手机中确认地图不再是横条，而是完整纵向原图；先不接机器人也可在 `observe_stress` 完成。
2. 单指 pan 应移动整个地图世界，双指缩放不移动页面；随后切换地图/相机、横竖屏和前后台。
3. 仅当上述稳定后，再连接真实机器人验证实际 map/pose/cloud。若仍有卡顿，保存该时刻的
   `[UnityVizNative]` / `[UnityViz]` device log 与截图；不要降低地图分辨率或把业务网络移进 Unity。

### 本轮涉及文件

- `unity/aletheia_viz/Assets/Scripts/{VizBridge,VizCamera,OccupancyMap,PointCloudRenderer,RobotMarker}.cs`
- `unity/aletheia_viz/Assets/Shaders/PointCloudUnlit.shader`
- `unity/aletheia_viz/Assets/Editor/{VizSceneBootstrap,VizFixtureValidation}.cs`
- `mobile/lib/features/live_observation/visualization/unity_visualization_engine.dart`
- `mobile/packages/aletheia_visualization/ios/Classes/{UnitySurfaceProvider,AletheiaUnitySurfaceBridge}.m`

### Skills

- `write-swift`：用于复核 iOS Unity/Swift 生命周期与 UIKit 表面附着边界。

## 2026-08-31：快速工作区切换残影修复（已完成模拟回归）

- 一级 HMI 入口原先使用 140ms 透明叠加。快速连续导航时，旧 Route 会在新 Route 下方继续合成，地图、视频和原生平台视图容易表现为短暂残影。`AletheiaMotion.rootPage` 现使用 `NoTransitionPage` 原子替换；工具二级页面仍保留短暂的语义过渡。
- 观测页地图/相机原先由 `AnimatedSwitcher` 作 180ms fade-through；该组件会在过渡期保留旧 child。对 Unity `UiKitView` / Android platform view 或 WebRTC renderer，这会同时保留两张原生 surface，快速切换时可能显示旧帧。观测工作区现直接以 keyed child 原子替换，不能叠留旧 surface。
- 验证：`dart format`、定向 widget test（4 passed）、`flutter analyze`，以及 `flutter test --concurrency=1 -r compact`（142 passed）均通过。已重新生成并检查 iOS Unity development IPA `aletheia-unity-release-development-20260831-2107.ipa`（SHA-256 `5becb777c654e82a3d8709d76b7dc324da48339f66d21ab5e63acc21c47d5ba1`）和 Android Unity internal APK `aletheia-unity-internal-debug-signed-20260831-2109.apk`（SHA-256 `f58833e62c15741eba710aa71f3e0e93facb841cd70ff988128bc55bc0fe3906`）；两者 archive 内容已检查，IPA 的签名校验通过。真机需人工快速交替点击首页/观测/工具/设置，以及地图/相机，确认不再出现残影。

### 涉及文件

- `mobile/lib/app/motion/aletheia_motion.dart`
- `mobile/lib/features/live_observation/presentation/live_observation_screen.dart`
- `mobile/test/app/aletheia_motion_test.dart`
- `docs/UI_SPEC.md`

## 2026-08-31：Unity 观测页全尺寸地图与卡死复盘（当前待真机回归）

### 已复现并确认的事实

- 真实样本地图保存在 `mobile/assets/debug_ui/sample_map.png`，是用户提供 PGM 的**无降采、无损**
  PNG 转换：`3480 × 10017`、`0.05 m/px`、origin `[-111.57, -248.79]`；其虚拟墙 YAML 也已进入
  Debug Gallery fixture。PNG 压缩约 0.8 MB，Unity GPU RGBA 解码约 133.0 MiB，不能把“文件很小”
  误判为无加载压力。
- Unity Editor 在真实 Metal 图形设备（Apple M2）完成该地图的 decode + `_BaseMap` material bind：
  `205 ms`、`maxTextureSize=16384`。`-nographics` 的 Null device 只报 `4096` 并会回退 dummy texture，
  不能用作地图渲染结论。
- 新增 `observe_stress` Debug Gallery 场景，直接复用 production `LiveObservationScreen` 与原始地图，
  生成 latest-wins 的 60 Hz 位姿和 8 Hz / 3,000 XY 点云。iPhone 17 Simulator 已实际运行并连续截图确认
  地图、虚拟墙、位姿持续变化且未失去响应；横屏布局与地图 pan/pinch 已由 production widget tests 覆盖。
- Simulator 曾因前一次 Unity device Pod 配置残留，错误地链接 iPhoneOS-only `UnityFramework` 而报
  `UnityAppController/UnityFramework` undefined symbols。普通 `pod install` 已恢复 stub 插件；
  `tool/build_mobile_packages.sh` 现主动清除继承的 `ALETHEIA_UNITY_ENABLED`，只在 Unity 打包分支显式开启。

### 本轮修复（尚待物理 iPhone Unity 回归）

1. `UnitySurfaceProvider` 不再无条件在两秒后重发 full-resolution `loadMap`。之前首次 map 已被 Unity
   接收时仍会启动第二次解码、停止第一条 coroutine，可能让大型地图反复加载；现在仅在 `VizRoot` 尚未 ready
   的窄竞态中重放。
2. 点云桥原来只限制 float 总数。对 XY 帧这会容许 `393,216` 点进入只分配 `262,144` 点的 Unity
   `GraphicsBuffer`，`SetData` 可越界导致观测页闪退。Dart FFI、C bridge、Unity acquire 和 renderer upload
   现在四层都验证 layout、整点数及 `262,144` 点硬上限；Unity Metal batch 对最大合法帧和超限直接调用通过。
3. 继续保留 Flutter 为默认与 Simulator renderer；Unity 只在物理设备、`ALETHEIA_UNITY_ENABLED=1` 与
   `--dart-define=AV_ENGINE=unity` 同时满足时替换地图画布，不得扩展到机器人通讯、视频或 HMI 逻辑。

### 本轮验证

- `flutter test --concurrency=1 -r compact`：通过，141 项。
- `flutter analyze`：通过，无问题；`clang -std=c11 -fsyntax-only`（shared bridge）通过；`git diff --check`：通过。
- Unity 2022.3.62f1 Metal batch：全尺寸 map/material bind、fixed-cap point-cloud validation 均通过。
- iOS Simulator：普通 Flutter production observation stress page 构建、启动并实际截图通过。Unity iPhoneOS
  framework 不包含 Simulator slice，因此该项只覆盖真实 HMI、完整地图和遥测负载，不能声称覆盖 Unity UaaL。

### 下一步

重新导出 Unity iOS framework 后，建立 Unity development IPA；在物理 iPhone 依次验证：连接真实车后进入
观测、等待原图出现、单指/双指、离开/返回、横竖屏、后台/前台。若仍出现卡死，优先保留该时刻 device crash
report 与 `[UnityViz]` log；不得用 try/catch 或降低原图分辨率掩盖问题。

## 2026-08-31：Unity 地图栅格缺失与触控阻塞修复（当前待真机确认）

### 真实现象与根因

- 真机截图 `IMG_5061.heic` 已确认 Unity surface、米制格栅、点云和位姿均在工作，只有
  occupancy 地图栅格没有出现。因此这不是机器人地图接口、点云 bridge 或 Unity 启动失败。
- `OccupancyMap` 的 Built-in shader 纹理字段是 `_BaseMap`，但运行时使用
  `Material.mainTexture` 赋值。该 Unity convenience API 默认只面向 `_MainTex`；在 iOS
  player 中会静默留下空纹理，导致“只见格栅和点云、不见地图”。现改为
  `SetTexture(Shader.PropertyToID("_BaseMap"), texture)`，保持原始 PNG、无需降采。
- `AletheiaVisualizationView` 先前以 `EagerGestureRecognizer` 将所有 map touch 交给
  platform view；而 Unity 本就不处理触控、Flutter 才是 pan/pinch 的唯一所有者。这会使地图页
  看似卡死。现使用显式空 recognizer 集合，且 iOS Unity root view 设置
  `isUserInteractionEnabled = false`，手势只进入 Flutter 再转换成 camera message。

### 最新产物与验证

- 新 IPA：`mobile/build/artifacts/aletheia-unity-release-development-20260831-1847.ipa`。
  SHA-256 在同名 `.sha256` 文件中；已通过 archive 完整性与
  `codesign --verify --deep --strict`，确认同时包含 `UnityFramework.framework` 和 plugin 的
  Unity `Data`。
- Unity 2022.3.62f1 iOS export、`UnityFramework` Release build 通过，导出日志无 shader
  compile error；Flutter `flutter analyze` 和 renderer wire-contract test 通过。
- 必须用此 IPA 在物理机确认：进入地图后底图出现；单指拖动/双指缩放可用；切回相机、离开再进
  地图时 Flutter HMI 仍响应。Unity 仍仅负责地图/点云绘制，不触碰网络、机器人协议、视频或业务。

## 2026-08-31：iOS Unity 观测页 Release 闪退修复（最新）

### 根因与修复

- 物理机 crash report 已定位为 `EXC_BAD_ACCESS / CODESIGNING Invalid Page`：
  `UnitySurfaceProvider.isReady()` 在调用 `av_renderer_is_ready_value()` 时跳到地址 `0x0`。
  原因不是地图数据或视频协议，而是 bridge 被编入 Runner 可执行文件；Release IPA 的动态
  导出表不向 sibling CocoaPods framework 提供这些符号，Swift 的 lazy binding 因此为空。
- bridge 现只编入已加载的
  `aletheia_visualization.framework`。Swift 直接链接自身的 C wrapper；Flutter FFI 显式打开
  该 framework；Unity iOS `DllImport` 使用同一 `@rpath/aletheia_visualization.framework/aletheia_visualization`
  image。三者共享**同一份** latest-wins 点云/metrics buffer，Runner 不再导出或保活 bridge。
- `UnitySurfaceProvider` 在 Unity 尚未实际 embed 前不调用 ready/metrics ABI，避免 UIKit 首次
  layout 前的无效探测；这只是生命周期保护，真正的 Release ABI 问题由上面的单 framework
  设计消除。

### 最新已验证产物

- `mobile/build/artifacts/aletheia-unity-release-development-20260831-1802.ipa`
  （SHA-256 `fe3911b04d2fc507986698185e1fedbc39f3fc992f4b24e10112e2e5e17145bb`）。
- 已直接解包检查 IPA：`aletheia_visualization.framework` 导出 `av_cloud_*`、
  `av_metrics_*`、`av_renderer_*`、`av_bridge_reset`；`UnityFramework` 和 Unity `Data`
  已嵌入；`codesign --verify --deep --strict` 通过。
- Unity 2022.3.62f1 iOS export 与 UnityFramework Release 编译通过；Flutter iOS archive/
  export 通过；`flutter analyze` 通过；清除本机代理后的全量
  `flutter test --concurrency=1 -r compact` 通过（141 项）；`git diff --check` 通过。

### 真机下一步

用 `xcrun devicectl` 安装上述 IPA（或在 Xcode Devices 安装），连接机器人后进入“观测”。
此版本必须优先验证：进入观测不退出、Unity 地图出现、返回/再次进入、横竖屏切换；若仍有问题，
保留对应时刻的 system crash log 再分析，不可用 try/catch 掩盖 native 崩溃。

### 2026-08-31 后续：Unity 地图洋红画布

- 真机截图显示 Unity splash 结束后整个地图 platform view 变为洋红色。该颜色是 Unity 的
  error material，不是地图、点云或 WebRTC 数据错误。
- `GraphicsSettings.asset` 确认本项目没有分配 URP asset（Built-in renderer），而
  `OccupancyUnlit`、`WorldGrid`、`PointCloudUnlit` 却只声明了
  `RenderPipeline=UniversalPipeline` 并引用 URP Core.hlsl；iOS player 因此找不到有效
  SubShader，4000m 的 WorldGrid 覆盖整个画面。
- 三个 shader 已改为 pipeline-neutral Built-in CG shader（`UnityCG.cginc`），Unity iOS
  export、UnityFramework Release 编译均通过，无 shader compile error。修复 IPA：
  `mobile/build/artifacts/aletheia-unity-release-development-20260831-1823.ipa`
  （SHA-256 `c8b4fdda849771b1db0d9e804e567769ee428db677715078b4b22c703af5d7c4`）。
- 此版本还通过 IPA framework/bridge export 与签名校验、`flutter analyze`、`git diff --check`。
  必须在物理机进入地图确认洋红色消失且 UI 保持响应后，才能关闭该问题。

## 2026-08-31：Android / iOS 真 Unity renderer 包（最新）

### 当前目标

交付两份可安装的、真正嵌入 Unity runtime 的 Aletheia 包。Unity 继续只负责观测页的
地图、姿态和点云渲染；Flutter 继续负责 HMI、导航、机器人协议、状态、测试和视频。

### 已完成

- Android 采用显式构建门控 `ALETHEIA_UNITY_ENABLED=1`：仅 Unity 版本包含
  `:unityLibrary`；普通 Flutter APK 不会引入 Unity。
- Unity Android 导出脚本已兼容当前 Flutter host 的 NDK `28.2.13676358`、Gradle 9 的
  IL2CPP task API，以及 AGP 9 的 consumer ProGuard 约束；重复导出是幂等的。
- 修正 Android Unity host：`UnityPlayer` 直接作为 `FrameLayout` 返回，并显式提供
  `unity-classes.jar` 的编译期依赖；删除 Unity 导出活动，避免出现第二个 launcher。
- 重新导出 Unity Android library 后，成功生成真正的 arm64 Unity APK：
  `mobile/build/artifacts/aletheia-unity-arm64-release.apk`（116 MB）。其内容包括
  `libunity.so`、`libil2cpp.so`、`libaletheia_viz_bridge.so` 及 Unity `Data`。
- 用同一 `AV_ENGINE=unity` 开关重新归档 iOS，成功生成开发签名 IPA：
  `mobile/build/artifacts/aletheia-unity-development.ipa`（24 MB）。已检查其中包含
  `UnityFramework.framework/UnityFramework` 和 plugin resource bundle 内完整 Unity `Data`。
- 产物校验 SHA-256：Android
  `e91937a168e8a17bc1fd6d2dad3dc2d2fdc2d9f87ca252797610f99047bc13f7`；iOS
  `80551adfa2145b97997c9e7019587fe6b22f6afc8d36a6c302a888db186da29c`。
- 已在生成 Unity 版 IPA 后运行普通 `pod install` 恢复默认 Flutter/iOS Simulator 配置。

### 使用方式

```sh
# Android：仅物理 arm64 设备
cd /Users/bob/Desktop/code/ry-aletheia/mobile
adb install -r build/artifacts/aletheia-unity-arm64-release.apk

# iOS：已注册开发设备；用 Xcode Devices and Simulators 安装 development IPA
open build/artifacts
```

如需重新构建，请严格使用 `unity/README.md` 的 `ALETHEIA_UNITY_ENABLED=1` 与
`--dart-define=AV_ENGINE=unity` 命令。没有这两个开关的包是默认 Flutter renderer，不是
Unity 版。iOS Unity 版本只支持物理 iPhone；Unity 2022 导出的 framework 没有 Simulator slice。

### 验证状态

- Unity Android library 重新导出：通过。
- Android Unity release APK：通过，且 archive 内容已核验。
- iOS Unity development IPA：通过，且 archive 内容已核验。
- `flutter analyze`：通过，无问题。
- `flutter test --concurrency=1 -r compact`：通过，141 项（须取消本机代理，避免测试
  runner 的 localhost 流量被代理）。
- 物理 iPhone Unity 页面生命周期：App runtime 可启动的先前验证仍成立；本轮无法再次
  自动安装，是 macOS “终端控制 Xcode” Automation 权限拦截。授予该权限后，应优先进入
  `observe_live` 检查 Unity surface attach/detach、旋转、前后台和返回页面。

### 当前涉及文件

- `mobile/android/settings.gradle.kts`：Unity module 的环境变量条件 include。
- `mobile/android/app/build.gradle.kts`、`AndroidManifest.xml`、`gradle.properties`：Unity
  arm64 build 约束及嵌入 launcher 清理。
- `mobile/packages/aletheia_visualization/android/build.gradle`、
  `.../UnitySurfaceProviderImpl.kt`：真实 Unity Android host。
- `unity/aletheia_viz/Assets/Editor/UaaLBuild.cs`：可重复的 Android Unity Gradle 正规化。
- `unity/README.md`：构建、恢复 CocoaPods、真实 renderer 的边界和命令。

### 架构决定与后续第一步

- 永远保留 `FlutterVisualizationEngine` 默认 fallback；只有构建期
  `ALETHEIA_UNITY_ENABLED=1` 加运行期 `AV_ENGINE=unity` 才进入 Unity。
- Unity 不拥有也不得改动 ROS2、HTTP、WebSocket、WebRTC 或视频流。两个包使用同一 bundle
  identifier，安装 Unity 版会替换同设备上的 Flutter 版。
- 下一步：在授权 Xcode Automation 后，用物理 iPhone 运行
  `ALETHEIA_UNITY_ENABLED=1 flutter run --debug --dart-define=AV_ENGINE=unity -d <device-id>`，
  进入观测页完成 surface/lifecycle 手动验收；不得以 Simulator 代替该验证。

## 2026-08-31：Unity renderer-only M1 环境、导出与设备验证（最新）

### 当前目标

完成 Claude 未完成的 Unity renderer-only M1 基础设施：让 Unity 作为 Aletheia Flutter
HMI 的**真机可选**地图/点云渲染器运行，同时永久保留 Flutter renderer 作为默认及 iOS
Simulator 的稳定路径。该轮只处理 Unity 工程、嵌入桥接与构建资源；不改 ROS2、HTTP、
WebSocket、WebRTC、地图业务模型或 HMI 信息架构。

### 已完成

- 已启用 Unity Personal，并验证 Unity **2022.3.62f1 (`4af31df58517`) Apple Silicon** 可用；
  `2022.3.73f1` 属于 Extended LTS，当前 Personal 许可证不能使用，不能作为本工程 Editor。
- Android 与 iOS Build Support 已安装。`VizSceneBootstrap.Rebuild` 已成功生成
  `unity/aletheia_viz/Assets/Scenes/Viz.unity`；`UaaLBuild.ExportAndroid` 成功导出
  `unity/builds/android/unityLibrary`，`UaaLBuild.ExportIos` 成功导出
  `unity/builds/ios`。
- 修复 `UaaLBuild.cs` 的导出根目录计算、首次导出缺场景、iOS 误用 Android-only
  `AcceptExternalModificationsToPlayer` 等问题；iOS bridge 由已嵌入的 Flutter plugin
  framework 单独提供，Unity、Swift 和 Flutter FFI 解析同一个 dynamic framework，不会链接
  第二份点云/metrics buffer。
- 成功用 Xcode 编译导出的 `UnityFramework.framework`；已将该 framework 与完整、未降采的
  `Data` 放入 `mobile/packages/aletheia_visualization/ios/UnityLibrary/`（均为生成产物，
  已 gitignore）。
- 发现并修复真机启动即退出的资源定位问题：CocoaPods 会把 plugin 的 `s.resources` 放进
  `aletheia_visualization.framework/Data`，而不是 Runner.app。`UnitySurfaceProvider.swift`
  现在从 `Bundle(for: UnitySurfaceProvider.self).bundleIdentifier` 取得实际数据 Bundle ID，
  再传给 `setDataBundleId`；不再错误地写死 `com.unity3d.framework`。
- 使用真机 `See you tomorrow (wireless)` 以
  `ALETHEIA_UNITY_ENABLED=1 --dart-define=AV_ENGINE=unity` 完成 Xcode build、安装、启动与
  Dart VM Service 连接，并保持至少 15 秒稳定；此前的启动后立即退出未复现。
- 随后已执行普通 `pod install` 恢复 Simulator 配置，并以
  **iPhone 17 (`B77BE4F1-BC75-4837-A759-309D06AA9D20`)** 成功启动默认 Flutter Debug app。
  日常 App/HMI 调试应使用此模拟器。
- 新增 `UnityStartupSplash`：仅当 `--dart-define=AV_ENGINE=unity` 时，在 Flutter 首帧显示
  Aletheia 标识与 “Powered by Unity”，760ms 后以 180ms 无弹跳淡出交接到 HMI；默认 Flutter
  与 iPhone Simulator 不显示该标识。该组件遵守 `MediaQuery.disableAnimations`。
- Unity 启动标识的定向组件测试、`flutter analyze`、全量 `flutter test` 已通过（当前 141 项）。
  再次对无线真机执行 Unity opt-in：Xcode build 通过，但 macOS 阻止终端经 Xcode 自动化安装；
  这需要用户在“系统设置 - 隐私与安全性 - 自动化”允许终端控制 Xcode，不是编译问题。

### 当前正在进行

Unity M1 已达到可构建且可启动的设备 PoC 断点。当前 iPhone 17 Simulator 正运行普通
Flutter Debug；不应在其上启用 Unity，因为 Unity 2022 导出的 iPhoneOS framework 不支持
Simulator 架构。

### 尚未完成

1. 在真机实际进入观测页后，验证 Unity surface 的 attach / detach / pause / resume / unload，
   以及地图、姿态与点云更新；本轮仅证明 App 和 Unity runtime 能稳定启动。
   同时人工确认 Unity 启动标识出现并在预期时间内淡出。
2. 在 Android 真机把已导出的 `unityLibrary` 接入并验证生命周期；尚未改 Android Gradle，
   避免未经真机验证的系统集成。
3. 完成 M2/M3/M4 的性能、GPU 点云、3D 场景与 A/B 指标，之前不得删除或默认切换 Flutter
   renderer。
4. iOS bridge 必须继续只编进 `aletheia_visualization.framework`，不得再移回 Runner
   executable，也不得编进 UnityFramework；否则会重现 Release 空 lazy binding 或两份
   staging buffer 的问题。

### 下一步第一件事

在连接的**物理 iPhone**上执行：

```sh
cd /Users/bob/Desktop/code/ry-aletheia/mobile/ios
ALETHEIA_UNITY_ENABLED=1 pod install
cd ..
ALETHEIA_UNITY_ENABLED=1 flutter run --debug \\
  --dart-define=AV_ENGINE=unity -d 00008110-001154A90AC3401E
```

进入“观测”，确认 Unity 画布真实出现后依次测试旋转、前后台、离开/返回观测页。完成后立即
执行普通 `cd ios && pod install`，再回到 iPhone 17 Simulator 做常规 Flutter 调试。

### 当前涉及文件

- `unity/aletheia_viz/ProjectSettings/ProjectVersion.txt`：Personal 可用 Unity 版本锁定。
- `unity/aletheia_viz/Assets/Editor/UaaLBuild.cs`：无交互场景生成、Android/iOS 导出、
  iOS shared bridge linker 设置。
- `unity/aletheia_viz/Assets/Scenes/Viz.unity` 及关联 `.meta`：可复现的 Unity 最小场景源。
- `unity/builds/android/`、`unity/builds/ios/`：本机导出产物，gitignore，按 Unity 源改动重建。
- `mobile/packages/aletheia_visualization/ios/UnityLibrary/`：iOS 真机 UnityFramework 与 Data
  的本机生成副本，gitignore，不是 App source。
- `mobile/packages/aletheia_visualization/ios/aletheia_visualization.podspec`：通过
  `ALETHEIA_UNITY_ENABLED=1` 有条件嵌入 framework/resource。
- `mobile/packages/aletheia_visualization/ios/Classes/UnitySurfaceProvider.swift`：进程唯一 Unity
  生命周期及正确的 plugin resource Bundle 定位。
- `mobile/lib/app/unity_startup_splash.dart`：Unity opt-in 专用的短暂启动归属标识。
- `mobile/lib/app/app.dart`：把启动标识注入根 `MaterialApp.router`，不影响 Router。
- `mobile/test/app/unity_startup_splash_test.dart`：有/无 Unity 标识和启动交接回归测试。

### 当前架构决策

- Flutter 拥有导航、HMI、状态、所有机器人协议、地图业务数据、任务和六路视频；Unity 只渲染。
- `AV_ENGINE=unity` 是显式实验开关；无该 Dart define 时永久使用
  `FlutterVisualizationEngine`。iOS Simulator 永远走默认 Flutter 路径。
- Unity 与 plugin 只能共享**一份** native bridge；UnityFramework 的 unresolved symbols 必须
  从宿主 plugin 解析，不能将 `aletheia_viz_bridge.c` 复制编译到 Unity。
- `Data` 按 CocoaPods 当前动态 framework 布局保留在 plugin bundle，并动态查询其 bundle ID；
  不假定其位于 Runner.app 或 UnityFramework bundle。

### 当前 UI 决策

- 此轮无用户可见 HMI 重设计；Unity surface 只在 opt-in 时替换观测地图内部渲染面，顶部状态、
  导航、视频和操作入口均继续由 Flutter HMI 承担。

### 当前问题

- plugin 仍会提示尚未支持 Swift Package Manager；当前 CocoaPods iOS build 可用，该 warning
  非阻塞。SPM 迁移另列任务，不能与 Unity 生命周期排查混改。
- CocoaPods 对 `Podfile` 的自动 iOS 15 平台与自定义 config 提示仍存在；当前真机/模拟器构建
  均通过，未经单独审计不要机械改 Podfile。

### 验证状态

- `flutter analyze`：2026-08-31 通过，无问题。
- `flutter test --concurrency=1 -r compact`：2026-08-31 通过，141 项。
- `Unity batch scene rebuild`：通过。
- Unity Android `unityLibrary` export：通过；Android App 真机嵌入未做。
- Unity iOS export 和 `UnityFramework.framework` Xcode Release build：通过。
- iOS 真机：Unity opt-in build/install/VM service/15 秒稳定通过；观察页 Unity surface 生命周期
  尚待人工设备验证。2026-08-31 再次 build 通过，但无线安装被 macOS Xcode Automation 权限阻断。
- iOS Simulator：iPhone 17 默认 Flutter build 与启动通过；Unity 故意不参与。
- Android Release：2026-08-31 已成功生成 `mobile/build/app/outputs/flutter-apk/app-release.apk`
  （约 95 MB，默认 Flutter renderer）。
- iOS Release：2026-08-31 已成功生成
  `mobile/build/ios/archive/Runner.xcarchive`（208.1 MB，默认 Flutter renderer）；IPA 导出尚被
  Apple 签名配置阻断：当前 Keychain/Xcode 没有 `iOS Distribution` 证书，且
  `com.ryaletheia.aletheiaMobile` 没有对应 Distribution Provisioning Profile。Archive 本身可在
  Xcode Organizer 中签名后导出。以开发签名导出的当前设备安装包已成功生成：
  `mobile/build/ios/ipa/aletheia_mobile.ipa`（16.0 MB）；它不能用于 App Store/TestFlight 分发。
- `git diff --check`：2026-08-31 通过；未创建 Git commit。

### PROJECT_OVERVIEW.md 约束

- `PROJECT_OVERVIEW.md` 是机器人接口与产品事实的最高基线。不可因 Unity 接入改动 ROS2、
  HTTP API、Binary WebSocket、WebRTC、PointCloud/Pose 数据语义或后端。
- 继续遵守 `mobile/AGENTS.md`：Unity 仅 renderer；App 的生产默认必须保留 Flutter fallback。

### Skills

- `write-swift`：用于审查并以最小、同步的方式修正 Unity iOS resource Bundle 解析；没有引入
  新并发、全局不安全状态或 try/catch 掩盖启动失败。

### Resume Prompt

先读取 `PROJECT_OVERVIEW.md`、`mobile/AGENTS.md`、本段、`unity/README.md` 和当前 git diff。
确认 iPhone 17 Simulator 的普通 Flutter Debug 仍可启动。若继续 Unity，先确认 macOS 已允许
终端控制 Xcode；只在物理 iPhone 上用
`ALETHEIA_UNITY_ENABLED=1` 和 `--dart-define=AV_ENGINE=unity` 验证观测页 lifecycle；完成后
恢复普通 `pod install`。不得把 Unity 加入 Simulator、不得删除 Flutter renderer、不得修改
ROS2/HTTP/WebSocket/WebRTC 或创建 Git commit。

## 2026-08-30：Unity M1 环境配置与工程预检（最新）

### 当前目标

继续 Claude 建立的 Unity renderer-only M1 PoC：先让 Unity 2022 LTS + Android/iOS
模块可用，再导入 `unity/aletheia_viz`、生成最小场景并验证平台库导出。Flutter
renderer 必须继续是默认 fallback，Unity 仅通过 `AV_ENGINE=unity` opt-in 验证。

### 已完成

- Unity Personal 已激活。经实际 batch import 验证，最初安装的 **2022.3.73f1** 属于
  Extended LTS，要求 Industry/Enterprise 许可证，不能用于当前 Personal 授权；该 Editor
  及其模块保留在本机但不用于工程构建。
- 已切换到 Unity Personal 可用的 Apple Silicon 版 **2022.3.62f1 (`4af31df58517`)**，并把
  `ProjectSettings/ProjectVersion.txt` 锁定到该版本；已启动它的 Android + iOS Build Support
  （含 Android SDK/NDK/OpenJDK 子模块）安装任务。
- 审查 M1 导出脚本，修复 `UaaLBuild.ProjectRelative` 的路径计算错误：原逻辑会导出到
  `<repo>/unity/unity/builds`，现在正确导出到 `<repo>/unity/builds`。
- 导出前现在会自动生成缺失的 `Assets/Scenes/Viz.unity`，避免首次 headless export 因场景
  尚未创建而失败。

### 当前正在进行

Unity 2022.3.62f1 与模块安装继续进行；尚未生成场景或导出平台产物，未将任何 Unity
Framework/Gradle library 接入 Flutter。

### 当前问题

- Unity 2022.3.73f1 的真实 batch import 输出已确认是 Extended LTS 授权限制；现已改用
  Personal 兼容的 2022.3.62f1。待该版本安装完成后才可验证 C#、URP 与平台导出。

### 下一步第一件事

待 Unity 2022.3.62f1 的 Android/iOS 模块安装完成后，执行 Unity batch import；成功后运行
`Aletheia.Viz.EditorTools.VizSceneBootstrap.Rebuild`，再分别导出 Android 与 iOS library，
仅以 `--dart-define=AV_ENGINE=unity` 验证 M1 生命周期和 Flutter fallback。

### 当前涉及文件

- `unity/aletheia_viz/ProjectSettings/ProjectVersion.txt`：Unity LTS 固定版本。
- `unity/aletheia_viz/Assets/Editor/UaaLBuild.cs`：正确的导出目录和首次导出场景保障。

### 验证状态

- Unity Hub：2022.3.73f1（Extended LTS）与其 Android/iOS 模块已装完但不适用 Personal；
  2022.3.62f1 Personal-compatible 安装进行中。
- Unity batch import：2022.3.73f1 已确认被许可证级别阻断；2022.3.62f1 尚待安装后验证，
  因此未把未验证的 Unity artefact 接进 App。
- `flutter analyze`：2026-08-30 通过，无问题。
- `git diff --check`：通过；未创建 Git commit。

### Resume Prompt

先确认 Unity Hub 已登录且 Unity Personal 已激活，再读取 `PROJECT_OVERVIEW.md`、
`mobile/AGENTS.md`、本段、`unity/README.md` 和当前 diff。确认 Android/iOS Build Support
模块安装完成后，用 2022.3.62f1 对 `unity/aletheia_viz` 做 batch import，生成 `Viz.unity`，
仅在 `AV_ENGINE=unity` 下继续 M1 导出和生命周期验证；不得改动 ROS2、后端、WebRTC 或
Flutter 默认 renderer，不创建 Git commit。

## 2026-08-30：iOS Unity 可视化插件桥接编译修复（最新）

### 当前目标

恢复 iPhone Simulator 上包含 `aletheia_visualization` 插件的 Debug 构建；保持
Flutter HMI、机器人协议和 Unity 渲染边界不变。

### 已完成

- 定位到 Swift 编译错误的第一层根因：共享 C bridge 虽有声明，但 CocoaPods 生成的
  `aletheia_visualization` umbrella module 没有导出该头文件，因而
  `UnitySurfaceProvider.swift` 无法解析 `av_metrics` / `av_metrics_read`。
- 定位到后续链接错误的第二层根因：CocoaPods 不会把 Pod iOS 根目录外的
  `../shared/*.c` 纳入 iOS target；声明可见后，`_av_metrics_read` 仍无实现可链接。
- 新增 `ios/Classes/AletheiaVisualizationBridge.h`：仅公开 Swift 需要的标量
  metrics 读取适配器；完整跨平台 ABI 仍只有 `shared/aletheia_viz_bridge.h` 一份。
- 新增 `ios/Classes/AletheiaVisualizationBridge.c`：唯一职责是编译包含共享 C bridge
  实现的 translation unit，并以标量方式转发 metrics，避免复制 C 逻辑或暴露 ABI struct。
- `UnitySurfaceProvider.swift` 改为通过该窄适配器读取 metrics；Unity、ROS2、HTTP、
  WebRTC、地图和业务逻辑均未改动。
- 已对 iPhone 17 Simulator 完成 Debug 构建和启动，应用安装/同步成功。

### 验证状态

- `flutter build ios --simulator --debug --no-codesign`：2026-08-30 通过。
- `flutter analyze`：2026-08-30 通过，无问题。
- `flutter test --concurrency=1 -r compact`：2026-08-30 通过，139 项。
- `git diff --check`：2026-08-30 通过；未创建 Git commit。
- 当前 iOS 仍显示 `aletheia_visualization` 尚未支持 Swift Package Manager 的 Flutter
  未来兼容性警告；这是非阻塞警告，当前 CocoaPods Debug build 已通过。后续单独评估
  SPM 支持，不能与渲染/业务改动混合。
- Android：本轮未构建；iOS bridge 变更只位于 `ios/`，Android 继续从 `shared/` 使用同一
  bridge 实现，仍应在下一次平台发布前执行 Android build。

### 当前涉及文件

- `mobile/packages/aletheia_visualization/ios/Classes/AletheiaVisualizationBridge.h`：
  CocoaPods module 的 Swift-facing 标量 metrics 声明。
- `mobile/packages/aletheia_visualization/ios/Classes/AletheiaVisualizationBridge.c`：
  iOS target 对共享 C 实现的编译入口。
- `mobile/packages/aletheia_visualization/ios/Classes/UnitySurfaceProvider.swift`：
  通过受限 adapter 读取指标。
- `mobile/packages/aletheia_visualization/ios/aletheia_visualization.podspec`：
  将 iOS 编译入口和 public header 纳入 CocoaPods module。
- `mobile/ios/Podfile.lock`、workspace/project：本地 `pod install` 同步结果。

### 下一步第一件事

用同一台 iPhone 17 在终端执行普通 Debug 启动，确认首屏进入后再按需要用
`--dart-define=AV_ENGINE=unity` 验证 Unity opt-in surface；未经真机 Unity export 验证，
不要将默认 Flutter renderer 改为 Unity。

### Skills

- `write-swift`：用于审查 Swift/CocoaPods 模块边界；采用窄、同步的 C interop adapter，
  不引入无必要并发或非受限 unsafe 数据通道。

### Resume Prompt

先读取 `PROJECT_OVERVIEW.md`、`mobile/AGENTS.md`、本段、`mobile/docs/ARCHITECTURE.md`、
`mobile/docs/DESIGN_SYSTEM.md`、`docs/UI_SPEC.md` 和当前 diff。确认 iOS bridge 的 Debug
build、analyze 与 139 测试仍通过。若继续 Unity M1，只在
`--dart-define=AV_ENGINE=unity` 下验证 renderer；Flutter renderer 继续作为默认 fallback，
不得修改 ROS2、后端协议或 WebRTC 链路。Android 发布前补跑 Android build。不要创建 Git commit。

## 2026-08-30：主题收敛与壳层同步修复（最新）

### 当前目标

将设置中的本机显示主题收敛为默认 HMI 深色与日间模式两项，并修复切换日间模式后 App 顶部壳层仍保留深色、内容已变浅色的不同步问题；不触及机器人数据、协议或业务能力。

### 已完成

- 移除 `AppThemePreference.highContrastDark`、对应 palette、选择器选项、文案与 App theme 分支；主题 Sheet 现在只显示“默认 HMI 深色”和“日间模式”。
- 兼容旧开发构建已保存的 `highContrastDark` 字符串：读取时自动回退 `hmiDark`，不会产生未知状态或隐藏第三主题。
- 定位并修复不同步根因：`AletheiaAppShell` 原先直接读取全局静态调色板，因此未订阅 inherited `Theme`；设置页因 Riverpod 偏好变化重建后变为浅色，但 AppBar 仍复用旧深色构建结果。
- App shell 现在使用 `Theme.of(context)` 提供顶栏、连接状态和紧凑导航的颜色，因此与 `MaterialApp` 同次主题更新重建；新增 180ms、无弹跳的 `easeOutCubic` 主题过渡，保持 HMI 几何稳定。
- Theme 的 AppBar `SystemUiOverlayStyle` 会随明暗主题更新状态栏与系统导航栏的亮度/底色，避免 iOS 顶部系统区残留上一主题。
- 新增根应用回归测试，验证从默认深色切换到日间时 AppBar 背景同步从 `#101415` 变为 `#F2F6F5`；设置页测试验证只有两项主题可选。
- 已同步 `PROJECT_OVERVIEW.md`、UI Spec、移动 README、Design System 和架构手册的现行主题定义。

### 当前正在进行

代码与回归测试已完成，处于可运行断点；全工程静态检查受当前 Unity PoC 的外部编译错误阻断，未跨范围修改 Unity。

### 尚未完成

1. 在 iPhone/Android 真机上人工确认日间模式的状态栏图标、底部系统导航、横竖屏与从视频/地图返回设置的过渡；自动化测试不能替代原生系统栏检查。
2. 若后续增加显示偏好，必须先评估是否真有使用价值；不要重新引入第三种只改变对比度的主题。

### 下一步第一件事

在 iPhone Debug build 打开“设置 → 主题”，分别选择默认 HMI 深色与日间模式，等待过渡完成后确认顶部、系统状态区、内容、底部导航和返回其他一级页面都为同一配色；再重启 App，确认两种偏好均能持久化。

### 当前涉及文件

- `mobile/lib/features/app_settings/domain/app_preferences.dart`：两项主题枚举与旧偏好回退。
- `mobile/lib/features/app_settings/presentation/app_settings_screen.dart`：两项主题选择 UI。
- `mobile/lib/app/app.dart`、`app_shell.dart`、`app/theme/aletheia_theme.dart`：主题切换、壳层依赖和系统栏同步。
- `mobile/test/app/app_theme_switch_test.dart`、`test/features/app_settings/*`：切换与选项数量回归测试。
- `PROJECT_OVERVIEW.md`、`docs/UI_SPEC.md`、`mobile/docs/DESIGN_SYSTEM.md`、`mobile/README.md`、`mobile/docs/ARCHITECTURE.md`：现行主题事实。

### 当前架构与 UI 决策

- App 只提供默认 HMI 深色和日间模式；日间模式是完整的低反光浅色 palette，而不是高对比模式或简单反相。
- 本机主题偏好只改变表现，不改变机器人地址、实时数据、地图证据、协议、运行配置或安全边界。
- App shell 不能读取与 inherited Theme 脱钩的主题颜色；任何持久 chrome 都必须在同一次主题变更中重建并同步系统栏样式。

### 当前问题与验证状态

- 首次定向测试在未清除本机代理时出现 Flutter tester 本地 HTTP 连接错误；按项目约定临时移除 HTTP(S)/ALL proxy 后，代码测试通过。这是环境问题，不是主题断言或应用异常。
- 定向 Flutter 测试：通过 6 项（主题、旧偏好回退、设置选择与 App shell 切换）。
- 全量 `flutter test --concurrency=1 -r compact`：2026-08-30 通过（包含主题切换回归与既有 Gallery Golden）。
- `flutter analyze`：2026-08-30 被与本轮无关的 Unity PoC 两项错误阻断：`unity_visualization_engine.dart` 的 invalid constant，以及 `packages/aletheia_visualization/.../visualization_view.dart` 的 `PlatformViewHitTestBehavior` 未定义；主题相关文件的定向测试均通过。
- `git diff --check`：2026-08-30 通过；未创建 Git commit。
- iOS/Android 构建：本轮未重复执行；主题变更未触及平台工程。真机系统栏验收仍待执行。

### Skills

- `apple-design`：用于确认主题切换应是克制、短时、无弹跳的可读性过渡，并要求系统栏与内容的视觉连续性；没有增加装饰性动效。

### Resume Prompt

先读取 `PROJECT_OVERVIEW.md`、`mobile/AGENTS.md`、本段、`mobile/docs/DESIGN_SYSTEM.md`、`docs/UI_SPEC.md` 和当前 diff。先完成主题收敛的全量 analyze/test/diff 检查；然后在真机验证两种主题的系统栏、横竖屏与持久化。不要恢复高对比深色，不修改机器人协议或业务逻辑，不创建 Git commit。

## 2026-08-30：Unity 可视化引擎 PoC — M0 seam（最新）

### 当前目标

正式启动“Flutter + Lightweight Unity Visualization Engine” PoC。后续产品已明确需要
3D 点云、3D 机器人模型、2D/3D 场景切换、3D 轨迹/路径/障碍、3D 场景交互和数字孪生，
Unity 不再是远期预留。架构边界锁定：Flutter 拥有 App（导航、HMI、业务逻辑、网络、
状态管理、六路 WebRTC 视频）；Unity 只是纯实时渲染引擎，不接触 ROS2/机器人通信、
Task JSON、业务逻辑、Mission Recovery、后端 API 和视频。现有 Flutter App 已基本完成，
不允许大规模重构；当前 Flutter Renderer 必须永久保留为 fallback。

分阶段执行，本次只做 **M0**：在 Flutter 侧插入 `VisualizationEngine` 抽象层，把现有
渲染实现包装为 `FlutterVisualizationEngine`，观测页经该接口取地图渲染面。零行为变更。

### 已完成

- 新建分支 `poc/unity-viz`（从 `v2.0` 切出），与出货分支隔离，未经 A/B 报告与签字不合并。
- 新增 `mobile/lib/features/live_observation/visualization/visualization_engine.dart`：
  `abstract interface class VisualizationEngine { Widget buildMapSurface({required LiveMapAsset map}); }`，
  文件头写明四条锁定原则（Flutter owns the App / Unity owns the Scene / Video stays outside
  Unity / Business logic never enters Unity）。
- `live_observation_screen.dart`（+27/−3）：新增 `FlutterVisualizationEngine`（返回现有
  `_MapViewport`，`ValueKey('${map.id}-viewport')` 不变）与 `visualizationEngineProvider`
  （`Provider<VisualizationEngine>` 默认 `const FlutterVisualizationEngine()`）；`_MapWorkspace`
  由 `StatelessWidget` 改为 `ConsumerWidget`，地图面由
  `ref.watch(visualizationEngineProvider).buildMapSurface(map: map)` 提供。
- `_MapViewport` 及其 painter/layer、手势逻辑、`_CloudMetricsReporter`、工具栏、位姿/连接
  读数、比例尺、`liveMapPreviewBuilderProvider`（Gallery 用）全部原地未动。数据层
  （telemetry client/provider、decoder、controller/repository、`live_map`）未触碰。
- 新增 `mobile/test/features/live_observation/visualization/visualization_engine_test.dart`：
  3 项——默认 provider 是 `FlutterVisualizationEngine` 且 surface key 正确；真实观测页默认
  渲染 `map-gesture-surface`；override 引擎后只替换地图面，`map-operational-readout` 等
  HMI chrome 不受影响。
- 产出 PoC 执行计划（artifact “Unity Visualization PoC Plan”）：
  https://claude.ai/code/artifact/21aadf8b-d97e-4817-8a4c-a3509cbe9918
  含数据链路审计、桥接契约（`pushCloud`=dart:ffi，其余 Method/EventChannel）、M0–M4
  里程碑、真机指标清单、A/B 报告模板与迁移门槛。

### 当前正在进行

M0 代码与测试已保存并通过；处于干净断点，未创建 Git commit。**Unity 尚未集成** ——
没有 Unity 工程、没有桥接插件、没有原生代码、没有任何东西经 Unity 渲染。

### 尚未完成（优先级）

1. **M1**：裁剪版 Unity 工程 `unity/aletheia_viz/`（URP、最小 runtime/package/asset，见计划 §4）
   + 桥接插件 `aletheia_visualization`（PlatformView 嵌入 + MethodChannel 生命周期 + `loadMap`）；
   Unity 正交相机渲染 Occupancy 底图 + 自适应米制栅格，在 iOS/Android 真机各跑通一次。
2. **M2**：`pushPose`（EventChannel）+ `pushCloud`（dart:ffi → 原生 staging buffer →
   `GraphicsBuffer` → GPU 点着色器）+ 车体/位姿；Flutter 侧相机控制器驱动 `setCamera`。
   保持 latest-wins 与零每帧分配。
3. **M3**：3D 点云 + 简单 3D 机器人 primitive + 透视相机 orbit/pan/zoom + `setViewMode`
   2D⇄3D 切换。
4. **M4**：合成点云发生器（3k / 5万 / 10万 / 20万点 @ 8/15/30Hz）+ A/B 引擎开关 +
   真机指标采集（FPS、帧时、CPU、GPU、内存、GC、发热、功耗、启动、包体、
   Flutter+Unity+WebRTC 并行稳定性、横竖屏、前后台、长时间运行）。
5. A/B 报告 → 决定是否将 Live Visualization 正式迁移到 Unity。迁移前不动任何用户界面，
   不删 Flutter Renderer。
6. 重定位：本轮不做；仅要求 Unity Scene 架构未来能承载
   `map + local cloud + candidate pose + 交互式 x/y/yaw 对齐`。

### 下一步第一件事

M0 可作为独立 PR 合入 `v2.0`（纯 Flutter 结构化，无 Unity 依赖）。随后开始 M1：需要本地
Unity Editor（最新 LTS）、Xcode + iOS 真机、Android 真机 + NDK/Gradle 链。先建
`unity/aletheia_viz/` 空 URP 工程并按计划 §4 逐项裁剪 Project Settings，再导出
`unityLibrary` / `UnityFramework` 并用一个最小 PlatformView 插件在 Flutter 观测页内显示一个
纯色 Unity 画面，验证生命周期 create/pause/resume/unload 干净、无泄漏。

### 当前涉及文件

- `mobile/lib/features/live_observation/visualization/visualization_engine.dart`：引擎接口与边界。
- `mobile/lib/features/live_observation/presentation/live_observation_screen.dart`：
  `FlutterVisualizationEngine`、`visualizationEngineProvider`、`_MapWorkspace` 接入 seam。
- `mobile/test/features/live_observation/visualization/visualization_engine_test.dart`：seam 回归。
- `docs/AI_CONTINUATION.md`：本断点。

### 架构 / UI 决策

- `VisualizationEngine` 只暴露 `buildMapSurface({required LiveMapAsset map})`；pose/cloud 由
  `FlutterVisualizationEngine` 内部 `ref.watch`，不进接口。M2 引入 Unity 实现时按需扩接口
  （`pushPose`/`pushCloud`/`setCamera`/`setViewMode`/`setLayerVisible`/lifecycle），不提前写死。
- 引擎切换是 `visualizationEngineProvider` 的 override（未来接 build flavor / flag）；
  还原 override 即完整回退。Flutter Renderer 永不删除。
- 点云跨界只走 dart:ffi（`CloudFrameDecoder` 产出的 packed `Float32List` 指针+长度）→ 原生
  staging buffer → Unity GPU buffer。禁止 JSON 点云、禁止逐点 MethodChannel、禁止大量对象转换。
  时效丢帧（cloud >100ms / pose >250ms）与 latest-wins 留在 Dart 侧。
- 六路 WebRTC 视频完全保持现有 Flutter/native 实现，绝不进入 Unity。
- 手势留在 Flutter（现有 `_MapViewportState` 双指质心缩放 / 有界平移），只把相机变换喂给引擎。
- 渲染面接入优先 PlatformView（M1/M2 验证），若合成开销过大再转 render-texture 共享（Phase B）。

### 问题与验证状态

- `flutter analyze`（全工程）：2026-08-30 通过，无问题。
- `flutter test --concurrency=1 -r compact`：2026-08-30 通过 **139 项**（136 基线 + 3 新 seam 测试）。
- Gallery Golden：78 项在套件内一并通过 —— M0 无任何像素变化。
- `git diff --check`：通过。未创建 Git commit。
- iOS/Android 真机、Unity 集成、性能与 A/B：**未开始**，无数据。
- Flutter test 仍需临时移除 HTTP(S)/ALL 代理环境变量。

### 项目边界

- `PROJECT_OVERVIEW.md` 仍是最高事实基线。Unity PoC 不改机器人协议、后端业务、二进制
  WebSocket / WHEP 契约、视频链路。
- Observation 只读边界不变；Unity 是渲染器，不承载任何命令或业务。
- 不大规模重构现有 Flutter App；M0 是最小 seam。

### Skills

- `artifact-design`：完整读取，用于 PoC 执行计划 artifact 的排版与信息设计。

### Resume Prompt

先读取 `PROJECT_OVERVIEW.md`、`mobile/AGENTS.md`、本文件本段、PoC 计划 artifact
（https://claude.ai/code/artifact/21aadf8b-d97e-4817-8a4c-a3509cbe9918）和当前 `git diff`。
确认 M0 seam 已在 `poc/unity-viz` 分支且 139 测试通过后，从 M1 开始：本地需 Unity Editor
+ iOS/Android 真机。建 `unity/aletheia_viz/` 最小 URP 工程按计划 §4 裁剪，导出
`unityLibrary`/`UnityFramework`，写最小 `aletheia_visualization` PlatformView 插件，在
Flutter 观测页显示 Unity 画面并验证生命周期无泄漏。不扩大 Unity 职责、不动视频链路、
不删 Flutter Renderer；点云跨界只用 dart:ffi + GPU buffer。执行 Flutter 测试时仅对命令
临时移除 HTTP(S)/ALL 代理环境变量。

## 2026-08-29：移动端维护与多 Agent 文档体系

### 当前目标

基于当前真实 Flutter 工程建立可持续维护的 App 文档体系，供后续人类开发者、Codex、Claude 和其他多 Agent 并行协作使用；本轮不改动业务功能、协议或视觉实现。

### 已完成

- 新增 `mobile/AGENTS.md`：定义最高事实基线、源码阅读顺序、不可跨越的协议/安全边界、并行文件所有权、UI/Gallery 约束、最小验证门槛及 AI 交接格式。
- 新增 `mobile/docs/ARCHITECTURE.md`：以现有源码说明 App 根、GoRouter 14 个路由、四个一级入口、Riverpod 责任分层、endpoint/HTTP、地图 world canvas、ALTM Pose/PointCloud、WHEP 三路视频上限、工具/设置、Gallery、品牌和平台安全边界。
- 新增 `mobile/docs/DEVELOPMENT_WORKFLOW.md`：记录本地运行、代理清除、Debug Gallery、定向/全量测试、Golden/UI 文档生成、Android/iOS 构建、真实地图/视频验收、SVG Icon 生成、多 Agent 协作和常见故障排查的可执行流程。
- 新增 `mobile/docs/README.md`：按新维护者、Flutter 开发、UI Review、实时观测、构建和 Agent 继续任务等角色组织的文档索引与维护规则。
- 更新 `mobile/README.md`，增加开发与维护文档入口；既有产品能力、业务文案及运行说明保持不变。
- 文档明确当前真实边界：Observation 只读、设置只影响本机、离线升级 ZIP/RViz/任意命令和底盘导航控制不属于 App；未来 Operation/Command 必须有独立契约、权限与审计。

### 当前正在进行

文档、源码事实复核和验证均已完成，处于可继续开发的干净断点（未创建 Git commit）。

### 尚未完成

1. 后续每个新 feature/新状态按 `mobile/AGENTS.md` 的流程同步更新源码测试、Gallery manifest 和此文档体系。
2. 当车端协议、平台构建或发布流程改变时，同步更新 `PROJECT_OVERVIEW.md`、架构手册和开发工作流，避免文档滞后。
3. 未来多人实际并行时，按文档声明文件所有权，并优先采用独立 Git worktree。

### 下一步第一件事

任何新维护任务开始时，先按 `mobile/AGENTS.md` 的“开始任何任务前”顺序重新读取 `PROJECT_OVERVIEW.md`、当前 diff、架构/工作流/设计文档和最新断点；然后只从明确的下一项产品任务开始，不重构已确定架构。

### 当前涉及文件

- `mobile/AGENTS.md`：维护者与多 Agent 的硬性协作约束。
- `mobile/docs/README.md`：移动端文档入口与维护责任。
- `mobile/docs/ARCHITECTURE.md`：当前源码架构和扩展边界。
- `mobile/docs/DEVELOPMENT_WORKFLOW.md`：开发、调试、验证和交接 SOP。
- `mobile/README.md`：快速入口与新文档链接。
- `docs/AI_CONTINUATION.md`：本轮最新开发断点。

### 当前架构与 UI 决策

- `PROJECT_OVERVIEW.md` 仍是产品能力、后端 API、协议和安全边界的最高事实基线；移动端文档只能解释 App 如何消费，不得自行定义车端能力。
- App 代码层级固定为 `app → core → features`；Page 不直接拼 URL、解析二进制帧或管理 WebRTC 原生资源。
- `lib/debug_ui/gallery_manifest.dart` 是 Gallery、Golden 和自动 UI 文档的单一清单来源；生成的 Screen Inventory/Map 不手工编辑。
- 一级入口保持“首页 / 观测 / 工具 / 设置”。地图/视频优先作为 HMI 工作区；Operation/Command 未实现，也不得混入只读观测架构。

### 当前问题

- 本轮仅文档变更，未发现新的业务 bug。
- 真实机器人地图、六路视频快速切流、iOS/Android 真机与新主题的现场验证仍须遵循先前断点记录执行；Gallery/Golden 不能代替真实网络与原生 WebRTC 验收。

### 验证状态

- 文档链接与内容：2026-08-29 已对照 `router.dart`、`app_shell.dart`、`robot_endpoint.dart`、API client、Gallery manifest 和脚本复核。
- `flutter analyze`：2026-08-29 通过，无问题。
- `flutter test --concurrency=1 -r compact`：2026-08-29 通过 **136 项**。
- iOS Simulator / Android：本轮未重复构建；最近记录为 debug 构建通过，文档变更没有触及 Dart/平台源。
- Git：已执行最终 `git status --short` 与 `git diff --check`；不自动创建 commit。

### PROJECT_OVERVIEW.md 约束

- 移动端仅消费现有可信局域网 HTTP、二进制 WebSocket 与 WHEP 能力；不得私自改变端点或部署配置。
- 不实现离线升级 ZIP、RViz、ROS 原生操作、底盘/导航控制、任意路径访问或任意命令。
- 用户可见测试、用例、报告、日志、实时观测都应保留为 HMI 的现有能力；不可因信息架构调整删除。

### Skills

- 本轮是基于真实源码的 Markdown 维护文档工作，未调用额外的实现型 Skill；沿用已有 `PROJECT_OVERVIEW.md`、Design System、UI Spec 和 Debug UI Gallery 约束作为事实来源。

### Resume Prompt

先读取 `PROJECT_OVERVIEW.md`、`mobile/AGENTS.md`、`docs/AI_CONTINUATION.md`、`mobile/docs/ARCHITECTURE.md`、`mobile/docs/DEVELOPMENT_WORKFLOW.md`、`mobile/docs/DESIGN_SYSTEM.md`、`docs/UI_SPEC.md` 和当前 `git diff`。确认文档最新段的验证状态后，针对用户下一项明确需求只改最小范围；涉及页面状态时同步 Gallery/Golden/UI Inventory，结束前执行相应测试、`flutter analyze`、`git diff --check`，不提交 Git commit。

## 2026-08-29：应用设置起步（最新）

### 当前目标

补齐 Aletheia 移动 HMI 的独立一级“设置”入口：语言偏好、经现场可读性审阅的显示主题、软件版本、App 更新检查和问题反馈；所有能力必须与机器人运行配置严格隔离。

### 已完成

- 新增独立一级“设置”路由与入口，不连接机器人即可访问；它使用应用级页标题、分组列表和系统底部选择器，不再被归类为工具二级页。旧 `/tools/app-settings` 深链接重定向至 `/settings`，不破坏既有 Debug/书签入口。
- 原“机器人”一级导航已统一命名为“首页”；它仍指向既有 `/robot` 连接与健康概览页面，未更改路由、连接逻辑或机器人业务对象。Gallery、Screen Inventory、Screen Map 和 Golden 已同步为“首页 / 观测 / 工具 / 设置”。
- 品牌资源已迁移至唯一设计源 `assets/branding/aletheia_icon_vector.svg`：App 内由 `flutter_svg` 直接绘制；`tool/regenerate_launcher_icons.sh` 以该 SVG 生成系统所需 PNG，并刷新 iOS AppIcon 与 Android legacy / Adaptive Icon。旧运行时 `app_icon.png` 已删除；现有 iOS Splash 不使用该 PNG，故保持原有启动页不变。
- 新增 SharedPreferences 本机偏好模型：`AppLanguage`（简体中文 / English）和 `AppThemePreference`（默认 HMI 深色 / 日间模式 / 高对比深色）。切换立即生效并尽力持久化；本地存储失败不会阻止进入 HMI。
- `MaterialApp` 现在接收保存的 App Locale 和主题偏好。语言选择已完整应用于设置页，作为其余正式页面逐页本地化的基础；不可伪称既有中文业务页已全部翻译。
- 高对比深色调整 Material 的文字、主色、轮廓、导航指示和表单对比度；日间模式以低反光冷白工作底、深色文字和保留对比的青绿主操作色覆盖所有现有 HMI token。两者都保留地图/视频证据和状态语义，不使用纯白或简单色彩反相。
- 新增日间模式的真实生产页 Gallery 状态与 Golden：`实时观测 · 日间模式` 使用与 App 相同的 Palette 渲染地图、点云、虚拟墙、位姿、连接状态与导航，而非单独复制一套审阅 UI；截图为 `docs/ui/screens/observe/live-daylight.png`。
- 版本显示使用 Flutter build name / number 环境常量；原“运行平台”已替换为可进入的“检查更新”。当前开发构建只展示本地检查结果，未来 App 更新只能经审核的移动发布渠道提供，绝不复用机器人 `updates/` 离线升级目录。
- 问题反馈现改为 App 内独立表单：可填写问题/建议、详细描述、联系方式，选择最多三张截图，并选择是否附加仅含版本、平台、语言、主题和本次 App 会话事件的诊断摘要。当前实现只进行本地校验，不上传、不保存表单内容；`FeedbackSubmissionRepository` 是未来经过隐私审查的上传接口边界。
- 应用设置、检查更新与问题反馈已加入 Debug UI Gallery、Screen Inventory 和 Screen Map；更新页覆盖“开发构建未接入在线服务”状态，反馈表单分别覆盖已填写状态和“截图/诊断摘要已选择”状态，自动截图为 `settings/update-ready.png`、`settings/feedback-draft.png`、`settings/feedback-attachments.png`。

### 当前正在进行

本轮实现、截图、规范与测试均已保存，处于可运行断点。

### 尚未完成

1. 将现有机器人、观测、工具业务页的用户文案逐页迁移到本地化资源；English 偏好当前保证设置页和 Flutter Locale，尚不代表全 App 英文化完成。
2. 在真实 iPhone 与 Android 上逐页验收日间模式下地图、视频、状态色、强光现场可读性、横竖屏和偏好重启持久化；特别确认地图/视频实时证据的对比度。
3. 在真机上验证系统图片选择器、表单校验、开发期零上传提示、中文/英文系统字体和高对比模式；这些都不需要或不应连接机器人。

### 下一步第一件事

在 iPhone / Android Debug 构建中从底部/侧栏“设置”一级入口进入，依次切换 English、HMI 深色、日间模式和高对比深色，完全退出并重新打开 App，确认本机偏好保留；在强光与横屏下检查日间模式的地图、视频与状态可读性。再验证问题反馈的系统图片选择、表单校验和“未上传或保存”提示。随后以“机器人”连接页为第一批全量英文迁移目标。

### 当前涉及文件

- `mobile/lib/features/app_settings/domain/app_preferences.dart`：本机语言与主题偏好模型。
- `mobile/lib/features/app_settings/data/app_preferences_store.dart`、`application/app_preferences_controller.dart`：本地持久化与即时偏好状态。
- `mobile/lib/features/app_settings/presentation/app_settings_screen.dart`：设置、版本/检查更新与 App 内问题反馈入口。
- `mobile/lib/features/app_settings/presentation/app_update_screen.dart`：App 本地更新检查入口；开发构建不接入网络，未来发布渠道与车端离线升级严格隔离。
- `mobile/lib/features/app_settings/presentation/feedback_screen.dart`、`domain/feedback_draft.dart`、`data/feedback_submission_repository.dart`、`data/app_diagnostic_log.dart`：问题与建议表单、受限 App 会话诊断摘要模型和当前零上传的开发期提交边界。
- `mobile/lib/app/app.dart`、`app/router.dart`、`app/theme/aletheia_theme.dart`：Locale、默认 HMI 深色 / 日间模式 / 高对比深色 Palette 状态和路由整合。
- `mobile/lib/app/app_shell.dart`、`app/router.dart`：独立一级首页 / 设置导航与旧深链接兼容。
- `mobile/assets/branding/aletheia_icon_vector.svg`、`mobile/lib/app/branding/aletheia_brand_mark.dart`、`mobile/tool/regenerate_launcher_icons.sh`：唯一矢量 Logo 源、运行时 SVG 渲染与平台 Launcher Icon 导出。
- `mobile/pubspec.yaml`、`pubspec.lock`、`android/app/src/main/res/mipmap-anydpi-v26/launcher_icon.xml`、`ios/Runner/Assets.xcassets/AppIcon.appiconset/`：`flutter_svg` 依赖、Android Adaptive / legacy Launcher Icon 和 iOS AppIcon 平台产物。
- `mobile/lib/debug_ui/gallery_manifest.dart`、`gallery_preview.dart`、`test/features/app_settings/`、`test/app/aletheia_theme_test.dart`：Gallery、日间模式截图和偏好/UI 回归。

### 验证状态

- `flutter analyze`：2026-08-29 通过，无问题。
- `flutter test -r compact --concurrency=1`：2026-08-29 通过 **136 项**。
- Gallery Golden：2026-08-29 通过 **78 项**；已人工检查应用设置、检查更新、问题反馈和日间模式观测截图，不存在重复返回控件、遮挡或溢出。
- `flutter build apk --debug`：2026-08-29 通过，输出 `mobile/build/app/outputs/flutter-apk/app-debug.apk`。
- `flutter build ios --simulator --debug --no-codesign`：2026-08-29 通过，输出 `mobile/build/ios/iphonesimulator/Runner.app`。
- `dart run tool/generate_ui_docs.dart`、`git diff --check`：2026-08-29 通过；未创建 Git commit。

### 当前架构与 UI 决策

- App 设置是手机所有，不属于当前机器人；绝不使用 `/api/settings`、HTTP、ROS、WebSocket、WHEP 或车端配置写入。
- 首页、观测、工具和设置是四个一级入口：首页是连接和当前车端健康概览的起点；设置是应用级本机偏好页，不显示机器人连接状态，也不放回工具页。
- 默认 HMI 深色继续是标准主题；日间模式是经设计的低反光浅色 Palette，而不是简单反相。切换只改变本机呈现，不改变机器人数据、协议或证据图层；高对比显示同样不能改变 PointCloud、虚拟墙、车体或告警的既有语义色。
- App 内 Logo 只从 SVG 渲染；系统 Launcher Icon 必须通过 `tool/regenerate_launcher_icons.sh` 从同一 SVG 重新导出，不能把平台 PNG 当成新的设计编辑源。Splash 当前没有品牌图形，故不为图标迁移添加或改变启动页视觉。
- 反馈由用户在 App 内主动发起，诊断摘要不得包含机器人地址、日志、节点、端口或地图数据；现场敏感资料仍应通过受控诊断流程交付。
- App 根部必须注册 Flutter 的 `GlobalMaterialLocalizations`、`GlobalCupertinoLocalizations` 和 `GlobalWidgetsLocalizations`；否则保存的 `zh_CN` Locale 会让 AppBar、RefreshIndicator 等 Material 组件启动失败。`test/app/app_localizations_test.dart` 锁定这一点。

## 2026-08-29：场景文件预览 Gallery 验收（最新）

### 当前目标

完成网页控制台现有用户能力向移动 HMI 的渐进适配；移动端明确不提供离线升级 ZIP，并让新增“场景前置配置 → 受控文件预览”能在 Debug UI Gallery 中按真实生产组件审阅。

### 已完成

- 审计网页控制台现有面向操作者的功能：测试运行/用例、报告、日志、运行配置、场景前置配置、Supervisor 状态与安全停止均已有对应移动入口；不扩展到 ROS、导航、底盘或机器人命令。
- 移动端已移除离线升级 ZIP 的页面、Repository API、Provider、Gallery 状态与文案；“控制台服务”仅保留有确认的安全停止。离线升级继续是网页/部署流程能力，不适配 iOS/Android。
- 场景受控文件在实际操作中通过既有 `GET /api/scenario-setup/file` 读取文本、大小和 SHA-256 摘要后才可选择；未新增任意路径访问能力。
- Debug Gallery 的 `scenario_setup_file_preview` 现从 Gallery 顶层打开正式 `ScenarioFilePreviewSheet`，覆盖真实生产页面而非复制 UI；修复异步页面数据完成后 BottomSheet 尚未绘制就被 Golden 截图的问题。
- 重新生成该 Golden 和 Screen Inventory / Screen Map；现有 Screenshot 状态为 73 个。

### 当前正在进行

本轮代码、Golden 和文档已保存，处于可运行断点；下一阶段仅需真实机器人/真机验证既有接口和视频，不再新增无契约功能。

### 尚未完成

1. 在可信局域网真机上验证场景文件预览、场景应用/恢复、运行配置写入、测试/日志/报告的真实权限和失败文案。
2. 本地网络权限启用后，验证六路视频逐一播放、任意三路并发、快速切流、前后台与横竖屏，并保留 Flutter/Xcode 日志。
3. 真车验证地图、Pose、PointCloud、虚拟墙、车体轮廓与地图手势；不得把 Gallery Mock 结果当作现场结果。

### 下一步第一件事

在可信局域网连接机器人后，从“工具 → 场景前置配置”进入受控目录，选择一个真实 FCRP 或 Lightning 文件，确认预览摘要、内容与选择动作都与网页控制台返回一致；记录任何失败响应。

### 当前涉及文件

- `mobile/lib/features/scenario_setup/domain/scenario_setup.dart`、`data/scenario_setup_repository.dart`：服务器验证后的场景源文件预览模型与读取接口。
- `mobile/lib/features/scenario_setup/presentation/scenario_setup_screen.dart`：正式 `ScenarioFilePreviewSheet` 和受控选择流程。
- `mobile/lib/debug_ui/gallery_manifest.dart`、`gallery_preview.dart`、`test/debug_ui/gallery_golden_test.dart`：同一状态清单、真实 Sheet 审阅入口及异步路由 Golden 时序。
- `mobile/lib/features/system_maintenance/`、`mobile/lib/features/tools/presentation/tools_screen.dart`：无离线升级的控制台安全停止入口。
- `docs/ui/`：自动生成的 73 张状态截图、Screen Inventory 与 Screen Map。

### 验证状态

- `flutter analyze`：2026-08-29 通过，无问题。
- `flutter test -r expanded --concurrency=1`：2026-08-29 通过 **119 项**。
- Gallery Golden：2026-08-29 通过 **73 项**；已视觉抽检 `tools/scenario-setup-file-preview.png`，预览 Sheet、路径、摘要、文本和选择按钮均已出现。
- `dart run tool/generate_ui_docs.dart`：2026-08-29 通过，Screen Inventory / Map 已同步。
- `git diff --check`：2026-08-29 通过；未提交 Git commit。

### 当前架构与 UI 决策

- 移动端与网页共享既有 HTTP 契约，但不是网页缩放版：高密度 HMI 保留机器人/观测/工具三级信息架构和移动触控布局。
- 离线升级 ZIP 不属于 iOS/Android App 能力；不得重新引入上传、升级状态轮询或相关 UI。安全停止仍必须显式确认。
- Debug Gallery 只能复用生产页面或生产组件，并以 Mock Provider/确定性模型驱动；异步弹层必须在 Golden 中等待真实路由绘制完成。

## 2026-08-28：网页能力移动端对齐与 RViz 清理（最新）

### 当前目标

在不改变可信局域网、只读观测与无底盘/导航控制边界的前提下，将网页控制台已有的测试、诊断、场景、运行配置、报告、日志与维护能力适配到 Flutter 的“工具”二级入口；并移除不再需要的 RViz 功能。

### 已完成

- Flutter 工具区新增运行配置、场景前置配置、用例导入导出/管理、报告与日志下载、受确认保护的报告删除与控制台安全退出入口；均复用既有 HTTP API，不新增 ROS、WebSocket、WebRTC 或控制协议。离线升级 ZIP 明确不适配到 App。
- 场景前置配置的受控文件浏览现可在选择前显示文本、文件大小与 SHA-256 摘要，和网页端 `GET /api/scenario-setup/file` 保持一致；该只读预览也已加入 Debug UI Gallery。
- 自动化测试页新增 Supervisor/运行依赖状态、停滞告警处理和只读轨迹证据入口；轨迹以既有 SVG 报告在应用内浏览，不新增 RViz。
- Debug UI Gallery 新增上述生产页面的 Mock 状态；`runtime_settings`、`scenario_setup`、维护、测试停滞告警与轨迹证据均可通过 Gallery 审阅，未复制第二套界面。
- 已从 Flutter、网页表单、网页偏好、运行模型、`RunManager` 启动路径和历史 RViz 启动实现中移除 RViz；网页残留样式选择器亦已清理。旧 `ui_preferences.open_rviz` 只在读取配置时被剔除，避免历史配置残留。
- Screen Inventory / Screen Map 已重生成，当前 Gallery Golden 覆盖 72 个状态。

### 当前正在进行

功能代码和文档已保存；正在做最终静态检查、全量 Flutter/Python/网页构建验证与 Git diff 检查。

### 尚未完成

1. 连接真实机器人后验证新增工具接口的权限、失败提示和数据契约；尤其是场景应用/恢复、受控文件预览和安全退出，必须在现场按既有确认流程执行。
2. 在 iPhone 本地网络权限启用后验证六路视频逐一播放、三路并发、快速切流、前后台与横竖屏；目前不应将模拟器/Gallery 结果等同于真机 WHEP 验证。
3. 若后端部署目录或服务进程还有旧版本 RViz 产物，应由部署升级流程替换旧二进制/网页静态资源；当前源码和 API 路径已无该功能。

### 下一步第一件事

在可信局域网的测试车上使用 Debug 构建，依次验证“工具 → 自动化测试 → Supervisor 状态/轨迹证据”和“工具 → 运行配置/场景前置配置”的真实 API 返回；记录失败状态与日志，不扩大控制边界。

### 本轮重要文件

- `mobile/lib/features/runtime_settings/`、`scenario_setup/`、`system_maintenance/`：既有工具 API 的移动端页面、模型、仓库与控制器。
- `mobile/lib/features/test_cases/`、`test_runs/`：用例生命周期/包导入导出、运行 Supervisor/停滞/轨迹证据界面。
- `mobile/lib/debug_ui/gallery_manifest.dart`、`gallery_preview.dart`：新增状态的真实页面预览清单。
- `mobile/lib/core/network/aletheia_api_client.dart`：受控下载、删除和二进制上传的通用客户端能力。
- `autodrive_console/settings.py`、`models.py`、`run_manager.py`、`web_console.py`、`autodrive_console/web/`：RViz 后端及网页入口、偏好、样式的彻底清理。

### 验证状态

- `flutter analyze`：通过。
- `flutter test -r expanded --concurrency=1`：通过 117 项。
- Gallery Golden：72 项状态通过并已更新。
- `pixi run test-offline`：通过 46 项（仅有既存 `TestCase` dataclass 的 Pytest collection warning）。
- `pixi run frontend-check`：通过网页 parity 检查与 Vite build。
- `python3 -m compileall -q autodrive_console web_console.py`：通过。

### 架构与 UI 决策

- RViz 不是测试执行、观测或移动 HMI 的能力；地图/轨迹证据统一使用既有活动地图、虚拟墙、位姿/点云与 SVG 轨迹报告。
- 工具页可承载测试、诊断、配置和维护，但高影响操作必须显式确认；不增加机器人 Operation / Command，不触达底盘、导航或 ROS 原生进程。
- Gallery 只能用 Mock Provider 驱动真实生产页面，以保证新增工具 UI 与正式界面同步。

## 当前目标

完成 Aletheia Flutter 的实时 HMI 可用性修复：保持机器人只读边界，提供单机器人连接、地图/位姿/点云/虚拟墙/真实车体轮廓、按需多流相机、自动化测试、诊断日志和只读报告。一级导航固定为“首页 / 观测 / 工具 / 设置”；首页是连接与健康概览的 HMI 起点。竖屏为默认入口，横屏按实际可用空间自适应，不锁定方向。本轮重点是释放横屏地图/视频工作区、修复以双指中心为锚点的地图手势、统一地图工作画布与排查 iOS 视频切流生命周期。

## 已完成

- 完成首页、观测、工具、设置四级导航和 HMI 产品语义；首页承载连接与健康概览，测试、用例、日志、报告均保留为工具的二级能力。
- 地图读取既有活动地图 PNG、metadata 和 `virtual_walls`，沿用 `world` / `image_relative` 坐标语义。
- 地图图层固定为底图 → 虚拟墙 → 未来真实轨迹 → 点云 → 真实车体轮廓。实时轨迹没有移动端契约，未虚构实现。
- 车体轮廓读取既有 `/api/settings` active vehicle model 的 `length_m` / `width_m`，按地图世界尺寸和当前缩放投影；设置不可用时仅回退为 PC Web 同样的 `1.00m × 0.68m`。
- PointCloud 保持单槽 latest-wins、100ms 过期丢帧，Painter 改为 `drawRawPoints` 直接消费 packed `Float32List`，移除每帧 `List<Offset>` 分配。
- Pose 改为单槽 latest-wins、250ms 过期丢帧；Pose 与 Cloud 仍是独立的二进制 WebSocket lane。
- 相机读取 `/api/video/status` 返回的全部 1-6 路已配置流，提供主画面选择器；默认前向流，未配置时才回退第一路。
- 宽横屏相机工作区最多同时显示三路 receive-only WHEP/WebRTC 真实画面：主画面加两路辅助画面；竖屏仍只保留主画面。进程内全局上限为三路，第四路等待已有 renderer/session 释放；切换、离开相机工作区或应用后台都会释放相应 WHEP session、PeerConnection 和 renderer。
- 地图/视频工作区按可用高度伸展；横屏收起非关键说明，地图使用紧凑覆盖层并提供全屏入口，连接状态与位姿内置于右下角；相机以左侧逐流开关、主画面和两路辅助真实流组织。竖屏保持单列、底部导航和可滚动访问路径。
- Debug UI Gallery 的正常地图状态包含虚拟墙，正常相机状态包含六路流；修复从地图预览切换到相机预览时复用错误 workspace State 的问题。
- 修复 Debug UI Gallery 跨状态切换仍沿用首次 Mock Provider 的问题：ProviderScope 以 Gallery screen id 重建，观测/视频等“已连接”状态现在真正驱动生产页面，而不会落回“先连接机器人”拦截页。
- 更新 `PROJECT_OVERVIEW.md`、`docs/DESIGN_SYSTEM.md`、`docs/UI_SPEC.md` 与 `mobile/README.md`，反映真实 HMI 契约、三路有界解码策略、图层和颜色语义。
- 更新 60 项 Gallery Golden、Screen Inventory 和 Screen Map；新增虚拟墙/车型解析测试与 iPhone 17 844×390 横屏地图/六路相机布局回归。
- 采用正式 Aletheia 深色白蓝标志作为应用图标。源图保存为 `mobile/assets/branding/app_icon.png`，由 `flutter_launcher_icons` 生成 iOS AppIcon catalog 和 Android launcher icon；不作为运行时图片资源打包。
- 修正短横屏全局布局：App Shell 在视口高度低于 600pt 时将顶栏从 64pt 压缩为 48pt，并使用 64pt 的自定义图标仪表导航条。每项保持 48pt 触控目标、Tooltip 和语义标签；动态岛位于首侧时只预留必要安全区，位于尾侧时分隔线紧贴导航条。这个改动只释放工作区，不改变“首页 / 观测 / 工具 / 设置”信息架构。
- 修复 Debug UI Gallery 在手机横屏把固定竖屏预览缩成中央小卡片的问题：短横屏直接以当前设备尺寸渲染真实生产页面，状态选择收为右下角 48pt 的仅调试入口；平板/桌面仍保留带状态列表的审阅布局。
- 修复现场 UI Review 发现的比例与遮挡问题：未连接观测状态改为最大 320pt、内容自适应高度的提示卡；短横屏使用不额外吞占安全区的 64pt 图标仪表导航条；地图的位姿/点云读数移到地图画布下方；机器人地址只保留输入框内的常用地址示例，不再显示 IPv6 链路本地技术提示。
- 应用内顶栏统一使用 `assets/branding/app_icon.png` 的正式 Aletheia 标志，不再以通用雷达图标充当品牌图形。
- Debug UI Gallery / Screen Inventory 新增“观测 · 需要连接机器人”这一既有状态，并以真实观测页和 Mock 连接状态生成 `docs/ui/screens/observe/disconnected.png`；不再让该实际入口游离于审阅清单之外。
- 修复 iPhone 横屏旋转后 Gallery 仍按旧竖屏 `MediaQuery` 判定、再次显示缩小预览的问题：改由根 `LayoutBuilder` 的实际约束判断紧凑横屏。已用“竖屏 MediaQuery + 横屏约束”的回归测试锁定这一旋转瞬态，并在 iPhone 17 Simulator 热重启后人工确认横屏为整屏真实页面。
- 调整短横屏仪表导航的视觉层级：导航条与主画布共用 `canvas`，只以低对比分隔线组织空间；选中入口改为中性 `surfaceRaised`，仍以青绿色图标表达当前位置。避免为结构制造一整块突兀的深色背景。
- 短横屏 HMI Chrome 进一步压缩为 44pt 顶栏与 56pt 图标导航带，去掉工作区外的观测模式切换器；地图和视频各在自身轻量工具栏提供相互切换入口，短横屏可用工作区由 312pt 增至 378pt（844×390 测试尺寸）。根 AppBar 去掉无意义的 leading 占位，品牌更靠近左侧，连接状态更靠近右侧。
- 机器人与观测两个 HMI 主工作区统一展示正式 Logo 与 Aletheia 名称；观测页使用透出地图的半透明状态顶栏；工具和二级业务页面不重复品牌，保留本页任务标题、必要返回路径和连接状态。
- 地图横向标题栏已收敛为左侧窄工具条；视频主画面居中，左侧为逐路开关和地图/刷新动作，右侧为两路辅助真实流，避免顶部连接状态覆盖操作目标。
- 地图从 `InteractiveViewer` 改为直接手势变换：双指缩放以实时双指中心锁定同一世界坐标，单指平移与 pinch 同时使用一套 translate/scale；添加地图边界约束，防止无限拖离。
- 地图、米制自适应格栅、虚拟墙、点云与机器人车体放到同一个 World Transform；地图外改用统一深色 Workspace Canvas 和低对比格栅，不再露出纯黑背景。
- 为 WHEP 视频增加进程内、最多三路的解码器租约及每路串行 renderer/session 生命周期：第四路等待释放；同一流的旧 session 先解除 `RTCVideoRenderer` 绑定并关闭旧 Peer，再交接新 session；异步回调以会话归属和 generation 过滤。原先被静默吞掉的 close/delete/协商错误现在会输出 Flutter 错误与 stack，便于保留真实 iOS crash 证据。
- 重新生成 61 张 Gallery Golden 基线并生成 Screen Map/Inventory；全量 Flutter 测试现为 99 项通过。
- 修复手机竖屏 Gallery 仍嵌套“审阅页中的预览”的问题：所有手机尺寸现在整屏渲染实际生产页面，只有 Debug 方格按钮用于切换 Mock 状态；平板/桌面保留 Screen Inventory 审阅布局。
- 修复 Gallery 横屏回竖屏后 Debug 方格入口会与正式底部导航重叠的问题：竖屏按钮固定在导航之上，横屏仍在右下角；回归测试覆盖真实的横转竖约束变化。
- Debug Gallery 观测状态现加载用户提供的真实地图 Fixture：`map.pgm` 无损转换为原始 3480×10017 像素 PNG，不做下采样；`map.yaml` 保留 0.05m/px、`(-111.57,-248.79)` 的原始世界元数据，`map_walls.yaml` 解析为 453 段 `image_relative` 虚拟墙。地图底图、米制格栅和红色墙段通过生产 `_MapViewport` 同一坐标变换渲染，不连接机器人；若实测存在卡顿，必须先采集性能证据再讨论优化。
- 修复全分辨率纵向地图在横屏被 contain 成窄条、初始 scale 无可拖拽溢出和旋转后沿用旧像素偏移的问题：地图现在落在有限的 World Workspace Canvas 内，单指移动整张工作画布而不是直接受图片边界约束；画布弱格栅、地图、米制格栅、虚拟墙、点云和车体共用 transform。初始视图保持比例的 cover，画布为地图四周提供可操作边距；双指仍以中心锚定，旋转时以当前世界位置重新投影。横屏地图不再拉伸、被推至一侧或在单轴锁死。
- 修复地图垂直拖动同时触发外层页面滚动：地图手势面以 eager recognizer 先取得 pointer sequence，再用同一组原始触点坐标进行单指画布平移与双指 pinch + pan。单指、双指和外层 `ListView` 不再争夺手势；双指每帧以真实两指中心和跨度计算，仍锁定该中心下的同一世界点。
- 米制格栅补齐可读尺度：格距继续按真实 `pixelsPerMeter` 自适应，地图左下角增加紧凑的“x m / 格”标尺与等于一格屏幕投影的横线。虚拟墙改为反缩放的 1.15 logical-pixel 细线，缩放时不会膨胀成粗红带。

## 当前正在进行

代码、截图和文档已保存，当前处于可运行的完整断点。iPhone 真机已无线安装并启动 Debug 构建，但 Flutter VM Service 因尚未在设备上授权 Aletheia「本地网络」权限而未能附加；因此真实三路并发 WHEP、六路逐一检查和快速切流仍待保留原生日志后的现场验证。

## 尚未完成

1. 在 iPhone 的“设置 → Aletheia → 本地网络”允许后重新附加 Debug；对真实 `/api/video/status` 的全部六路逐一播放，并验证“主画面 + 两路辅助画面”的三路并发、快速连续切换、前后台和方向切换，保存 Flutter/Xcode 日志。当前无 native crash trace，不能宣称实机 P0 已完全关闭。
2. 连接真实机器人验证地图、Pose、PointCloud、虚拟墙、真实车体轮廓、以双指中心锚定的缩放/平移、地图边界和地图切换是否与 PC Web 对齐。
3. 在真实 iPhone 与 Android 设备收集 Flutter DevTools / 车端 `client_metrics` 性能证据：UI/Raster frame time、jank、内存、Cloud 接收与绘制、Pose 接收与绘制。没有真实指标前不得声称性能达标。
4. 若横屏仍崩溃，先保存完整 Flutter/native stack trace、设备型号、系统版本、触发顺序与视频状态，再按证据修复；不能用宽泛 `catch` 隐藏崩溃。
5. 后续仅在有明确只读 API 时加入测试历史/详情。未授权前不加入多机器人、操作/控制、导航任务、运行配置写入或报告删除。

## 下一步第一件事

在 iPhone 设置中允许 Aletheia 使用“本地网络”，用 `env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy flutter attach -d 00008110-001154A90AC3401E` 附加并保存日志；然后连接可信局域网机器人，验证六路 WHEP 的逐一播放、任意三路并发和快速切流。

## 当前涉及文件

- `PROJECT_OVERVIEW.md`：最高事实基线，补充移动端 HMI 的多流、图层和三路 decoder 上限。
- `mobile/lib/app/responsive_layout.dart`：按实际视口高度计算主工作区尺寸。
- `mobile/lib/app/app_shell.dart`：短横屏的 44pt 紧凑顶栏、56pt 图标仪表导航条、动态岛首侧安全区处理和导航可访问性提示。
- `mobile/lib/app/branding/aletheia_brand_mark.dart`：应用内共享品牌标志，和 iOS/Android 启动图标使用同一源图。
- `mobile/lib/app/theme/aletheia_theme.dart`：点云、虚拟墙、车体轮廓的数据可视化语义色。
- `mobile/lib/features/live_observation/domain/live_map.dart`：虚拟墙和车型尺寸领域模型。
- `mobile/lib/features/live_observation/data/live_observation_repository.dart`：活动地图、虚拟墙和 active vehicle model 读取。
- `mobile/lib/features/live_observation/data/pose_telemetry_client.dart`：Pose single-slot latest-wins 与接收计数。
- `mobile/lib/features/live_observation/domain/video_status.dart`：按名称查找已配置视频流。
- `mobile/lib/features/live_observation/application/video_status_controller.dart`：主视频流选择与逐路已配置流启停。
- `mobile/lib/features/live_observation/presentation/live_observation_screen.dart`：自适应地图/视频工作区、地图全屏、同变换米制格栅、双指中心锚定手势、地图边界、真实车体、地图右下角连接/位姿读数、三路相机布局和低分配点云绘制。
- `mobile/lib/features/live_observation/data/whep_playback_coordinator.dart`：跨 WHEP widget 的有界（最多三路）renderer/decoder 租约。
- `mobile/lib/features/live_observation/data/whep_session.dart`、`mobile/lib/features/live_observation/presentation/whep_video_view.dart`：有归属保护、可诊断错误日志的 WHEP/RTC 生命周期。
- `mobile/lib/features/robot_connection/presentation/robot_connection_screen.dart`：面向操作者的连接页文案与共享品牌标志。
- `mobile/lib/debug_ui/gallery_manifest.dart`、`gallery_preview.dart`：Gallery / Inventory / Screen Map / Golden 的单一状态来源和多流 Mock。
- `mobile/lib/debug_ui/debug_map_fixture.dart`、`mobile/assets/debug_ui/`：真实 PGM 地图的轻量预览、原始 YAML 元数据/虚拟墙及仅 Debug 的本地 Fixture 解析。
- `mobile/test/features/live_observation/connection_required_layout_test.dart`：锁定观测连接门槛提示的最大宽度与内容自适应高度；`landscape_observation_layout_test.dart` 同时锁定遥测读数在地图画布外。
- `mobile/lib/debug_ui/debug_ui_gallery_screen.dart`：Gallery 的平板/桌面审阅布局；以实际 `LayoutBuilder` 约束识别全部手机尺寸，整屏渲染真实页面并提供右下角调试状态切换入口。
- `mobile/test/debug_ui/debug_ui_gallery_screen_test.dart`：锁定手机竖横屏均为整屏预览，并覆盖 iOS 旋转期间 `MediaQuery` 尚未同步而约束已横向变化的情形。
- `mobile/test/debug_ui/debug_map_fixture_test.dart`：锁定样例地图尺寸、世界元数据、解码预览尺寸与 453 段墙体。
- `mobile/pubspec.yaml`、`mobile/pubspec.lock`、`mobile/assets/branding/app_icon.png`：应用图标生成配置、固定生成器版本和受版本控制的原始图标。
- `mobile/ios/Runner/Assets.xcassets/AppIcon.appiconset/`、`mobile/android/app/src/main/res/mipmap-*/ic_launcher.png`：由图标生成器输出的平台资源。
- `mobile/test/features/live_observation/`、`mobile/integration_test/portrait_user_journey_test.dart`：地图/视频契约、横屏布局和 iOS 全路径回归。
- `mobile/test/app/app_shell_layout_test.dart`、`mobile/test/features/live_observation/landscape_observation_layout_test.dart`、`mobile/test/features/live_observation/data/whep_playback_coordinator_test.dart`：844×390 的 44pt/56pt Chrome、双指中心地图变换、同变换格栅和 WHEP 交接回归。
- `docs/DESIGN_SYSTEM.md`、`docs/UI_SPEC.md`、`mobile/README.md`、`docs/ui/`：规范、使用说明和自动生成截图。

## 当前架构决策

- `PROJECT_OVERVIEW.md` 是最高事实基线。Flutter 只能使用既有 HTTP、Binary WebSocket 与 WHEP 契约，不能接触 ROS、底盘、导航、物理相机或车端进程树。
- Observation / Monitoring 是只读域。未来 Robot Operation / Command 必须另建领域、路由、状态管理、后端命令契约、权限、确认和审计路径。
- `/pose`、`/cloud`、WHEP 保持独立。高频路径保持容量 1、latest-wins、过期丢弃，绝不追赶历史帧。
- 相机可识别 1-6 路流。宽横屏最多解码主画面与两路辅助真实流，进程内总上限严格为三路；竖屏和紧凑布局只解码主画面。禁止创建第四路或后台隐藏 WHEP peer。
- 每一个 WHEP renderer 的销毁、解绑和新 renderer/session 的建立必须在其自身会话序列中串行；全局租约在旧 session 释放后才可授予等待中的第四路。旧 session 的异步回调不能触碰新 session 的 renderer 或页面状态。
- 地图世界坐标只允许一套变换。地图、格栅、虚拟墙、点云和车体必须在同一 transform 下绘制；手势的缩放锚点是实时双指中心，非画布中心。
- 车体尺寸只能来自 active vehicle model；虚拟墙只能来自既有 map layers；实时轨迹只能在真实只读数据契约存在后接入。
- Router 保持普通 `ShellRoute`，离开观测页时应释放实时资源，不变成常驻后台的 indexed tab stack。
- Debug Gallery 只通过 Mock Provider 驱动真实生产页面；不接入真实机器人、ROS2、HTTP、WebSocket 或 WebRTC，也不维护第二套 UI。

## 当前 UI 决策

- 深石墨、professional / industrial / precise / restrained 的单主题保持不变。HMI 的功能可靠性、数据可见性与实时性优先于纯视觉效果。
- 地图和主相机画面优先占据工作区。刷新、状态与选择信息只能用覆盖层或横屏侧栏，不能持续挤占主要视觉证据区域。
- 点云为高对比青蓝，虚拟墙为受限红色，真实车体为暖色深描边；文字和图标仍同时表达状态，颜色不是唯一信息来源。
- 默认竖屏单列和底部导航；横屏仅根据空间显示侧边导航/侧栏，不创建另一套信息架构。
- Flutter 的后续设计审阅同时以网页移动端为参考：检查 `frontend/src/liveObservation.css` 的观测专用移动工作区，以及 `autodrive_console/web/mobile_console.css` 的 `/m/` 通用壳。复用其空间取舍、Safe Area、地图/相机优先级和状态层级，不复制 Web CSS、旧配色或六路无上限策略；Flutter 宽横屏严格保持最多三路 WHEP/WebRTC decoder。
- 视口高度低于 600pt 的横屏使用 44pt 顶栏和 56pt 无文字仪表导航条；每项保留 44pt 触控目标，导航标签保留为 Tooltip / Semantics，确保工作区优先而不牺牲可访问性。较高横屏、平板和竖屏维持完整标签。
- 短横屏导航条只在动态岛位于首侧时加入所需安全区，尾侧则让分隔线紧贴 56pt 导航条。这避免系统默认 Rail 形成空白宽栏，同时不让系统硬件区域遮住实际触控目标。
- 短横屏导航条不是下沉黑色侧栏，而是与 HMI 画布连续的结构带；只有选中入口使用中性抬升表面，信号色仅用于其图标和真实状态。
- 地图内只悬浮“活动地图 / 相机 / 全屏 / 刷新”这一轻量工具栏；连接状态与位姿采用右下角低对比轻量读数，不能遮挡地图证据。左下角比例尺是空间参考而非装饰，维持小尺寸并避开主证据区域。空状态卡只使用内容所需高度，不能被未约束的 Column 拉伸。
- 地图外是同一色系的 Workspace Canvas，而不是纯黑空洞；弱米制格栅延续到画布，且地图只能在有限边界内平移。
- App 内品牌图形必须复用正式 Aletheia App Icon 源图，不能回退为通用 Material 图标。
- Debug Gallery 在所有手机尺寸均不嵌套“手机里的手机”：被选中的生产页面直接使用完整设备空间；右下角 48pt 状态切换按钮只用于 Debug，点击后打开原有 Mock 状态列表。
- Gallery 是否使用手机整屏预览只按实际约束的短边（< 600pt）判断，绝不以横屏长边阈值判断。这样横向超过 900pt 的大屏 Android 手机和旋转中的 iPhone 都持续保留右下角 Debug 方格，不会误落入桌面审阅布局。
- Gallery 的方向判断以实际布局约束为准，不能只读取可能在 iOS 旋转过渡期滞后的 `MediaQuery` 尺寸；这保证横屏始终展示可审阅的真实页面，而不是经 `FittedBox` 缩放的预览卡片。
- 不把 HTTP、ROS、WHEP、端口、文件路径、协议或“不会控制什么”等开发者说明放入常规用户界面。

## 当前问题

- 当前没有真实机器人、全套六路流或真实横屏 WHEP crash trace，不能将 Widget/模拟器验证等同于现场验证。
- 横屏截图揭示的空间浪费、画布纯黑边界和地图覆盖层遮挡已通过自适应布局修复；尚无 native crash stack，当前只能确认旧代码存在 renderer/session 异步竞态，不能臆断唯一原生崩溃根因。
- iPhone 真机无线 Debug 启动后等待本地网络权限，尚未拿到 Dart VM 服务；必须在设备允许权限后再收集切流日志。
- 历史 RViz 开关已从 Flutter、网页表单、UI 偏好、运行模型和后端启动逻辑移除；旧 `ui_preferences.open_rviz` 会在读取配置时自动丢弃。地图轨迹证据仍固定开启，不受该清理影响。
- Android `flutter_webrtc` 仍给出 Built-in Kotlin 的未来兼容性警告。当前 Debug 构建成功，未进行高风险依赖替换。
- Flutter test 需要临时移除 HTTP(S)/ALL 代理环境变量，否则代理会拦截 test runner 的 localhost 服务。不要修改系统代理。
- iPhone Simulator Debug 的 Dart VM WebSocket 同样会被本机代理拦截。以 `env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy flutter run ...` 或同样形式的 `flutter attach --debug-url ...` 启动/附加；不要更改系统代理。

## 验证状态

- `flutter analyze`：2026-08-27 在本轮实时 HMI、地图手势/格栅和 WHEP 生命周期修复后通过，无问题。
- 短横屏 Chrome：2026-08-27 `flutter analyze` 通过；`test/app/app_shell_layout_test.dart` 和既有 `responsive_layout_test.dart`、`landscape_observation_layout_test.dart` 均通过，锁定 844×390 下的 48pt 顶栏、64pt 仪表导航条、动态岛首侧安全区和主要观测工作区可用性。
- Debug Gallery 状态切换：2026-08-27 `debug_ui_gallery_screen_test.dart` 与横屏观测回归通过；已在 iPhone 17 Simulator Debug 会话中确认 `observe_live` 展示 Mock 活动地图、位姿、点云和已连接状态，并确认 `observe_loading` 在短横屏整屏显示、右下角状态按钮可打开选择器。
- UI 比例与遮挡：2026-08-27 `flutter analyze` 通过；连接空状态、地图读数不覆盖画布、短横屏导航轨和 Gallery 相关 6 项 Widget 回归通过。iPhone 17 Simulator Debug 已人工检查更新后的品牌标志、精简的机器人地址说明，以及无遮挡的 Mock 活动地图。
- Gallery 横屏旋转：2026-08-27 `debug_ui_gallery_screen_test.dart` 与 `landscape_observation_layout_test.dart` 共 5 项相关 Widget 测试通过；iPhone 17 Simulator Debug 已热重启并人工确认 `observe_loading` 横屏直接呈现生产观测页（无“界面检查”标题、无嵌套设备卡），右下角保留 48pt 调试状态入口。
- 地图 Debug Fixture 与旋转手势：2026-08-27 已以原始 3480×10017 PNG 解码并渲染，不做下采样；`landscape_observation_layout_test.dart` 锁定纵向地图在横屏使用保持比例的 cover、有限工作画布内的横纵单指拖拽以及双指中心锚定。方向切换把旧视窗中心的世界位置投影到新画布，避免复用旧像素偏移造成地图被推到一侧或视觉拉伸。
- 地图手势与标尺：2026-08-28 `flutter analyze`、`landscape_observation_layout_test.dart`（3 项）和 61 项 Gallery Golden 均通过。回归明确断言：地图单指拖动改变世界画布、外层 `Scrollable` 偏移不变，双指缩放后两指中心锚定保持；截图已重生成并显示“x m / 格”米制参考与细虚拟墙。
- Debug 方格持久性：2026-08-28 `debug_ui_gallery_screen_test.dart`（5 项）通过，覆盖普通手机、844×390 横屏、960×432 宽横屏及横竖屏旋转；所有手机尺寸均应保留状态选择方格。
- 全量 `flutter test -r expanded --concurrency=1`：2026-08-27 临时移除代理后通过 **101 项**，包括 61 项重新生成的 Gallery Golden、原始地图 Fixture、单指/双指地图手势、同变换格栅、短横屏布局和 WHEP 交接单元测试；`flutter analyze`、`git diff --check` 同次通过。
- 应用图标：2026-08-27 已通过 `flutter analyze` 与 Android Debug APK 构建；iOS Simulator 构建已生成 `Runner.app`，并抽检 iOS 1024×1024 资源为无透明 PNG。
- `dart test`：2026-08-27 通过 10 项相关响应式、视频、地图/虚拟墙和车型解析测试。
- `flutter test -r expanded --concurrency=1`：2026-08-27 临时移除代理后通过 90 项，包括 60 项 Gallery Golden、横屏地图/六路视频布局回归和全部既有测试。
- iOS Simulator：`flutter test integration_test/portrait_user_journey_test.dart -d <Booted iPhone 17>` 于 2026-08-27 通过。默认竖屏逐页覆盖连接、地图、六路相机选择器的等待状态、测试、用例、日志和报告。横屏由同尺寸 844×390 Widget 回归验证，未连接真实 WHEP 流。
- iOS 真机安装包：2026-08-27 15:28 已成功生成 Release `Runner.xcarchive`（193.0MB，Bundle ID `com.ryaletheia.aletheiaMobile`、版本 `1.0.0 (1)`），并于 15:30 使用 Apple Development 证书导出当前的 **Release Development IPA**：`mobile/build/ios/ipa-development/aletheia_mobile.ipa`（14MB，SHA-256 `f2a8732d7d4ac87816d7115ca059f089519f4d72cda3f422cf331a2612d306b7`）。包内已核验 `embedded.mobileprovision` 与签名资源。默认 `flutter build ipa --release` 的 App Store 导出仍因缺少 `iOS Distribution` 证书、团队没有创建 App Store Profile 权限而失败；Development IPA 可从主屏启动，但仅用于开发团队中已注册的设备，不可用于 App Store 或任意分发。
- Android：`flutter build apk --release --target-platform android-arm64` 于 2026-08-27 15:28 通过，产物为 `mobile/build/app/outputs/flutter-apk/app-release.apk`（53MB，Dart AOT 为 `arm64-v8a`，SHA-256 `5a74bb20cf92c1e16571f17d93cfdbbdd5dec434df2b8877379d2517c6e59016`）。APK 仍包含部分插件的其他 native slice，但 Flutter 应用本体要求 arm64 Android 设备。`apksigner` 已核验 v2 签名有效，但当前签名者为默认 Android Debug 证书，因此该 Release 编译包适于开发安装，不能作为正式商店/生产分发包。首次构建所有 ABI 时 Dart AOT snapshot 被系统以 `-9` 终止，因此当前 Release 包选择现代 Android 设备通用的 arm64；未更改产品代码或 Android 签名配置。此前 Debug APK 仍为 `mobile/build/app/outputs/flutter-apk/app-debug.apk`，且已在 Android 14 的 PERM10 真机前台启动。

## PROJECT_OVERVIEW.md 约束

- HTTP 控制台固定 `:8087`；Pose/Cloud 使用独立 Binary WebSocket；视频使用独立 WHEP/WebRTC。
- 地图是低频缓存资产；Pose/Cloud 是高频 overlay。禁止因高频数据重绘地图或积压历史数据。
- 视频帧不能进入 Python、HTTP、遥测 WebSocket 或 Canvas 2D；移动端仅以原生 WebRTC 接收最多三路真实画面，不能扩展成六路无上限解码。
- 不修改既有机器人导航、定位、地图、ROS topic、安全控制、任务、报告、缓存、设置或用户已有 `pixi.toml` 改动。
- 日志和报告遵守车端白名单。客户端不得扫描、写入、删除或猜测车端文件路径。

## Skills

- `apple-design`：本轮完整读取，用于默认竖屏入口、方向不锁定、实际空间自适应、触控选择器、状态反馈和直接工作区操作。
- `design-taste-frontend`：本轮完整读取。其明确 native mobile / dense product UI 不属于主适用范围，因此只采用审计、信息层级、文案一致性和反装饰化原则，不用它决定 HMI 业务架构或原生组件风格。

## 2026-09-02：Monorepo 第一阶段整理

- 实际模块位置保持不变：robot backend 为 `web_console.py`、`autodrive_console/`、`live_preprocessor/`；Web 为 `frontend/`；Flutter 为 `mobile/`；Unity 为暂停 PoC。
- `shared/contracts/` 是跨端接口事实来源；接口变化必须更新契约并检查 backend/Web/Mobile 消费端。
- 根 Pixi 管理 backend/Web 工具链；新增 `backend-test`、`web-check`、`backend-run` alias，旧命令不变。
- `mobile/.fvmrc` 固定 Flutter 3.47.1；Mobile 文档和 scripts 统一使用 FVM。当前机器未安装 FVM，且 JDK 26 不符合 Android 的 JDK 17 基线，doctor 会 WARN，不会阻断非 Mobile 开发。
- `scripts/` 提供 bootstrap、doctor、按模块测试及 Flutter-only mobile 构建；`.github/workflows/module-checks.yml` 按路径运行基础检查。
- 物理迁移到 `apps/` 是第二阶段，前置条件位于 `docs/architecture/monorepo-migration.md`；未经单独计划不得移动源码。

## Resume Prompt

继续开发前，先读取 `PROJECT_OVERVIEW.md`、`AGENTS.md`（如存在）、本文件、`docs/DESIGN_SYSTEM.md`、`docs/UI_SPEC.md`、当前 Git diff 和相关 Skill。先确认现有代码状态，不重新分析或推翻已完成的三级导航、只读边界、多流选择、虚拟墙/真实车体、统一世界变换、三路有界 decoder 租约和 latest-wins 决策。执行 Flutter 测试时，只对命令临时移除 HTTP(S)/ALL 代理环境变量。第一步是在 iPhone 设置中允许 Aletheia 使用本地网络后附加 Debug 并保存日志；再连接可信机器人，逐一验证六路 WHEP、任意三路真实并发、快速切流、前后台、竖横屏、双指中心地图缩放、边界及地图/虚拟墙/车体对齐。若有异常或崩溃，先保存完整 Flutter/native trace 再修复。不得新增虚假控制能力、实时轨迹、第四路或未确认业务 API；未来 Command 必须保持独立权限与命令边界。
