# 局部代价地图实时观测实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to execute this plan task-by-task.

**Goal:** 在不改变既有地图、点云、位姿、视频和移动端行为的前提下，把 ROS2 `/local_costmap/costmap` 以独立、latest-wins 的二进制实时通道显示到 PC 端实时运行观测中。

**Architecture:** 新增第三条 `costmap` 实时链路：ROS `OccupancyGrid` 由独立 C++ 预处理进程读取，在工作线程中按消息时间戳将栅格原点从其源坐标系转换到 `map`，经 RALT UDP loopback 发送给 `TelemetryGateway`，再以 ALTM Binary WebSocket 独立发给 PC 浏览器。前端以单张动态 PixiJS texture 渲染代价栅格；它不会复用或阻塞点云、位姿、地图缓存或视频链路。

**Tech Stack:** ROS2 Humble、C++17/rclcpp/tf2/nav_msgs、非阻塞 UDP、Python asyncio/socket/WebSocket、PixiJS、Vite、pytest。

**Spec:** `docs/superpowers/specs/2026-09-04-local-costmap-realtime-design.md`

## Global Constraints

- 仅修改 PC Web 的实时观测数据接入与渲染；`mobile/`、移动端观测连接和 UI 不新增 costmap。
- 不改已有 `map` 快照、虚拟墙、点云、位姿、MediaMTX/WebRTC、任务执行、控制和配置业务逻辑。
- 保持既有 UDP RALT 30-byte 外层头与 ALTM WebSocket 外层头的二进制兼容性；新增 lane 使用 `kind=3`。
- UDP 与 WebSocket 均采用 latest-wins：不确认、不重传、不缓存历史帧；慢客户端最多保留一个待发完整帧。
- ROS 回调不得进行 TF 查询、编码、网络发送或等待；只校验并覆盖最新输入槽。
- 成本地图 `header.frame_id` 可能是 `odom`；必须按 `header.stamp` 查询 `map <- source`，不能把当前实车的 identity 变换写死。
- 代价地图默认可见但可临时隐藏；隐藏只停止前端绘制，不能停订阅、停进程或改变自动驾驶。
- 不提交构建产物、运行日志、地图、缓存或任何现有未提交工作的文件。

---

### Task 1: 为 RALT/ALTM 增加受限的 costmap 协议与网关 lane

**Files:**
- Modify: `autodrive_console/telemetry.py`
- Modify: `tests/test_telemetry.py`
- Modify: `shared/contracts/realtime_observation.md`

**Step 1: 先写失败的协议与 latest-wins 测试。**

在 `tests/test_telemetry.py` 为 `_LatestFrameAssembler` 增加真实二进制 datagram 测试，覆盖：

- `kind=3` 完整 160×160 costmap，20-byte metadata 加 25,600-byte raw cells；
- 乱序分片能够完成一个最新完整帧；
- 缺片帧不能产出；重复分片不会重复完成；新 `frame_seq` 到达会淘汰旧未完成帧；
- `record_count > 65535`、`width * height != record_count`、短 payload、超长 payload、错误 chunk index/count 和错误 kind 都被丢弃；
- cloud 与 pose 的既有解析边界仍保持不变。

运行：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest -q tests/test_telemetry.py -k costmap
```

预期：新增测试在协议支持前失败。

**Step 2: 用最小改动扩展协议。**

在 `autodrive_console/telemetry.py` 中：

- 定义 `KIND_COSTMAP = 3`、`COSTMAP_UDP_PORT = 8771`、`MAX_COSTMAP_CELLS = 65535`、`COSTMAP_META_STRUCT = struct.Struct("!ffffHH")`；metadata 字段为 `map_origin_x/y/yaw`、`resolution`、`width`、`height`。
- 保持 RALT `!4sBBIIQHHHH` 的总长度和字段顺序不变；将 Python 内部语义名由 `point_count` 改为 `record_count`，但不改变 wire bytes。
- 让 `_LatestFrameAssembler` 按 kind 校验 raw payload：cloud 为 `record_count * 8`，pose 为 `12`，costmap 为 `20 + record_count`；完整帧才解析 `width * height == record_count`，并要求正分辨率及有限浮点元数据。
- 保持单个最新 frame assembler；帧序号推进时立即丢弃旧 incomplete frame，过期 partial 受固定 TTL 清理，且没有无限队列。
- 给 gateway 增加独立 loopback UDP socket/thread、`/costmap` WebSocket path、单待发 payload 客户端和 `costmap` 客户端/包率/源年龄 metrics。未知 path 一律按现有方式拒绝，不发起任何 TCP 探测。

**Step 3: 更新明确的协议契约。**

在 `shared/contracts/realtime_observation.md` 记录：lane `costmap`、RALT/ALTM `kind=3`、payload 的网络字节序、OccupancyGrid `-1 -> uint8 255` 约定、最大 65,535 cells、无 ACK/重传/历史缓存与 PC-only 消费者范围。

**Step 4: 验证。**

运行：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest -q tests/test_telemetry.py
```

