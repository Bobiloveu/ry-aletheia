# 手动控制：急停与底盘参数增量设计

**日期：** 2026-09-03
**状态：** 已确认设计，待实施
**范围：** 仅扩展现有 PC Web 手动控制模块及其受控车端 Backend；不改变既有 miniapp / navigation 控制权协议。

## 1. 目标与边界

本次在既有 `VehicleControlController` 上增加两项能力：

1. 订阅真实急停状态，并以该状态对手动运动建立 fail-closed 门控；
2. 提供经状态反馈确认的软件解除急停，以及持久化的底盘 `press`、运动加速度和停止加速度配置。

不在本次范围内：重新实现手动控车、修改 `/cmd_vel_miniapp` 的速度/控制权协议、改变 `/control_source_cmd` 或 `/control_source_state` 的语义、实现 `place` 控制、增加 Mobile 控制界面，或改变任务、导航、地图、视频、Supervisor 与实时观测功能。

## 2. 已有调用链

`web_console.py` 是 HTTP 适配层；`VehicleControlController` 独占 ROS2 node、executor、20 Hz timer、控制源订阅和手动 Twist publisher。PC 手动控制页与建图工作台都调用 `/api/vehicle-control/*` 并根据 `manual_ready` 使能方向控制。因此安全门控必须放在 Controller，不能只放在某一页面。

所有现有停止入口最终调用 Controller 的零速度输出：页面停止按钮、方向按钮松开、键盘松开、页面失焦、输入看门狗、心跳看门狗、退出会话、外部控制源离开 miniapp 与控制器关闭。它们将继续保持现有路径，不新增页面侧直接 ROS 调用。

## 3. 方案选择

| 方案 | 结论 | 原因 |
| --- | --- | --- |
| 新建独立急停 ROS 节点或浏览器直连 ROS | 拒绝 | 会重复 ROS 生命周期与状态管理，并绕过现有 Backend 安全边界。 |
| 只在 Web 轮询中禁用按钮 | 拒绝 | 网络、刷新或建图工作台路径都可能绕过，且不能保证已发送速度目标被停止。 |
| 扩展既有 `VehicleControlController` | 采用 | 同一锁、同一 ROS executor、同一安全 STOP 与同一状态响应可覆盖两处既有手动控制消费者。 |

## 4. ROS 所有权与状态机

### 4.1 急停状态

Backend 只订阅 `/is_emergency_stop`（`std_msgs/msg/Bool`），使用底盘实际发布的 `RELIABLE + TRANSIENT_LOCAL` QoS。底盘将当前状态锁存；这让后启动的 Aletheia 也能立即取得 `false` 或 `true`，而非等待下一次物理急停变化。首次未收到回调、ROS2 控制运行时不可用或无法取得状态时，急停状态是 `unknown`；它绝不能被当作 `false`。

状态映射：

| ROS 值 | API / UI 状态 | 手动运动 |
| --- | --- | --- |
| `false` | `normal` / 正常、未触发急停 | 只有实际控制源为 `miniapp` 且会话有效时允许。 |
| `true` | `triggered` / 急停已触发 | 立即清空已有运动目标并禁止。 |
| 未收到 / 运行时异常 | `unknown` / 急停状态未知 | 禁止。 |

当收到 `true`，Controller 在锁内清空非零目标并设置一次 STOP；锁外发布原有零 Twist。会话不会被伪装成新的控制源，也不会自动重新发送之前按住的方向。状态恢复为 `false` 后仍需操作者重新输入方向。

`manual_ready` 与 `can_begin_manual` 同时要求急停真实为 `false`。现有 `actual_source` 和会话语义不变。

### 4.2 软件解除急停

Controller 新增唯一的 `/command`（`std_msgs/msg/String`）publisher。仅在最新真实急停状态是 `true` 且当前没有未决解除操作时允许发布以下固定 JSON；它不读取可配置的手动参数：

```json
{"speed":0.0,"angle":0.0,"acc":2000,"press":1400,"place":-1,"ulock":0}
```

API 调用后的状态为 `waiting_confirmation`，HTTP 仅表示发布已被 Backend 接受。只有 `/is_emergency_stop` 的后续回调为 `false` 才将状态记为 `confirmed`。确认窗口固定为既有控制源切换的 4.0 秒；超时仍为 `true` 时记为 `failed`，运行时失效或状态变为 unknown 时记为 `unconfirmable`。不因为 `/command` publisher 成功而显示“解除成功”。

该操作不发布 `/control_source_cmd`，不建立或销毁手动会话，也不改变 `navigation` / `miniapp` 实际控制源。

## 5. 底盘参数与零速度选择

新增持久化 `vehicle_control` 配置。原手动 `acc=1200` 超出本次确认的 `movement_acc` 上限 1000，因此默认运动值按安全范围收敛为 1000：

```json
{
  "press": 1400,
  "movement_acc": 1000,
  "stop_acc": 1200
}
```

| 字段 | 范围 | 使用位置 |
| --- | --- | --- |
| `press` | 20–2000 | 所有 Aletheia 手动 Twist 的扩展 pressure 字段。 |
| `movement_acc` | 10–1000 | 有效非零运动 Twist 的扩展 acceleration 字段。 |
| `stop_acc` | 20–2000 | 所有 `speed=0` 且 `angle=0` 的手动 STOP Twist。 |

