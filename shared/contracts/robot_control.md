# 机器人控制

**Status: Existing（已实现）**

| 字段 | 事实 |
| --- | --- |
| 运行时执行方 | `autodrive_console/vehicle_control.py` 拥有 ROS2 节点、安全定时器、控制源状态订阅和发布器。 |
| HTTP 适配层 | `web_console.py` 拥有 `/api/vehicle-control/*` 请求校验和 HTTP 状态映射。 |
| 当前消费者 | `web_console` 的手动控制与建图工作台页面；`mobile/` 的“工具 / 手动控制”受控 HMI。 |
| Mobile 影响 | Mobile 是 Existing HTTP 消费者：使用 `/vector` 提交连续的前后与转向比例，不直接访问 ROS、不会发送 Twist，也不提供导航、地点或横向平移命令。进入控制必须由操作员二次确认；摇杆只会在本地持有 `enter` 返回的会话 ID、车端 `manual_ready=true` 且真实急停为 `normal` 时解锁。多个 Web / Mobile 客户端可以同时持有各自会话，Backend 仍是唯一速度发布者和最终安全边界。 |
| PC Web 影响 | PC Web 手动控制是 Existing `/vector` 消费者：默认键盘 `I/J/K/L` 与方向按钮可组合为前后速度加转向的弧线行驶，不提供横向平移。操作员可在当前浏览器本机将四个方向改绑为互不重复的字母、数字、方向键或数字键盘按键；该偏好不进入 HTTP、ROS 或跨端共享状态，打开设置会先走既有 STOP 路径。它携带会话内递增的 `input_sequence`，避免延迟的旧行驶请求覆盖较新的松键 STOP。既有 `/command` 保留给兼容页面，不作为 PC 手动操作台的连续输入入口。 |
| 兼容性 | 优先增量变更。任何破坏性变更必须同步修改 Backend、Web、受影响的 Mobile 工作、本文档和定向验证。 |

## 控制台启动与 ROS 域

“运行配置”中的开机自启是可选的用户级控制台启动，不是机器人节点自启。启用后 Backend 为当前普通用户写入 `ry-aletheia.service`（`systemd --user`；无用户 bus 时回退为 XDG 桌面自启），服务设置 `Restart=on-failure`，不会安装 root system unit、不会调用 sudo，也不会启动、停止或重启车端 Supervisor 节点。关闭开关会撤销该用户级入口。

自启服务显式继承 `config/video.json` 的 `ros_domain_id`，没有有效配置时使用目标车默认域 `66`；开发环境仍可通过 `ROS_DOMAIN_ID` 覆盖。点云、视频等链路正常而控制源状态为空时，应先用 `ROS_DOMAIN_ID=66 ros2 topic info -v /control_source_state` 对照检查控制台与车端是否在同一 DDS 域，再检查车端节点是否已经发布状态。状态 Topic 使用 `TRANSIENT_LOCAL` 时，控制台启动早于车端节点也必须保持 `pending/unknown`，待收到实际发布或受控服务补齐后再确认，不能把启动时的空读数当作 `navigation` 或 `miniapp`。

## ROS 所有权

| Topic | 方向 | 类型 / 允许值 | 含义 |
| --- | --- | --- | --- |
| `/control_source_cmd` | Aletheia → 机器人 | `std_msgs/String`：`navigation` 或 `miniapp` | 请求允许的控制源切换。 |
| `/control_source_state` | 机器人 → Aletheia | `std_msgs/String`：实际控制源状态 | 唯一确认来源。客户端不得根据一次按钮点击或成功 HTTP 请求推断控制权。 |
| `/cmd_vel_miniapp` | Aletheia → 机器人 | `geometry_msgs/Twist` | 仅在受控会话有效时由 Backend 输出速度。`linear.x` 和 `angular.z` 承载命令；协议专用辅助字段只能由 `MiniappTwistFactory` 构造。 |
| `/is_emergency_stop` | 机器人 → Aletheia | `std_msgs/Bool`，`RELIABLE + TRANSIENT_LOCAL` | 车端急停的 Topic 依据（服务补齐见下一行）：`false` 为未触发，`true` 为已触发。该状态由底盘锁存，Aletheia 必须以相同 QoS 订阅，以便后启动时立即取得当前状态。未收到或 ROS2 不可用时为 `unknown`，必须禁止手动运动。Aletheia 只订阅，绝不发布。 |
| `/get_emergency_stop` | Aletheia → 机器人 | `master_interfaces/srv/GetEmergencyStop` | 启动状态未知时补齐，并在手动会话、重定位占用、miniapp 切源或地图标记导航期间限频异步确认底盘当前急停状态，响应字段 `is_emergency_stop`。服务响应受查询世代与新鲜度保护；不可用、超时或异常不得推断为 `false`。 |
| `/command` | Aletheia → 机器人 | `std_msgs/String` | 仅用于经确认的软件解除急停，固定内容为 `{"speed":0.0,"angle":0.0,"acc":2000,"press":1400,"place":-1,"ulock":0}`；不得读取手动驾驶参数，不得用于 `place` 控制。 |

