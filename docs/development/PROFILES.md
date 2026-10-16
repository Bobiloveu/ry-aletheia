# 开发 Profile 与工具链矩阵

RY Aletheia 保持一个仓库以共享事实、协议和发布规则，但不要求每位维护者安装全部工具链。先选择职责，再执行对应 Doctor：

```sh
./scripts/doctor.sh --profile backend
./scripts/doctor.sh --profile web
./scripts/doctor.sh --profile mobile-android
./scripts/doctor.sh --profile mobile-ios
```

Windows PowerShell 使用：

```powershell
./scripts/doctor.ps1 -Profile mobile-android
```

Doctor 的状态含义：`OK` 为当前 Profile 已满足；`MISSING` 为当前 Profile 的必需工具缺失；`OPTIONAL` 为未选择域或仅真机调试才需要的工具；`UNSUPPORTED` 表示当前 OS 无法提供该能力，例如 Windows/Linux 的 iOS 工具链。只有 `MISSING` 使 Doctor 返回非零状态。

## 角色矩阵

| 角色 | 支持的 OS | 必需工具 | 不要求安装 | 常用入口 |
| --- | --- | --- | --- | --- |
| Backend Developer | macOS、Linux、Windows | Pixi | Flutter、Android SDK、Xcode、Unity | `pixi install`；`./scripts/test-backend.sh`；`pixi run backend-run`（Windows 使用 `pixi run backend`） |
| Web Developer | macOS、Linux、Windows | Pixi | Flutter、Android SDK、Xcode、Unity | `./scripts/bootstrap.sh web`；`./scripts/test-web.sh`；`pixi run vue-preview` |
| Mobile Android Developer | macOS、Linux、Windows | Dart、FVM 4.3.0、Flutter 3.47.1、JDK 17+、Android SDK | Pixi、ROS2、Xcode、CocoaPods、Unity | `fvm flutter pub get`；`./scripts/test-mobile.sh`；`fvm flutter build apk --debug` |
| Mobile iOS Developer | macOS | Android Profile 的 Dart/FVM 基础、Xcode、CocoaPods | Pixi、ROS2、Unity；Android 设备/adb | `fvm flutter pub get`；`fvm flutter build ios --simulator --debug --no-codesign` |
| macOS Full-stack Developer | macOS | 仅安装当前任务涉及的上述工具 | Unity（暂停 PoC） | 分别运行对应 Profile，不建议盲目执行 `full` |

## 锁定与版本规则

### Backend 与 Web

`pixi.toml` 与 `pixi.lock` 是 Backend/Web 的环境事实来源。Pixi 当前锁定 Python 3.10、Node 20、CMake、Ninja、编译器、PyInstaller、pytest 和 PyYAML。不要以系统 Python/Node 版本替换 Pixi 环境，也不要删除 lock 文件。

现有 Pixi task 继续有效：

```sh
pixi install
pixi run test
pixi run test-offline
pixi run test-realtime
pixi run frontend-install
pixi run frontend-check
pixi run verify
pixi run vue-preview
```

Windows 中 `backend` 是现有任务名；macOS/Linux 继续使用 `backend-run`。这是兼容现状，不是要求所有系统使用同一 shell。

### 任务编译（实验）

新项目的 `fixed_task_line_v1` 支持独立户外图、摆渡层、室内大厅或用户楼层。single 输出完整往返任务，multi 只输出实际阶段去返文件，不要求公共段或乘梯。楼层多线路仍逐目标导出 floor 文件对；全局摆渡不虚构楼栋归属。旧单图项目需明确保存固定线路后使用该入口，不自动推测业务动作。下述 `indoor_elevator_v1` 是仍保留的历史室内电梯模板，不作为独立单图部署的限制。

历史项目缺少 `task_lines` 字段且不是已迁移的单图项目时，继续走 `indoor_elevator_v1` 兼容编译入口。其核心是大厅—用户层的同一物理电梯往返模板；single/multi 包装器还可从已保存的自动定位路线组合户外、摆渡公共段，按目标和栋单元生成任务。不能把该核心模板的两图结构当成整个工作台的限制。物理电梯在首张图建立编号、协议与服务楼层，其他地图关联同一设备并确认本层门向、尺寸和候梯距离；路线与转场由 Backend 校验和派生。

“预览”与“下载”只在项目自己的实验导出目录生成任务 JSON、行为树 XML、定位 YAML 与 ZIP；它们不写入机器人任务目录、行为树运行目录或定位运行配置，也不会启动 ROS、Supervisor 或下发任务。任何产物都必须逐项对照已批准样例，并在本地任务执行器中验证后，才能由现场维护流程另行决定是否安装。

固定线路的同图导航段可展开实际经过的闸机、自动门、窄通道、坡道和慢行区；设备动作使用受管模板。跨图固定线路目前使用同栋单元、唯一关联的物理电梯连接；multi 仅支持一个公共源图加一个连续用户楼层段，或独立单图。电梯候梯点到轿厢中心的直接段不支持夹带其他设施。流程允许编辑与模板可执行范围分别校验，不能据此生成任意跨图动作。速度模式与用户指定参考 XML 的差异见 [速度模式模板基线](SPEED_MODE_TEMPLATES.md)。

### Flutter 与 Android

`mobile/.fvmrc` 固定 Flutter `3.47.1`，对应 Dart 随 Flutter SDK 提供；`mobile/pubspec.lock` 必须提交。首次安装：

```sh
dart pub global activate fvm 4.3.0
cd mobile
fvm install
fvm flutter pub get
```

Android 的 CI 基线是 JDK 17；工程维持 AGP 9.1.0、Gradle Wrapper 9.3.1、Kotlin 2.4.0 和 JVM target 17。`compileSdk`、`targetSdk`、`minSdk` 由固定 Flutter SDK 提供的值注入，不在此仓库另行复制或手改。Android Studio/SDK 必须可被 `ANDROID_SDK_ROOT`、`ANDROID_HOME` 或标准默认路径发现；`adb` 只在真机调试时必需。

### Flutter 与 iOS

iOS 仅在 macOS 构建。当前工程维持 iOS Deployment Target 15.0、Swift 5.0、CocoaPods 与 SwiftPM；测试过的本机 Xcode 为 26.6。`mobile/ios/Podfile.lock` 与两份 SwiftPM `Package.resolved` 必须提交。依赖变化才运行 `pod install`；不要为常规构建升级 Pods、Swift Packages、Flutter 或 Xcode 配置。

## 共享契约变更流程

1. 在 `shared/contracts/` 找到 Existing Contract，确认其中的 Backend/Web/Mobile consumers 与影响范围。
2. 先更新 Contract 的字段、兼容性和状态；不存在的能力必须标为 Planned。
3. 同一变更中更新实际消费者和对应测试。普通 Backend/Web/Mobile 单模块修改不需要安装其他端环境。
4. Contract 变更合并前至少运行受影响模块的测试；CI 会触发 Backend、Web、Flutter 公共检查、Android 和 iOS 验证。

机器人控制接口的详细规则以 [`shared/contracts/robot_control.md`](../../shared/contracts/robot_control.md) 为准。Web 与 Mobile 不得直接发布 ROS2 Topic；所有控制请求必须通过后端受控 API。
