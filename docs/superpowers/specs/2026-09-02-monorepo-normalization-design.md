# RY Aletheia Monorepo 工程结构整理设计

**状态：** 第一阶段已实施，待合并至 `v2.0`  
**日期：** 2026-09-02  
**范围：** 工程边界、开发入口、环境锁定、契约文档、Agent 规则与渐进式 CI；不重构机器人业务逻辑。

## 1. 背景与目标

仓库同时承载机器人端控制台后端、Vue/PixiJS Web Console、Flutter HMI、ROS2/C++ 预处理和暂停中的 Unity 可视化 PoC。当前功能可用，但开发入口、跨端协议事实来源和维护规则分散；多个维护者或 Agent 容易误触另一端的高风险路径。

本次目标是建立清晰的“逻辑 Monorepo”边界，并固定各端可复现的开发环境。稳定性优先于物理目录美观：第一阶段不移动依赖根目录布局的生产源代码。

**实施记录：** 已建立 `shared/contracts`、`scripts`、模块 README/AGENTS、FVM 4.3.0 + Flutter 3.47.1 锁定和按路径 CI。根 Pixi 后端测试与 Web 构建已通过。Mobile 的 FVM 配置可用，但其现有 `features/reports` 源文件缺失，导致 analyze/test 不能通过；这不是环境或目录迁移导致，需作为独立移动端功能修复处理。

## 2. 审计结论与不可直接迁移项

| 实际位置 | 当前职责 | 为什么第一阶段不移动 |
| --- | --- | --- |
| `web_console.py` + `autodrive_console/` | 机器人端 HTTP API、运行控制、ROS/视频/建图适配、传统静态 Web 资源 | 启动入口、运行数据目录、PyInstaller、DEB/升级包和多套 Python 测试均假定仓库根路径。 |
| `frontend/` | Vue/Vite/PixiJS Web 源码 | Vite 固定构建到 `../autodrive_console/web-vue`，后端按此位置提供静态资源。 |
| `live_preprocessor/` | ROS2/C++ 点云和视频预处理 | 构建脚本、Python 运行时、打包路径固定使用 `build/live_preprocessor/`。 |
| `config/`、`tasks/`、`packaging/`、根构建脚本 | 后端配置、任务模板、Linux 发布资产 | 属于机器人端发布边界，存在目标车部署和离线升级兼容契约。 |
| `mobile/` | Flutter App | 相对独立，但 Golden/UI 文档、工具脚本和 Unity PoC 测试存在相对父目录引用。 |
| `unity/` | 暂停中的 Unity renderer PoC | 已明确非正式主线；保留源码与恢复说明，不能让其影响 Flutter 默认构建。 |

因此，直接把上述目录搬到 `apps/` 会产生高回归风险，不符合本次“不破坏现有功能”的前提。

## 3. 第一阶段信息架构

第一阶段保留物理源目录，建立逻辑模块注册与统一入口。`apps/` 只作为未来迁移说明的入口，不作为空壳或影子源码目录；避免维护者误以为同一模块存在两份代码。

```text
ry-aletheia/
├── autodrive_console/          # 当前 robot_backend 的 Python package 与传统 Web assets
├── web_console.py              # 当前 robot_backend 入口（保留）
├── frontend/                   # 当前 web_console 的 Vue/Vite 源码（保留）
├── mobile/                     # Flutter HMI（保留；本轮优先规范环境）
├── live_preprocessor/          # ROS2/C++ 预处理（robot_backend 发布组成）
├── unity/                      # 暂停的 renderer PoC（未来 visualization/unity 候选）
├── shared/
│   ├── contracts/              # 跨端接口事实来源：文档，不放业务实现
│   ├── schemas/                # 可验证 JSON 数据格式（初期只放 README/准入规则）
│   ├── models/                 # 跨端领域模型说明
│   └── templates/              # 行为、配置、部署模板说明
├── scripts/                    # 跨模块 bootstrap/doctor/test/build 入口
├── docs/
│   ├── architecture/           # 边界、模块注册、迁移路线
│   ├── backend/                # 机器人端开发与 ROS/发布说明索引
│   ├── web/                    # Web 开发说明索引
│   ├── mobile/                 # Flutter 文档索引，不复制 mobile/docs
│   ├── protocols/              # 指向 shared/contracts 的阅读入口
│   └── deployment/             # 构建、升级、发布说明索引
├── apps/README.md              # 仅说明未来物理迁移，不承载重复源码
├── AGENTS.md                   # 全仓规则
├── PROJECT_OVERVIEW.md         # 保留既有完整工程事实，逐步改为架构详情入口
└── README.md                   # 新开发人员的最短入口
```

现有 `docs/ui/`、`docs/images/` 和 `docs/superpowers/` 保持原位，避免移动生成截图、历史设计/计划引用。

## 4. 模块边界

### robot_backend

