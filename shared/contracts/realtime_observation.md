# 实时观测

**Status: Existing（已实现）**
**权威实现：** `autodrive_console/telemetry.py`、`autodrive_console/observation.py`、`frontend/src/liveObservation.js` 和 `mobile/lib/features/live_observation/`
**消费者：** `robot_backend`、`web_console`、`mobile`
**兼容性：** 优先增量变更；破坏性变更必须同时更新所有消费者和本文档。

## 控制面 API

`GET /api/observation`、`GET /api/observation/active-map` 和 `GET /api/observation/maps/{id}/layers` 暴露活动地图、世界元数据、虚拟墙和遥测数据。当前会话生命周期使用 `POST /api/observation/start`、`/heartbeat` 和 `/stop`。

`GET /api/observation/localization-status` 是 PC 实时页使用的只读定位健康快照；它不下发重定位、Node Manager 或车辆控制命令。响应为：

```json
{
  "phase": "relocalizing",
  "label": "重定位中",
  "detail": "NDT 匹配质量低",
  "updated_at": 12345.67
}
```

`phase` 的闭集为 `initializing`、`normal`、`warning`、`error`、`relocalizing` 与 `unavailable`。Backend 只读订阅既有 `/localization/status`（`master_interfaces/msg/LocalizationStatus`），将原始 `state`/`error_code` 转换为可读文本；不公开 `fault_id` 或原始数值。接口由车辆运行时提供：该车未提供 `LocalizationStatus` 时，必须返回 `unavailable` 与“该车不支持实时定位状态”，不得暴露 Python 路径或原始异常。超过新鲜度窗口、其他 ROS 模块不可用或未收到首条状态时同样必须返回 `unavailable`，不得假定正常。一次重定位证据以同一非空 `fault_id` 首次进入 `state=4` 计数；它仅在自动测试运行中以已验证的地图坐标附到轨迹及离线报告，坐标不可验证时保留次数而不渲染地图标记。

当前消费者为 `robot_backend` 与 PC `web_console`；Mobile 不是该端点消费者。该接口是增量控制面 API，既有客户端可忽略。

## 实时传输

机器人侧预处理器以 `RALT` 格式发送本机接入的 UDP 帧。网关在端口 **8768** 暴露二进制 WebSocket 通道：

| 通道 | 路径 | UDP 接入端口 | 记录载荷 |
| --- | --- | --- | --- |
| `cloud` | `/cloud` | `8769` | XY 浮点数对，最多 3000 个点 |
| `pose` | `/pose` | `8770` | 单条 X/Y/yaw 浮点记录 |
| `costmap` | `/costmap` | `8771` | map 坐标系栅格原点、分辨率、宽高及最多 65,535 个 OccupancyGrid 原始 cell；PC Web 与 Flutter Mobile 消费 |

浏览器和 Mobile 载荷以 **ALTM v1** 开头。消费者必须在渲染前验证魔数、版本、通道类型、记录数、声明载荷长度和有限数值。`costmap` 使用 `kind=3`，payload 以网络字节序 `float32 map_origin_x/y/yaw/resolution`、`uint16 width/height` 开头，随后为 `width × height` 个原始 unsigned cell。ROS `OccupancyGrid.data` 的 `-1` 按其原始字节值传输为 `255`；浏览器必须把未知值视为不可绘制区域，而不能误当作致命障碍物。

## 时效与渲染

所有阶段均为 latest-wins：每个来源只保留一帧待处理数据，不确认、不重传，过期帧直接丢弃而非回放。`costmap` 的 C++ 预处理必须先拒绝默认 5 秒之外的 ROS `header.stamp`（包括晚启动收到的旧锁存图），再按该时间戳将其 `header.frame_id` 和 `info.origin` 投影到 `map`；消费者只显示已经在 map 坐标系中的栅格，不能默认 `odom == map` 或以最新 TF 猜测旧栅格位置。唯一受限兼容是新鲜 `odom` 栅格的精确时间查询失败时：只有最新 `map ← odom` 经完整 3D 单位变换校验后才可使用；非单位变换、其它 source frame 或查询失败必须丢弃。PC 与 Flutter Mobile 都将未知/自由 cell（`255` / `0`）透明绘制，使用同一分段色标，并在本地接收超过 5 秒、切图或无有效后继帧时安全隐藏。地图图像、格栅、局部代价地图、虚拟墙、点云、位姿和车辆指示器共享同一个世界坐标到屏幕坐标变换；固定图层顺序为底图 → 格栅 → costmap → 虚拟墙 → 点云 → 车体。地图保持北向/原始地图朝向，仅车辆旋转。

## Planned（规划中）

尚未批准通用遥测总线。新增实时数据必须使用独立版本化通道，并明确有界内存与时效行为。
