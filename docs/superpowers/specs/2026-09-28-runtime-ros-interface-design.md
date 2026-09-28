# 运行时 ROS 接口优先设计

## 背景与问题

实时观测页新增的定位状态订阅依赖
`master_interfaces/msg/LocalizationStatus`。现场车辆可以通过
`ros2 topic echo /localization/status` 输出该消息，但已安装的 Aletheia
单文件程序在 PyInstaller 临时目录中加载了升级包内旧版的
`master_interfaces`，其中没有该消息类。因此订阅在导入阶段失败，页面只能显示
“定位状态暂不可用”。

问题不是定位模块、共享内存或 ROS topic 不工作，而是升级程序中固化的接口版本
覆盖了车辆运行时接口。

## 目标与边界

目标是让同一份 Aletheia 升级包在不同车辆上优先使用各车
`/opt/ry/install` 已安装并已 source 的 `master_interfaces`；定位状态仅在该车
提供 `LocalizationStatus` 时启用。

- 不从单台车导出 `master_interfaces` 并嵌入通用升级包。
- 不改变 ROS 节点、定位算法、任务服务、Node Manager 或任何安全控制逻辑。
- 缺少新消息的旧车仍可运行既有控制台和任务功能，只是定位状态区域显示安全、
  可读的“不支持实时定位状态”。
- `master_interfaces` 仍可作为构建所需的基础接口覆盖层导出；它不再是 Aletheia
  运行时 Python 接口的来源。

## 运行时数据流

1. 现有 launcher source `/opt/ry/install/setup.bash`，并由 `web_console.py`
   的环境守卫保证进程从同一 ROS 环境启动。
2. PyInstaller runtime hook 只读取 `AMENT_PREFIX_PATH` 中的前缀，按 Python
   ABI 推导 `<prefix>/local/lib/pythonX.Y/dist-packages`。
3. hook 仅把确实包含 `master_interfaces` 的上述目录前置到 `sys.path`；不扫描
   任意文件系统路径、不接受外部下载路径。
4. 冻结程序不包含 `master_interfaces` 的 Python 包或其 ROSIDL 动态库，避免
   `/tmp/_MEI...` 中的旧接口抢在车辆接口前被导入。
5. `LocalizationStatusMonitor` 从车辆接口导入 `LocalizationStatus` 并只读订阅
   `/localization/status`。成功时按既定契约返回状态；消息缺失、导入失败或 ROS
   初始化失败时，记录诊断原因并返回不泄露路径/原始异常的公共状态。

## 构建与兼容性

- 构建预检继续验证 Aletheia 基础任务依赖（`rclpy`、任务服务接口、TF），但不以
  `LocalizationStatus` 是否存在作为打包成败条件；它是车辆可选能力。
- `build_binary.sh` 保留 Aletheia 自身、视频和通用 ROS 依赖；移除
  `master_interfaces` 的 hidden import、`--collect-all` 以及类型支持库收集。
- 构建产物检查不得出现内嵌 `master_interfaces`。若目标车辆接口结构正确，
  `/opt/ry/install` 的 package 和动态类型支持库由已 source 的运行环境提供。
- 兼容性按车辆接口能力分级：提供同名消息的车辆显示实时状态；不提供的车辆稳定
  降级，不影响其余控制台功能。若同名消息的字段不兼容，ROS 类型支持的加载/订阅
  失败同样走只读降级，不执行任何控制动作。

## 可观察性与错误处理

- 内部日志区分“车辆未提供 LocalizationStatus 接口”和其他 ROS 初始化/订阅失败，
  便于现场判断。
- API 和界面只展示受控的中文语义，不暴露 `/tmp/_MEI`、Python 路径或异常文本。
- 该监控器始终是旁路能力：失败不会中断任务、轨迹采样、视频或报告生成。

## 验证与发布

1. 单元测试覆盖：运行时 hook 只选择 `AMENT_PREFIX_PATH` 内合规的接口目录；构建
   脚本不再捆绑 `master_interfaces`；缺少接口时 API 安全降级。
2. 运行 Backend 与 Web 最小相关检查，并对生成包检查归档内容不含
   `master_interfaces`。
3. 使用现有签名升级流程生成并安装升级包；安装后读取
   `/api/observation/localization-status`，预期现场 `state: 1` 映射为“定位正常”，
   而不是 `unavailable`。
4. 在 PC 实时观测页面核验状态胶囊与地图、任务控制均正常；旧接口车辆则核验
   仅该状态胶囊可读降级。