- **实际源码/入口：** `web_console.py`、`autodrive_console/`、`live_preprocessor/`、`config/`、`tasks/`、`packaging/` 与根发布脚本。
- **负责：** 受控 HTTP API、任务/报告、机器人连接、ROS2 适配、建图、视频运行时、遥测网关和机器人端发布。
- **不负责：** Flutter UI 状态、Vue/PixiJS 页面渲染、Unity 场景渲染。
- **环境：** 根 `pixi.toml` / `pixi.lock` 是唯一 Python/Node/CMake 基础工具链事实来源；ROS2 Humble 和车端专有 overlay 是外部前置条件。
- **接口：** `shared/contracts/` 中标记为 Existing 的 HTTP、遥测、控制和视频契约。

### web_console

- **实际源码：** `frontend/`；后端传统静态 Web 资源仍位于 `autodrive_console/web/`。
- **负责：** Vue/Vite/PixiJS Web 页面、浏览器侧实时地图/视频编排、调用受控后端 API。
- **不负责：** 直接操作 ROS、转发视频帧、修改后端运行数据的内部格式。
- **构建兼容：** 保留 `frontend → autodrive_console/web-vue` 输出关系，直到第二阶段迁移完成。

### mobile

- **实际源码/入口：** `mobile/`，Flutter `lib/main.dart`。
- **负责：** iOS/Android HMI、可信局域网 API/遥测/WHEP 消费、移动端 UI 与本地偏好。
- **不负责：** ROS2 直接访问、机器人任务执行实现、Unity 默认启动。
- **环境：** FVM 固定 Flutter；`pubspec.lock` 必须提交；默认 Flutter `CustomPaint` renderer。

### visualization / unity（暂停）

- **实际源码：** `unity/aletheia_viz/` 和 `mobile/packages/aletheia_visualization/`。
- **状态：** 保留的实验性 renderer PoC，不进入默认开发、测试或正式包。
- **恢复前提：** 必须遵循 `docs/UNITY_PAUSED_HANDOFF.md`，并在独立变更中完成 Android/iOS 生命周期回归。

## 5. shared/contracts 设计

`shared/contracts/` 是跨端“接口事实来源”，只存接口定义、版本、示例和兼容性规则；不复制 Python、Dart、JavaScript 或 ROS 实现代码。

初始文件：

| 文件 | 内容 |
| --- | --- |
| `README.md` | 版本规则、Existing/Planned 标记、变更流程和消费端检查清单。 |
| `robot_control.md` | Existing：`/control_source_cmd`、`/control_source_state`、`/cmd_vel_miniapp`，以及对应受控 HTTP API 的权限/心跳/停止语义。 |
| `realtime_observation.md` | Existing：地图、虚拟墙、活动地图、`/cloud`、`/pose`、`ALTM v1`、8768/8769/8770 端口、latest-wins 和过期帧规则。 |
| `video.md` | Existing：`/api/video/status`、`/api/video/control`、WHEP/WebRTC 生命周期边界。 |
| `task_execution.md` | Existing：测试用例、运行、报告、取消/恢复等受控 API 语义。 |
| `deployment.md` | Existing：部署、地图、虚拟墙、组件和拓扑 API；Planned 的模式演进边界。 |

每份契约至少包含：状态（Existing/Planned）、消费者、端点或 Topic、请求/响应或 wire 格式、失败语义、兼容性策略、相关实现链接和最低测试。

## 6. 开发环境策略

### Pixi

- 保持根 `pixi.toml` / `pixi.lock` 为 robot_backend 和 web 的工具链锁定来源。
- 不移动或删除现有 `pixi run test`、`pixi run frontend-check`、`pixi run verify`、`pixi run vue-preview`。
- 可增加语义清晰的兼容别名（例如 `backend-test`、`web-check`），但旧 task 名保留。
- 当前 Python 3.10 的理由是与 ROS2 Humble 目标 ABI 对齐；不可因本机 Python 3.13 改写后端。

### Flutter / FVM

- 在 `mobile/.fvmrc` 固定审计到的 Flutter `3.47.1`，不升级 Flutter、Gradle、AGP 或 Xcode。
- `mobile/pubspec.lock` 和本地 package 的 lock 均继续受版本控制。
- 文档与新脚本统一使用 `fvm flutter pub get`、`fvm flutter run`、`fvm flutter analyze`、`fvm flutter test`。
- 若开发者未安装 FVM，`doctor.sh` 报 WARN 并说明安装/使用方式；只开发 backend/web 时不得阻断。

### 平台基线

| 平台 | 当前锁定/要求 | 规则 |
| --- | --- | --- |
| Android | AGP 9.1.0、Gradle 9.3.1、Kotlin 2.4.0、Java 17；`compileSdk`/`targetSdk` 由 Flutter SDK 注入 | `doctor.sh` 检查 JDK 主版本；当前本机 JDK 26 只作不兼容 WARN，不自动切换。 |
| iOS | Xcode 26.6 审计环境、iOS 15.0、Swift 5.0、CocoaPods、SwiftPM | `Podfile.lock` 和 `Package.resolved` 保留提交；不自动执行 Pod/Swift 依赖升级。 |
| Unity | Unity 2022.3.62f1（暂停 PoC） | 缺失仅 WARN；不能阻断 Flutter 构建。 |

