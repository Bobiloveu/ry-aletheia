# 当前开发断点

## 2026-08-29：移动端维护与多 Agent 文档体系（最新）

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

## Resume Prompt

继续开发前，先读取 `PROJECT_OVERVIEW.md`、`AGENTS.md`（如存在）、本文件、`docs/DESIGN_SYSTEM.md`、`docs/UI_SPEC.md`、当前 Git diff 和相关 Skill。先确认现有代码状态，不重新分析或推翻已完成的三级导航、只读边界、多流选择、虚拟墙/真实车体、统一世界变换、三路有界 decoder 租约和 latest-wins 决策。执行 Flutter 测试时，只对命令临时移除 HTTP(S)/ALL 代理环境变量。第一步是在 iPhone 设置中允许 Aletheia 使用本地网络后附加 Debug 并保存日志；再连接可信机器人，逐一验证六路 WHEP、任意三路真实并发、快速切流、前后台、竖横屏、双指中心地图缩放、边界及地图/虚拟墙/车体对齐。若有异常或崩溃，先保存完整 Flutter/native trace 再修复。不得新增虚假控制能力、实时轨迹、第四路或未确认业务 API；未来 Command 必须保持独立权限与命令边界。
