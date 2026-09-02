# 机器人控制

**Status: Existing（已实现）**

| 字段 | 事实 |
| --- | --- |
| 运行时执行方 | `autodrive_console/vehicle_control.py` 拥有 ROS2 节点、安全定时器、控制源状态订阅和发布器。 |
| HTTP 适配层 | `web_console.py` 拥有 `/api/vehicle-control/*` 请求校验和 HTTP 状态映射。 |
| 当前消费者 | `web_console` 的手动控制与建图工作台页面。 |
| Mobile 影响 | Mobile 当前没有 Existing 手动控制 UI。未来 Mobile 命令功能只有在其权限、确认和审计契约获批后，才能消费本受控 HTTP 契约。 |
| 兼容性 | 优先增量变更。任何破坏性变更必须同步修改 Backend、Web、受影响的 Mobile 工作、本文档和定向验证。 |

## ROS 所有权

| Topic | 方向 | 类型 / 允许值 | 含义 |
| --- | --- | --- | --- |
| `/control_source_cmd` | Aletheia → 机器人 | `std_msgs/String`：`navigation` 或 `miniapp` | 请求允许的控制源切换。 |
| `/control_source_state` | 机器人 → Aletheia | `std_msgs/String`：实际控制源状态 | 唯一确认来源。客户端不得根据一次按钮点击或成功 HTTP 请求推断控制权。 |
| `/cmd_vel_miniapp` | Aletheia → 机器人 | `geometry_msgs/Twist` | 仅在受控会话有效时由 Backend 输出速度。`linear.x` 和 `angular.z` 承载命令；协议专用辅助字段只能由 `MiniappTwistFactory` 构造。 |

只有机器人 Backend 可以发布或订阅这些 Topic。Web 和 Mobile 不得直接使用 ROS、发布 Twist 或自行选择控制源 Topic。

## 控制源状态机

允许的控制源值为 `navigation` 和 `miniapp`。

1. 仅在不存在 Aletheia 手动会话、没有自动运行占有车辆，且实际控制源为 `navigation` 或已确认的 `miniapp` 时，才允许 `POST /api/vehicle-control/enter`。
2. 从 `navigation` 切换时，Backend 请求 `/control_source_cmd=miniapp` 并进入 `switching`，最多等待 **4.0 s** 取得 `/control_source_state=miniapp`。
3. 只有收到实际状态确认后，会话才成为 `active`；此后才可以接受非零命令或速度变更。
4. `stop` 立即产生 Backend 生成的零 Twist。`exit` 执行 **STOP → 请求 `navigation` → 等待实际状态确认**。切换失败时会话保持无效，不能猜测控制已切换。
5. 若其他控制源接管、控制源确认超时或 ROS2 控制器不可用，Backend 必须清除运动并拒绝后续移动。

## 受控 HTTP API

所有 POST 请求体都是不超过 16 KiB 的 JSON 对象。`session_id` 由 Backend 创建；客户端必须将其视为不透明值，在 `exit`、失效或错误后不得复用。

| 方法与端点 | 请求体 | 可接受动作 |
| --- | --- | --- |
| `GET /api/vehicle-control` | 无 | 返回观测到的运行时/控制源/会话状态和安全限制。 |
| `POST /api/vehicle-control/enter` | `{}` | 发布 STOP 后启动会话，或接管已实际确认的 `miniapp` 控制源。 |
| `POST /api/vehicle-control/heartbeat` | `{ "session_id": "…" }` | 保持有效活动会话。 |
| `POST /api/vehicle-control/command` | `{ "session_id": "…", "command": "forward\|backward\|left\|right\|stop" }` | 更新保持方向；`stop` 时发送 STOP。 |
| `POST /api/vehicle-control/speed` | `{ "session_id": "…", "linear_speed": number, "angular_speed": number }` | 更新经过校验的线速度和角速度。 |
| `POST /api/vehicle-control/stop` | `{ "session_id": "…" }` | 保留会话的同时立即发送 STOP。 |
| `POST /api/vehicle-control/exit` | `{ "session_id": "…" }` | 停止、请求返回 `navigation`，并等待实际确认。 |

成功时返回当前状态对象。`200 OK` 表示没有控制源切换等待中；`202 Accepted` 表示切换仍在等待。`400 Bad Request` 表示输入格式错误或不支持的命令。`409 Conflict` 表示不安全控制状态、活动运行、重复会话或缺少控制源确认。`503 Service Unavailable` 表示 Backend ROS2 控制器无法运行。客户端在返回 `status` 时必须展示，且不得实现无界重试循环。

## 状态响应与安全限制

每个成功的状态响应至少包含：

```json
{
  "runtime": "ready",
  "actual_source": "miniapp",
  "transition": null,
  "manual_ready": true,
  "can_begin_manual": false,
  "session": { "present": true, "state": "active" },
  "safety": {
    "publish_hz": 20.0,
    "input_timeout_ms": 350,
    "heartbeat_timeout_ms": 1200
  },
  "speed": {
    "linear_mps": 0.20,
    "angular_radps": 0.30,
    "min": 0.10,
    "max": 1.00
  }
}
```

Backend 以 **20 Hz** 发布。保持输入必须在 **350 ms** 前刷新；会话心跳必须在 **1200 ms** 前到达。缺失输入或心跳会触发安全停止；浏览器 UI 的刷新频率不能代替 Backend 看门狗。两项请求速度必须是 **0.10–1.00**（含边界）范围内的有限值。默认线速度为 **0.20 m/s**，默认角速度为 **0.30 rad/s**。客户端不能覆盖这些限制。

## 变更影响与验证

| 变更 | 必需的受影响检查 |
| --- | --- |
| ROS Topic、控制源枚举、Twist 映射、超时或速度策略 | Backend 测试、安全审查、本文档和 Web 行为验证；未来任何 Mobile 控制消费者也必须验证。 |
| HTTP 字段、端点或响应变更 | Backend 测试、Web 测试、本文档和每个 Existing 消费者。 |
| 不改变请求语义的仅 Web 展示变更 | 仅 Web 检查；不编辑本文档。 |
| 未来 Mobile 控制 UI | 先建立独立的权限/审计/确认契约，再更新本文档并运行 Mobile 检查。 |

## Planned（规划中）

尚未批准新的直接 Mobile 操作协议。未来命令 UI 在成为 Existing 前，需要独立契约、权限模型、审计轨迹和显式确认流程。
