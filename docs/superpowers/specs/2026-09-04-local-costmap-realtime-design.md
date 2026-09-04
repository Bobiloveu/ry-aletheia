# PC 实时观测：局部代价地图设计

**日期：** 2026-09-04
**状态：** 已实施；自动化、前端生产构建与 C++ 编译已通过，实车验收待执行。
**范围：** 仅扩展 PC 实时运行观测；不修改 Flutter 移动端、导航、地图、任务、视频或任何机器人控制路径。

## 1. 目标与边界

在现有地图、虚拟墙、车体和点云之上，增加只读的 `/local_costmap/costmap` 可视化。它用于让现场人员同时看到传感器障碍物与 Nav2 当前的局部通行风险，不是导航控制界面，也不改变代价地图的配置、刷新、发布或使用方式。

局部代价地图默认显示。PC 操作者可在地图内的轻量图层开关中临时隐藏它，以检查底图、虚拟墙或点云；该显示偏好不写入机器人配置。移动端不显示、不订阅、不建立 costmap WebSocket。

本次不做：发布或调用任何 ROS costmap 接口、修改 `local_costmap` 参数、增加 Foxglove/rosbridge、混入现有 cloud/pose 通道、保存历史代价图，或把局部代价图作为报告/验收证据。

## 2. 已验证的现场事实

目标车已实测：

| 项目 | 实际值 |
| --- | --- |
| ROS Topic | `/local_costmap/costmap` |
| 消息 | `nav_msgs/msg/OccupancyGrid` |
| Publisher | `/local_costmap/local_costmap` 节点 |
| QoS | `RELIABLE + TRANSIENT_LOCAL` |
| `header.frame_id` | `odom` |
| 分辨率 | `0.05 m/cell` |
| 尺寸 | `160 × 160`，即 `8 × 8 m` |
| 原点 | 当前为 `(-2.5, -7.8)`，随局部窗口滚动 |
| 观测到的发布率 | 约 `0.286 Hz`（3 个样本；须在实际行驶时复核） |
| `map ← odom` | 初始短暂不可用后可查询；该次采样为单位变换 |

单帧原始栅格为 25,600 个 int8 单元，约 25 KiB。即使以 5 Hz 传输也远低于视频负载；当前实测频率更低。实现仍必须有尺寸和频率上限，不能依赖该车的当前小尺寸。

## 3. 现有调用链与选择

当前实时路径为：

```text
ROS PointCloud2 → C++ cloud 预处理 → UDP :8769 → WebSocket /cloud → PixiJS 点云
TF map→base_* → C++ pose 预处理 → UDP :8770 → WebSocket /pose → PC/移动端车体
```

`TelemetryGateway` 的每路 UDP assembler、每个浏览器连接和浏览器渲染器均使用容量一的 latest-wins 槽。点云与位姿使用独立 UDP socket、线程和 WebSocket lane；这一隔离必须保持。

采用第三条独立 lane，而非把代价栅格混入点云或改用 HTTP/PNG 轮询：

```text
/local_costmap/costmap
  → 独立 C++ costmap 预处理进程
  → loopback UDP :8771（RALT kind=3）
  → TelemetryGateway latest-wins assembler
  → Binary WebSocket :8768/costmap（ALTM kind=3）
  → 仅 PC PixiJS 动态纹理图层
```

这条链路不经过 Python ROS 转发、Foxglove Bridge、rosbridge、HTTP 轮询或 MediaMTX。`/cloud`、`/pose` 的包布局、端口和行为保持不变。

## 4. C++ 预处理与坐标正确性

### 4.1 订阅和生命周期

复用 `aletheia_live_cloud` 现有的参数化进程模型，新增加 `enable_costmap` 模式；`ObservationManager` 用第三个独立子进程 `ry_aletheia_live_costmap` 启动它。三进程分别只启用 cloud、pose、costmap 中的一项，因而栅格处理或网络发送不会阻塞位姿。

costmap 订阅使用与现场 Publisher 匹配的 `RELIABLE + TRANSIENT_LOCAL + keep_last(1)`；它能在 Aletheia 后启动时收到锁存的当前图，但只保留最新图。ROS callback 只校验、拷贝到最新槽并返回；TF、变换、编码和 UDP 发送在该进程的独立工作路径完成。

进程停止、页面空闲回收、控制台退出与升级时，costmap 子进程、其 socket、工作线程和浏览器连接须与 cloud/pose 一样成对回收。无法订阅、消息非法、TF 缺失或 UDP 停止都只使该图层不可用，不能阻塞地图、点云、位姿或小车导航。

### 4.2 投影到 `map`

