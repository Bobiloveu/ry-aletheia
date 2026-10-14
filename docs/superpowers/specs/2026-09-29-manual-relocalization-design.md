# 实时观测手动重定位设计

## 目标

当现场人员从实时观测发现车体位姿漂移或定位丢失时，可在不移动小车的前提下，拖动地图上的车体预览，使实时点云与局部代价地图和静态地图特征对齐；确认后由 Backend 使用该预览位姿调用既有 `/localizer/relocalize` 服务。

这是受控车辆操作，不是浏览器 ROS 通道。浏览器不能指定 ROS 服务、地图配置文件、`z` 值或控制源。

## 安全与运行边界

- 活动测试任务**允许**开始校准；测试状态不被取消、暂停或篡改。
- 开始校准时，Backend 专门占用车辆控制器：请求 `miniapp`、发布有界 STOP，并且只在 `/control_source_state=miniapp` 的真实回报后允许拖拽或下发服务。
- 此占用不创建可驾驶的浏览器手动会话，且所有常规 `/api/vehicle-control/*` 非零运动命令在占用期间都被拒绝。
- 服务成功返回只代表接受请求；必须观察到本次请求后的 `initializing` 或 `relocalizing`，再收到新的、未过期的 `normal`，才请求 `navigation` 并等待 `/control_source_state=navigation` 确认。原任务可继续由车辆既有系统处理。
- 重定位服务超时、返回失败、ROS 不可用或恢复 `navigation` 失败时，均保持 `miniapp` 停车。页面必须显示受控原因和显式“切回自动驾驶”操作；绝不猜测已经恢复自动驾驶。
- 重复开始、并发确认、取消和恢复请求由服务端单次 operation 锁串行化。取消校准仅清除预览；在已进入 `miniapp` 后不得偷偷切回 navigation。

## 配置与地图来源

`config/console.json` 的 `live_observation.manual_relocalization` 是唯一的工具配置：

```json
{
  "z_m": 0.4,
  "service_timeout_seconds": 12
}
```

- `z_m` 默认为 `0.4`，限制为有限的安全范围；`roll`、`pitch` 固定为 `0`。
- 当前配置由定位节点持有。默认模式不读取定位 YAML、不制作临时副本，也不从启动脚本或行为树推测切图后的当前配置。默认请求 `map_path=""`，由定位节点沿用当前配置，位姿由本次请求传入。可选的手选模式只读浏览 `/opt/ry/config/localization` 内目录和 YAML，并在 Backend 校验其 `system.map_path/map.yaml` 属于受控地图目录后，将规范配置路径传给定位服务，并行调用 `/map_server/load_map` 切换对应二维地图；重复/合并字段、路径逃逸、不可读文件或文件变化都拒绝。两种模式均不改写配置或启动脚本。
- 只允许已核验空路径语义的运行版本：同时检查包版本、实际运行程序及加载库的内容和文件身份，未知或升级后未重启的混合版本拒绝操作。开始时绑定定位进程身份和直接查询的当前二维地图；切图、进程重启或地图无法确认时保持停车。支持版本以 `relocalization_config.py` 的已核验指纹清单为准。
- 服务请求固定使用 `lightning/srv/Relocalize`、`/localizer/relocalize`、自动空路径或已验证的手选 `map_path`、确认的 `x/y/yaw`、配置 `z_m`、`roll=0`、`pitch=0`。车辆协议必须先以 `use_wheel_odom=true` 发送准备阶段；仅在其成功后，才以相同位姿发送 `use_wheel_odom=false` 启动重定位。

## 后端协议与职责

`ManualRelocalizationController` 依赖既有 `VehicleControlController`、运行版本核验、直接地图参数查询、独立定位状态监控和 ROS2 service client。它不复用浏览器的普通 miniapp session，也不让 HTTP handler 直接调用 ROS。

`GET /api/observation/relocalization` 返回受控快照：是否可开始、阶段、可读原因、当前可预览真实位姿、operation 状态以及是否仍停在 `miniapp`。不泄露 lightning YAML 绝对路径、ROS 异常或 service payload。

新增动作均为 JSON `POST`：