## 7. 统一脚本

新增脚本必须只编排已有命令，不直接修改机器人配置、运行数据或签名资料。

| 脚本 | 行为 |
| --- | --- |
| `scripts/bootstrap.sh` | 输出按模块初始化提示；可选执行 Pixi install、前端 npm ci、FVM pub get，不强迫安装所有工具。 |
| `scripts/doctor.sh` | 以 `[OK]` / `[WARN]` / `[FAIL]` 检查 Pixi、Pixi Python、Node、FVM/Flutter/Dart、JDK、Android SDK/adb、Xcode、CocoaPods、Unity。缺失非当前模块工具时只 WARN。 |
| `scripts/test-backend.sh` | 调用现有 Pixi backend/offline 测试。 |
| `scripts/test-web.sh` | 调用现有 Pixi frontend check。 |
| `scripts/test-mobile.sh` | 在 `mobile/` 以 FVM 运行 analyze 与 test。 |
| `scripts/build-mobile.sh` | 仅委托 `mobile/tool/build_mobile_packages.sh --engine flutter`；不暴露 Unity 为默认选项。 |

所有脚本从仓库根解析路径，明确检查前置工具，且不写入发布签名或机器人状态。

## 8. 文档与 Agent 规则

根 `README.md` 缩短为项目简介、模块选择、最少命令和文档入口。既有 `PROJECT_OVERVIEW.md` 继续保存详细工程/机器人事实，避免一次性重写。

新增根 `AGENTS.md`：

1. 先读根 README、模块 README 和涉及的 Existing contract。
2. 未获明确授权不得大规模物理迁移、删除、重写业务逻辑或修改机器人安全边界。
3. 修改跨端 API、Topic、wire format 或数据模型时，先更新 `shared/contracts/`，并检查所有消费者。
4. 只改某模块时，不修改其他模块，除非契约或脚本兼容性要求；说明跨域影响。
5. 完成前运行对应模块验证；不混入 build/cache/log/测试失败图片。
6. 不默认恢复 Unity；Flutter 是当前正式移动端 renderer。

模块规则落在真实模块位置，而非未迁移的 `apps/` 空目录：

- `autodrive_console/AGENTS.md`：ROS、运行数据、发布、后端测试约束；
- `frontend/AGENTS.md`：Vite 输出与浏览器/API 边界；
- `mobile/AGENTS.md`：补充 FVM、平台和 UI 验证，保留既有移动端规则。

文档分类目录将以索引/迁移说明形式建立，不复制现有内容。旧链接先保留，逐步迁移可稳定内容。

## 9. CI 设计

仓库当前无 CI。本阶段新增按路径过滤的 GitHub Actions，避免无关全量构建：

- backend 变动：Pixi backend Python tests；
- web 变动：Pixi frontend check；
- mobile 变动：FVM Flutter analyze + test；
- `shared/contracts` 变动：执行所有轻量的 backend/web/mobile 基础检查；
- 文档、Unity paused PoC 单独变动：只执行格式/链接或相关静态检查，不启动 Unity 构建。

移动端 CI 在第一阶段以不依赖签名的分析和测试为主；Android/iOS 发布构建继续是可选的受控发布步骤，避免在 CI 注入签名资料。

## 10. 验收标准

1. 既有 `pixi install`、`pixi run verify` 和 `pixi run vue-preview` 保持可用。
2. 新脚本不会要求 backend/web 开发者安装 Flutter，也不会要求 mobile 开发者安装 ROS2/Unity。
3. FVM 版本文件与 Flutter 文档一致，lock 文件仍被 Git 跟踪。
4. 每个模块均有职责、入口、依赖、运行/测试/构建方式和 contracts 链接。
5. Existing/Planned 明确，跨端接口不再只依赖散落源码。
6. CI 只执行受变更路径影响的检查。
7. 不产生 build、缓存、签名、日志或现有 Golden failure 图的误提交。

## 11. 第二阶段迁移前置条件

只有在以下条件均满足后，才单独计划将源码物理迁至 `apps/robot_backend`、`apps/web_console`、`apps/mobile`：

1. 后端已支持显式 `RY_ALETHEIA_WORKSPACE` / package-root，而不是隐式依赖当前文件父目录；
2. Vite 输出改为受配置控制，后端静态资源发现机制已覆盖兼容路径；
3. PyInstaller spec、DEB、升级包、C++ 构建和所有测试改为模块根解析；
4. Flutter UI 文档、Golden 和 Unity 暂停契约不再依赖 `mobile/..` 的固定父路径；
5. 建立迁移前后的完整回归矩阵，并在 Linux ROS 发布环境复核。

在这些前置条件完成前，第一阶段的逻辑边界即为正式维护边界。
