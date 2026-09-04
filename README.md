# RY Aletheia 自动测试平台

RY Aletheia 是部署在机器人小车本机的离线自动测试平台，用于管理测试用例、恢复受控运行依赖、执行多轮任务、记录多地图轨迹，并生成可离线查看的测试报告。

它不替代小车已有的导航、定位、地图或安全控制系统；实时页面仅用于只读观察地图、车体、虚拟墙、点云和按需低延迟相机视频。

## 开发入口

先按职责运行 `./scripts/doctor.sh --profile <profile>`；未选择模块的工具显示
`OPTIONAL`，当前操作系统不支持的 iOS 工具显示 `UNSUPPORTED`，不会阻断 Backend、Web
或 Android 开发。完整的角色、操作系统和命令矩阵见
[docs/development/PROFILES.md](docs/development/PROFILES.md)。

| 开发域 | 实际位置 | 最小命令 |
| --- | --- | --- |
| Robot Backend | `web_console.py`、`autodrive_console/`、`live_preprocessor/` | `./scripts/test-backend.sh` |
| Web Console | `frontend/` | `./scripts/test-web.sh` |
| Flutter Mobile Android | `mobile/` | `./scripts/test-mobile.sh`（先安装 FVM） |
| Flutter Mobile iOS | `mobile/` | macOS 上使用 `fvm flutter build ios --simulator --debug --no-codesign` |
| Unity | `unity/` | 当前暂停，不属于默认构建 |

源码尚未物理迁移到 `apps/`；迁移条件见
[架构文档](docs/architecture/monorepo-migration.md)。跨端 API、ROS Topic、WebSocket 和
数据格式的唯一文档入口是 [shared/contracts](shared/contracts/README.md)。更多开发说明见
[架构](docs/architecture/README.md)、[后端](docs/backend/README.md)、
[Web](docs/web/README.md)、[Mobile](docs/mobile/README.md) 和
[部署](docs/deployment/README.md)。

不同模块只准备自身需要的工具链：Backend/Web 使用 Pixi；Mobile 使用 FVM；Android 需要
JDK 和 Android SDK；iOS 只在 macOS 上额外需要 Xcode 与 CocoaPods。根脚本目录见
[scripts/README.md](scripts/README.md)。

## 快速开始

目标小车应已具备 ROS 2 Humble 基础运行环境。首次安装完整离线包后，以普通账户启动：

```bash
sudo dpkg -i ./ry-aletheia_<版本号>_amd64.deb
ry-aletheia
```

测试电脑与小车连接同一 Wi-Fi 后，在浏览器打开：

```text
http://<小车IP>:8087
```

已部署旧版本时，优先在“运行配置 → 工具离线升级”上传维护人员发布的 `ry-aletheia_<版本号>.zip`；无需重新安装 DEB。新版本会在替换前校验 Ed25519 发布签名与 SHA-256 完整性，校验失败不会替换当前程序。

实时观测中的“低延迟相机流”默认关闭。页面既可统一启停全部视频，也可逐路任意开关；视频窗口会随当前启用的路数自适应排布。关闭最后一路后，工具会停止并回收自己的 MediaMTX 与视频编码进程，不需要使用 Supervisor 或额外的常驻管理命令。

> **视频发布配置**：`./make_upgrade.sh <版本号>` 默认生成 ROS 相机版；`./make_upgrade.sh <版本号> --shm` 生成 ShmSDK 相机版。前、后、左、右四路仅随发布配置切换；目标检测与分割始终读取既有 ROS 图像话题。ShmSDK 现场边界与观察项见 [ShmSDK 视频接入试运行记录](docs/SHMSDK_VIDEO_TRIAL_2.3.8.md)。

完整安装、移动端使用、页面操作、人工恢复、升级和常见问题请阅读 [USER_GUIDE.md](USER_GUIDE.md)。

## 运行与维护边界

维护前先明确以下归属，避免工具升级意外影响正在运行的小车：