| 端点 | 请求 | 结果 |
| --- | --- | --- |
| `/api/observation/relocalization/begin` | `{}` | 请求并确认 `miniapp` STOP 后进入 `calibrating`。 |
| `/api/observation/relocalization/apply` | `{ "x": number, "y": number, "yaw": number, "config_path"?: string }` | 有限值与阶段校验后调用重定位服务；服务接受初始化后，必须确认定位状态经历本次请求后的 `initializing` 或 `relocalizing` 再回到 `normal`，才请求 `navigation`。 |
| `/api/observation/relocalization/cancel` | `{}` | 仅在尚未 apply 时取消浏览器校准预览并恢复 navigation。 |
| `/api/observation/relocalization/recover-navigation` | `{}` | 服务失败后，由现场人员显式请求恢复 navigation。 |

服务端记录操作开始、确认位姿（仅 x/y/yaw）、结果和切源结果的受控审计事件；不记录 YAML 路径或任意 ROS 原始错误。`LocalizationStatusMonitor` 仍只读，使用独立有界状态记录保留无故障编号的手工初始化过程；重复正常心跳不会挤掉短暂初始化证据，请求前的旧初始化不算本次证据。既有按非空 `fault_id` 去重的故障事件流及轨迹报告计数不变。

手选文件仅用于本次重定位，每次开始默认自动；不持久化选择。面板在停车确认后开放配置模式与文件浏览，支持进入子目录、上一级、根目录和收起；浏览失败可切回自动。提交确认显示所选文件，请求在途锁定选择并废弃旧浏览结果。Backend 预校验失败不发送 ROS 请求、保留对齐状态供重新选择；准备阶段之后发生文件变化则保持停车等待恢复。

## 观测预览与交互

实时数据仍由既有 latest-wins WebSocket 输入；校准绝不改写、缓存或重新发布它们。

- 初始预览车体等于最新真实 pose `P0`。拖动与旋转手柄生成候选 pose `P1=(x,y,yaw)`。
- 对所有已在 `map` 坐标系的、随车观测层使用同一刚体预览变换 `T=P1 * inverse(P0)`：点云点 `p` 显示为 `T(p)`；局部代价地图的 origin 和 yaw 同样使用 `T`。底图、格栅、比例尺、虚拟墙和部署路线保持不动。
- 候选车体显示为预览态，明确标示“未下发”；传输中的真实 pose 继续更新为新的 `P0`，若尚未确认则以最新真实 pose 重新计算 `T`，避免用历史遥测判断匹配。
- 入口位于地图边角，与“图层”同级但默认低强调度。展开后为紧凑的阶段卡片：停车确认、拖拽对齐、提交确认。拖拽时显示米制 x/y 和 rad yaw；提交必须二次确认。遵循现有实时页的半透明中性表面、紧凑圆角、清晰状态色与 reduced-motion 约束。
- 关闭、取消、页面卸载或服务端阶段变化都必须清理仅前端存在的预览变换；不会改变实际定位。

## 契约、兼容与验证

- 更新 `shared/contracts/realtime_observation.md`：声明上述 PC-only 受控 API、状态机、坐标限制、停车/失败语义和不信任浏览器路径的规则。Mobile 不是消费者，不增加移动端入口。
- 更新 `shared/contracts/robot_control.md`：声明定位校准占用可以在活动任务期间建立、禁止普通运动会话、并且成功/失败后的控制源语义。
- 后端测试覆盖：配置默认/校验、运行版本及文件身份核验、无 YAML 读写、切图/定位进程重启拒绝、任务运行时可 begin、控制源确认前拒绝 apply、两阶段空路径 Relocalize 请求、短暂初始化/重定位和无故障编号、旧状态拒绝、service timeout/失败保持 miniapp、成功与显式恢复 navigation、并发锁和审计脱敏。
- Web 测试覆盖：校准入口与阶段展示、候选 pose 数值校验、拖拽/旋转的预览变换、点云与 costmap 共同变换、取消复位、确认请求以及服务端错误显示。
- 完成后执行受影响 Backend 与 Web 测试，审阅契约消费者，并以浏览器核验深色与浅色主题、窄屏和真实遥测连续刷新时的拖拽体验。
