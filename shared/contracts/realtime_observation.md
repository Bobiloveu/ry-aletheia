# 实时观测

**Status: Existing（已实现）**
**权威实现：** `autodrive_console/telemetry.py`、`autodrive_console/observation.py`、`frontend/src/liveObservation.js` 和 `mobile/lib/features/live_observation/`
**消费者：** `robot_backend`、`web_console`、`mobile`
**兼容性：** 优先增量变更；破坏性变更必须同时更新所有消费者和本文档。

## 控制面 API

`GET /api/observation`、`GET /api/observation/active-map` 和 `GET /api/observation/maps/{id}/layers` 暴露活动地图、世界元数据、虚拟墙和遥测数据。当前会话生命周期使用 `POST /api/observation/start`、`/heartbeat` 和 `/stop`。

## 实时传输

机器人侧预处理器以 `RALT` 格式发送本机接入的 UDP 帧。网关在端口 **8768** 暴露二进制 WebSocket 通道：

| 通道 | 路径 | UDP 接入端口 | 记录载荷 |
| --- | --- | --- | --- |
| `cloud` | `/cloud` | `8769` | XY 浮点数对，最多 3000 个点 |
| `pose` | `/pose` | `8770` | 单条 X/Y/yaw 浮点记录 |

浏览器和 Mobile 载荷以 **ALTM v1** 开头。消费者必须在渲染前验证魔数、版本、通道类型、记录数、声明载荷长度和有限数值。

## 时效与渲染

所有阶段均为 latest-wins：每个来源只保留一帧待处理数据，不重传，过期帧直接丢弃而非回放。地图图像、格栅、虚拟墙、点云、位姿和车辆指示器共享同一个世界坐标到屏幕坐标变换。地图保持北向/原始地图朝向，仅车辆旋转。

## Planned（规划中）

尚未批准通用遥测总线。新增实时数据必须使用独立版本化通道，并明确有界内存与时效行为。