只有机器人 Backend 可以发布或订阅这些 Topic。Web 和 Mobile 不得直接使用 ROS、发布 Twist 或自行选择控制源 Topic。

### 前往地图标记的 Nav2 所有权

Backend 的 `MapMarkerNavigationController` 是唯一可以使用 `/navigate_to_pose`（`nav2_msgs/action/NavigateToPose`）的 Aletheia 组件。它只在 `/control_source_state` 已确认 `navigation`、急停已确认 `normal`、定位状态为 `normal`、当前地图严格匹配且没有活动测试、手动会话或手动重定位占用时，向 `map` frame 发送一个受控地图标记 Goal。浏览器和 Mobile 不得发布 `/goal_pose`、创建 Action、传入坐标、航向、地图路径、速度或行为树，也不得把该能力伪装为 `/command`、`/vector` 或手动控制扩展。

该操作进行中的 `checking`、`navigating`、`cancelling`、`cancellation_unconfirmed` 均为车辆控制互斥占用。新手动会话和手动重定位必须被拒绝；反向地，确认的 `miniapp` 会话、重定位占用、急停、控制源丢失或定位异常必须使控制器请求取消自己的 Goal。控制器不切换到 `miniapp`，不发布 Twist，只通过 Nav2 Goal cancel 终止操作。

`/is_emergency_stop=false` 只在新鲜确认窗口内可作为运动或地图标记导航许可。手动会话、重定位占用、切至 `miniapp` 或地图标记导航进行时，Backend 必须受限地异步复查 `/get_emergency_stop`；Topic/服务确认超时或连续服务失败会清空目标、发送 STOP 并将急停状态变为 `unknown`。地图标记刚进入 `checking` 而急停仍为 `pending` 时，Backend 最多等待一个固定且短暂的确认窗口；期间持续互锁且绝不发送 Nav2 Goal，窗口结束仍未确认则拒绝。不能持续确认急停的车辆不得保留既有 `false` 的运动权限。

地图标记导航控制器的路线数据仍由上述 Backend Action worker 在已接受的自有 Goal 期间只读订阅 `/plan`；它不是新的控制入口。worker 只公开经过 `map` frame、有限坐标、当前 Goal 终点匹配和点数上限校验的二维快照，并在取消、终态、失效安全条件、切图和新 Goal 时清空。PC 通用“规划路线”图层另由观测缓存器只读接收 `/plan`，仅以只读导航状态管理显示生命周期，不修改上述所有权/互锁；具体有界、过期与兼容规则见实时观测契约。Mobile 不消费或展示路线数据。

## 控制源状态机

2026-10-16 修复约束：Backend 在实际提交非零 Twist 的串行出口重新核验当前目标、
控制源、会话、急停与既有看门狗；核验和 publish 之间不得接受更新的 STOP 状态。
已被 STOP 或新目标取代的定时器快照不能随后提交。Web/Mobile HTTP 格式、20 Hz、
350 ms 输入超时与 1.2 s 心跳边界保持不变；两个消费者均受益，无新增必需客户端字段。
PC Web 对控制操作、heartbeat 与 GET 状态响应统一按本页请求代际应用；已被更新确认
替代的旧响应不得清除当前按键。此展示层保护不替代 Backend 的真实急停与看门狗。
PC Web 连续输入只保留一个在途运动请求及一个最新待发送向量，STOP 使用独立优先请求，
不能等待旧运动响应。控制 HTTP 有总期限（一般请求 2 秒，运动请求不超过车端输入窗口），
运动请求超时清空输入并单次提交更高序号零向量；不无限重试或自动恢复运动。
新鲜安全锁定或当前心跳连接失败清空输入时，若仍有运动意图或未被停止序号覆盖的
在途运动，同样单次提交更高序号零向量，避免恢复许可后迟到旧运动复活。
合法会话的零向量仍校验序号，但不受未知急停或控制源未确认的非零运动许可限制；
真正运动许可不变。当前运动失败与明确会话失效不能被展示层代际保护吞掉。
急停服务的退休 future 和旧代回调必须无副作用，同一次失败不能重复计数；真实当前
失败、确认过期与急停继续按原规则锁定。上述无 HTTP/ROS 格式变化，Mobile 保持兼容。
失效会话的 409 响应增量附带 `code: "session_invalid"`，只表示本次提交的会话失效，
不表示所有端都退出。PC Web 仅对仍持有的同一会话应用该结果；兼容旧端的明确
409 + `status.session.present=false`。普通聚合 GET 没有会话 ID 不能据此清理会话。
Mobile 旧错误处理保持兼容，可忽略新增错误码；无新增必需请求字段。
PC Web 普通离页使用已有 `/release` 且每次会话只提交一次，不全局切回 navigation；
显式退出按钮继续使用全局 `/exit`。自己的运动目标随 release STOP，其他端保留会话。

