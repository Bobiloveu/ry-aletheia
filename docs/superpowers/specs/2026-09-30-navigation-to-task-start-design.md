# 实时观测前往任务起点设计

## 目标

PC 实时观测页允许操作者在车辆没有测试任务执行时，选择一个已知任务起点并让车辆自动驶向该点。该能力服务于测试前就位和现场分析，不改变任务执行协议，也不让浏览器直接访问 ROS。

现场已确认 ROS 域 `66` 存在 `/navigate_to_pose`（`nav2_msgs/action/NavigateToPose`）Action Server，由 `/bt_navigator` 提供；`/goal_pose`（`geometry_msgs/msg/PoseStamped`）也由该节点订阅。实现只使用前者，以获得目标接受、反馈、成功、失败和取消的明确结果；不把 RViz 的 `/goal_pose` 发布入口暴露给 Web。

## 起点来源

页面将提供两个互斥的来源，而不是把大量 JSON 文件直接列成文件选择器。

1. **测试用例起点**：列出测试用例工作区中的用例，默认预选任务指挥台保存的当前用例。对所选文件只接受完整任务组 JSON 的 `subtasks[0].waypoints[0]`。
2. **小车常用任务起点**：只读扫描当前 `settings.task_directory` 的单点任务根，以及其同级 `multi_tasks/` 多点任务根。单点文件仍取 `subtasks[0].waypoints[0]`；多点文件是一个直接子任务对象，取 `waypoints[0]`。多点扫描只接纳正向文件，忽略 `_r.json` 返程片段。

小车常用任务不展示每个文件。Backend 将有效首点按规范化地图身份、`x`、`y`、`yaw` 精确分组，返回一个不透明的候选 ID、来源类型、可读标签和同起点文件数量。例如“单点任务常用起点（32 个文件）”。选择一个候选后，操作只读取该组已验证的代表文件；绝不把文件绝对路径、`map_url` 或原始 JSON 返回给浏览器。文件变更后必须重新扫描并重新校验，不能复用过期候选。

空目录、目录逃逸、非 UTF-8/畸形 JSON、空 subtasks/waypoints、缺少地图、非有限坐标、无效四元数或不可归一化航向都只形成受控诊断，不能变成可导航候选。扫描严格只读，不创建、覆盖、移动或删除机器人任务文件。

## 地图身份硬门槛

“前往起点”只支持当前正在显示的同一张地图，绝不自动切图、跨楼层、经过电梯或推测地图转换。

- Backend 从候选文件的 `map_url` 取得目标地图身份，同时从活动 `map_server` YAML 取得当前真实地图身份。
- 两者必须在受控根内解析为同一规范化文件，并由当前 OccupancyGrid 快照的分辨率、尺寸和原点再次确认；任一信息不可用、过期或不一致均为拒绝。
- 候选列表可将其他地图的起点隐藏并给出计数说明；即使页面已显示“可用”，`POST` 执行前仍以最新活动地图重新验证。
- 浏览器只得到“当前地图匹配 / 不匹配”与可读原因，不能得到文件路径或地图配置内容。

因此，测试用例可拥有不同起点；只要其首点所属地图不是当前观测地图，入口必然不可用。

## 导航状态机与安全边界

新增一个 Backend 拥有的 `TaskStartNavigationController`。它维护单一操作锁和有限状态：`idle`、`checking`、`navigating`、`cancelling`、`succeeded`、`failed`、`cancelled`。终态保留简短可读结果，直到下一次开始或刷新来源；并发开始和取消不得创建两个 Nav2 Goal。

开始前与 Action 提交前都必须同时满足：

- 没有普通测试或部署验收运行：`queued`、`preparing`、`running`、`awaiting_recovery`、`recovering`、`cancelling`、`interrupted` 均视为占用。
- 没有浏览器/移动端手动会话，手动重定位占用为 `idle`。
- `/control_source_state` 已确认且为 `navigation`；不能切到 `miniapp` 来执行本操作。
- 急停状态已确认且为 `normal`，定位状态为 `normal`。
- 目标文件、首点、当前地图和 `/navigate_to_pose` Action Server 全部经最新校验。

