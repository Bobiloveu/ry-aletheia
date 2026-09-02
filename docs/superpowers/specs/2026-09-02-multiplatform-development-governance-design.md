# 多端开发环境与维护治理设计

## 目标

在不移动或重命名任何核心目录、不改变机器人部署方式和 Flutter 业务功能的前提下，让 Backend、Web、Mobile Android、Mobile iOS 能够按职责独立开发，并让跨端接口拥有清晰的唯一事实来源。

## 不变约束

- Backend 继续位于 `web_console.py`、`autodrive_console/`、`live_preprocessor/`、`tasks/` 与 `config/`。
- Web 源码继续位于 `frontend/`，构建输出继续兼容 `autodrive_console/web-vue/`。
- Flutter 工程继续位于 `mobile/`；Flutter SDK 由 `mobile/.fvmrc` 锁定；Unity 仍是暂停的 PoC。
- Pixi 是 Backend/Web 的唯一环境管理入口；FVM 是 Flutter SDK 的唯一入口。
- Mobile 与 Web 只能消费后端受控 API，不能直接发布 ROS2 Topic。
- 不升级 Flutter、Gradle、AGP、Kotlin、iOS Deployment Target 或机器人安全参数。

## 方案

### Profile 与平台能力

根脚本使用 `backend`、`web`、`mobile-android`、`mobile-ios`、`full` 五种 Profile。`doctor` 根据操作系统区分：当前 Profile 的必需工具缺失为 `MISSING`；与当前 Profile 无关的工具为 `OPTIONAL`；当前操作系统不能提供的 iOS 工具为 `UNSUPPORTED`。因此 Windows/Linux 的 Android 或公共 Dart 开发不会因 Xcode 缺失失败。

macOS/Linux 继续使用 Bash 脚本；Windows 提供 PowerShell 版 `doctor`。不以 Python、Pixi 或 Xcode 作为 Mobile Android Profile 的前提条件。

### 环境入口

不新增 Makefile 或新的任务运行器。Backend/Web 继续转发至既有 Pixi task；Mobile 继续转发至既有 FVM 和 `mobile/tool/build_mobile_packages.sh`。`bootstrap.sh` 只增加兼容别名和 Profile 选择，既有 `backend|web|mobile|all` 调用保持有效。

### Shared Contracts

`shared/contracts/robot_control.md` 保留为人类可读的控制契约唯一入口，并补全 HTTP 生命周期、字段、枚举、状态迁移、超时与速度限制。后端实现是 ROS 运行时的权威执行者；Contract 是 Backend/Web/Mobile 对外协作的唯一事实来源。不会虚构当前不存在的 Mobile 控制能力，也不会将 ROS 代码复制进 Shared。

### CI

保留路径过滤，扩展为 Backend、Web、Flutter 公共质量、Android Debug 构建和 iOS Simulator 构建。Shared Contract 变化触发所有消费者；脚本、锁文件和 CI 变化触发对应环境检查。Android 在 Linux，iOS 在 macOS，不要求开发者本机具备对方平台。

### 验收标准

- `doctor` 的每个 Profile 在 macOS/Linux 产生可预测状态，且 iOS Profile 在非 macOS 明确输出 `UNSUPPORTED`。
- Windows PowerShell Doctor 不依赖 Bash。
- Contract 文档包含 Topics、HTTP 操作、控制枚举、安全时间和速度范围。
- CI 分别存在 Linux Android 与 macOS iOS 的验证路径。
- 原有 Pixi 与 FVM 命令保持可用。
