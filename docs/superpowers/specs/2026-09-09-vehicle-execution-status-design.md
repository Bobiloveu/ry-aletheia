# 车辆执行状态极简显示设计

**状态：** 已实现
**范围：** PC Web 首发；后端只读 ROS 状态采集与受控 HTTP 快照；车载小屏与 Mobile 后续复用同一接口。

## 目标

为任务指挥台增加“执行状态”入口，打开一个全屏、只读的车辆行为状态页面。页面唯一业务信息是当前行为文字，例如“呼梯中”“进梯中”“乘梯中”“出梯中”“开闸机”“泄水/卸货中”或“任务完成”。表情动画只强化该文字，不传达第二套未经确认的业务语义。

该页面须同时适合 PC 全屏和未来车载小屏：远距离阅读、低视觉密度、无操作控件、无任务进度/时长/路径/任务文件名/阶段链路/调试选择器。

## 范围与非目标

- 仅新增只读状态能力；不得下发任务、控制底盘、切换地图、调用电梯或改变任何机器人安全边界。
- 不改变任务指挥台、手动控制、部署建图或其他既有页面的布局、样式和行为；仅在任务指挥台增加一个入口。
- PC 页面本地集成 `jeremy-prt/bloub` 的框架无关动画引擎，固定到 `b4bb3c1b5f93c7b87a2e8d620f667c4093d97749`；不得在运行时请求 GitHub、CDN 或其他外部资源。派生 ESM 模块、固定来源说明和完整 MIT 许可证保存在 `autodrive_console/web/vendor/bloub/`。
- 车载屏和 Mobile 不是本次消费者；本次不修改 Flutter 或其构建链。

## 后端分层

新增独立 `vehicle_execution_status` 模块包，保持每层可单独测试：

1. **ROS 采集器**：一个常驻、只读的 ROS2 节点订阅 `/task_status`、`/navigate_todoor_detailed_status` 与 `/navigate_todoor_status`。三者均为 volatile；详细状态只作为路径点/行为上下文，简单导航状态是持续心跳。采集器负责持续保存最近消息和其单调时钟接收时间，不能让页面打开时才创建订阅。
2. **状态分类器**：纯 Python 函数/不可变快照，不导入 rclpy、不读取时钟、不访问文件系统。输入为规范化的导航状态、完整 `TaskStatus` 事件和已批准的行为树语义；输出固定 `phase`。分类优先级为“当前物理速度段 → 源码定义的最近任务状态码 → 当前行为树文件语义 → 活跃导航通用状态”。
3. **语义解析器**：仅在经配置允许、解析后仍位于批准任务根目录的 XML 文件中读取 `ElevatorCaller target_floor` 等信息；本次极简接口不返回该信息。任何路径异常、读取失败或未知模板都只产生 `unknown`，绝不猜测。
4. **HTTP 适配器**：`web_console.py` 只注册 `GET /api/vehicle-execution-status` 并返回采集器快照；不包含 ROS、分类或 DOM 逻辑。

采集器可与现有 `NavigationStatusMonitor` 共用字段定义，但不得把全局车辆状态生命周期塞进按轮次创建/停止的 `TrajectorySession`。

## 状态判定

公开 `phase` 为稳定枚举，内部可保留原始码和文件名用于诊断日志，但极简 API 不返回这些字段。

| phase | 显示文字 | 已知判定依据 |
| --- | --- | --- |
| `idle` | 空闲中 | 控制台正常启动后未收到任务、未收到导航上下文，或导航明确为 `idle` |
| `task` | 任务中 | 活跃导航，或 `100`–`103`、`500`、`600`、`601`、`700`、`701` |
| `calling_elevator` | 呼梯中 | 代码 `200`，或 `elevator_in_*` 候梯/呼梯行为 |
| `entering_elevator` | 进梯中 | `current_speed_mode=elevator_in`，或代码 `201` |
| `riding_elevator` | 乘梯中 | 代码 `202` 或 `209`，或 `elevator_out_*` 行为 |
| `exiting_elevator` | 出梯中 | 代码 `203`，或已批准的 `backward` 出梯路段 |
| `closing_elevator_door` | 关电梯门 | `close_elevdoor_*` 行为树语义（无更高优先级阶段码时） |
| `opening_gate` / `closing_gate` | 开闸机 / 关闸机 | 代码 `301` / `302`，或已批准闸机行为树语义 |
| `opening_access_door` / `closing_access_door` | 开门禁 / 关门禁 | 代码 `303` / `304`，或已批准门禁行为树语义 |
| `draining_or_unloading` | 泄水/卸货中 | 代码 `400`–`403` 与取/放水行为树语义 |
| `completed` | 任务完成 | 代码 `109` 或导航终态 `completed` / `successful` |
| `restarting_nodes` | 节点重启中 | 仅限 Aletheia `RunManager` 实际执行受控依赖编排/恢复期间 |
| `unavailable` | 状态暂不可用 | ROS 运行时不可用，或已知活跃任务的导航心跳失联且无法确认终态 |

