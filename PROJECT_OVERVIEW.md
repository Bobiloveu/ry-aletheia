# RY Aletheia 工程手册

> 面向维护、开发、构建与现场排障人员。项目入口见 [README.md](README.md)；日常安装、使用和升级请优先阅读 [USER_GUIDE.md](USER_GUIDE.md) 与 [GitHub Releases](https://github.com/Bobiloveu/ry-aletheia/releases)。模块边界与迁移状态见 [docs/architecture](docs/architecture/README.md)，跨端接口事实来源见 [shared/contracts](shared/contracts/README.md)。

本文也是交接基线：新增功能、替换依赖或在新车型部署前，先核对本文的接口契约、数据所有权和发布检查表，再开始实现。文中“不得”表示不能为临时排障绕过的运行边界。

## 1. 工程定位与边界

RY Aletheia 是部署在机器人小车 Ubuntu 主机上的离线自动测试平台。测试人员通过同一 Wi-Fi 下的浏览器访问 `http://<小车IP>:8087`；任务调用、ROS2 通信、Supervisor 操作、地图缓存与报告生成均在小车本机完成。

它负责测试编排、证据记录和只读观测，不替代小车原有的导航、定位、地图服务或安全控制。

- 任务仅通过既有 `/start_execute_tasks` 服务下发，不向底盘或导航发布控制指令。
- 不修改任务 JSON；别名、依赖编排和场景方案均保存在工具配置目录。
- 场景前置配置只替换启动脚本中已登记的 FCRP 与 lightning 参数。应用场景时以先落盘的可校验恢复事务、定向原子替换和运行依赖重启验证构成闭环；恢复常规方案时只回写启动脚本，不操作运行中的节点，常规参数在相关节点下次自行启动时生效。
- 实时观测采用“时效优先”：点云/位姿过期帧直接丢弃，不追赶历史画面；可选视频走独立的低延迟 WebRTC 链路。
- 小车运行阶段不依赖互联网、Node.js、npm 或开发源码；主程序必须以普通账户运行。

### 1.1 Flutter 移动端产品定位

Flutter 客户端是 Aletheia 面向可信局域网中移动机器人的专业 HMI（Mobile Robot HMI / Test & Diagnostic Console）。它将当前机器人的状态监控、实时可视化、测试诊断和测试任务管理组织为统一的移动端使用入口；这一定义只描述客户端产品语义，不改变本工程作为离线自动测试平台的后端职责。

移动端的语言、显示主题、版本信息、App 更新检查与问题反馈属于手机本地的一级“设置”入口，只能写入设备本地偏好，不能进入 `/api/settings` 或任何车端配置。App 更新功能必须与车端 `updates/` 离线升级目录严格隔离；当前开发构建不联网检查，未来只能使用经过审核的移动应用发布渠道。问题反馈当前只进行本地表单校验；未来上传必须经独立移动端接口，且只能发送用户可见并主动选择的问题文本、联系方式、截图及 App 版本/平台/语言/主题和本次 App 会话事件摘要，绝不能附加机器人地址、地图、视频、ROS 或车端日志。主题仅保留默认 HMI 深色与经地图、视频、状态面板回归验证的日间模式；日间模式只切换手机本机低反光浅色配色，必须保持地图、点云、虚拟墙、车体和告警语义色的可读性，绝不改变实时数据或车端配置。

当前移动端以 Observation / Monitoring、Test 和 Diagnostic 为主要能力，沿用本手册已有的 HTTP、专用实时遥测和 WHEP/WebRTC 契约。未来若引入 Robot Operation / Command，必须先形成独立、明确确认的后端命令契约，并具备权限、确认和审计模型；命令路径不得复用观测的只读数据链路，也不得因此扩大现有 ROS2、底盘、导航或安全控制边界。

测试执行不再启动、管理或暴露 RViz。轨迹证据由既有地图与 SVG 轨迹报告链路统一提供；历史配置中的 `open_rviz` 偏好仅在升级读取时被清理，不能再影响运行行为。

移动端观测必须忠实消费既有数据契约：地图按底图、虚拟墙、未来真实轨迹、点云、车体轮廓的顺序分层；车体尺寸以运行配置的 active vehicle model 为准。相机必须识别车端配置中的 1 至 6 路流，操作者可独立启停已配置流并切换主画面。Flutter 宽横屏可同时解码固定上限三路真实 WHEP/WebRTC（主画面加两路辅助画面）；竖屏保留单主画面，第四路必须等待已有解码会话释放。这个客户端上限避免把全部六路相机无约束地变成移动端高频负载，且不改变既有视频 API、ROS 或 MediaMTX 契约。

## 2. 功能域

| 功能域 | 核心能力 |
| --- | --- |
| 测试用例管理 | 扫描 `tasks/` 任务 JSON、保存别名、绑定每条用例的场景前置方案，并以可校验用例包跨车交付。 |
| 测试指挥台 | 多轮串行执行、任务文件同步、依赖预检、Supervisor 编排、人工恢复和终止。 |
| 场景前置配置 | 选择 FCRP `.launch.py` 与 lightning YAML，受控替换 `handle_modules.sh`；应用/恢复均让受控依赖重读脚本并确认稳定运行。 |
| 多地图轨迹 | 缓存实际地图，叠加实际轨迹、理想路线、虚拟墙并归档。 |
| 报告中心 | 生成、预览、下载、删除可离线查看的单文件 HTML 报告。 |
| 实时运行观测 | 地图、虚拟墙、车体轮廓、定位、点云，以及网页按需启停的低延迟相机视频。 |
| 运行配置 | 依赖编排、车型、实时观测、升级和持久化设置。 |
| 工具日志 | 独立记录升级、ROS2、专用遥测、观测和异常诊断。 |

## 3. 总体架构

```text
同网段浏览器
  │ HTTP :8087（控制台、API、报告）
  │ Binary WebSocket :8768（专用实时遥测：点云/位姿）
  │ WHEP/WebRTC :8889（可选相机直出）
  ▼
RY Aletheia（普通账户）
  ├─ Python 控制台：计划、任务、Supervisor、轨迹、报告、配置、升级
  ├─ C++ 轻量位姿进程：最新 TF map → base_* → 回环 UDP 位姿帧（60Hz）
  ├─ C++ 轻量点云进程：/collision_voxel_layer/points（或 /livox/lidar 回退）→ 回环 UDP 点云帧（≤3000 点）
  ├─ Aletheia 专用遥测网关：UDP 最新帧组装 → 两条 Binary WebSocket
  ├─ 可选视频运行时（由控制台拥有）
       ├─ 原生 `aletheia_video_ingest`：按发布配置读取四路 ROS Image 或 ShmSDK 最新图像；检测/分割始终读取 ROS Image → rawvideoparse → VAAPI H.264 → 本机 RTSP
       └─ 私有 MediaMTX：RTSP 输入 → WHEP/WebRTC 输出
  └─ 已有机器人系统的受限集成
       ├─ ROS2：/map、/odom、TF、/amcl_pose、/start_execute_tasks、/collision_voxel_layer/points
       ├─ Supervisor：受限 sudo supervisorctl status/start/restart
       └─ 运行数据：tasks、config、reports、maps_cache、updates、logs
```

测试执行经 HTTP API 进入 `RunManager`。地图仍由既有缓存/API 机制加载。C++ 点云和位姿预处理分别写入独立最新数据槽，并分别经独立的回环 UDP 入口交给 Aletheia 专用遥测网关；网关只组装最新完整帧，并以两条 Binary WebSocket 分离点云与位姿，避免大点云阻塞车体姿态。相机视频不经过遥测网关：浏览器用 WHEP 与本机 MediaMTX 建立 WebRTC 会话，Python 只提供受控的状态与开关 API。

## 4. 目录与数据所有权

| 目录 / 文件 | 用途 | 升级 ZIP 是否覆盖 |
| --- | --- | --- |
| `dist/ry-aletheia` | 最终控制台二进制 | 是 |
| `tasks/` | 测试任务 JSON | 否 |
| `config/console.json` | 运行、依赖、车型、观测配置 | 否 |
| `config/video.json` | 视频开关、ROS 域、网关、编码器与流配置 | 否 |
| `config/scenario_setup.json` | 场景方案与用例绑定 | 否 |
| `config/case_workspace.json` | 用例版本、状态、标签、说明、来源与任务指纹 | 否 |
| `config/scenario_backups/` | 场景应用时的常规配置备份 | 否 |
| `reports/` | HTML/CSV 报告与轨迹证据 | 否 |
| `maps_cache/` | 地图、虚拟墙、观测底图缓存 | 否 |
| `updates/` | 升级暂存与唯一 `.bak` 备份 | 否 |
| `runtime/video/` | 内置 MediaMTX、最小 GStreamer/VAAPI 与驱动的私有视频运行时 | 启用视频时按二进制内嵌版本原子刷新；不改写 `config/video.json` |
| `logs/` | 控制台、遥测网关、预处理与错误日志 | 否 |
| `autodrive_console/` | Python 业务源码、正式网页输出 | 仅构建时 |
| `frontend/` | Vue/Vite 源码 | 仅开发机 |
| `live_preprocessor/` | C++ 点云预处理节点源码 | 仅构建时 |
| `install/` | 目标小车导出的最小 ROS 构建覆盖层（`master_interfaces`、`livox_ros_driver2`） | 仅开发机 |
| `releases/` | ZIP、校验文件和可选 DEB 的本地构建输出；正式交付通过 GitHub Releases | 开发机输出，忽略 |

升级必须只替换程序产物，不能覆盖任务、报告、缓存或用户配置。

### 4.1 `video.json` 配置契约

`config/video.json` 只描述 Aletheia 视频旁路：总开关、DDS 域、受控网关、私有编码器和每路输入、分辨率、帧率、码率。它不是小车相机驱动配置，**不得**记录或修改 USB 路径、`/dev/video*`、v4l2loopback、相机 UVC 控制项或原相机节点参数；这些均属于既有机器人系统。

发布时只能选择一种四路物理相机默认输入：`./make_upgrade.sh <版本号>` 嵌入 ROS 模板，`./make_upgrade.sh <版本号> --shm` 嵌入 ShmSDK 模板。ShmSDK 模板固定 `front_camera → CamFront`、`back_camera → CamBack`、`left_camera → CamLeft`、`right_camera → CamRight`，旁路只调用 `GetLastCamImage` 取得最新帧，再在自身进程内解码 ShmSDK 提供的 JPEG；它不启动、停止或配置 `mempool`，也不接管原相机驱动。ROS 模板固定使用四路既有 `source_topic`。`detection_camera` 与 `segmentation_overlay` 始终使用既有 `sensor_msgs/msg/Image` `source_topic`（当前支持 `rgb8` 或 `bgr8`）。ZIP 升级保留车端 `config/video.json`；ShmSDK 包只会迁移未自定义的旧四路默认 ROS 输入，绝不覆盖自定义输入、视频开关、分辨率、帧率或码率。现场 ShmSDK 边界与观察项见 [docs/SHMSDK_VIDEO_TRIAL_2.3.8.md](docs/SHMSDK_VIDEO_TRIAL_2.3.8.md)。

## 5. 后端模块职责

| 模块 | 职责 |
| --- | --- |
| `web_console.py` | HTTP 入口、静态资源、API、下载与安全退出。 |
| `case_store.py` | 用例 JSON 校验与扫描。 |
| `case_workspace.py` | 本机用例元数据、SHA-256 指纹、`.rycase.zip` 导入导出与冲突保护。 |
| `settings.py` | `console.json` 默认值、迁移、校验、原子保存。 |
| `models.py` | 计划、轮次、人工干预和统计模型。 |
| `run_manager.py` | 执行状态机、预检、恢复、场景应用/恢复、报告编排。 |
| `ros_executor.py` | ROS2 `/start_execute_tasks` 客户端。 |
| `runtime_env.py` | ROS2 环境探测与兼容降级。 |
| `robot_gateway.py` | 任务文件同步和受控本机操作。 |
| `supervisor.py` | Supervisor 状态解析、阶段编排、start/restart 与稳定等待。 |
| `scenario_setup.py` | 启动脚本识别、受控浏览、方案预览/应用/恢复、事务备份。 |
| `trajectory.py` | `/map`、`/odom`、TF 采集，多地图会话、进度与停滞检测。 |
| `navigation_status.py` | 电梯任务阶段识别，抑制合理等待期间的误告警。 |
| `map_assets.py` / `trajectory_render.py` | 地图、路线、虚拟墙缓存及轨迹 SVG 渲染。 |
| `observation.py` | 专用遥测/C++ 预处理生命周期、地图缓存和观测诊断。 |
| `video.py` | 视频配置校验、MediaMTX 健康状态、WHEP 地址生成与控制台拥有的视频进程树生命周期。 |
| `tool_logging.py` | 工具级日志。 |
| `upgrade_manager.py` | 清单/MD5 校验、备份、原子替换与重启交接。 |

## 6. 测试执行状态机

```text
queued → preparing → running → completed
                    │
                    ├─ 单轮失败 → awaiting_recovery → recovering → running
                    │                         │
                    │                         └─ 终止 → cancelled
                    └─ 终止剩余轮次 → cancelling → cancelled
```

一次轮次严格按以下顺序执行：

1. 校验计划、任务文件和运行互斥状态。
2. 应用用例绑定的场景方案，先持久化恢复事务，再替换脚本；未启用完整编排时立即重启已登记的定位/导航启动消费者。
3. 等待方案应用后的稳定窗口。
4. 按依赖编排阶段 `restart` 节点；STOPPED 节点使用 `start`。
5. 每阶段等待所有依赖稳定为 `RUNNING`，再进入下一阶段。
6. 同步任务文件（仅目标目录没有同名文件时复制），确认 ROS2 服务可用。
7. 下发任务，开始轨迹和轮次记录。
8. 单轮失败后等待人工恢复；恢复后重新应用方案和依赖编排才允许继续。
9. 计划完成、取消或不可恢复失败后，回写原常规启动配置并关闭恢复事务；不启动、不停止、不重启任何 Supervisor 节点，常规参数在相关节点下次自行启动时生效。

节点名称、默认预检集、阶段顺序与等待时间必须由配置驱动，不能在业务代码中写死某一台车的节点名。

## 7. 场景前置配置安全模型

该模块不是通用文件编辑器。它用来避免测试人员手动改错启动脚本：

- 默认脚本为 `/opt/ry/scripts/handle_modules.sh`，可受控配置实际路径。
- 只识别 `ros2 launch fcrp_bringup ...` 和 `ros2 run lightning run_loc_online --config ...` 的参数位置。
- 只能按层浏览脚本所在受控目录树，不递归扫描整机文件系统。
- FCRP 仅可选择 `.launch.py`；lightning 仅可选择 `.yaml`/`.yml`。
- 应用前可预览完整替换结果；应用时先持久化原文、SHA-256、时间、方案 ID、精确参数位置及命令行上下文，再替换脚本。断电或写入异常时宁可保留待恢复事务，也不能留下无备份的已改脚本。
- 使用临时文件、`fsync` 与原子替换；存在未恢复方案时锁定保存、添加、删除、重新应用及用例绑定，只保留预览与恢复入口。
- 恢复只回退本工具登记的两个参数，保留其他脚本改动；若受控命令或参数被外部修改、重复定位不唯一或恢复记录损坏，拒绝覆盖并明确报错。恢复常规方案只回写脚本并清理事务，绝不启动或重启任何 Supervisor 节点。
- “恢复常规配置”只会回写脚本并清理恢复事务，绝不启动、停止或重启任何 FCRP/lightning 相关依赖。页面明确说明这只影响后续启动参数，不将文件恢复误报为正在运行的节点已切回常规参数。
- 人工应用会重启同一受控依赖，使页面“已应用”与实际运行参数一致。存在待处理恢复事务时会阻止控制台安全退出和离线升级。
- 用例仅保存方案 ID 绑定；删除方案前必须解除相关绑定。

任何扩展都必须维持“白名单参数位置、受控根目录、可恢复事务”三项边界。

## 8. 多地图轨迹与报告原则

- 从任务 JSON 提取全部 `map_url`，支持 P1/P2/P3 及更多地图。
- 结合 `/map` 签名与 map_server 元数据识别实际切图，不能只依赖文件名或 `map_load_time`。
- `/odom` 必须按消息时间经 TF 转为 `map` 坐标后记录；坐标不匹配时拒绝该点，不猜测。
- 同一地图多次进入时保留独立轨迹段，不能跨切图连接直线。
- 报告按地图分段：实际轨迹按任务/去返分色，理想路线为细虚线，虚拟墙为红色实线。
- 报告优先显示用例别名；轨迹图片内联，下载后仍可离线查看。

轨迹只反映定位输出，不能替代定位标定或平滑度评估。

## 9. 实时运行观测的工程策略

### 9.1 分层渲染

```text
PixiJS 地图纹理 + 虚拟墙 ─┐
PixiJS 最新点云几何       ├─ Pixi 世界容器：缩放、拖动（固定 map 朝向）
车体 DOM 覆盖层           ┘
```

实时二维地图由 PixiJS 管理：静态占据地图为纹理，虚拟墙和点云为独立图层；首次取得或切图时才更新静态地图纹理。PC 保留原有高对比蓝色观测主题和无格栅画面；仅移动端的 `html.mobile-console` 额外绘制严格对齐 `map` 世界坐标的米制格栅，并按当前缩放在 1m、2m、5m 小格之间自适应，主格恒为小格的 5 倍。移动端比例尺反算当前 `pixelsPerMeter`，线宽也反算到地图像素，因而缩放后仍保持稳定的屏幕可读性。拖动、缩放与位姿跟随只更新 Pixi 世界容器变换，点云只替换最新一帧几何，均不重绘静态底图。缩放以鼠标位置为中心，中键或左键拖动仅改变视图变换。地图必须稳定保持原始 `map` 坐标朝向，不能在进入页面时按车体初始航向旋转；只允许车体 DOM 图标旋转。相机视频先由独立的浏览器原生 `<video>` 元素接收 WHEP/WebRTC，再作为 PixiJS `Video Texture` 合成到相机卡片；视频数据本身不进入 Canvas 2D、WebSocket 或 Python。

### 9.2 时效优先与背压

| 数据 | 策略 | 时效边界 |
| --- | --- | --- |
| 点云 | C++ `keep_last(1)`，最多 3000 点；扫描回调到达即处理并写入 UDP 发送最新槽，PixiJS 单槽最新帧渲染 | 节点内最新槽停留超过 140ms 才丢弃；浏览器包超过 100ms 丢弃；仅绘制最新一帧固定不透明点 |
| 位姿 | 独立 C++ 进程获取最新 `map → base_*` TF，写入独立 UDP 最新槽，浏览器独立动画 | 超过 250ms 丢弃；60Hz 发布；独立 Binary WebSocket 专线 |
| UDP / 浏览器 WebSocket | UDP 应用层分片不确认、不重传；网关、每个浏览器连接和浏览器渲染器均只保留容量 1 的 latest-wins 帧 | 新包覆盖未组装或未发送旧包，避免网络积压与 TCP 队头阻塞 |
| 地图 | 短订阅读取；仅切图时再更新 | 不持续传输大栅格 |
| 相机视频 | 独立 WHEP/WebRTC 会话；每路只保留编码器与浏览器各自需要的实时缓冲 | 不通过实时遥测、Python 或历史队列追传图像 |

短暂 Wi-Fi 抖动时允许跳帧，但恢复后必须尽快回到实车当前状态，不能显示数秒前的历史画面。

位姿流的 60 Hz 发布率是链路心跳率，不等同于底层 TF 每一包都有新的坐标。浏览器必须分开保存“最近收到消息时间”和“最近一次位置/航向真实变化时间”：前者用于判断断链，后者才是车体平滑外推的起点。重复 Pose 心跳包不能重置该测量时刻，否则渲染器会每帧把图标拉回旧坐标，表现为卡住后跳变。显示层的预测窗口严格不超过 300 ms；超过窗口即停止外推，等待真实新位姿。

### 9.3 C++ 预处理节点

`live_preprocessor/` 的 `ry_aletheia_live` 仅服务本工具，不改动原自动驾驶节点：

- 数据输入和输出必须明确区分：点云优先读取导航实际使用的 `/collision_voxel_layer/points`（`sensor_msgs/PointCloud2`）；该主流连续 500ms 未到达时，才回退读取 `/livox/lidar`（`livox_ros_driver2/CustomMsg`）。两路不能同时混合，否则网页会在两组近乎同时的扫描之间跳变。位姿不读取单独的定位话题，而是查询小车现有 TF 的 `map → base_footprint`，并兼容 `base_link`、`base_footprint_link`。
- 网页专用输出为已投影到 `map` 的紧凑二进制点云和最小位姿记录：点云只包含 `float32 x/y`，位姿只包含 `timestamp/seq/x/y/yaw`。它们不会重新发布 ROS topic，也不会暴露 ROS 图发现、订阅、服务或参数能力。
- 点云与位姿由两个独立进程运行，避免坐标转换或点云限采样阻塞高频位姿。
- 只接受标准 `float32 x/y/z`，限制距离、均匀抽样。节点默认及运行上限均为 3000 点；点云输入为 best-effort、depth=1。ROS 回调不执行网络发送，只写入最新槽；独立发送线程将数据按不超过 1152 byte payload 的 UDP 分片发送到回环网关，无 ACK、重传或历史缓存。
- 标准点云携带逐点 `timestamp` 时，按 5ms 时间桶查询历史 `map → 输入 frame` TF 后投影；快速原地旋转优先逐点去畸变。若某一时间桶缺少历史覆盖，则降级为扫描 header 时刻的刚体变换，必要时才使用最新 TF；实时页不能因增强去畸变失败而整帧无点云。
- 点云在节点内最新槽停留超过 140ms 才丢弃；不能把传感器或导航管线固有的旧 header 时间戳误判为网络滞后。header 时间仍用于 TF/逐点去畸变，TF 不可用则跳过当前帧。车体位姿使用最新可用 `map → base_*` 变换，避免低频 `map → odom` 的合成时间戳使显示流断续。
- 不使用 PCL、不改写原 ROS 话题、不写导航参数。

### 9.3.1 协议、生命周期与实现边界

这是私有、固定格式的数据通道，不是通用 ROS-Web Bridge。C++ 到网关的 UDP 分片以 `RALT` 魔数和版本号开头，携带流种类、流 ID、`frame_seq`、时间戳、`chunk_index`、`chunk_count`、总点数和 payload 长度；头部为 30 Byte，payload 上限为 1152 Byte。点云固定使用 `127.0.0.1:8769`，位姿固定使用 `127.0.0.1:8770`，各自有 socket、接收线程和 assembler。网关拒绝错误魔数/版本、截断包、非法分片号、超出分片或点数上限的包。分片可以乱序到达；重复分片不重复计数；新序号会立即淘汰未完成旧帧，残帧在短超时后清理。协议没有 ACK、重传、历史缓存或“补全旧帧”的等待逻辑。

网关到浏览器的 Binary WebSocket 帧以 `ALTM` 魔数和版本号开头，固定携带流种类、序号、时间戳、记录数和紧凑 payload。点云 payload 为网络字节序 `float32 x/y`；位姿 payload 为网络字节序的最小位置/航向记录。`/cloud` 与 `/pose` 是独立 WebSocket 连接：每个客户端每条连接只允许一个待发送帧，内核发送缓冲和写入超时也受到限制。浏览器刷新、断线和慢客户端只会使该客户端丢弃旧数据，不能积压或阻塞其他客户端、网关或 ROS executor。

`ObservationManager` 的启动、心跳、自动空闲回收和停止由同一生命周期锁串行化；遥测网关的 start/stop 也使用独立生命周期锁和代际标记，旧线程不能复用新 socket。网络发送只发生在 C++ 发送线程与网关线程：ROS 回调只转换数据并覆盖最新槽。控制台正常退出或升级前会停止两个预处理进程和网关；页面断开后由心跳空闲策略统一回收，避免一个标签页关闭时误停仍被其他标签页使用的观测。

现场排障优先看 `logs/live_preprocessor_cloud.log`、`logs/live_preprocessor_pose.log` 和工具日志；再检查 `/collision_voxel_layer/points`（主流）、`/livox/lidar`（回退）与 `map → base_*` TF 是否存在且持续更新。页面保持打开约 10 秒后，可从 `GET /api/observation` 的 `telemetry` 和 `client_metrics` 读取网关状态、点云/位姿源年龄、接收频率、渲染帧率和长帧计数，以区分上游、车端预处理、网络和 PixiJS 图层更新问题。实车参考：预处理点云约 10Hz，前端为降低点云几何更新竞争主动消费约 8Hz。

### 9.4 可选低延迟相机链路

视频是实时页的独立能力，默认关闭。页面提供全局开关与六路独立开关：全局开关启动/停止当前选中的流；MediaMTX 在至少一路启用期间保持不变，单路开关只增删该路原生编码进程，不会重连其他流的 WebRTC 会话；关闭最后一路才停止整个进程组。配置写入 `config/video.json`，控制台以普通账户拥有其生命周期；因此不占用 ROS 图像订阅、GPU 编码器或网络带宽的时间只发生在用户实际选择的流上。它不交由 Supervisor 管理，也不要求操作员额外执行 `ry-aletheia-video start|stop|status|restart`；后者仅可作为维护诊断入口，不能成为正常使用前置条件。

```text
视频输入（发布配置固定，禁止运行时自动猜测）
  ├─ ROS 包：/front_camera/image_raw /back_camera/image_raw /left_camera/image_raw /right_camera/image_raw
  ├─ ShmSDK 包：CamFront / CamBack / CamLeft / CamRight（四路物理相机）
  ├─ /rfdetr_detect（`rfdetr_depth_node` 的目标检测结果图，ROS Image，bgr8）
  └─ /segmentation/overlay（可通行区域分割叠加图，预设 bgr8）
          │
          ▼
原生 aletheia_video_ingest（每路一进程）
  fd 字节流 → rawvideoparse → videoconvert → vaapih264enc → h264parse → RTSP :8554（localhost）
          │
          ▼
工具私有 MediaMTX
  RTSP 输入 → WHEP 端点 :8889/<path>/whep → 浏览器 WebRTC <video>
```

- 运行时固定面向 `amd64` / Ubuntu 22.04 基线，并携带受锁定版本约束的 MediaMTX、最小 GStreamer 插件、VAAPI 用户态库和 Intel `iHD` 驱动；目标车无需为该功能另装 apt 包、Node.js、npm 或开发工具。
- `rawvideoparse` 是链路必需部分：管道读取可能把一帧 RGB/BGR 数据拆成多段，不能假设一次读取就是一帧图像。
- Python 不传递视频帧。`GET /api/video/status` 只返回配置、MediaMTX 健康和逐路状态；`POST /api/video/control` 只接受全局布尔开关，或已配置流名加布尔开关。后端拒绝浏览器提交的路径、话题、命令或可执行文件。视频数据只在原生编码器、MediaMTX 和浏览器之间流动。
- 视频配置允许逐流启用；网页首次整体打开时使用配置中的已启用流。ROS 包的四路物理相机预设订阅原始 ROS 图像话题；ShmSDK 包的四路物理相机预设为 JPEG 640×480、15 FPS，经旁路解码为 `rgb8` 后送入现有 VAAPI 编码器。后两路仍分别订阅 `/rfdetr_detect` 和 `/segmentation/overlay`（预设 `bgr8`、640×480、10 FPS），只旁路编码视觉结果，不读取或控制深度相机驱动，不修改检测或分割节点，也不向自动驾驶链路发布任何消息。原生旁路编码器输出支持 `rgb8` 与 `bgr8`，每一路配置都要与实际输入格式、分辨率、帧率、码率以及 `/dev/dri/renderD128` 的访问权限相匹配。
- `video.json` 不得为方便排障写入物理 USB 路径或虚拟 V4L2 节点。四路 ShmSDK 通道是受限输入契约，不能改作检测/分割输入；检测和分割保持受校验的 ROS `source_topic`。原相机驱动与设备映射仍由小车系统维护，视频旁路不应拥有第二份物理设备配置真相。
- 升级 ZIP 仍维持既有的单文件升级协议。视频运行时被内嵌到核心二进制；新二进制下一次启用视频时会将 `runtime/video/` 原子刷新到匹配版本，同时保留用户的 `config/video.json`。控制台启动时会以追加方式迁移缺失的默认视频流（例如新增的 `detection_camera`），绝不覆盖既有流的开关或其他用户配置。因此已安装工具的小车可以只上传升级 ZIP，无需仅为视频改走 DEB。

## 10. 前端维护

前端源位于 `frontend/src/`，构建产物输出到 `autodrive_console/web-vue/`。主要页面为任务指挥台、实时运行观测、测试用例管理、场景前置配置、报告中心、运行配置和工具日志。实时观测页依赖 `pixi.js`：`liveObservation.js` 负责地图纹理、虚拟墙、点云图层、DOM 车体层与页面交互；PC 地图独占工作区，不保留冗余图像订阅选择器。相机卡片以原生 `<video>` 接收 WHEP/WebRTC，并转为 PixiJS `Video Texture`。桌面网格按启用路数自适应列数；移动端五路时保持一主四预览，六路时切换为均衡 3×2（横屏）或 2×3（竖屏）矩阵，确保所有画面完整可见。控制调用 `/api/video/status` 与 `/api/video/control`，不会直接接触 ROS 或 MediaMTX。

共享视觉样式集中在 `autodrive_console/web/*.css` 与 `frontend/src/*.css`。PC 与移动端必须有明确样式边界：移动主题仅以 `html.mobile-console` 或 `/m/` 壳层选择器生效，不能用未限定的 `:root`、`body`、`aside`、地图配色或格栅逻辑覆盖 PC。深/浅主题只写浏览器 Local Storage，不写机器人配置。新页面默认避免冗余说明文字，但必须保留必要的安全状态和错误反馈。

### 10.1 PC 与移动端入口

桌面页面仍使用既有 URL 和既有 HTML/CSS；移动端不复用、也不覆盖桌面壳层。`web_console.py` 会依据 Client Hint（优先）和 User-Agent（兼容）将已知页面自动转入 `/m/` 对应入口，例如 `/live-observation.html` 对应 `/m/live-observation.html`，根路径及 Vue 任务台对应 `/m/`。`?view=desktop` 是明确的桌面回退开关，便于调试或用户临时切换。

`/m/` 页面由服务端在原页面中注入下列独立资源，调用的是相同受控 API 与页面控制器：

- `autodrive_console/web/mobile_console.js`：通用页面的固定品牌栏、五项底部导航和页面链接改写；识别实时观测的专用响应式壳层后只改写链接，绝不叠加第二个导航、抽屉或旧全屏按钮；
- `autodrive_console/web/mobile_console.css`：共享的石墨、暖灰、砂金与鼠尾草绿视觉令牌，以及安全区、单列内容区、最小 42px 触控目标和横竖屏规则；仅通过 `/m/` 页面加载，不能被桌面页面引用；
- `frontend/src/liveObservation.css` 与 `liveObservation.js`：实时观测的横竖屏响应式壳层、安全区、真实可视视口高度、地图/相机单主视图切换、1～6 路视频自适应栅格和地图专属触控手势。

移动端实时观测同时支持横屏和竖屏。布局高度使用 `VisualViewport` 的实时尺寸写入 CSS 变量，避免 Safari/Chrome 常驻地址栏把固定 `100dvh` 工作区压扁；横屏低高度使用紧凑顶栏和底栏，并把初始地图改为横向路线优先的工作视图，避免近方形全图在浅视口缩成中央小图；竖屏保留完整地图，并让相机卡片在主视图内部纵向滚动。页面通过 viewport 策略、`touch-action` 和 Safari `gesture*` 事件共同禁止整体捏合缩放；地图交互层保持 `touch-action: none`，由 Pointer Events 独立实现单指拖动及双指以中点为锚的缩放/平移。全屏按钮只改变浏览器显示状态，不再强制锁定屏幕方向。地图页停止手机端 WebRTC 解码，相机页停止点云/位姿可视化订阅与地图绘制，切回时恢复对应实时链路，避免手机同时承担两套重渲染。不得以全局媒体查询修改 PC 布局，也不得为移动端复制一套 API、实时流或业务状态。

### 10.2 前端修改自检

涉及移动端时，至少检查桌面宽度、390×844 与 430×932 竖屏、932×430、667×375 及 720×300 低高度横屏、全屏进入/退出、地图单指拖动/双指缩放、页面级缩放锁定、地图/相机切换以及 1～6 路视频排布。桌面页面应不加载 `mobile_console.*`，移动端所有导航页面应保留与 PC 相同的功能入口；自动分流、`?view=desktop` 回退、浏览器刷新及屏幕旋转都不能造成状态丢失或重复订阅。

```bash
./run_vue_preview.sh
# 浏览器：http://127.0.0.1:5173
```

Vite 预览调用本机 `8087` API；页面导航必须保持在 `5173`，不能跳回后端端口。

## 11. 构建、发布与验证

### 11.1 获取源码与开发环境

其他开发者应从 GitHub 获取源码，并使用当前 `v2.0` 分支开始开发：

```bash
git clone https://github.com/Bobiloveu/ry-aletheia.git
cd ry-aletheia
git switch v2.0
```

推荐在与目标小车一致的 Ubuntu 22.04 `amd64` + ROS 2 Humble 环境开发。完整二进制构建还依赖小车业务工作空间的 `master_interfaces` 类型支持库；仅安装通用 ROS Humble 不能替代该接口。开发机至少应具备：Python 3、Node.js 20+、npm、CMake、C++17 编译器、PyInstaller，以及 `rclcpp`、`sensor_msgs`、`geometry_msgs`、`tf2_ros`、`livox_ros_driver2` 的 ROS 2 C++ 开发包。

`v2.0` 使用仓库根目录的 `pixi.toml` 管理可复现的开发工具链：Python 3.10、Node.js 20、CMake、C++ 编译器、PyInstaller 和 pytest。其基础开发环境支持 macOS（Apple Silicon/Intel）、Linux x86_64 与 Windows x86_64。首次进入仓库执行：

```bash
pixi install
pixi run frontend-install
pixi run verify
```

常用任务为 `pixi run test`、`pixi run frontend-check` 和 `pixi run vue-preview`。在 Windows 上，`pixi run vue-preview` 只启动 Vite；需要另开一个终端执行 `pixi run backend` 启动本地 API。Pixi 不管理 ROS 2 Humble、`master_interfaces` 或小车导出的 `install/`：它们仍是目标小车/参考车提供的外部构建前置条件，完整二进制构建及面向小车的升级 ZIP/DEB 只能在匹配的 Linux x86_64 ROS 环境执行。

不使用 Pixi 时，仍可手工安装锁定的前端依赖并确认基础检查：

```bash
cd frontend && npm ci && cd ..
python3 -m pytest -q tests
```

不要提交 `node_modules/`、`build/`、`dist/`、`releases/`、车辆日志、报告、地图缓存或本机 `console.json`。提交前先执行 `git status --short`，只允许源码、测试、文档和构建脚本进入提交。

### 11.2 导入小车专有 ROS 依赖

在一台已正常运行、且与目标环境匹配的参考小车上执行一次最小依赖导出。脚本只读取已有 ROS 安装，不修改小车系统：

```bash
mkdir -p third_party/robot_build_deps
./export_robot_build_deps.sh \
  third_party/robot_build_deps/ry-aletheia-robot-build-deps-humble-amd64.tar.gz
```

压缩包只包含 `master_interfaces`、`livox_ros_driver2` 与加载它们所需的根启动脚本，不包含整车导航、感知、地图、任务或运行数据。仓库中的 `third_party/robot_build_deps/` 受版本控制，便于已获授权的开发者开箱构建；其中含小车专有接口，推送到远程前必须确认仓库成员具有访问权限。将压缩包和对应的 `.sha256` 一并复制到开发机；在干净开发机的源码根目录中解压，使 `install/setup.bash` 与 `build-deps-manifest.json` 出现在工程根目录：

```bash
tar -xzf /path/to/ry-aletheia-robot-build-deps_*.tar.gz -C .
test -f install/setup.bash && test -f build-deps-manifest.json
```

接收方仍必须自行安装匹配的 Ubuntu 22.04 `amd64` + ROS 2 Humble；最小包不是 ROS 发行版替代品。`cpp_sdk/` 不是仓库目录，也不被 `build_binary.sh` 读取。`export_robot_cpp_sdk.sh` 仅保留给需要在无 ROS 开发包的异机构建机上进行原生 C++ 兼容性验证时使用；不要把 SDK 解压到工程根目录、`/opt/ros`，也不要覆盖系统 ROS。

### 11.3 日常开发与本地预览

修改 Vue 页面时，使用下列命令启动 Vite 预览；它会代理本机 `8087` API，浏览器地址保持在 `5173`：

```bash
./run_vue_preview.sh
# 浏览器：http://127.0.0.1:5173
```

修改 C++ 预处理节点或视频输入节点时，先在已 source 的 ROS 环境中进行独立编译：

```bash
source install/setup.bash
cmake -S live_preprocessor -B build/live_preprocessor -DCMAKE_BUILD_TYPE=Release
cmake --build build/live_preprocessor --parallel 2
```

完整构建由 `build_binary.sh` 统一执行：它先构建 Vue 产物、C++ 预处理节点和视频输入节点，再构建锁定的视频私有运行时，最后生成 `dist/ry-aletheia`。可通过 `ROVER_QA_ROS_SETUP=/path/to/setup.bash` 指定参考小车的 ROS 工作空间；未指定时依次使用 `/opt/ry/install/setup.bash` 和工程内 `install/setup.bash`。视频私有运行时也可单独生成，便于检查其锁定依赖：

```bash
./build_binary.sh

# 仅生成私有 MediaMTX / GStreamer / VAAPI runtime（不安装到系统）
./build_video_runtime.sh
```

### 11.4 专用实时遥测的边界

完整离线包不包含通用 ROS-Web Bridge，也不会复制整套 ROS Humble。`ObservationManager` 只拥有 Aletheia 创建的两个 C++ 预处理进程和本机遥测网关：点云 UDP 接收端固定绑定 `127.0.0.1:8769`，位姿 UDP 接收端固定绑定 `127.0.0.1:8770`，浏览器 Binary WebSocket 端口为 `8768`。网关没有 ROS client、topic 发现、订阅选择或控制接口；它只接受具有固定二进制协议的本机点云/位姿帧。

网关健康状态来自自身受控生命周期和有效帧时间，而不是对其他 ROS 服务或 WebSocket 端口做裸 TCP 探测。任何启动、端口占用、无点云、无 TF、浏览器连接失败或源数据过期都会记录到工具日志；网络发送与 ROS 回调隔离，慢浏览器只能丢弃自己的历史帧。

车端 ROS Humble 与业务 ROS 图仍是明确集成契约：`/start_execute_tasks`、TF、地图、雷达驱动、导航、`master_interfaces` 及 Supervisor 属于机器人系统，不随工具复制。完整包只要求目标车为匹配 CPU 架构的 ROS Humble 平台。

### 11.5 私有视频运行时与显卡边界

`build_video_runtime.sh` 仅在开发/构建机执行。它根据 `tools/video-runtime-packages.lock` 下载并校验 Ubuntu 22.04 `amd64` 归档，解包为受限的私有运行时；不会在小车或开发机执行 `apt install`，也不会覆盖系统 GStreamer、VAAPI、ROS 或 MediaMTX。构建后的运行时只暴露受控 `RGB → VAAPI H.264 → RTSP` 链路所需的插件，MediaMTX 版本同样由脚本固定并校验。

2.3.8 的 ShmSDK 试运行要求：ShmSDK 2.0 的 `mempool` 与四路 `CamFront/CamBack/CamLeft/CamRight` 生产端由小车系统持续维护；检测/分割节点仍持续发布配置的 `sensor_msgs/msg/Image`；运行账户可访问相应 ROS 域以及 VAAPI 渲染节点（通常是 `/dev/dri/renderD128`，需要 `render` 权限或等价 ACL）。NVIDIA、纯软件编码或其他 GPU 不会被自动假装成 Intel VAAPI；不满足契约时视频应在页面显示可诊断错误，而不影响地图、点云、任务或报告功能。试运行未验收前，禁止把 `mempool`、相机驱动或 USB/V4L2 配置的维护责任转交给 Aletheia。

### 11.6 发布构建

```bash
# 生成默认 ROS 相机版升级 ZIP
./make_upgrade.sh <版本号>

# 生成 ShmSDK 相机版升级 ZIP。
./make_upgrade.sh <版本号> --shm

# 任一版本可同时生成完整首次安装 DEB。
./make_upgrade.sh <版本号> --deb
./make_upgrade.sh <版本号> --shm --deb
```

完整包输出到 `releases/<版本>-ros/` 或 `releases/<版本>-shm/`，文件名也带 `_ros` 或 `_shm` 后缀；发布人员必须把相应文件交给相应车辆。其 `DEB` 不依赖系统通用 ROS-Web Bridge，且包内包含 MediaMTX 和最小视频运行时。`build_offline_foxglove_bundle.sh` 仅作为兼容旧发布入口的脚本名保留，实际只生成当前完整 DEB，输出到 `releases/<版本>-offline/`。网页升级 ZIP 会替换新的控制台核心，其中包含专用遥测网关；视频运行时则在下一次启用视频时自动、安全地同步。ZIP 始终仅含 `manifest.json` 和 `ry-aletheia` 两项：清单同时保留 MD5（供旧升级器过渡读取）、SHA-256 和 Ed25519 发布签名；新控制台必须验证内置公钥对应的签名。发布私钥通过 `RY_ALETHEIA_UPGRADE_SIGNING_KEY` 指定，默认位于被 Git 忽略且仅发布人员可读的位置，绝不可随源码或发布包分发。

版本号必须为数字点号格式。脚本会拒绝覆盖已有发布目录，并在 `releases/<版本>/` 输出 ZIP、`SHA256SUMS`、说明和可选 DEB。

发布前要在干净工作树或明确记录的变更集上完成：校验 `SHA256SUMS`、`unzip -t` 升级 ZIP、确认 ZIP 中没有车辆配置/日志/私钥，并检查 `postinst` 的 `visudo -cf`。首次安装 DEB 与已安装车的 ZIP 升级分别验证；不要因 ZIP 正常就假设 DEB 的安装脚本也正常。涉及试运行接入时，发布前必须准备上一稳定版本的**已签名**回退 ZIP，并记录其校验值、适用车端版本和恢复检查项；具体流程见 [ShmSDK 视频接入试运行记录](docs/SHMSDK_VIDEO_TRIAL_2.3.8.md)。

### 11.7 每次改动后的最小验证集

```bash
env -u PYTHONPATH pixi run verify
npm --prefix frontend run check
cmake --build build/live_preprocessor --parallel 2
```

发布前仍需低风险实车验证：任务下发、Supervisor 阶段等待、方案应用/恢复、地图切换、报告下载、升级回滚和实时观测的移动/缩放表现。涉及视频时，额外验证六路流（含 `/rfdetr_detect` 与 `/segmentation/overlay`）的 MediaMTX `ready/online` 状态、浏览器 WebRTC 播放、关闭后进程树回收，以及视频失败不影响其余观测功能或自动驾驶执行。

实时遥测变更还必须单独验证：点云完整帧、乱序分片、丢片、重复分片、新帧覆盖旧帧、异常分片和残帧超时；位姿的初连、断开重连、慢客户端、连续刷新与 TF 暂时不可用。实车压力测试时，以小车本机 `htop` 记录 Aletheia 的 C++ 预处理进程、控制台进程和原自动驾驶进程的 CPU/内存；不得只凭打开观测页后的视觉效果判断性能。

## 12. 常见排障

| 现象 | 优先检查 |
| --- | --- |
| 服务可见却无法调用 | 普通账户的 ROS_DOMAIN_ID、RMW 环境、`/opt/ry/install/setup.bash`、`master_interfaces` 类型支持库。 |
| 重启节点后立即失败 | 编排是否等待每阶段全部 `RUNNING` 和稳定时间；方案应用后是否留出稳定窗口。 |
| 无点云或位姿 | 先看 `/api/observation`：`telemetry.online`、预处理进程状态与 `client_metrics.cloud_packet_rate_hz` 是否非零；再看 `logs/live_preprocessor_cloud.log`、`logs/live_preprocessor_pose.log`。确认 `/collision_voxel_layer/points` 有发布者和非零频率，`map → base_*` TF 可查询；主流缺失 500ms 后才会尝试 `/livox/lidar` 回退。 |
| 观测落后实车 | 先读取 `/api/observation` 的 `client_metrics`：位姿年龄低而 `cloud_source_age_ms` 高时优先检查激光源时间戳/频率；再检查预处理日志、Wi-Fi 与浏览器长帧。不要提高队列深度或恢复长点云历史。 |
| 点云基本正常但车体图标卡顿 | 先比较 `pose_packet_rate_hz`、`pose_applied_rate_hz`、`pose_source_age_ms`、`vehicle_render_rate_hz` 和长帧数；再检查 `live_preprocessor_pose.log` 及 `map→odom→base_*` 的真实值变化。若链路心跳连续但坐标变化稀疏，检查前端是否把重复 Pose 的接收时间误作最后真实测量时间。 |
| 地图/墙体不对齐 | `/map` origin/resolution、map_server 当前 YAML、缓存 ID、实际墙体文件。 |
| 轨迹缺段 | map/TF 可用性、切图、坐标变换拒绝原因和报告中的证据提示。 |
| 视频卡片一直“等待相机” | 先看 `GET /api/video/status` 与 MediaMTX paths；四路物理相机检查 `logs/video-runtime.log` 中 ShmSDK 的 `InitMem/OpenMem/GetLastCamImage` 诊断以及小车 `mempool`/相机生产端；检测、分割再确认 ROS 图像话题有发布者、`ROS_DOMAIN_ID` 与控制台一致、像素格式/分辨率符合 `config/video.json`。 |
| ShmSDK 试运行需停止或回退 | 先关闭所有视频流，确认没有执行中/恢复中的测试；在“运行配置”上传维护人员提供的已签名 2.3.7 回退 ZIP。不要手工覆盖 `dist/ry-aletheia`、改 `mempool` 或重启原相机驱动；完整判断与验证项见 [试运行记录](docs/SHMSDK_VIDEO_TRIAL_2.3.8.md)。 |
| 视频启动失败或无硬件编码 | 检查 `runtime/video/` 是否完整、`/dev/dri/renderD128` 的 ACL/`render` 组、Intel `iHD` 驱动、`logs/` 中视频运行时错误；不要为此修改系统 GStreamer 或让工具接管原相机驱动的 Supervisor 组。 |
| 升级后视频无法启动 | 确认升级 ZIP 已替换核心二进制；打开网页视频开关以触发私有运行时同步，检查 `runtime/video/ry-aletheia-runtime.json`，同时保留并核对既有 `config/video.json`。 |
| 升级后不能启动 | `updates/` 备份、`logs/ry-aletheia-error.log`、8087 端口占用、二进制权限。 |

## 13. 安全红线与维护准则

- 不使用 `sudo ./dist/ry-aletheia`；控制台应由普通账户运行。
- 受限 sudo 仅允许 `supervisorctl status/start/restart`，不得扩大为任意命令。
- 不覆盖机器人目标任务目录中已有的同名任务文件。
- 不将场景前置功能扩展为无约束的任意文件写入器。
- 不在 `running`、`cancelling`、`awaiting_recovery` 状态升级。
- 不以提高队列深度或保存历史帧换取“连续感”；实时性优先。
- 不为诊断而对机器人已有 WebSocket 服务做裸 TCP 探测；专用遥测网关只使用自身受控状态和有效帧时间健康检查。
- 未经明确确认，不自动创建升级包、DEB 或部署到小车。

工程维护遵循：静态数据缓存、动态数据分层；高频路径限频/单槽队列/背压/超时丢弃；低频配置原子写入与备份；每次修改必须有编译、构建或回归测试，并定义缺地图、缺 TF、缺接口、端口冲突、权限不足等失败降级路径。

## 14. 维护交接清单

### 14.1 先定位责任边界

| 变更目标 | 首选代码位置 | 必须保持不变的边界 |
| --- | --- | --- |
| 测试流程、恢复、报告 | `autodrive_console/run_manager.py` 及相关后端模块 | 不扩大 Supervisor 白名单；场景配置必须可恢复。 |
| 实时地图、位姿、点云 | `frontend/src/liveObservation.js`、`live_preprocessor/`、`observation.py` | ROS 原话题只读；容量 1、latest-wins、过期丢弃。 |
| 视频按钮、流布局与播放 | `frontend/src/liveObservation.*`、`autodrive_console/video.py` | ROS 发布包读取 ROS Image；ShmSDK 发布包仅读取固定四路 `Cam*` 最新帧；Python 不承载视频帧，不管理物理相机。 |
| 通用移动端壳层 | `autodrive_console/web/mobile_console.*` | 仅 `/m/` 或明确限定选择器生效，不能污染 PC。 |
| 离线包、安装/卸载 | `make_upgrade.sh`、`build_*`、`packaging/debian/` | 保留用户数据；ZIP 与 DEB 都必须可校验、可回退。 |

### 14.2 每次合并前的最低检查

1. 运行 `env -u PYTHONPATH pixi run verify`；前端改动还必须完成生产构建。
2. 审查 `git diff --check` 与 `git status --short`，确认没有构建产物、车辆配置、日志、报告、缓存或凭据进入提交。
3. 实时链路改动须验证缺地图、缺 TF、遥测网关未启动、浏览器后台、网络恢复五种降级；不能只在正常网络下看一次页面。
4. 移动端改动按 10.2 的横竖屏、低高度和 1～6 路视频矩阵实测，同时复查 PC 页面未被影响。
5. 准备发布时分别走 ZIP 升级和全新 DEB 安装的检查表，确认程序版本、配置保留、备份回滚和观测/视频按需启动。

### 14.3 现场信息收集顺序

先记录工具版本、复现时间、浏览器/设备类型和是否开启视频；随后导出工具日志并采集 `ry-aletheia-status --once`、`/api/observation`、`/api/video/status`。只有在这些证据指向小车 ROS 链路时，再请机器人系统维护者检查对应话题、TF 或相机驱动。这样能避免把网页问题误处理为导航问题，也避免为视频问题重启整车相机栈。