- **机器人系统拥有**：相机 USB 设备、`/dev/video*`/v4l2loopback 映射、ROS 相机节点、定位、导航、地图、雷达和底盘控制。
- **Aletheia 只读使用**：地图、TF、点云，以及检测/分割的既有 `sensor_msgs/Image` 话题。ROS 发布包的前、后、左、右相机读取原始 ROS 话题；仅 ShmSDK 发布包只读访问固定 `Cam*` 最新图像。两种配置都不会直接打开摄像头设备，也不会启动、停止或配置 `mempool`。
- **Aletheia 自己拥有**：8087 控制台、按需运行的专用遥测网关（回环 UDP 与 Binary WebSocket）、点云/位姿/局部代价地图预处理进程，以及按需运行的 MediaMTX 和视频编码进程。它们不由 Supervisor 管理。
- **用户数据不随 ZIP 覆盖**：`tasks/`、`config/`、报告、地图缓存和日志都被保留。升级包只替换程序二进制，并自动留下可回退备份。

现场先用 `ry-aletheia-status --once` 确认控制台与视频运行器的资源状态；再从“运行配置”或 `GET /api/observation`、`GET /api/video/status` 判断观测链路。不要为排障停止或重启小车已有的相机、导航、定位和 Supervisor 进程。

## 版本与发布

