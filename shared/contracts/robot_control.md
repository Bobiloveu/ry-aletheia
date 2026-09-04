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
| `/is_emergency_stop` | 机器人 → Aletheia | `std_msgs/Bool`，`RELIABLE + TRANSIENT_LOCAL` | 真实急停唯一依据：`false` 为未触发，`true` 为已触发。该状态由底盘锁存，Aletheia 必须以相同 QoS 订阅，以便后启动时立即取得当前状态。未收到或 ROS2 不可用时为 `unknown`，必须禁止手动运动。Aletheia 只订阅，绝不发布。 |
| `/get_emergency_stop` | Aletheia → 机器人 | `master_interfaces/srv/GetEmergencyStop` | 仅在启动期 `unknown` 时异步读取底盘当前急停状态，响应字段 `is_emergency_stop`。这是 Topic 锁存在部分车端未送达时的受控补齐；不可用、超时或异常不得推断为 `false`。 |
| `/command` | Aletheia → 机器人 | `std_msgs/String` | 仅用于经确认的软件解除急停，固定内容为 `{"speed":0.0,"angle":0.0,"acc":2000,"press":1400,"place":-1,"ulock":0}`；不得读取手动驾驶参数，不得用于 `place` 控制。 |

只有机器人 Backend 可以发布或订阅这些 Topic。Web 和 Mobile 不得直接使用 ROS、发布 Twist 或自行选择控制源 Topic。

## 控制源状态机

允许的控制源值为 `navigation` 和 `miniapp`。

1. 仅在不存在 Aletheia 手动会话、没有自动运行占有车辆，且实际控制源为 `navigation` 或已确认的 `miniapp` 时，才允许 `POST /api/vehicle-control/enter`。
2. 从 `navigation` 切换时，Backend 请求 `/control_source_cmd=miniapp` 并进入 `switching`，最多等待 **4.0 s** 取得 `/control_source_state=miniapp`。
3. 只有收到实际状态确认后，会话才成为 `active`；此后才可以接受非零命令或速度变更。
4. `stop` 立即产生 Backend 生成的零 Twist。`exit` 执行 **STOP → 请求 `navigation` → 等待实际状态确认**。切换失败时会话保持无效，不能猜测控制已切换。
5. 若其他控制源接管、控制源确认超时或 ROS2 控制器不可用，Backend 必须清除运动并拒绝后续移动。
6. 只有 `/is_emergency_stop=false` 且控制源已实际确认 `miniapp` 时，手动会话才允许输出非零 Twist。`true` 或 `unknown` 会立即停止并拒绝后续运动。
7. 软件解除急停只发布固定 `/command` 报文，随后最多等待 4.0 s；仅在收到 `/is_emergency_stop=false` 后才可显示成功。该动作不请求也不改变控制源。

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
| `POST /api/vehicle-control/release-emergency-stop` | `{}` | 仅当真实急停为 `true` 时发布固定解除报文，并等待 `/is_emergency_stop=false` 确认；等待中返回 `202`。 |
| `POST /api/vehicle-control/chassis-parameters` | `{ "press": integer, "movement_acc": integer, "stop_acc": integer }` | 持久化并更新手动驾驶参数。`press` 为 20-2000，`movement_acc` 为 10-1000，`stop_acc` 为 20-2000。 |

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
  },
  "emergency_stop": {
    "state": "normal",
    "release": "idle"
  },
  "chassis_parameters": {
    "press": 1400,
    "movement_acc": 1000,
    "stop_acc": 1200
  }
}
```

Backend 以 **20 Hz** 发布。保持输入必须在 **350 ms** 前刷新；会话心跳必须在 **1200 ms** 前到达。缺失输入或心跳会触发安全停止；浏览器 UI 的刷新频率不能代替 Backend 看门狗。两项请求速度必须是 **0.10–1.00**（含边界）范围内的有限值。默认线速度为 **0.20 m/s**，默认角速度为 **0.30 rad/s**。客户端不能覆盖这些限制。

`emergency_stop.state` 只能为 `normal`、`triggered` 或 `unknown`；unknown 不等价于 normal。`release` 为 `idle`、`waiting_confirmation`、`confirmed`、`failed` 或 `unconfirmable`，只能由实际 Bool 回调或超时变更。非零 Twist 使用持久化的 `movement_acc`，任何零 Twist（主动停止、输入/心跳超时、退出或外部控制源接管）使用 `stop_acc`。解除急停的固定 `acc=2000`、`press=1400` 与这些手动驾驶参数保持分离。

`/is_emergency_stop` 订阅使用 `RELIABLE + TRANSIENT_LOCAL` QoS，以读取底盘锁存的当前状态。控制台启动期若仍为 `unknown`，同一 ROS 节点会以非阻塞、至多一个在途请求的方式调用 `/get_emergency_stop`；它只可填补 unknown，绝不能覆盖已由 Topic 确认的状态。服务不可用、超时或异常时仍为 `unknown` 并锁定手动运动，不能以订阅创建成功、旧缓存或服务失败推断为未急停。

## 变更影响与验证

| 变更 | 必需的受影响检查 |
| --- | --- |
| ROS Topic、控制源枚举、Twist 映射、超时或速度策略 | Backend 测试、安全审查、本文档和 Web 行为验证；未来任何 Mobile 控制消费者也必须验证。 |
| HTTP 字段、端点或响应变更 | Backend 测试、Web 测试、本文档和每个 Existing 消费者。 |
| 不改变请求语义的仅 Web 展示变更 | 仅 Web 检查；不编辑本文档。 |
| 未来 Mobile 控制 UI | 先建立独立的权限/审计/确认契约，再更新本文档并运行 Mobile 检查。 |

## Planned（规划中）

尚未批准新的直接 Mobile 操作协议。未来命令 UI 在成为 Existing 前，需要独立契约、权限模型、审计轨迹和显式确认流程。