预期：协议测试全部通过，既有 cloud/pose 测试不退化。

### Task 2: 在 C++ 预处理器中实现独立 costmap 输入槽、TF 投影与编码

**Files:**
- Modify: `live_preprocessor/CMakeLists.txt`
- Modify: `live_preprocessor/package.xml`
- Modify: `live_preprocessor/src/live_cloud_preprocessor.cpp`
- Modify: `live_preprocessor/README.md`

**Step 1: 先增加可编译边界与源级断言。**

在现有 live observation 测试中增加针对 C++ 源的回归断言，确认 `nav_msgs/msg/occupancy_grid.hpp`、`enable_costmap`、`/local_costmap/costmap`、`SensorDataQoS`/可靠持久 QoS、`map_frame` TF 查询和 costmap worker 都存在；并确认 costmap callback 内不直接调用 TF 或 `UdpLatestSender::submit`。

运行 Task 1 的测试命令，预期新增源级断言在实现前失败。

**Step 2: 声明 ROS 依赖。**

在 `live_preprocessor/CMakeLists.txt` 和 `live_preprocessor/package.xml` 增加 `nav_msgs`，并把它加入 `ament_target_dependencies`。不引入新的 ROS bridge 或 Python 中转。

**Step 3: 实现受控 costmap 模式。**

在 `live_cloud_preprocessor.cpp`：

- 新增参数 `enable_costmap`（默认 false）、`costmap_input_topic`（默认 `/local_costmap/costmap`）和 costmap UDP port；cloud 与 pose 进程显式传 false，costmap 进程显式传 true。
- 使用 `rclcpp::QoS(1).reliable().transient_local()` 订阅，保证工具晚于 local_costmap 启动时仍可拿到最后一帧。
- callback 只检查 `width`、`height`、`data.size()`、上限与有限 resolution 后，在短 mutex 内覆盖 `latest_costmap_input_`；不能做 TF、RGBA 转换、分片或 send。
- 独立成本图 worker 从槽取走最新输入，按 `header.stamp` 查询 `map <- header.frame_id`；把 `info.origin` 复合为 `T_map_grid_origin = T_map_source * T_source_grid_origin`，从所得变换编码 map 原点位置和 yaw。无 TF、过期输入、零尺寸/超限或不一致 data 时丢弃且限频记录原因。
- payload 按 `!ffffHH + uint8 cells` 编码；把 ROS `int8` cell 逐字节保持为 unsigned 值，使 `-1` 成为 `255`。`UdpLatestSender` 接到完整 frame 只在独立网络线程发送，单 payload 不超过 1152 bytes；网络拥塞只可覆盖旧待发 frame。
- costmap 不共享 cloud 计算、cloud rate 限制或 pose timer；任一 lane 异常不终止其他 lane。

**Step 4: 文档化运行边界。**

在 `live_preprocessor/README.md` 增加 costmap 的 topic、QoS、map-frame TF 规则、帧率不主动放大、最大 payload/cell 限制和 latest-wins 说明。

**Step 5: 验证编译。**

在可提供 ROS2 Humble 依赖的环境运行：

```bash
source /opt/ros/humble/setup.bash
colcon build --packages-select aletheia_live_preprocessor
```

预期：目标编译成功。若开发机无 ROS2/colcon，此项只记录为实车构建检查，不以假设代替结果。

### Task 3: 接入 Observation 生命周期、状态和运行文档

**Files:**
- Modify: `autodrive_console/observation.py`
- Modify: `tests/test_live_observation_realtime.py`
- Modify: `PROJECT_OVERVIEW.md`
- Modify: `README.md`

**Step 1: 先写失败的生命周期测试。**

在 observation manager 现有 mock/Popen 测试模式中断言：

- `enable_telemetry` 开启时会启动 cloud、pose、costmap 三个同一二进制的独立进程；
- costmap 命令包含独立 node 名 `ry_aletheia_live_costmap`、`enable_cloud:=false`、`enable_pose:=false`、`enable_costmap:=true` 和 `TelemetryGateway.COSTMAP_UDP_PORT`；
- cloud/pose 命令显式携带 `enable_costmap:=false`；
- status 暴露 `preprocessor.costmap_managed`、`clients.costmap`、costmap packet/source-age 指标，停止/异常状态与 cloud/pose 一致。