控制器以 `map` frame 构造 `PoseStamped`，将受控首点的 yaw 转为规范化四元数，创建 Action Goal 并异步跟踪反馈与结果。单次导航的受控上限为 300 秒；达到上限必须请求取消并显示超时。`accepted` 只表示请求被接受，不是到达成功；只有 Nav2 最终成功结果才显示“已到达”。失败、拒绝、服务不可用、超时或安全状态变为急停/未知、控制源丢失、手动/重定位占用时，都请求取消目标且显示受控失败原因，不自动重试。

取消操作只调用该 Goal 的 Nav2 cancel 流程并等待其结果；不发布 Twist、不伪造停止成功、不切换控制源。操作结束后仍为 `navigation`，由 Nav2 与机器人既有安全链路拥有车辆停止行为。

当导航处于 `checking`、`navigating` 或 `cancelling`，`RunManager` 必须拒绝创建任何新的测试/验收执行（409）；反向地，任一新运行状态也会阻止开始导航。这是双向互斥，不会暂停、修改或重发任务。

## 受控 HTTP API 与审计

实时观测增加 PC-only API：

| 方法 | 端点 | 请求 | 说明 |
| --- | --- | --- | --- |
| `GET` | `/api/observation/task-start-navigation` | — | 返回阶段、可否开始/取消、当前选择、来源候选摘要、地图匹配和受控说明。 |
| `POST` | `/api/observation/task-start-navigation/begin` | `{ "source": "case"\|"robot_task", "id": "opaque-id" }` | 重新解析来源并完成所有安全门槛后创建一个 Nav2 Action Goal。 |
| `POST` | `/api/observation/task-start-navigation/cancel` | `{}` | 仅取消当前控制器拥有的导航 Goal。 |

请求体上限 16 KiB。HTTP 只解析受限来源和不透明 ID，不接受坐标、yaw、map path、Action 名称、行为树、速度或 ROS 参数。冲突和安全拒绝使用 `409`，ROS 不可用使用 `503`；客户端不得无限重试。

工具日志记录来源类别、可读候选标签、地图匹配、Action 接受/终态、取消和安全拒绝；不得记录绝对路径、原始任务 JSON、ROS request/feedback、地图内容或异常堆栈。

## PC 界面

入口保持为地图上的独立半透明控件，与“图层”和“手动重定位”分离。点击后展开一个紧凑的“前往测试起点”浮层：来源分段选择、去重起点或测试用例选择、地图匹配状态及一条主操作。

- 默认使用任务指挥台当前选中的测试用例；操作者可以切换用例或改用车端常用任务起点。
- 当前地图不匹配、任务正在执行或任一安全前提不满足时，主操作不可用，并直接展示原因。
- 可开始时点击后先出现确认面板，名称为选中的用例或常用起点标签；确认按钮才触发 `begin`。
- 导航中浮层只展示阶段、简短状态和“取消导航”；不会遮挡地图、重置地图视角或移动图层。
- 使用既有实时页的半透明表面、紧凑圆角与状态颜色；浅色/深色和 `prefers-reduced-motion` 均须保持可读。Mobile 不展示该入口，也不消费新端点。

## 契约、兼容与验证

- 更新 `shared/contracts/realtime_observation.md`，声明 PC-only API、两种起点来源、地图硬门槛、阶段、取消与脱敏规则；标明 Mobile 非消费者。
- 更新 `shared/contracts/robot_control.md`，声明该 Action 是 Backend 拥有的 `navigation` 控制源操作，不能复用 `/goal_pose`、`/command` 或 `/vector`，并写明手动/重定位/急停互斥。
- 更新 `shared/contracts/task_execution.md`，声明活动“前往任务起点”操作阻止测试/验收开始，反之活动任务阻止该操作。
- Backend 测试覆盖：单点与多点只读解析、返程排除、精确去重、异常文件拒绝、候选过期重读、地图匹配/切图后二次校验、全部安全门槛、Action 接受/反馈/成功/失败/300 秒超时/取消、安全状态改变后的取消、RunManager 双向互斥、HTTP 错误映射与审计脱敏。
- Web 测试覆盖：来源切换、默认用例、候选去重标签、地图不匹配禁用、确认与取消、终态显示、深浅主题、窄屏和 reduced-motion。
- 完成时执行 `scripts/test-backend.sh`、`pixi run test-offline`、`pixi run frontend-check` 与 `git diff --check`。在实车仅在操作者明确指示下，以安全空旷区域验证一次同图起点导航、一次地图不匹配拒绝及一次取消；实现/CI 阶段不得自行发出实车运动 Goal。