发布包仅通过 [GitHub Releases](https://github.com/Bobiloveu/ry-aletheia/releases) 交付：

- `ry-aletheia_<版本号>.zip`：已安装工具的小车在网页中离线升级使用。
- `ry-aletheia_<版本号>_amd64.deb`：新小车首次部署或需要完整重装时使用。

仓库中的 `releases/` 是本地构建输出目录，默认不纳入版本控制；不要将 ZIP、DEB、日志、报告或车辆配置提交到源码仓库。

## v2.0 分支说明

`v2.0` 是独立开发分支，`v1.0-baseline` 保持 v1.0 基线内容；当前 v2.0 改动不会自动进入 1.0，除非后续明确合并。

| 范围 | `v1.0-baseline` | `v2.0` |
| --- | --- | --- |
| 实时二维地图 | Canvas 静态地图、点云 Canvas/Worker 合成 | PixiJS 场景树：地图纹理、虚拟墙与最新点云独立图层 |
| 地图交互与车体 | CSS 视图变换、DOM 车体层 | PixiJS 世界容器变换、保留 DOM 车体层 |
| 点云时效策略 | 单槽 latest-wins、限频合成 | 保持相同单槽 latest-wins、限频与过期帧丢弃策略 |
| 相机预览 | 原生 Canvas 2D 绘制 | 可选的 MediaMTX + WHEP/WebRTC 直出；浏览器原生视频元素解码，视频帧不经过 Python 或实时遥测链路 |
| ROS/遥测/API | 既有实现 | 点云/位姿与 PC 局部代价地图使用专用 UDP + Binary WebSocket；保持既有控制边界，不新增机器人控制接口 |
| 开发工具链 | 手工管理 Python、Node 与构建工具 | 根目录 `pixi.toml`/`pixi.lock` 锁定 Python 3.10、Node 20、CMake、编译器、PyInstaller 与 pytest |

`v2.0` 将地图、虚拟墙和点云重构为 PixiJS 分层渲染；相机则采用独立的按需 WebRTC 链路。目标检测和分割视频继续读取既有 ROS 图像话题；前、后、左、右物理相机由发布配置选择 ROS 或 ShmSDK 只读旁路。两者都只在工具私有运行时内编码、转发，不改变任务下发、Supervisor 编排、ROS2 原有节点或机器人控制边界。详细设计和环境边界见 [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md)。

## 主要能力

- 测试用例导入、校验、别名管理及跨车用例包交付。
- 专项自动测试：以既有任务 JSON 承载电梯连续进出、门禁多次通行、多任务连续配送、往返运行、窄通道等真实场景；可设置轮次与间隔，正常轮次自动串行执行。失败会记录结果并进入人工恢复，而非在异常位置无条件重复发车。
- 多轮串行测试、场景前置参数的事务化受控替换、Supervisor 依赖编排与人工恢复；场景应用和恢复均验证受控运行依赖已重新读取脚本。每轮保留耗时、服务反馈、通过/失败、人工干预与轨迹证据，并自动统计成功次数、失败次数、已完成次数和通过率。
- 多地图轨迹、理想路径与虚拟墙证据，以及 HTML/CSV 离线报告。
- 部署验收：从正式任务只读生成冻结计划；抽样按实际物理楼宇单元（`栋号 + 单元`）优先覆盖，显示实际覆盖范围而不是要求覆盖每层、每户。场景方案和 Supervisor 依赖编排均为可选运行准备，未选择时按常规验收流程执行；选择后在整份验收开始前统一执行一次，并在页面显示当前准备阶段。结束时只恢复常规启动配置，不逐项重启节点。验收完成后会生成带范围、时间、结果与轨迹证据的离线 HTML/CSV，并与自动测试报告一同归档到“报告中心”。
- 低延迟实时观测：PC Web 保持 PixiJS 高对比地图观测界面；移动端使用 Flutter `CustomPaint` 渲染地图、米制格栅、虚拟墙、点云和车体。四路工业相机、目标检测结果图和可通行区域分割图经可选 MediaMTX/WebRTC 直出，并可由网页按需启停。
- 机器人日志下载：PC 的独立页面可维护当前小车本机日志目录，按文件名检索并逐文件下载到打开网页的电脑；页面显示小车到浏览器的传输进度。默认仅在下载副本中把可识别 ROS 时间转为北京时间，关闭后保留原始文件。它不使用 SSH/SFTP，也不与“工具日志”混合。
- PC 桌面布局与独立移动端界面；全部 `/m/` 业务页使用统一的品牌栏、五项底部导航和石墨暖灰主题。手机实时观测同时适配横屏、竖屏及带常驻地址栏的低高度视口：浅横屏优先呈现可读的横向地图工作区，可在地图与六路 WebRTC 相机之间单触切换。页面缩放被锁定，双指缩放仅作用于地图世界视图。
- 完整离线 DEB 不携带通用 ROS-Web Bridge，不改写小车已有 ROS 环境。

### 专项自动测试的适用边界

工具负责重复执行、状态编排、证据采集和统计，不替代任务系统对物理世界的语义判断。电梯流程会识别预期等待并抑制普通停滞误报；门禁、窄通道、配送和往返等场景由真实任务路线定义。报告会保留任务返回消息、当前轮次、轨迹位置、停滞/电梯等待状态及人工干预，作为失败节点定位依据；只有上游任务服务实际提供具体站点或门禁标识时，工具才会把失败准确归因到该物理节点。当前不接入门禁设备状态或通道宽度测量来凭空判定通过。

## 系统结构

```text
浏览器（PC / 手机）
  ├─ HTTP :8087：控制台、任务、报告与配置
  ├─ Binary WebSocket :8768：点云、位姿与 PC 局部代价地图实时观测
       └─ PixiJS：地图栅格、局部代价地图、虚拟墙、最新点云
  └─ WHEP/WebRTC :8889：低延迟相机视频直出
             │
RY Aletheia（小车普通账户）
  ├─ Python 控制台与测试编排
  ├─ C++ 实时预处理：/collision_voxel_layer/points（Livox 原始流回退）→ 回环 UDP 最新帧
  ├─ 专用遥测网关：UDP 组装最新帧 → 三条 Binary WebSocket
  └─ 可选视频运行时：ShmSDK 最新图像（四路试运行）或 ROS Image（检测/分割）→ 原生 RGB 输入 → VAAPI H.264 → 本机 MediaMTX
             │
小车已有 ROS 2 Humble、定位、地图、导航与传感器节点
```

实时位姿、点云和 PC 局部代价地图分别使用网页专用流，浏览器侧采用独立连接与“只保留最新帧”策略。PixiJS 只更新地图世界容器、最新点云几何或单张代价地图 texture，车体仍由独立 DOM 层显示，避免大帧拖慢车体显示。视频走浏览器与 MediaMTX 的直连 WebRTC 会话：Python 只负责配置、进程生命周期和健康状态，绝不转发视频帧。

### 实时观测链路约束

实时观测不启动、也不经由 `foxglove_bridge`、`rosbridge_suite` 或隐藏 ROS topic。点云由 C++ 预处理进程读取 ROS 点云、投影到 `map` 后，以回环 UDP 交给 Aletheia 遥测网关；位姿由另一独立 C++ 进程读取 `map → base_*` TF；局部代价地图由第三个轻量实例读取 `/local_costmap/costmap`，按消息时间戳将 `header.frame_id` 与栅格原点投影到 `map`。网关向 PC 浏览器暴露三条 Binary WebSocket（同为 `:8768` 的 `/cloud`、`/pose`、`/costmap`）；移动端不连接或渲染 costmap，不具备 ROS 图发现、订阅、服务或控制能力。

- UDP 仅绑定本机：点云为 `127.0.0.1:8769`、位姿为 `127.0.0.1:8770`、局部代价地图为 `127.0.0.1:8771`；每个分片 payload 最多 1152 Byte，UDP 包不会依赖 IP 分片。
- 点云仅保留最新完整帧：最多 3000 个 `float32 x/y` 点；丢片、过期、乱序旧帧或网络拥塞都直接丢弃，不确认、不重传、不补历史。
- 位姿只发送网页所需的 `timestamp / seq / x / y / yaw`，与点云使用独立进程、UDP 入口/发送槽、WebSocket 和浏览器渲染节奏；慢浏览器只能丢弃自己的旧帧，不能反压 ROS 回调。
- 局部代价地图只供 PC：最多 65,535 个原始 OccupancyGrid cell，以单张动态纹理绘制。局部图无 TF、过期或切图时安全隐藏，恢复后只显示最新有效帧；其独立通道不能影响点云或位姿。
- 页面关闭后，观测进程依照空闲回收策略停止；控制台退出或升级前会主动回收其遥测网关和预处理子进程。详细协议、故障边界和实车验证清单见 [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md#9-实时运行观测的工程策略)。

## 文档

| 文档 | 面向对象 | 内容 |
| --- | --- | --- |
| [USER_GUIDE.md](USER_GUIDE.md) | 测试人员、部署人员 | 安装、启动、页面操作、手机端、执行测试、升级、卸载与常见问题。 |
| [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) | 开发、维护人员 | 架构、数据边界、实时链路、构建、测试与现场排障。 |
| [docs/SHMSDK_VIDEO_TRIAL_2.3.8.md](docs/SHMSDK_VIDEO_TRIAL_2.3.8.md) | 现场试运行、维护人员 | 四路 ShmSDK 接入边界、已完成验证、观察项、停止条件与安全回退。 |
| [live_preprocessor/README.md](live_preprocessor/README.md) | C++ 模块维护人员 | 实时点云/位姿/局部代价地图预处理节点的构建与运行参数。 |
| [GitHub Releases](https://github.com/Bobiloveu/ry-aletheia/releases) | 发布与部署人员 | 下载正式 ZIP 与 DEB 发布包。 |

## 仓库结构

```text
autodrive_console/  Python 业务模块、正式网页资源与移动端壳层
frontend/            Vue/Vite 前端源码与 PixiJS 实时地图渲染
live_preprocessor/   ROS 2 C++ 实时点云、位姿与局部代价地图预处理节点
                     及 ROS 图像到 H.264 的原生视频输入节点
tests/               自动化回归测试
docs/images/         用户操作指南配图
packaging/           Debian 安装、启动与卸载脚本
build_*.sh           构建离线依赖、二进制和 DEB 的脚本
make_upgrade.sh      生成网页升级 ZIP 与完整离线 DEB 的发布入口
```

## 开发与验证

`v2.0` 使用 Pixi 管理 Python、Node.js、CMake、编译器、PyInstaller 与 pytest，支持 macOS（Apple Silicon/Intel）、Linux x86_64 和 Windows x86_64 的前端开发与基础验证；ROS 2 Humble 及小车专有接口仍需从参考车导入。完整前置条件、命令和发布检查表见 [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md)。首次初始化及基础验证：

```bash
pixi install
pixi run frontend-install
pixi run verify
```

## 支持与反馈

提交问题时请附上工具版本、复现步骤、页面截图和“工具日志”导出的诊断文件。日志可能包含内部节点、端口和运行信息，请勿公开其中的敏感环境数据。
