# Aletheia Mobile 架构手册

> 本文描述当前 `mobile/` 的真实 Flutter 实现。它不定义新的车端协议；接口、权限和产品边界以 [`../../PROJECT_OVERVIEW.md`](../../PROJECT_OVERVIEW.md) 为准。

## 1. 产品边界

Aletheia Mobile 是面向移动机器人的专业 HMI（Mobile Robot HMI / Test & Diagnostic Console）。当前能力是：机器人状态确认、实时地图/位姿/点云/视频观测、自动化测试与用例、报告、诊断、运行配置和维护入口。

它不是通用 ROS 客户端，也不是控制台命令终端。观测链路只读；未来的 Robot Operation / Command 若被立项，必须使用独立的 API、权限、审计、风险确认和导航入口。

明确不在移动端实现：离线升级 ZIP、RViz 开关、任意文件系统访问、任意 shell/ROS 命令、底盘与导航直接控制。

## 2. 运行时总览

```text
main.dart
  └─ ProviderScope
      └─ AletheiaApp (app/app.dart)
          └─ MaterialApp.router
              └─ GoRouter (app/router.dart)
                  └─ AletheiaAppShell (app/app_shell.dart)
                      ├─ 首页：连接、健康与当前机器人
                      ├─ 观测：地图 / Pose / PointCloud / WHEP 视频
                      ├─ 工具：测试、报告、日志、运行与维护
                      └─ 设置：语言、主题、版本、更新、反馈

Page → Riverpod Controller/Provider → Repository → AletheiaApiClient
                                       └──────────→ HTTP / Binary WS / WHEP
```

`AletheiaApp` 监听应用生命周期：恢复时恢复受控心跳/测试轮询；进入 inactive、hidden、paused 或 detached 时暂停它们。App 只保留本地诊断事件，不在后台继续占用高频观测资源。

## 3. 目录与职责

| 路径 | 职责 | 依赖方向 |
| --- | --- | --- |
| `lib/app/` | App 根、GoRouter、四级入口 shell、主题与统一文案 | 可以依赖 `core` 和 feature public UI |
| `lib/core/` | endpoint 解析、HTTP client、连接状态、错误、共享 UI | 不依赖具体 feature Page |
| `lib/features/` | 各业务 feature 的 Page、Controller、Repository、Model | feature 依赖 `core`，不要横向偷用私有实现 |
| `lib/debug_ui/` | Debug-only Gallery、mock 状态、Gallery manifest | 复用 production Page/Widget/Theme |
| `test/` | widget/unit/Golden 测试 | 与生产代码保持同一状态入口 |
| `integration_test/` | 用户旅程与真实导航验证 | 通过公开 UI 行为驱动 |
| `tool/` | Gallery 文档、截图、Launcher Icon 生成脚本 | 不属于运行时业务 |
| `assets/branding/` | SVG 品牌设计源 | UI 可直接加载 SVG |

Feature 的常见结构：

```text
features/<feature>/
  <feature>_page.dart          页面布局与交互编排
  <feature>_controller.dart    Riverpod 状态、生命周期、操作入口
  <feature>_repository.dart    API 调用与数据解析
  <feature>_models.dart        不依赖 Widget 的模型
  widgets/                      可复用的 feature 内组件
```

不要让 Page 直接拼 URL、解析 WebSocket 二进制帧或管理 `RTCVideoRenderer`；这些责任分别归 Repository/专用控制器/播放协调器。

## 4. 路由与页面层级

`lib/app/router.dart` 由 `GoRouter` 管理。以下是当前路由事实；页面标题可本地化，路径应保持稳定以兼容 Gallery 与深链。

| Route | 所属入口 | 页面职责 |
| --- | --- | --- |
| `/` | 根 | 进入应用壳 |
| `/robot` | 首页 | 机器人地址、连接、健康与状态概览 |
| `/observation` | 观测 | 地图/相机实时工作区 |
| `/tools` | 工具 | 工具总览与二级能力入口 |
| `/tools/testing` | 工具 | 测试计划、执行、结果、Supervisor 信息 |
| `/tools/testing/cases` | 工具 | 测试用例库 |
| `/tools/logs` | 工具 | 诊断日志 |
| `/tools/reports` | 工具 | 测试报告 |
| `/tools/runtime` | 工具 | 运行配置 |
| `/tools/scenario-setup` | 工具 | 场景前置配置 |
| `/tools/maintenance` | 工具 | 控制台/系统维护入口 |
| `/settings` | 设置 | 本地语言、主题、版本/更新、反馈入口 |
| `/settings/feedback` | 设置 | 反馈草稿及附件选择；当前不上传 |
| `/settings/update` | 设置 | App 更新检查 UI |
| `/__debug/ui-gallery` | Debug only | Gallery；Release/Profile 不注册 |