运行：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest -q tests/test_live_observation_realtime.py -k "preprocessor or observation"
```

预期：新增断言在接入前失败。

**Step 2: 最小化接入。**

在 `ObservationManager._start_preprocessor` 增加 `costmap` 定义，沿用既有可执行文件、日志、健康检查、停止和重启机制；不得为 costmap 新增 HTTP 服务器、ROS node 或独立配置系统。把 status allowed client metrics 扩展为 costmap。

**Step 3: 同步运行事实。**

在 `PROJECT_OVERVIEW.md` 和 `README.md` 中标明：实时观测现含 cloud/pose/costmap 三条专用二进制链路；costmap 源是 `/local_costmap/costmap`，`frame_id` 按消息动态转换到 map；该新视图仅 PC 消费，旧地图与视频链路不受影响。

**Step 4: 验证。**

重新运行 Task 3 的 pytest 命令，预期通过，且没有改变默认遥测关闭时的行为。

### Task 4: 在 PC PixiJS 观测页接入和绘制 costmap

**Files:**
- Modify: `frontend/live-observation.html`
- Modify: `frontend/src/liveObservation.js`
- Modify: `frontend/src/liveObservation.css`
- Modify: `tests/test_live_observation_realtime.py`

**Step 1: 使用前端设计约束并写失败检查。**

执行 Impeccable 的 `craft-floor` 和 `impeccable` 流程，维持现有观测页视觉系统。为前端增加测试/源级断言：PC 使用 `/costmap` binary lane；移动端没有 lane 和控件；解析器验证 ALTM kind、metadata、cell count；显示层位于 map/grid 上方、虚拟墙与点云下方；单 texture 生命周期可销毁；数据超过 5 秒后隐藏。

**Step 2: 实现二进制接入与 latest-wins 解析。**

在 `liveObservation.js`：

- 新增 costmap connection state、一个待渲染完整 frame 和独立 `openLane("costmap", "/costmap", ...)`；只在 `!mobileConsoleEnabled()` 时连接。
- ALTM parser 仅接受 `kind=3`，以 network byte order 解码 `!ffffHH`，验证 raw `20 + width * height`，拒绝超限/非法 packet；新完整帧覆盖待渲染帧，浏览器不保留历史数组。
- 不将 data 转为 JSON、Base64、PNG 或逐 cell Pixi object；将一个 Uint8Array 转为一个 RGBA buffer，更新一张 `Texture`。仅尺寸改变时重建并 destroy 旧 texture。
- 正确处理 OccupancyGrid 行方向与 Pixi y 轴：通过 texture 行翻转或局部 transform，使 `(0,0)` 表示 `info.origin` 的地图坐标下角；应用协议内 map 原点和 yaw，不能默认 odom=map。
- 色彩：unknown（255）/0 全透明，1–252 半透明黄橙梯度、253 强橙、254 红色；虚拟墙仍为红线，点云仍为现有深紫且在 costmap 上层。
- 帧到期、WebSocket close、页面 hidden/visible 和 renderer teardown 都安全清空/销毁 costmap texture，不改变其他 renderer 资源。

**Step 3: 加入轻量 PC 控件。**

在 `live-observation.html` 增加与现有地图控件风格一致的“局部代价地图”可见性开关，默认勾选、不持久化。`liveObservation.css` 只添加此控件的必要状态和小屏隐藏规则；不要新增移动端布局或大面积重设计。

**Step 4: UI 静态检查与生产构建。**

运行：

```bash
node /home/bob/.codex/skills/impeccable/scripts/detect.mjs --json frontend/live-observation.html frontend/src/liveObservation.js frontend/src/liveObservation.css
./scripts/test-web.sh
```

预期：检测器没有阻塞性发现，Vite 生产构建通过。构建产生的 `autodrive_console/web-vue/` 输出不加入提交。

### Task 5: 全链路回归、协议模拟与实车验收

**Files:**
- Modify: `tests/test_live_observation_realtime.py`
- Modify: `docs/superpowers/specs/2026-09-04-local-costmap-realtime-design.md`

**Step 1: 补齐可在开发环境运行的模拟验证。**

补充 gateway 单元测试，使用 loopback datagram 和 mock WebSocket 客户端，验证 costmap 正常帧、乱序、缺片、重复、新帧覆盖旧帧、非法 header/metadata、TTL 清理、断连和慢客户端单 pending frame。测试只验证 telemetry 模块，不访问实车 ROS。

运行：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest -q tests/test_live_observation_realtime.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest -q tests/test_observation.py tests/test_repository_conventions.py
./scripts/test-web.sh
git diff --check
```

**Step 2: 更新设计实施状态。**

在设计文档中把状态改为已实施，并只填写已实际完成的验证结果；无 ROS 环境的项目仍保留为实车验证项，不伪造通过状态。

**Step 3: 执行实车验收清单。**

在机器人上构建、部署且不改变自动驾驶配置后，执行：

```bash
source /opt/ry/install/setup.bash
ros2 topic info /local_costmap/costmap -v
ros2 topic echo --once /local_costmap/costmap --field header
ros2 run tf2_ros tf2_echo map odom
htop
```

并在 PC 浏览器确认：默认显示正确对齐的 8m×8m costmap、切换开关不影响数据接收、局部图暂时无 TF 时安全隐藏、恢复后迅速显示、虚拟墙/点云/车体层次正确；打开/关闭/刷新页面不增长 costmap 进程、socket 或客户端计数。移动端确认没有 costmap 控件、连接和回归。

**Step 4: 交付边界。**

报告实际运行的命令和输出、未能在开发环境运行的实车项目、修改文件与协议字段。除非用户另行要求，不执行 `git add`、`git commit` 或 `git push`。