每个 `OccupancyGrid` 使用自身 `header.stamp` 与 `header.frame_id`。若 source frame 已是 `map`，直接使用其 `info.origin`；否则精确查询 `map ← source_frame`，并计算：

```text
T_map_costmap_origin = T_map_source(stamp) × T_source_grid_origin
```

输出 `map_origin_x / map_origin_y / map_origin_yaw`、resolution、width、height 和栅格数据。不能假设当前 `map ← odom` 为单位矩阵；TF 暂不可用、时间戳无法转换、frame_id 为空、四元数/数值非有限或尺寸越界时，直接丢弃该帧并限频记录原因。唯一受限兼容是新鲜 `odom` 栅格的精确时间查询失败时：仅在最新 `map ← odom` 的完整 3D 位移与四元数均严格验证为单位变换时，才可使用该无损单位变换；非单位、其它 source frame 或最新查询失败均不回退。绝不用“最近一次 TF”猜测局部栅格位置。

网格数据保持 OccupancyGrid 原始单元的 uint8 位模式：ROS 中的 `-1` 转为 `255`（unknown），不改写其导航语义。发送前验证 `width × height == cell_count`、`resolution > 0`、单元总数不超过 65,535；该上限覆盖现场 160×160 但避免异常大图耗尽内存。

## 5. 二进制协议与背压

### 5.1 UDP：RALT kind 3

沿用现有 30-byte `RALT v1` header、1152-byte payload 上限、frame sequence、timestamp、stream id 和应用层分片。新增 `KIND_COSTMAP = 3`，回环端口为 `127.0.0.1:8771`。header 内现有 `point_count` 字段在内部重命名为中性的 `record_count`；其线上字节布局不变：cloud 仍是点数、pose 仍是 1、costmap 为 cell count。

costmap frame payload 为 network-byte-order：

```text
float32 map_origin_x
float32 map_origin_y
float32 map_origin_yaw
float32 resolution
uint16  width
uint16  height
uint8   cells[width × height]
```

`record_count == width × height`；完整 payload 长度必须恰为 `20 + record_count`。实际 160×160 帧约需 23 个 UDP datagram，均小于 MTU。无 ACK、重传、补片、历史缓存或阻塞式 send；新 frame sequence 到达立即废弃旧残帧，残帧最多保留 300 ms。

### 5.2 WebSocket：ALTM kind 3

网关新增 `/costmap`，仍使用 :8768、ALTM v1 header 和 Binary WebSocket。它只转发经过完整性校验的紧凑 binary payload；不会 JSON、Base64、PNG 编码或 Python 逐单元转换。每个客户端最多一个待发 frame；慢客户端覆盖旧帧，超过既有 socket timeout 后关闭，重连直接接收新的完整 frame。

`TelemetryGateway.status()` 增量公开 costmap UDP port、浏览器连接数和最后完整帧 age；Observation 状态与日志明确标识 costmap lane，但不会把无帧误报为 cloud/pose 故障。

## 6. PC PixiJS 图层与交互

PC 打开实时页时，除现有 `/cloud`、`/pose` 外建立 `/costmap`。移动端不建立该连接，也不创建代价纹理。前端验证 ALTM magic/version/kind、declared cell count、固定 metadata 长度、维度乘积、payload 长度、有限 origin/yaw/resolution 与最大尺寸；无效、过期或 map-generation 已变更的帧直接丢弃。

地图世界容器内图层顺序为：

```text
静态地图 → 米制格栅 → 局部代价地图 → 虚拟墙 → 点云 → DOM 车体
```

costmap 使用一张复用的 `160 × 160` 等比例动态 Pixi texture，不逐格创建 Sprite/Graphics。每个新有效帧最多更新一次纹理；旧 texture 在尺寸变化、切图和页面释放时销毁。它按 map-space origin、resolution 和 yaw 变换，因此随滚动局部窗口正确落在静态地图上；仍使用现有缩放、拖动和跟随变换。

颜色只表达代价：

| Cost 值 | 视觉 |
| --- | --- |
| 0（free）/ 255（unknown） | 完全透明 |
| 1–252（普通/膨胀） | 低透明度黄至橙 |
| 253（inscribed inflation） | 清晰橙色 |
| 254（lethal obstacle） | 半透明红色 |

虚拟墙继续使用现有红线并处于 costmap 上层，点云继续保持现有深紫色且在其上层。默认显示；图层开关只切换 Pixi texture 可见性，不能停 ROS 订阅或改变导航。

## 7. 失败降级、日志与性能

