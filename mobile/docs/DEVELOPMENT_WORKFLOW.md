# Aletheia Mobile 开发、调试与验证工作流

本文命令均在 `mobile/` 目录执行。车端服务使用可信局域网的既有 HTTP/WS/WHEP 接口；不要把调试便利性当作放宽生产安全边界的理由。

开发者先阅读 [`../../docs/development/PROFILES.md`](../../docs/development/PROFILES.md) 选择
`mobile-android` 或 `mobile-ios`。Windows/Linux 可以完整开发、分析、测试 Flutter 公共 Dart
代码并构建 Android；iOS 原生编译、Simulator 和签名验证只在 macOS 执行。

## 1. 环境检查

```sh
cd /Users/bob/Desktop/code/ry-aletheia/mobile
dart pub global activate fvm 4.3.0
fvm install
fvm flutter --version
fvm flutter devices
fvm flutter pub get
```

当前 macOS 开发环境如存在系统代理，Flutter / Xcode 的依赖解析可能被代理污染。需临时清除代理时，在命令前使用：

```sh
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
    -u http_proxy -u https_proxy -u all_proxy \
    fvm flutter <command>
```

统一脚本会自动将 `127.0.0.1`、`localhost` 与 `::1` 加入 `NO_PROXY`，确保 Flutter tester 与本地编译服务直连；手动执行 `fvm flutter test` 时若出现本地 `127.0.0.1` 连接提前关闭，也应使用相同的 `NO_PROXY` 设置或上面的临时清除代理命令。

不要把账号、私有 token 或局域网机器人地址写入源码、截图或提交记录。

## 2. 常用运行方式

### 常规 App

```sh
fvm flutter run -d <device-id>
```

设备 ID 从 `flutter devices` 取得。iOS Simulator 示例：

```sh
fvm flutter run --debug -d B77BE4F1-BC75-4837-A759-309D06AA9D20
```

### Debug UI Gallery

Gallery 仅在 Debug build 注册；它不需要机器人也不请求真实 HTTP、WebSocket、ROS 或 WebRTC。

```sh
fvm flutter run --debug -d <device-id> \
  --route '/__debug/ui-gallery'
```

直接打开具体状态（screen key 以 `lib/debug_ui/gallery_manifest.dart` 为准）：

```sh
fvm flutter run --debug -d <device-id> \
  --route '/__debug/ui-gallery?screen=observe_live'
```

在运行中的 `flutter run` 终端：`r` 是 hot reload，`R` 是 hot restart，`q` 退出调试会话。旋转设备后 Gallery 网格或 query 状态显示异常时优先按 `R`；如果仍然存在，停止后带完整 `--route` 重新启动，检查 `gallery_manifest.dart` 的状态恢复逻辑。不要试图在 Release/Profile 中添加 Gallery 后门。

## 3. 代码与测试

### 快速反馈

```sh
dart format lib/path/to/changed_file.dart test/path/to/test.dart
fvm flutter test test/path/to/test.dart -r compact
fvm flutter analyze
```

### 合并前完整 Dart 验证

```sh
fvm flutter test --concurrency=1 -r compact
fvm flutter analyze
git diff --check
git status --short
```

全量测试数量会随着真实测试增加而变化；验收以命令成功退出及失败项说明为准，而不是文档中的固定数量。`--concurrency=1` 用于让 Golden 和依赖共享资源的测试在本机可重复。

### Gallery Golden 与 UI 文档

```sh
fvm flutter test test/debug_ui -r compact
dart run tool/generate_ui_docs.dart
```

当特意接受新的视觉基线时，按项目已有 Golden 测试说明更新 Golden；不要无审查地批量接受截图。Gallery manifest 改动后必须生成 `../../docs/ui/SCREEN_INVENTORY.md` 和 `../../docs/ui/SCREEN_MAP.md`，并检查它们只包含真实页面/状态。

CI 中的普通 Dart/Widget 测试运行在 Linux，并通过 `--exclude-tags golden` 排除依赖 macOS 中文系统字体的截图套件；`mobile-golden` 则在 macOS 上单独运行 `gallery_golden_test.dart`。不要删除 `golden` 标签，也不要将该测试重新并入 Linux Job。

## 4. 构建 Android 与 iOS

### Android

```sh
fvm flutter build apk --debug
```

输出通常为：

```text
build/app/outputs/flutter-apk/app-debug.apk
```

真实 Android 设备还应检查：局域网 HTTP 是否可访问、横竖屏、返回/手势导航、地图单指平移及双指 pinch、视频选流与后台恢复。

### iOS Simulator

```sh
fvm flutter build ios --simulator --debug --no-codesign
```

输出通常为：

```text
build/ios/iphonesimulator/Runner.app
```

### iOS 实机

首次实机需要有效的 Xcode signing team、Developer Mode 和设备信任。推荐先在 Xcode 打开 `ios/Runner.xcworkspace`，确认 Signing & Capabilities 后再使用 Flutter 安装：

```sh
fvm flutter run --debug -d <physical-ios-device-id>
```

如出现 Swift Package Manager 失败，不要误判为 Flutter/Dart 页面问题。先检查完整 `xcodebuild` 日志、网络/DNS/代理、Xcode 的 Package Dependencies 与本地缓存，再重试。依赖正在显示 “Fetching from … (cached)” 时是 Xcode 在解析 iOS 原生插件依赖，不是 App 已卡死。

## 5. Debug Gallery 与真实 App 的区别

| 项目 | Gallery | 常规 App / 真机 |
| --- | --- | --- |
| 数据 | Mock repository/service/state | 真实机器人 endpoint |
| 状态覆盖 | 可强制 loading、empty、error、offline、任务与节点状态 | 由车端和用户动作触发 |
| 地图/视频 | 预览或 mock；不能证明实时协议 | 验证 HTTP、WS、WHEP、原生 renderer |
| 用途 | UI Review、Golden、回归检查 | 功能、性能、网络、权限、崩溃验证 |