参数由现有 `SettingsStore` 校验、持久化并在成功保存后注入现有 Controller。前端输入仅作第一层约束；Controller 和 SettingsStore 均独立执行有限数与范围校验。参数更新不会改变解除急停 JSON 的固定 `acc=2000` 与 `press=1400`。

`MiniappTwistFactory` 继续是唯一的手动 Twist 构造入口：非零 `linear.x` 或 `angular.z` 选择 `movement_acc`；二者均为零时选择 `stop_acc`。因此所有既有 STOP 路径共享同一规则，不能各自硬编码 `acc`。

## 6. HTTP 状态与兼容性

现有 `GET /api/vehicle-control` 保持端点和已有字段，增量返回：

```json
{
  "emergency_stop": {
    "state": "normal|triggered|unknown",
    "release": "idle|waiting_confirmation|confirmed|failed|unconfirmable",
    "message": ""
  },
  "chassis_parameters": {
    "press": 1400,
    "movement_acc": 1000,
    "stop_acc": 1200
  }
}
```

新增受控 POST：

- `/api/vehicle-control/release-emergency-stop`：无需要会话 ID；仅发送固定 `/command`，以订阅反馈确认；未决时返回 `202`。
- `/api/vehicle-control/chassis-parameters`：接收三个数值，Controller 与 `SettingsStore` 二次校验并保存；成功后返回当前完整控制状态。

既有 enter、heartbeat、command、speed、stop、exit 接口、请求字段与状态码语义保持；它们只会因急停门控返回现有的安全冲突状态。建图工作台无需新的 endpoint 或 UI，即会因 `manual_ready` 的变化自动停用运动。

## 7. PC Web 界面

只扩展 `manual-control.html`：

- 在已有“安全状态”区域放置明显的三态急停读数与“解除急停”按钮；未知和触发状态均用清晰文字说明且保持方向控制锁定。
- 在已有速度设置之后增加紧凑的“底盘参数设置”，采用带 label、范围提示和保存动作的三个 number input；不改动原速度控件、方向盘或控制权动作。
- 按钮有 pending / disabled / error 状态，且从后端状态渲染，不凭前端动作假定成功。
- 延续现有工业控制台 token、间距与小圆角；不引入页面重构、装饰性卡片或动画。

## 8. 修改范围

- `autodrive_console/vehicle_control.py`：ROS subscription / publisher、急停状态机、固定解除命令、参数快照与统一 Twist acceleration 选择。
- `web_console.py`：新增两个受控 HTTP action，保存参数后更新当前 Controller。
- `autodrive_console/settings.py`：默认、迁移、严格校验与持久化 `vehicle_control`。
- `autodrive_console/web/manual-control.html`、`manual_control.js`、`manual_control.css`：仅新增急停/参数 UI 与现有状态渲染扩展。
- `shared/contracts/robot_control.md`、`PROJECT_OVERVIEW.md`：记录新的 ROS topic、HTTP 增量、固定解除边界及配置事实。
- `tests/test_vehicle_control.py`、`tests/test_offline_modules.py`（必要时 HTTP 定向测试）：覆盖安全状态、固定报文、停止 acceleration、范围/持久化与前端结构。

不会修改任务执行、轨迹、实时观测、视频、MediaMTX、地图、Supervisor、Mobile 或 `place` 控制。

## 9. 验证策略

### 自动化

1. 首次状态为 unknown 时拒绝进入和非零运动；`false` 加 miniapp 实际确认后恢复允许。
2. `true` 时立即清空运动并输出带 `stop_acc` 的零 Twist；所有看门狗、退出和 STOP 也验证该 acceleration。
3. 解除请求在 true 时发布精确固定 String，状态保持 waiting；只有 false 回调确认；超时和 unknown 分别失败。
4. `press`、`movement_acc`、`stop_acc` 的边界、NaN、布尔值、越界与 `SettingsStore` 重启加载均测试。
5. 既有控制源切换、速度档位、输入/心跳 watchdog、建图工作台共享状态与既有 API 回归。
6. 运行 Backend 测试、Web 检查/生产构建、JS 语法检查、差异检查与 UI detector。

### 实车验收

1. `ros2 topic info -v /is_emergency_stop` 确认 QoS，正常 false → 物理急停 true → 物理解除 false。
2. true 与 unknown 状态下，手动控制页和建图工作台均不能产生新非零 `/cmd_vel_miniapp`。
3. 软件解除只发布固定 `/command`，不改变 `/control_source_state`；回调 false 前页面不得报成功。
4. 逐一检查停止按钮、松开、失焦、键盘松开、输入超时、心跳超时、退出与外部切源的实际 `acc=stop_acc`。
5. 更新三个参数、重启 Aletheia 后确认保留；确认运动报文使用 `movement_acc`，STOP 使用 `stop_acc`。
6. 有真实安全观察员和物理急停可用时进行；任何 unexpected command、状态不一致或 QoS 不兼容即停止实车测试并导出工具日志。