允许 Aletheia 请求的控制源值为 `navigation` 和 `miniapp`。车端状态 Topic 还可能报告如 `remote` 的外部控制源；任何非空回传均为已确认的实际状态。`remote` 只表示当前来源，不是浏览器禁用切换请求的理由。

1. 自动运行未占有车辆时，任意 Web / Mobile 客户端都可 `POST /api/vehicle-control/enter` 获取自己的会话。当前来源可以是 `navigation`、`miniapp`、`remote` 或尚未确认的值；同一轮 `miniapp` 切换允许其他客户端加入等待，且请求本身不输出非零 Twist。
2. 首个 `POST /api/vehicle-control/enter` 请求 `/control_source_cmd=miniapp` 并进入 `switching`，最多等待 **4.0 s** 取得 `/control_source_state=miniapp`。`POST /api/vehicle-control/navigation` 是全局动作：严格先 STOP、清空全部会话，再请求 `/control_source_cmd=navigation`。
3. 只有收到实际状态确认后，会话才成为 `active`；任一 active 会话均可接受非零命令或速度变更，**最后一条有效输入**更新 Backend 唯一的运动目标。
4. `stop` 立即产生 Backend 生成的三帧有界零 Twist（首帧立即、后两帧按 20 Hz），以容忍单帧丢失；完成后不再占用速度 Topic。`release` 只删除调用方会话；若它拥有当前运动目标则立即 STOP，但绝不请求切源。`exit` 是全局动作，执行 **STOP → 清空全部会话 → 请求 `navigation` → 等待实际状态确认**。切换失败时不能猜测控制已切换。
5. 若其他控制源接管、控制源确认超时或 ROS2 控制器不可用，Backend 必须清除运动并拒绝后续移动。
6. 只有车端 Topic 或有效服务响应确认急停为 `false`，且控制源已实际确认 `miniapp` 时，手动会话才允许输出非零 Twist。`true` 或 `unknown` 会立即停止并拒绝后续运动。
7. 软件解除急停只发布固定 `/command` 报文，随后最多等待 4.0 s；仅在车端 Topic 或有效服务响应确认急停为 `false` 后才可显示成功。该动作不请求也不改变控制源。

### 手动重定位占用

PC 手动重定位是 Backend 内部的不可驾驶 `miniapp` 占用，不是 `/api/vehicle-control/enter` 会话。它可在自动测试任务执行时建立，但必须先清空运动目标、发布 STOP，并等待 `/control_source_state=miniapp` 的真实确认。占用期间普通浏览器手动会话、非零速度和常规 `navigation` 请求均被拒绝；测试任务状态不会被 HTTP 控制层取消、暂停或改写。

定位算法自身的自动重定位/初始化/异常状态不阻止建立该停车占用。操作者可在失败占用上显式重新开始手动对齐：清空目标并重发 STOP，若实际来源不为 miniapp 则重新请求并等待真实来源确认；不经过 navigation，不创建可驾驶会话。活动占用、恢复/切源在途、手动会话和地图标记导航仍互斥。影响消费者为 Backend 与 PC Web，Mobile 控制契约不变。

第二阶段重定位服务的 `success=true` 仅表示车辆接受外部位姿初始化请求，并不表示定位完成。Backend 必须在该请求之后确认 `/localization/status` 经历 `initializing` 或 `relocalizing` 再回到新鲜的 `normal`，才请求 `navigation` 并等待真实确认。服务未明确确认、定位状态未完成该转换、超时、拒绝或恢复失败时必须保持 `miniapp` 停车，不能假设车辆已恢复自动驾驶；仅专用的显式恢复操作可以再次请求 `navigation`。

