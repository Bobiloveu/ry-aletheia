# Aletheia Mobile — 维护与多 Agent 协作约束

本文件适用于人类维护者、Codex、Claude 及其他自动化 Agent。目标是让多人能并行维护 Flutter App，同时不改变机器人端既有协议、权限边界和已验收的 HMI 行为。

## 0. 开始任何任务前

按下列顺序阅读；越靠前的文档事实优先级越高：

1. [`../PROJECT_OVERVIEW.md`](../PROJECT_OVERVIEW.md)：产品、车端能力、协议与边界的最高事实基线。
2. 本文件：移动端协作约束与改动边界。
3. [`README.md`](README.md)：移动端能力和运行方式。
4. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)：真实源码结构与数据流。
5. [`docs/DEVELOPMENT_WORKFLOW.md`](docs/DEVELOPMENT_WORKFLOW.md)：开发、调试、验证和交接命令。
6. [`docs/DESIGN_SYSTEM.md`](docs/DESIGN_SYSTEM.md) 与 [`../docs/UI_SPEC.md`](../docs/UI_SPEC.md)：已确认的视觉、交互和页面职责。
7. [`../docs/AI_CONTINUATION.md`](../docs/AI_CONTINUATION.md)：上一次工作断点。它是上下文，不会自动授权未说明的范围扩大。
8. 当前 `git status --short`、`git diff`，以及将要改动文件的完整源码和测试。

Flutter SDK 以 [` .fvmrc`](.fvmrc) 锁定的 `3.47.1` 为准。先按
[`../docs/development/PROFILES.md`](../docs/development/PROFILES.md) 选择 Android 或 iOS
Profile；Windows/Linux 的 iOS 条目为 `UNSUPPORTED` 而不是 Mobile 环境故障。首次进入模块执行
`dart pub global activate fvm 4.3.0 && fvm install`；后续统一使用 `fvm flutter`
而非裸 `flutter`。Android 维持 JDK 17、AGP 9.1.0、Gradle 9.3.1、Kotlin 2.4.0；
iOS 维持 iOS 15.0、Swift 5.0、CocoaPods 和 SwiftPM。不要为解决本机环境差异升级
这些锁定版本，也不要删除 `pubspec.lock`、`Podfile.lock` 或 `Package.resolved`。

如果文档与源码不一致：先以 `PROJECT_OVERVIEW.md` 和可运行源码为准，记录差异，再修正文档；不要凭记忆重写协议。

## 1. 不可跨越的边界

- 不修改 ROS2、后端 HTTP API、二进制 WebSocket、WHEP/WebRTC 协商或测试后端契约，除非任务明确覆盖车端与移动端并有对应协议验证。
- App 当前是**监控、观测、测试与诊断 HMI**。Observation 必须只读。未来 Operation / Command 必须采用独立路由、独立权限、独立审计和显式确认，不能复用观测链路。
- 不在 App 中实现离线升级 ZIP、任意文件系统读写、任意命令执行、RViz 开关、底盘/导航直接控制或 ROS topic 输入。
- 修改 `shared/contracts/` 时，先确认 Mobile 是否为 Existing consumer；当前 Observation 只消费受控 HTTP、WebSocket 与 WHEP 契约，不能把未来控制能力写成已经可用。
- 设置只影响本机偏好；不能借设置入口修改机器人运行配置。
- 不用 `try/catch` 吞掉 WebRTC renderer、PeerConnection、MediaStream 生命周期错误。要修复真实的 initialize / dispose / 切流竞态，并测试切流。
- 不能以 Gallery mock 代替正式页面。Gallery 必须通过真实 Page/Widget/Theme + Mock 状态驱动。
- 不执行 `git reset --hard`、`git checkout --`、自动提交或覆盖未归属的脏改动。
- Flutter `CustomPaint` 是当前正式渲染主线；Unity 仅为暂停 PoC。除非任务明确恢复该 PoC，否则不得传入 Unity 构建开关或将其设为默认。

## 2. 当前代码边界

```text
lib/
  main.dart                    ProviderScope → AletheiaApp
  app/                         MaterialApp、GoRouter、四个一级入口、Theme
  core/                        endpoint、HTTP client、连接状态、错误与共享组件
  features/                    按业务能力拆分的 page / controller / repository
  debug_ui/                    仅 Debug 的 Gallery、Mock 与页面清单
```

一级导航固定围绕用户目标而不是内部技术对象：**首页、观测、工具、设置**。

- 首页：连接、当前机器人与健康信息。
- 观测：地图、位姿、点云、视频；工作区优先级最高。
- 工具：测试、用例、报告、日志、运行配置、场景、维护。
- 设置：语言、HMI 显示、版本/更新、问题反馈；本地功能。

更完整的路由、Provider、实时渲染和平台说明见架构手册。

## 3. 并行开发规则

多人同时工作前，要先在任务描述或共享记录中声明“文件所有权”。推荐用独立 Git worktree；至少要避免两位 Agent 同时格式化或修改同一全局文件。