兼容重定向仍保留：`/connection` → `/robot`，`/cases` → `/tools/testing/cases`，`/runs` → `/tools/testing`，`/tools/app-settings` → `/settings`。不要再把“用例”或“运行”恢复为一级导航。

## 5. 状态管理、连接和 HTTP

### 5.1 Riverpod 原则

Controller 对外暴露 `AsyncValue` 或明确的不可变 state；Repository 处理 I/O 和序列化；Page 只订阅 provider、展示状态并调用用户触发的 action。长生命周期资源必须由 provider/controller 的 dispose/lifecycle 管理。

核心 Provider 包括：

- `robotConnectionControllerProvider`：当前 endpoint、连接状态、健康检查、10 秒心跳和操作 epoch。
- App preferences providers：语言、主题等本机 `SharedPreferences` 偏好。
- Live observation providers：观测状态、地图、实时 Pose/Cloud、视频状态/会话协调。
- Tool feature providers：用例、计划/运行、报告、日志、运行配置、场景和维护状态。

任何异步 connect/start/refresh 动作都应使用 operation epoch 或取消语义，避免旧请求覆盖新 endpoint/新页面的结果。

### 5.2 Endpoint 与 HTTP

`core/connection/robot_endpoint.dart` 支持 IPv4、主机名和方括号包裹的 IPv6，并固定使用已有控制台 HTTP 端口 `8087`。它是所有 REST URL 的唯一地址格式化来源。

`AletheiaApiClient` 集中处理：5 秒请求超时、`Accept: application/json`、`Cache-Control: no-store`、JSON/bytes/download/postBytes 与统一 `ApiException`。新增端点须落在该 client/repository 层，不要在 Widget 中直接使用 `http`。

常见既有 HTTP 能力按 Repository 分类：

| 功能 | 既有 API 类别 |
| --- | --- |
| 连接/观测 | observation 状态、启动、heartbeat |
| 地图 | active map、图层/墙体、PNG preview |
| 视频 | `video/status`、受限 stream `video/control` |
| 测试 | cases、计划、latest run、动作/报告 |
| 工具 | 日志、运行设置、Supervisor、场景、维护 |
| 设置 | 本地偏好；反馈当前不上传 |

端点名称、请求字段和权限必须从根目录 `PROJECT_OVERVIEW.md` 或现有 Repository 读取，不能在本文猜测后扩展。

## 6. 实时观测：地图与视频

### 6.1 地图 world canvas

地图视图不是“可以拖动的图片”，而是一个有世界坐标的 canvas。渲染顺序固定为：

```text
base map → metre grid → virtual walls → future trajectory → point cloud → vehicle footprint / pose
```

所有层必须共用同一 world-to-screen transform；地图 resolution、origin、缩放、平移在一个 viewport 内计算。栅格是米制参考，不是纯装饰：密度随着 zoom 调整，并使用低对比度色彩。地图边界之外显示深色 Workspace Canvas（可延续弱 grid），不使用突兀纯黑；平移受合理范围约束但允许检查周边空间。

手势规则：

- 单指拖动移动 viewport，不让父页面跟随滚动。
- 双指缩放以两指中心为 anchor；缩放与 pan 同时发生时地图不能跳动或漂移。
- 旋转若未显式实现，不把 rotation 手势误映射到平移。
- 横竖屏尺寸变化后重新 fit map，同时保留正确 image aspect ratio 与 layer transform。

地图 active 状态以约 5 秒轮询为主；切换或 refresh 必须由 epoch 防止过期响应覆盖当前地图。

### 6.2 Pose 与 PointCloud 二进制流

Pose 与 PointCloud 从车端独立二进制 WebSocket 获取（当前端口 `8768`，路径按现有实现分别为 pose/cloud）。协议为严格校验的 `ALTM` v1：验证 magic、版本、stream type、record count、payload 长度和有限 float 值。

- Pose：读取网络序 3 个 `float32`（x/y/yaw）；本地待处理帧超过 250ms 直接丢弃。
- Cloud：最多 3000 组 x/y；只保留一个未消费帧，在下一帧渲染时解码；超过 100ms 的帧丢弃。
- `Float32List` 直接交给 `CustomPainter.drawRawPoints`，禁止每帧创建大量 `Offset`。
- 断线可指数退避重连，但不得请求历史帧或堆积回放。

### 6.3 WHEP 视频

视频通过 `flutter_webrtc` receive-only WHEP 会话播放：创建 SDP offer → 请求车端 answer → 设置 remote description → 绑定原生 `RTCVideoRenderer`。只允许已配置的受限流名称，不能让用户输入 topic/路径/命令。