- ROS topic 尚无 publisher / 锁存图：显示“等待局部代价地图”，其他图层照常。
- 工具晚启动时收到旧锁存栅格：若其 `header.stamp` 已超过 5 秒，直接记录“源数据过期”并等待新帧；不以最新 TF 猜测旧栅格的位置。
- TF 启动短缺或中断：丢弃本帧，保留最后一个不超过 5 秒的已投影纹理；到期后隐藏，状态显示“等待 map→odom 变换”。仅新鲜 `odom` 栅格且最新 `map ← odom` 已严格验证为单位变换时可安全显示；这不是对非单位定位变换的通用回退。
- UDP/WebSocket 分片缺失、重复、超大或错误尺寸：网关丢帧并只记录限频诊断，绝不等待或重放。
- 浏览器后台暂停后恢复：只绘制最新完整 costmap，不逐帧补画。
- 地图切换：连同 pending costmap frame 一起按 map generation 作废；收到新地图上下文后才接受新的 `map` 投影 frame。
- 性能指标增量增加 `costmap_packet_rate_hz`、`costmap_source_age_ms`、`costmap_render_ms` 与 `costmap_dropped_frames`；服务端仅在连续过期、TF 失败或非法帧时写有原因的限频日志。

当前 25 KiB/帧、约 0.286 Hz 的实测输入约为 7 KiB/s；即使后续上升到 5 Hz，也约 125 KiB/s 的应用层原始数据。没有 JSON/PNG/Base64 或 Python 栅格转码，高于此规模的地图会在 C++ 侧被拒绝而非扩大队列。

## 8. 修改范围

- `live_preprocessor/src/live_cloud_preprocessor.cpp`：costmap QoS subscription、header-stamp TF 投影、costmap latest slot、RALT kind 3 编码和独立 UDP sender。
- `live_preprocessor/CMakeLists.txt`：增加 `nav_msgs` 依赖。
- `autodrive_console/telemetry.py`：kind 3 assembler、:8771 UDP socket/thread、`/costmap` handshake、状态与边界校验。
- `autodrive_console/observation.py`：第三独立预处理进程、日志、状态和受控回收。
- `frontend/src/liveObservation.js`：仅 PC 的 costmap lane、binary parser、单槽渲染、动态纹理、图层开关和指标。
- `frontend/src/liveObservation.css` 与 `frontend/live-observation.html`：克制的 PC 图层开关及状态文案；无移动端样式/功能扩展。
- `shared/contracts/realtime_observation.md`、`PROJECT_OVERVIEW.md`、`live_preprocessor/README.md`：更新第三 lane、协议、QoS、端口、PC-only 消费者与排障边界。
- `tests/test_live_observation_realtime.py`、适用的 `tests/test_offline_modules.py`：协议、latest-wins、TF/尺寸失败降级、前端图层和生命周期回归。

不会修改：`/cloud`、`/pose`、地图缓存/虚拟墙匹配、视频、MediaMTX、任务、报告、轨迹、Supervisor、手动控制、Flutter 或任何 ROS 导航参数。

## 9. 验证策略

### 自动化与构建

1. RALT/ALTM costmap 正常完整帧、乱序、重复、缺片、新帧覆盖旧残帧、超时残帧、超大/截断/错误 count/尺寸乘积不符。
2. costmap lane 的单客户端 slow-send 覆盖、断开重连、网关 stop/start 和第三 UDP socket/thread 回收。
3. `map ← odom` identity、平移、旋转、缺失 TF、旧 timestamp、无效 origin/quaternion 的 C++ 单元或可抽取纯函数测试。
4. PC 前端 binary parser、map-generation 丢弃、动态 texture 生命周期、默认可见、临时隐藏、移动端不连接 `/costmap`。
5. 既有 cloud/pose protocol 和 latest-wins 测试必须保持通过。
6. 执行受影响 Backend tests、`./scripts/test-web.sh`、前端生产构建和 C++ ROS 构建；不因 PC-only lane 运行无关 Flutter 构建。

### 实车验收

1. 观测页面开关前后，确认 `/local_costmap/costmap` 的 Publisher/Subscriber 数量只新增 Aletheia 一个只读订阅。
2. 使用 RViz 的 local costmap 对照：静止、直行、转弯、靠近墙体和障碍物时，栅格相对静态地图、车体和点云无整体平移/旋转误差。
3. 模拟 TF 短暂不可用或切图，确认只隐藏/过期该层，点云、位姿、地图、视频和导航不受影响。
4. 在 `htop` 下比较关闭实时页、仅 cloud/pose、开启 costmap 三种状态；确认 Aletheia 无持续 CPU 增长、无 socket/线程增长，导航进程无异常变化。
5. 浏览器刷新、关闭、Wi-Fi 短断重连与持续运行后，只恢复最新帧；不出现历史回放或内存增长。
6. 导出工具日志，确认异常时包含 topic/QoS、TF、非法 packet、过期与 reconnect 的可定位原因。