| 工作域 | 主要文件 | 同时修改风险 |
| --- | --- | --- |
| 应用壳与导航 | `lib/app/router.dart`、`app_shell.dart`、`app.dart` | 高；一次只允许一个负责人 |
| 全局主题与文案 | `lib/app/theme/*`、`lib/app/copy/*`、设计文档 | 高；影响所有 Golden |
| 机器人连接 / HTTP | `lib/core/connection/*`、`lib/core/network/*` | 高；不得改变协议语义 |
| 实时观测 | `lib/features/live_observation/*` | 高；地图和 WHEP 分别验证 |
| 工具业务 | `lib/features/test_*`、`tool_*`、`system_*` | 中；按 feature 划分 |
| 设置与反馈 | `lib/features/app_settings/*` | 中；不得越过本地边界 |
| UI Gallery / Golden | `lib/debug_ui/*`、`test/debug_ui/*`、`tool/*` | 高；清单是单一来源 |
| 平台/依赖 | `pubspec.yaml`、`ios/`、`android/` | 高；单独变更并构建双平台 |

每个并行任务应：

1. 只修改自己的文件集合；全局文件改动要显式声明。
2. 将 API/模型变更拆成独立提交或独立工作项，先合并契约，再让 UI 消费。
3. 不把大范围 `dart format lib`、依赖升级或项目重构混入功能任务。
4. 合并前重新基于最新主线运行针对性测试；涉及 shell/theme/router/gallery 时运行完整测试和 Gallery Golden。
5. 在交接记录中写出：已改文件、验证命令、剩余风险、下一步精确动作。

## 4. 变更流程

### 任何小改动

1. 读事实基线与当前 diff。
2. 找到所属 feature 的 Page、Controller、Repository 与测试。
3. 最小化实现；避免同时改变 UI、协议和状态模型。
4. 对改动 Dart 文件执行 `dart format <files>`。
5. 运行相关 test；随后运行 `fvm flutter analyze` 与 `git diff --check`。
6. UI 可见变化时，更新 Gallery state / Golden / Screen Inventory（按实际需要），并在真机或 Simulator 检查横竖屏。

### 新增屏幕或关键状态

必须同时完成：Route 或既有入口、production Page、loading/empty/error/permission/offline 等真实可达状态、Debug Gallery entry、Screen Inventory、必要 Golden 与文档。不得另写一份 preview UI。

### 新增后端能力

先确认 `PROJECT_OVERVIEW.md` 已列出能力、端点、权限与错误语义。Repository 负责传输和解析，Controller 负责状态与生命周期，Page 不直接拼 URL 或处理协议字节。

## 5. UI 与交互质量门槛

- 保持 Professional / Industrial / Precise / Restrained / Modern / High Information Efficiency；实用性优先，不堆叠大标题、大卡片、装饰性 Glow 或无意义动效。
- 默认纵向可用；横屏根据可用宽度切换到紧凑 HMI 工作区，而不是强制横屏。地图/视频优先占据可用空间，导航与状态条保持轻量。
- 手势地图使用同一 world-to-screen transform；地图、米制格栅、虚拟墙、点云、轨迹、机器人共用坐标变换。双指缩放锚定双指中心，平移不得拖动页面滚动。
- 相机工作区最多三路真实画面；每个窗口有明确边界和不遮挡的控制层。切流与后台恢复要释放旧 renderer/session。
- Apple 平台交互遵循可打断、克制、尊重 Reduce Motion 的原则。非必要的动效宁可不加。
- App 内品牌标志使用 SVG；系统桌面图标由同一 SVG 源生成，不能手工漂移为第二个设计源。

## 6. Debug UI Gallery

- 仅 Debug 模式可访问：`/__debug/ui-gallery`；Release/Profile 不得暴露入口。
- `lib/debug_ui/gallery_manifest.dart` 是 Gallery、Golden 与生成 UI 文档的单一清单来源。
- Mock 只能替换数据来源和状态，不能复制正式 Widget；不得访问机器人、ROS、HTTP、WebSocket 或 WebRTC。
- 新状态先在 Gallery 预览，再更新必要 Golden。生成的 `docs/ui/SCREEN_INVENTORY.md` 和 `docs/ui/SCREEN_MAP.md` 不要手工编辑。
- **任何新增生产页面，以及现有页面新增的关键操作、故障或空/加载状态，必须先加入 Debug Gallery。** Gallery 使用正式 Page/Widget 与本地 Fake，仅模拟数据与状态；不得把调试入口或真实命令带入 Release。

## 7. 验证最低要求

| 改动类型 | 至少执行 |
| --- | --- |
| 纯文档 | 链接/事实复核、`git diff --check` |
| 单 feature Dart | 定向 `fvm flutter test` + `fvm flutter analyze` |
| UI / Theme / Router / Gallery | 全量 `fvm flutter test --concurrency=1 -r compact` + Gallery Golden + Simulator 横竖屏检查 |
| Map / WS / WHEP | 上述 UI 验证 + 真机/真实车端受控验证；说明未验证项 |
| iOS / Android / 依赖 / icon | 两平台构建；`fvm flutter pub get`（依赖变更时） |

命令、输出路径、真机调试与故障排查见 `docs/DEVELOPMENT_WORKFLOW.md`。

## 8. 交接要求

连续开发或剩余额度接近阈值时，更新 `../docs/AI_CONTINUATION.md` 顶部的最新断点，至少包含：目标、已完成、当前进行、未完成优先级、下一步第一件事、文件列表、架构/UI 决策、问题、验证状态、项目边界、实际使用的 Skills 和可直接执行的 Resume Prompt。

交接前不得留下半个函数、明显语法错误或未保存文件；运行可行的验证，检查 `git status --short` 与 `git diff --check`，但不要自动提交。