## 受控 HTTP API

所有 POST 请求体都是不超过 16 KiB 的 JSON 对象。`session_id` 由 Backend 创建；客户端必须将其视为不透明值，在 `release`、`exit`、失效或错误后不得复用。

| 方法与端点 | 请求体 | 可接受动作 |
| --- | --- | --- |
| `GET /api/vehicle-control` | 无 | 返回观测到的运行时/控制源/会话状态和安全限制。 |
| `POST /api/vehicle-control/enter` | `{}` | 请求 `miniapp` 并启动等待确认的会话；当前 `remote` 或急停/未知状态不阻止该请求，但不会解锁运动。 |
| `POST /api/vehicle-control/navigation` | `{}` | 请求切换至 `navigation`；没有手动会话时也可请求。仅在 Aletheia 当前拥有 miniapp 会话/来源时先发布 STOP。 |
| `POST /api/vehicle-control/heartbeat` | `{ "session_id": "…" }` | 保持有效活动会话。 |
| `POST /api/vehicle-control/command` | `{ "session_id": "…", "command": "forward\|backward\|left\|right\|stop" }` | Existing 兼容方向入口；更新保持方向，`stop` 时发送 STOP。 |
| `POST /api/vehicle-control/vector` | `{ "session_id": "…", "linear_ratio": number, "angular_ratio": number, "input_sequence"?: positive integer }` | Existing Mobile 与 PC Web 连续输入入口。两个比例均须为有限 `[-1.0, 1.0]` 数值；Backend 以当前速度档换算目标。`(0,0)` 立即清除运动并走三帧 STOP 路径，但保留会话。`input_sequence` 可选；带该字段的同一会话必须单调递增（重复相同输入用于保活），较小序号或相同序号但不同向量会被忽略，防止网络延迟旧输入复活运动。 |
| `POST /api/vehicle-control/speed` | `{ "session_id": "…", "linear_speed": number, "angular_speed": number }` | 更新经过校验的线速度和角速度。 |
| `POST /api/vehicle-control/stop` | `{ "session_id": "…" }` | 保留会话的同时立即发送 STOP。 |
| `POST /api/vehicle-control/release` | `{ "session_id": "…" }` | 仅释放调用方会话；若其拥有当前运动目标则 STOP，但保留其他端会话和已确认的 `miniapp` 控制源。供 App 后台、离页或断开连接使用。 |
| `POST /api/vehicle-control/exit` | `{ "session_id": "…" }` | 停止、请求返回 `navigation`，并等待实际确认。 |
| `POST /api/vehicle-control/release-emergency-stop` | `{}` | 仅当真实急停为 `true` 时发布固定解除报文，并等待车端 Topic 或有效服务响应确认急停为 `false`；等待中返回 `202`。 |
| `POST /api/vehicle-control/chassis-parameters` | `{ "press": integer, "movement_acc": integer, "stop_acc": integer }` | 持久化并更新手动驾驶参数。`press` 为 20-2000，`movement_acc` 为 10-1000，`stop_acc` 为 20-2000。 |

成功时返回当前状态对象。`200 OK` 表示没有控制源切换等待中；`202 Accepted` 表示切换仍在等待。`400 Bad Request` 表示输入格式错误或不支持的命令。`409 Conflict` 表示不安全控制状态、活动运行、重复会话或缺少控制源确认。`503 Service Unavailable` 表示 Backend ROS2 控制器无法运行。客户端在返回 `status` 时必须展示，且不得实现无界重试循环。