`WhepPlaybackCoordinator` 管理 renderer lease：进程内最多**三路**同时真实解码（横屏主画面 + 两个辅助画面）；竖屏默认单主画面。第四路必须等待资源释放，绝不能无上限解码六路。

切流、离开相机、切换到地图、App 后台及 dispose 均要按 generation/lifecycle 顺序关闭 session、PeerConnection、MediaStream 和 renderer。出现 iOS 崩溃时先查 native Flutter/WebRTC 日志并复现快速切换六路流，禁止只用 try/catch 隐藏。

## 7. 工具与设置

| Feature | 当前职责 | 关键限制 |
| --- | --- | --- |
| `test_cases` | JSON / `.rycase.zip` 用例管理、受控导入导出 | 不改写车端 `tasks/` |
| `test_runs` | 计划、运行、预检、轮次、Supervisor、恢复/中止 | 影响运行的动作需显式确认；活动运行约 1 秒轮询 |
| `reports` | 报告列表、下载、删除 | 删除前确认 |
| `tool_logs` | 诊断日志与受控下载 | 不提供任意路径访问 |
| `runtime_settings` | 车端既有运行配置 | 复用既有 API 与确认语义 |
| `scenario_setup` | 受控场景预览/选择/应用/恢复 | 只读受控目录文本、摘要和大小；不任意读写 |
| `system_maintenance` | 控制台服务与安全停止 | 停止必须确认 |
| `app_settings` | 本机语言、主题、版本、App 更新、反馈 | 不依赖机器人且不修改车端；反馈开发期无上传 |

新增网页端功能时先按其用户目标放入“首页 / 观测 / 工具 / 设置”之一；内部数据对象不能直接变成一级 Tab。

## 8. Debug Gallery、Golden 和 UI 文档

`lib/debug_ui/gallery_manifest.dart` 是当前 UI Review 的单一清单来源。每个 entry 描述 Screen、状态、preview 和 Golden 标签；Gallery 使用 production Page/Widget/Theme，加 Mock repository/service/provider 状态以避免机器人、ROS、HTTP、WS 和 WebRTC 依赖。

流程：

```text
新增/修改真实页面状态
  → 在 gallery_manifest 增加或更新 mock 状态
  → Debug Gallery 人工检查
  → 更新对应 Golden
  → dart run tool/generate_ui_docs.dart
  → 审阅生成的 Inventory / Screen Map
```

`docs/ui/SCREEN_INVENTORY.md` 和 `docs/ui/SCREEN_MAP.md` 是生成物，不手工编辑。Golden 覆盖静态关键状态与布局回归；它不取代真机 WebRTC、手势和原生权限测试。

## 9. 主题、文案与品牌

主题由 App settings 的本机偏好驱动：默认 HMI 深色，并提供日间模式和高对比深色；主题切换不改变任何机器人数据与安全边界。颜色、字体、间距、横竖屏 breakpoints 以 `docs/DESIGN_SYSTEM.md` 为准。

运行时 Logo 使用 `assets/branding/aletheia_icon_vector.svg` 和 `flutter_svg`。iOS/Android 系统 Launcher Icon 不能直接引用 SVG，所以由同一个 SVG 设计源经 `tool/regenerate_launcher_icons.sh` 生成平台 PNG/Adaptive Icon；不要手工编辑生成的 AppIcon 或 icon mipmap 文件。

## 10. 平台与安全

- Android application id 当前为 `com.ryaletheia.aletheia_mobile`，构建使用 Java 17；因既有车端部署允许本地 HTTP/网络访问。
- iOS 声明本地网络用途，并为既有可信局域网 HTTP 配置平台例外；支持 portrait 与 landscape。
- App 仅适用于可信局域网。生产安全升级应先由车端提供 TLS、认证和权限模型，再收窄 Android/iOS 网络例外。
- 不要为了绕过模拟器构建问题删除或放宽安全/网络声明；要先定位 Xcode SPM、签名或本地网络权限原因。

## 11. 安全扩展方式

### 新增只读实时数据

先确认车端协议 → 建 model/parser + 有界队列/最新帧策略 → 独立 provider 生命周期 → 通过同一 world transform 绘制（若为空间数据）→ 增加 Gallery mock 状态与真机检查。不得在 UI isolate 积压原始帧。

### 新增工具页

先确认现有后端受控 API → repository → controller → Page → Tools 二级入口 → loading/empty/error/permission state → Gallery/Inventory/Golden。涉及破坏性动作必须明确说明目标和后果并二次确认。

### 未来新增操作/控制

先完成产品与安全设计，再建立独立 `operation` domain、独立 command API、身份/权限、确认、审计日志、网络失败安全策略和单独测试。未具备这些条件前，任何“控制”按钮都不应出现。