Gallery 预览比例等于实际运行 Page 所在的当前设备和方向；它不是一个缩放后的“手机截图”。审查时应在目标 Simulator/真机切换 portrait/landscape，并通过 Gallery 内状态选择控件进入每个 state。

## 6. 新页面 / 新状态的标准接入

```text
确认 PROJECT_OVERVIEW 的能力边界
  → Repository（传输/解析）
  → Controller（状态/生命周期）
  → Production Page（真实 loading/empty/error）
  → Router 或既有二级入口
  → Gallery manifest mock entry
  → 定向 test / Golden
  → 生成 UI Inventory / Screen Map
  → 设备尺寸与横竖屏人工检查
```

如果一个状态无法通过真实业务方便触发，也必须能通过 production 组件的 mock provider/repository 在 Gallery 触发；不允许复制另一份静态 UI。

## 7. 真机与实时能力检查

### 地图工作区

- 已连接、地图 loading、地图为空、地图正常、数据断流和错误状态均可确认。
- 单指只平移地图 canvas，不滚动父页面。
- 两指以 pinch 中心缩放；同时 pinch + pan 不跳动、不漂移。
- 基础地图、米制 grid、虚拟墙、点云、Pose/车体在同一坐标变换下对齐。
- 地图外区域是主题一致的 workspace，而非纯黑；不能无限把内容拖走。
- 旋转设备后不拉伸 map image，overlay 与比例尺仍一致。

### 视频工作区

- 从 `/api/video/status` 检查已配置流，并只使用车端允许的控制入口。
- 竖屏验证主画面；横屏验证主画面加最多两路辅助真实流。
- 验证画面分隔线、选流控件可点击、叠层不遮挡标题/状态/按钮。
- 逐一选择现有六路流，并快速连续切换；观察 Flutter、Xcode 和 WebRTC 日志。
- 离开视频页、切到地图、切后台/前台后确认 renderer、PeerConnection、MediaStream 与 WHEP session 被正确释放并可恢复。

iOS 视频闪退属于 P0：需要原生日志、可复现步骤、所选流、生命周期时序和修复后六路/快速切流的真实验证记录。不能以“未崩”替代日志检查。

## 8. Launcher Icon 与 SVG 品牌源

App 内 Logo 使用 `assets/branding/aletheia_icon_vector.svg`。系统桌面图标要由同一源生成：

```sh
./tool/regenerate_launcher_icons.sh
fvm flutter pub get
fvm flutter build apk --debug
fvm flutter build ios --simulator --debug --no-codesign
```

该脚本通过 macOS `sips` 生成临时 PNG 设计输入，再调用 launcher icon 配置生成 iOS/Android 所需尺寸。不要手动编辑 `ios/Runner/Assets.xcassets/AppIcon.appiconset/` 或 Android `mipmap-*` 的生成 PNG。

## 9. 多 Agent 实操协议

1. 在任务开头写清目标、拥有文件与禁止修改文件。
2. 第一个 Agent 负责 `router.dart` / `app_shell.dart` / `pubspec.yaml` / `gallery_manifest.dart` 等全局文件时，其他 Agent 只读或等待其合并。
3. Feature Agent 只改自己 feature 的 Page、Controller、Repository、测试和相关 Gallery entry。
4. 文档 Agent 以实际源码为准，不把设想写为“已实现”。
5. 每个 Agent 结束时提供：修改文件、执行命令及结果、已知风险、下一步建议。
6. 集成人员在最新代码上运行完整 tests、analyze、diff check 和必要双平台 build。

建议使用 worktree：

```sh
git worktree add ../ry-aletheia-mobile-feature -b feature/mobile-feature
```

在未明确授权时，不自动创建分支、不提交，也不清理其他人的 worktree。

## 10. 故障排查

| 现象 | 优先检查 | 不应做 |
| --- | --- | --- |
| `No MaterialLocalizations found` | `MaterialApp` / `localizationsDelegates` / locale 设置是否在 App 根生效 | 在单个 Page 随意包嵌套 `MaterialApp` |
| Gallery 旋转后状态丢失 | route query、manifest key、hot restart 后完整 route | 在 Release 打开 Gallery |
| Xcode SPM 无法拉取 | proxy/DNS、Package Dependencies、完整 xcodebuild log | 修改 Flutter UI 来“解决”构建问题 |
| iOS 视频崩溃 | renderer/session generation、initialize/dispose、切流日志 | 吞掉异常或保留无限 renderer |
| 地图拖动带动页面 | gesture arena 与 scroll physics、canvas 手势边界 | 直接禁用全部手势 |
| Golden 意外大面积变化 | theme/font/设备尺寸/manifest、变更 diff | 未审查就批量更新基线 |

## 11. 工作断点模板

在 `../../docs/AI_CONTINUATION.md` 顶部写入最新记录：

```md
## YYYY-MM-DD：简短任务名（最新）

### 当前目标
...
### 已完成
- ...
### 当前正在进行
...
### 尚未完成（优先级）
1. ...
### 下一步第一件事
...
### 当前涉及文件
- `path`：用途
### 架构 / UI 决策
- ...
### 问题与验证状态
- `fvm flutter analyze`：...
- `fvm flutter test ...`：...
- iOS / Android：...
### Resume Prompt
先读取 PROJECT_OVERVIEW.md、mobile/AGENTS.md、AI_CONTINUATION.md、设计文档与当前 diff；确认状态后从“下一步第一件事”继续。
```

停止前执行 `git status --short` 和 `git diff --check`，保存所有文件，但不要自动 commit。