`POST /enter` 以及使用该 ID 的会话操作响应会携带供该客户端后续请求使用的会话 ID；常规 `GET` 状态快照只保证提供聚合的 `session.present`、`session.state` 与 `shared_sessions` 计数，客户端不得因轮询快照没有 ID 而丢弃已持有的有效会话 ID，也不得从快照自行生成或猜测 ID。

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
  "shared_sessions": { "active_count": 2, "switching_count": 0 },
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
  "car_state_sync": {
    "control_source": "confirmed",
    "emergency_stop": "confirmed"
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

`car_state_sync.control_source` 与 `car_state_sync.emergency_stop` 取值为 `pending` 或 `confirmed`，分别说明实际控制源和急停真值是否已从车端收到。控制源收到 `remote` 等外部值时也必须为 `confirmed`，客户端应展示外部接管而非“正在读取”。急停确认窗口到期后的 `pending` 与首次读取语义相同：客户端必须显示“正在重新确认”，不得将缓存的 `false` 显示或推断为正常、启用接管或运动。

Desktop Web 的车辆执行状态页通过 Backend 内部 `VehicleExecutionStatusMonitor` 只读消费本控制器快照：`emergency_stop.state=triggered` 显示“急停已触发”，已确认的 `actual_source=miniapp` 显示“手动控制中”。这不创建新的浏览器控制接口、不改变多端会话或底盘安全门控，也不得由浏览器会话、点击结果或 `pending` 状态推断。

`can_begin_manual` 表示当前客户端可以加入或发起 `miniapp` 会话，不表示可运动；`can_request_navigation` 表示可以发起全局 `navigation` 切换请求。两者在 `remote`、急停或急停未知时仍可为真。`manual_ready` 才是唯一的非零速度许可，仍要求至少一个有效会话、`miniapp` 实际确认及车端 Topic 或有效服务响应确认急停为 `false`。`shared_sessions.active_count` 与 `switching_count` 只用于展示当前参与数，绝不泄露其他客户端的会话 ID。

`/vector` 不是直接 ROS 速度接口：`target_linear = linear_ratio × linear_mps`，`target_angular = angular_ratio × angular_radps`。移动端和 PC Web 都以车头向上为视觉坐标：上/下分别为正/负 `linear_ratio`，左/右分别为正/负 `angular_ratio`；因此右上为正线速度与负角速度，即前进并右转的弧线。它不是横向右前平移。新的向量目标与旧的 `/command` 目标互斥；多个客户端中最后一条有效 `/command` 或 `/vector` 更新该唯一目标。任一后续 `/speed` 更新必须按保存的比例重新换算。急停、未知急停、外部切源、拥有当前目标的会话输入/心跳超时、任一 `stop`、`release`、`exit` 和 `(0,0)` 均清除两类目标并使用 `stop_acc`。每次实际清除运动都发布固定三帧零 Twist，之后停止发布；这不是持续制动流。

`emergency_stop.state` 只能为 `normal`、`triggered` 或 `unknown`；只有当前确认窗口内的车端 `false` 才能是 `normal`，unknown 不等价于 normal。`release` 为 `idle`、`waiting_confirmation`、`confirmed`、`failed` 或 `unconfirmable`，只能由实际 Bool 回调或超时变更。非零 Twist 使用持久化的 `movement_acc`，任何零 Twist（主动停止、输入/心跳超时、退出或外部控制源接管）使用 `stop_acc`。解除急停的固定 `acc=2000`、`press=1400` 与这些手动驾驶参数保持分离。

`/is_emergency_stop` 订阅使用 `RELIABLE + TRANSIENT_LOCAL` QoS，以读取底盘锁存的当前状态。控制台启动期若仍为 `unknown`，同一 ROS 节点会以非阻塞、至多一个在途请求的方式调用 `/get_emergency_stop`；它只可填补 unknown，绝不能覆盖已由 Topic 确认的状态。服务不可用、超时或异常时仍为 `unknown` 并锁定手动运动，不能以订阅创建成功、旧缓存或服务失败推断为未急停。

## 变更影响与验证

| 变更 | 必需的受影响检查 |
| --- | --- |
| ROS Topic、控制源枚举、Twist 映射、超时或速度策略 | Backend 测试、安全审查、本文档和 Web 行为验证；未来任何 Mobile 控制消费者也必须验证。 |
| HTTP 字段、端点或响应变更 | Backend 测试、Web 测试、本文档和每个 Existing 消费者。`/vector` 变更必须验证 PC 组合输入、Mobile 向量映射和本表安全规则。 |
| Mobile 手动 HMI 的交互或生命周期变更 | Mobile 单元/组件测试、`scripts/test-mobile.sh`，并手工确认二次进入、松手 STOP、后台/离页仅 RELEASE、显式退出才 EXIT、急停 `unknown` 锁定和横竖屏布局。 |
| 不改变请求语义的仅 Web 展示变更 | 仅 Web 检查；不编辑本文档。 |
| 未来 Mobile 控制 UI | 先建立独立的权限/审计/确认契约，再更新本文档并运行 Mobile 检查。 |

## Planned（规划中）

Mobile 已消费上表所列的受控 HTTP 契约；尚未批准导航、地点、任务执行、原始 ROS、横向移动或其他车辆操作协议。未来若要增加此类能力，必须先建立独立的权限模型、审计轨迹和显式确认流程，不能将其伪装为当前 `/command` 或 `/vector` 的扩展。