`TaskStatus` 的源码状态码表是阶段语义的唯一权威：`203` 必定为出电梯，`209` 为电梯到达且在下一物理阶段前保持乘梯显示。`300` 仅表示门禁等待，本身无开关方向，须回退至已批准的行为树语义或通用“任务中”。采集器保留 `task_uuid` 与 `message`；`TaskStatus` 是一次性阶段事件，最近状态在同一任务内锁存到下一状态码、导航终态/空闲、控制覆盖或活跃任务心跳失联，普通导航行为切换不得清除它。不得以名称模糊匹配扩展到未批准的模板。

## 时效与故障边界

- 快照拥有 `observed_at` 与 `fresh`，但极简浏览器页面只根据 `phase` 和 `label` 进行渲染。
- 导航详细状态是过渡上下文而不是心跳。已知活跃任务的简单导航状态心跳连续超过固定短时效窗口未更新时，采集器才输出 `unavailable`；最后一个任务事件不能无限延长旧阶段。控制台正常启动后没有任务或导航上下文、以及明确的导航 `idle`，均输出 `idle`，不属于状态源异常。
- 若任务事件先于导航状态到达，它只作为最近事件候选；导航显示终态、错误或失联时必须清除/降级。
- ROS 运行时初始化失败不阻塞 Web 控制台；接口安全返回 `unavailable`，并由工具日志记录原因。
- API 是只读、无缓存的普通 JSON；页面轮询无需保留历史队列，最新响应覆盖旧响应。

## API 契约

`GET /api/vehicle-execution-status` 是新增、向后兼容的接口。

```json
{
  "phase": "riding_elevator",
  "label": "乘梯中"
}
```

只有运行时或活跃任务心跳异常的不可确认状态返回 HTTP 200 与：

```json
{
  "phase": "unavailable",
  "label": "状态暂不可用"
}
```

运行时执行方为 Backend；当前 Existing 消费者为 PC Web；Mobile 和未来车载屏为明确的非消费者。实施时同步更新 `shared/contracts/task_execution.md`，记录接口、枚举、消费者、兼容性和定向验证。

## Web 页面与动画

- 任务指挥台新增一个小型“执行状态”入口，指向独立全屏页面。
- 全屏页面只渲染 `phase` 对应的圆形表情和 `label`。无导航栏、卡片、统计、说明文字、按钮、开发状态选择器或业务细节。
- `vehicle_execution_avatar.js` 是项目自有的薄桥接层：它只负责 `phase → Bloub state` 映射、单一 SVG 的生命周期和减少动态效果；`vendor/bloub/engine.js` 只保留固定上游引擎。两者不得混入轮询、ROS 或业务状态判定。
- 显式映射为：急停 `alert`（主体、提示点与文字统一红色），手动控制/任务完成/空闲 `idle`，任务/泄水卸货 `thinking`，呼梯 `notify`，进梯 `comet`，乘梯 `orbit`，出梯 `play`，开闸机/门禁 `wide`，关闸机/门禁/电梯门 `wink`，节点重启 `swirl`。`idle` 与 `unavailable` 固定为静止的 `idle`，不得伪造运行中的动画。
- `idle` 与 `unavailable` 表情静止；`prefers-reduced-motion: reduce` 时所有非必要动画停止。状态文字需以车载远距尺度呈现，页面保持高对比度。
- 动画状态映射、DOM 渲染、轮询客户端和样式各自独立，不能再向 `app.js` 堆叠长逻辑。开发预览中的 query 参数模拟状态不进入生产页面。

## 验证

1. 分类器单元测试：代码/行为树语义优先级、状态码复用、导航终态、未知输入、`restarting_nodes` 受控来源。
2. ROS 采集器测试：消息规范化、时效过期、ROS 不可用降级和最新快照并发读取。
3. HTTP 测试：正常与不可用快照、只读路由、`Cache-Control: no-store`。
4. Web 模块测试：响应到 `phase/label` 的唯一映射、旧响应不回退新响应、`phase → Bloub state` 映射、不可用静止、减少动态效果和 Vite 预览的本地 vendor 代理。
5. 手工视觉验证：PC 常用桌面尺寸与车载小屏参考尺寸，仅含表情与大号状态文字；确认不改变既有任务指挥台视觉。
6. 运行 `scripts/test-backend.sh`、`scripts/test-web.sh` 与 `git diff --check`；本次不运行 Mobile 测试。
