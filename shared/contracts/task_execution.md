# 任务执行

**Status: Existing（已实现）**
**权威实现：** `web_console.py`、`autodrive_console/case_store.py`、`autodrive_console/run_manager.py` 和 Mobile 功能 Repository
**消费者：** `robot_backend`、`web_console`、`mobile`
**兼容性：** 优先增量变更；破坏性变更必须同时更新所有消费者和本文档。

## 任务状态码注册表影响记录（2026-09-27）

`/task_status` 的生产者仍是车辆行为树；Topic、消息 envelope（`status_code`、`task_uuid`、`message`）和既有 ROS 所有权均不变。`autodrive_console/task_templates/indoor_elevator_v1/task-status-codes.json` 是该实验 profile 的受控状态码注册表：数值在注册表内为整数，已渲染 XML 和入站 ROS `status_code` 按字符串比较。实验任务编译器、`VehicleExecutionStatusMonitor`、验收自动返程 bridge 与 R6B 多点配送收集器是当前注册表消费者。编译器只渲染已批准的 `STATUS_*` 模板令牌并记录注册表 SHA；监控和收集器每次按命名值读取注册表。

PC Web 仍只消费 `GET /api/vehicle-execution-status` 的 `{phase,label}`，不消费状态码、注册表或 ROS Topic；Mobile 仍是该协议的非消费者。注册表读取失败时，状态显示通常只保留已有的文件名/通用导航降级语义；唯一窄例外是监控器可继续显示一个在摄入时已匹配上次可信 `task_complete` 码、并已通过同 UUID 会话保护的完成事件。首次加载注册表失败时没有可信完成码，不能完成任何事件；任意未验证事件也不能因后续注册表恢复或映射变化被追溯提升为完成。自动返程与配送通过判定仍必须拒绝，不能基于旧的硬编码数字采取动作。

Backend 拥有任务文件、校验、执行状态、报告、取消、恢复和 supervisor 协调能力。现有 API 家族包括 `/api/cases`、`/api/runs`、`/api/runs/latest`、`/api/reports`、`/api/acceptance`、`/api/scenario-setup`、`/api/supervisor/processes` 和 `/api/tool-logs`。

变更性操作属于受控动作：客户端 UI 必须呈现目标、确认、返回错误和当前状态。Mobile 可以消费这些 API，但不得直接改写机器人任务、执行任意命令或创建离线升级包。

## 用例管理（Desktop Web）

**运行时执行方：** Backend `CaseStore`、`CaseWorkspace` 与既有场景方案/设置存储；**现有消费者：** PC Web `/case-library.html`；**非消费者：** Mobile。

`DELETE /api/cases/{case_id}` 仅删除当前正式任务目录中已扫描、通过基础校验的一个本地 JSON 用例。`case_id` 必须是精确的已发现文件标识，不能包含路径分隔符；Backend 再次确认其解析路径仍位于正式任务目录，绝不接受浏览器提交的文件路径。执行任务存在时必须返回 HTTP 409，不能删除。成功删除后仅清理该用例的本地别名、场景方案绑定和可选管理元数据，不触碰其他用例、机器人运行时或 ROS 控制边界。PC 页面必须在“用例管理与交付”区域以行内二次确认展示完整文件名与不可恢复提示；失败时保留确认状态并展示 Backend 返回的原因。该操作不提供给 Mobile，新增消费者前须更新本文档并完成其定向验证。

## 部署验收（Desktop Web）

**运行时执行方：** Backend `AcceptanceOrchestrator` 通过既有 `RunManager`；**现有消费者：** PC Web `/acceptance-test.html`；**非消费者：** Mobile。

验收计划只能从正式任务目录只读扫描并冻结任务 SHA-256；执行仍走既有受控测试序列，不创建新的 ROS 控制或任务下发路径。范围可以是整个小区，或一个实际物理楼宇单元；物理楼宇单元的稳定键为 `(building, unit)`，例如 `5栋1单元` 与 `5栋2单元` 必须视为两个不同验收对象，即使它们属于相连的“5栋”。

抽样是代表性验收，不是住户普查。响应中的 `selection_summary` 以 `tasks`、`delivery_points`、`physical_buildings`、`floors`、`doors` 描述本次实际覆盖；`tasks` 是冻结任务条数，`delivery_points` 是这些任务包含的配送点总数，后三项按所有冻结配送点去重统计。不得把“抽样未覆盖每层/每户”当作告警。计划内部保存的随机种子仅用于可审计复现和离线报告，公共 API 与页面不得返回或显示该字段。

部署验收不要求实施人员填写通过率、覆盖率或允许失败数。系统自动显示计划的实际样本覆盖，并按固定规则判定：计划内**所有**任务通过才通过；任一未通过任务即不通过。抽样计划的结果文案必须明确为“本次抽样通过 / 不通过”，并说明它不代表全小区全量验收。旧本地状态中的阈值字段仅为读取兼容保留，不参与新计划的判定，也不应出现在新的计划公共响应或页面。

部署验收计划可选用已有的受控运行前置条件。`POST /api/acceptance/plans` 只额外接受 `scenario_profile_id: string | null`、`use_dependency_plan: boolean` 与 `use_automatic_return: boolean`：前者只能引用已保存的场景方案，后两者只能请求冻结当前已启用的 Supervisor 编排及自动返程策略；浏览器不得提交路径、节点名、阶段内容或 ROS topic。响应的 `execution_preflight` 仅公开方案名称、编排阶段/节点数量及 `automatic_return_enabled`，持久化计划保留完整的已验证依赖编排快照；`execution_preflight_status` 公开固定状态、受控中文说明、更新时间及只读的 `dependency_progress`。后者在未选择依赖编排时为 `null`；选择后只包含冻结阶段的序号、阶段状态（`pending`、`restarting`、`waiting_stable`、`settling`、`ready`、`blocked`、`cancelled`）及同一冻结节点的受限 Supervisor 状态（`PENDING`、`RUNNING`、`STARTING`、`STOPPED`、`BACKOFF`、`EXITED`、`FATAL`、`MISSING`、`UNKNOWN`）。它不含命令、脚本、节点配置、实时进程详情或任何浏览器控制能力。开始计划时，Backend 在**整份序列开始前一次性**应用方案并执行冻结的依赖编排；每项任务继续使用既有安全检查、同步、ROS 服务和轨迹链路，但不得再次重启依赖或重应用场景。启用自动返程后，Backend 仅在当前验收项已实际下发后监听既有 `/task_status`；只有注册表可验证的 `task_return_waiting` 事件（默认值 `103`）才会向既有 `/start_return` 发布一次 `std_msgs/msg/Bool {data: true}`，并在计划结束时释放该 ROS bridge。注册表无效时必须拒绝自动返程，不能用固定数字替代。普通测试继续使用 `task_execution_timeout_s` 本地等待上限；验收序列的单项任务不使用这个通用截止时间，而是等待既有任务服务返回真实终态，同时始终响应操作员取消和人工判定失败。取消请求被接受后，计划先进入 `cancelling`：页面必须保持范围锁定，且不得允许创建或开始下一计划；仅在执行线程确认已安全停止并回传 `sequence_finished/cancelled` 后，计划才进入 `cancelled`、生成唯一 HTML/CSV 报告并解锁下一计划。若此期间发生进程或整车断电重启，计划必须转为 `interrupted`，清除失效的运行 ID 与预检快照，并由操作员核对未知项；绝不自动重发。计划进入 `completed`、`cancelled`、`blocked` 或 `failed` 的任一终态时，都必须仅生成一份 HTML/CSV 验收报告，保留已经获得的结果、未执行项和轨迹证据。完成、取消、阻塞或异常后，如已应用方案，Backend 只恢复常规启动脚本，绝不因恢复而启动、停止或重启 Supervisor 节点。PC Web `/acceptance-test.html` 是该字段的唯一消费者；Mobile 不是消费者，保持不变。

`ready` 只表示计划已生成、尚未下发，允许操作员重新选择范围或运行准备并再次调用创建接口覆盖该计划；浏览器不得因 `ready` 禁用范围、抽样或生成计划控件。只有 `preparing`、`running`、`awaiting_recovery`、`recovering`、`cancelling` 和 `interrupted` 会锁定该范围；其中 `interrupted` 必须先由操作员完成现场核对，才可创建新计划。

部署验收计划的 `execution_mode` 为 `single_r6s` 或 `multi_r6b`，旧计划缺少该字段时按 `single_r6s` 读取。R6S 继续从 `origin_tasks` 读取并调用 `/start_execute_tasks`；R6B 只读 `/opt/ry/data/tasks/multi_tasks/{community}`，以 `floor` 下同一任务的正返程文件作为发任务测试来源并冻结目录指纹，不读取 `origin_tasks`。`indoor/`、`outdoor/` 和 `sub_outdoor_eguard*` 不是 R6B 发任务测试的必需目录；仅当创建请求显式启用 `out_eguard` 时，Backend 才要求对应的 `sub_outdoor_eguard.json`。

R6B 创建请求的 `multi_options` 提交 `out_eguard`、`return_origin`、`chain_mode`、`max_points_per_task` 以及 `floor_ranges`。`max_points_per_task` 是 `1..10` 的整数，缺省按 10 兼容旧客户端；它只约束多点链路和组合验收，单点链路仍固定每条任务一个配送点。`floor_ranges` 是按范围内栋单元填写的 `{building, unit, min_floor, max_floor}` 数组；最低/最高值遵循电梯服务楼层规则（`-20..120`、最低不高于最高、自动排除 0 层）。标准 `floor/{building}_{unit}_n_nXX.json` 模板按该栋单元的按钮范围展开：每个按钮层生成一个业务楼层和保留模板门牌后缀的目的地，例如 `6_1_n_n01` 在 5～12 层范围生成 `6_1_5_501` 至 `6_1_12_1201`。`floor/{building}_{unit}_{physical_floor}_{door}.json` 专用文件仍只代表文件名中的一个具体目的地；与模板目的地重合时专用文件优先，其余楼层继续使用模板。没有模板的栋单元不要求填写范围。

多点链路抽样时，`sample_size` 表示要冻结的任务条数，而不是模板文件数。Backend 对当前范围内展开的配送点做带随机种子的乱序，为每条任务随机分配 `1..max_points_per_task` 个点；同一计划的不同任务之间不重复使用配送点，同一任务也不重复点位，并且不得跨栋单元混合一条链。可用配送点少于 `sample_size` 时创建失败并返回最多可生成的不重复任务数。全量模式按栋单元随机打乱全部配送点，再以 `max_points_per_task` 为上限分组，确保每个配送点恰好覆盖一次。组合验收为每个上述随机分组冻结一条对应的单点基线与一条多点链路。Backend 在冻结时生成本计划内唯一的短格式 `task_uuid`（如 `task-001`）与链内顺序配送码（如 `01`、`02`）。冻结后的 `multi_options` 保存点数上限、楼层范围和一组链路；每条链路包含唯一 `task_uuid` 与按顺序排列的 `tasks_seqs`，每个目的地包含业务栋、单元、楼层、门牌、`cargo_type`（`1` 上舱自动、`2` 下舱自动、`0` 双舱自动、`-1` 不自动）和链内唯一 `delivery_code`。Backend 使用 `master_interfaces/srv/StartMultiTasksExecute` 的强类型 `MultiTaskDestination[]` 下发，不把请求编码为旧版 JSON 字符串。

R6B 链路执行期间只读监听既有 `/task_status`；注册表可验证的 `multi_task_arrived` 事件（默认值 `701`）且 `task_uuid` 与当前链路相同、消息等于某个冻结 `delivery_code` 时，该点记为 `passed`。注册表无效时不得标记配送点通过。服务成功但缺少任一配送码事件时链路记为 `failed`，未收到事件的点记为 `skipped`；Aletheia 不创建货舱控制通道，货舱动作仍由导航任务行为树完成。R6B 报告和 CSV 逐点保留链路 UUID、配送码、货舱类型、事件状态、跳过原因和来源文件指纹。该模式的唯一消费者仍是 PC Web `/acceptance-test.html`，Mobile 不消费这些字段。

`GET /api/reports` 继续返回 `filename`、`size`、`modified_at`、`csv_filename`，并增量返回 `report_type: "test" | "acceptance"` 和 `title`。所有现有消费者可忽略新增字段；两类报告均使用既有预览、HTML 下载、CSV 下载与删除路径。两类报告均为单文件 HTML，并内嵌已验证的轨迹 SVG、采样点数据和离线交互脚本：鼠标靠近轨迹时磁吸最近采样点，卡片显示在点上方，展示北京时间、路线标识、X/Y 坐标及采样序号，不显示未经定义的“偏差”推断值。删除时只会依据 Aletheia 写入的受限清单删除其专属轨迹目录；既有已生成报告不会被后台改写，需重新生成才能获得新交互。

## 车辆执行状态显示（Desktop Web）

**运行时执行方：** Backend `VehicleExecutionStatusMonitor`；**现有消费者：** PC Web `/vehicle-execution-status.html`；**非消费者：** Mobile 与未来车载屏。本能力只读订阅既有 `/task_status`、`/navigate_todoor_detailed_status` 和 `/navigate_todoor_status`，不创建 ROS 控制通道、不下发任务，也不影响底盘、导航、电梯或 Supervisor 的既有安全边界。

`GET /api/vehicle-execution-status` 返回不可缓存的 JSON 快照，响应严格只有两个字段：

```json
{
  "phase": "riding_elevator",
  "label": "乘梯中"
}
```

`phase` 是闭集：`idle`、`emergency_stop`、`manual_control`、`task`、`calling_elevator`、`entering_elevator`、`riding_elevator`、`exiting_elevator`、`closing_elevator_door`、`opening_gate`、`closing_gate`、`opening_access_door`、`closing_access_door`、`draining_or_unloading`、`completed`、`restarting_nodes`、`unavailable`。显示优先级为真实急停、已确认的 `miniapp` 控制源、受控节点重启、车辆任务行为。急停只采纳既有 `VehicleControlController` 对 `/is_emergency_stop=true` 的锁存确认；手动控制只采纳其对 `/control_source_state=miniapp` 的确认，绝不由浏览器会话或点击结果推断。控制台正常运行但尚未下发任务、尚未收到首条导航上下文，或导航明确为 `idle` 时，接口返回：

```json
{
  "phase": "idle",
  "label": "空闲中"
}
```

只有 ROS 运行时明确不可用，或已知活跃任务的导航心跳过期且无法确认安全终态时，接口才以 HTTP 200 安全返回：

```json
{
  "phase": "unavailable",
  "label": "状态暂不可用"
}
```

`/navigate_todoor_detailed_status` 是路径点/行为切换上下文，不要求持续发布；`/navigate_todoor_status` 是导航存活心跳。只要心跳仍新鲜，后端保留最近详细状态的路点、速度模式和行为树上下文；已知活跃任务的心跳中断后才将非终态降级为 `unavailable`。没有活跃任务或导航上下文本身是正常空闲，必须显示 `idle`，不得降级为 `unavailable`。`/task_status` 的 `status_code`、`task_uuid`、`message` 是任务执行方定义的正式协议，后端内部保留三者但极简 API 不公开它们；它是边沿事件而不是心跳，同一任务的最近阶段码必须锁存到下一阶段码、导航终态/空闲、控制覆盖或活跃任务心跳失联，路径 XML 的普通切换不得清除它。状态阶段由注册表命名值映射：`task_complete`（默认值 `109`）只有在摄入时匹配当时有效或上次可信的完成码、且本监控器此前已观察到同一非空 `task_uuid` 的非终态事件后才表示“任务完成”；孤立、空 UUID、UUID 不匹配或注册表恢复后才被映射为完成的未验证事件必须忽略，未下发任务的车辆保持 `idle`。判定优先级是：真实急停、确认的手动控制、受控节点重启、当前物理速度段、正式 `TaskStatus` 阶段码、已批准行为树语义、活跃导航的通用“任务中”。因此 `elevator_in` 速度段优先显示“进梯中”；`elevator_waiting`/`elevator_in`/`elevator_taking`/`elevator_outing`/`elevator_arrived`（默认 `200/201/202/203/209`）依次表示呼梯、进梯、乘梯、出梯、电梯到达（继续显示乘梯）；`gate_in`/`gate_out`（默认 `301/302`）表示开/关闸机，`auto_door_in`/`auto_door_out`（默认 `303/304`）表示开/关门禁；`clamp_water_waiting`/`clamp_water`/`place_water_waiting`/`place_water`（默认 `400`–`403`）表示泄水/卸货；`photo_upload`（默认 `500`）表示任务内图片上传并显示“任务中”；`door_waiting`（默认 `300`）仅表示门禁等待，保留已批准行为树语义或“任务中”，不得单独造成“状态暂不可用”。注册表读取失败时不得从固定数字推断特定物理阶段。

`restarting_nodes` 仅表示 `RunManager` 正在执行 Aletheia 已配置的 Supervisor 依赖控制与稳定等待，绝不从普通运行状态、进程名或浏览器行为推测。当前 PC 页面只显示 `phase` 与 `label`；未来 Mobile/车载消费者接入前必须在本文档更新消费者清单并运行其定向验证。当前定向验证为 `scripts/test-backend.sh` 和 `scripts/test-web.sh`。

## Planned（规划中）

新的任务 schema 版本在使用前，需要在 `shared/schemas` 中提供 JSON Schema、经过 Backend 校验、完成消费者兼容性评审并给出迁移说明。

### Mobile Native Reports（Mobile 原生测试报告）

**Status: Planned（仅契约，尚未由 Backend 实现）**
**未来运行时生产者：** `robot_backend`
**未来消费者：** `mobile`；**PC Web：非消费者**，保持现有 HTML/CSV 报告流程不变。
**兼容性：** 本节是对既有报告索引的增量约定。本文档的 Existing `GET /api/reports`、文件下载、预览和 filename 删除语义在 Backend 完成迁移并通过消费者验证前均保持不变。

#### 索引增量字段

`GET /api/reports` 必须继续返回既有的 `filename`、`size`、`modified_at`、`csv_filename`、`report_type` 和 `title`。当车端具备原生报告数据时，可以为单个索引项额外返回可选的 `native_report`：

```json
{
  "schema_version": 1,
  "report_id": "rpt_01J8",
  "kind": "test",
  "title": "路径验证 · 第 3 次运行",
  "status": "failed",
  "created_at": "2026-09-23T10:30:00+08:00",
  "duration_ms": 184000,
  "summary": {
    "total": 12,
    "passed": 10,
    "failed": 1,
    "blocked": 1,
    "pass_rate": 83.3
  },
  "headline": "定位收敛超时。"
}
```

`schema_version` 当前只能为 `1`；`report_id` 是服务端生成的 opaque identifier，客户端不得从文件名、路径或内容推导它。`kind` 只允许 `test`、`acceptance`；`status` 只允许 `passed`、`failed`、`blocked`、`cancelled`、`incomplete`、`unknown`。时间为 ISO-8601 带时区时间；`duration_ms`、任务数及其计数必须是有限且非负的整数，`pass_rate` 必须为有限的 `0..100` 数值，且 `passed + failed + blocked <= total`。`headline` 为短的受控纯文本，允许缺省。

未知 schema、非法 identifier/枚举、畸形时间或指标、以及缺失 `native_report` 都表示该索引项没有可安全展示的原生数据；Mobile 必须显示“车端尚未提供原生报告数据”，不得将其降级为 HTML、CSV、浏览器、WebView 或文件下载。

#### 分页详情端点

Backend 完成实现后提供：

```text
GET /api/reports/{report_id}/native?cursor=<opaque>&limit=<1..100>
```

未传 `cursor` 时返回第一页；默认 `limit` 为 `50`，最大为 `100`。`cursor` 仅能原样回传服务端先前给出的 opaque cursor，不能作为路径、文件名或查询表达式解析。成功响应重复固定 `report` 元数据，返回一个 `items` 页及 `next_cursor`（末页为 `null`）：

```json
{
  "report": { "schema_version": 1, "report_id": "rpt_01J8", "kind": "test", "title": "路径验证 · 第 3 次运行", "status": "failed", "created_at": "2026-09-23T10:30:00+08:00", "duration_ms": 184000, "summary": { "total": 12, "passed": 10, "failed": 1, "blocked": 1, "pass_rate": 83.3 }, "headline": "定位收敛超时。" },
  "items": [
    {
      "item_id": "task_01",
      "title": "到达目标点",
      "status": "passed",
      "duration_ms": 84000,
      "summary": "到达阈值内。",
      "detail": "受控诊断摘要。"
    }
  ],
  "next_cursor": null
}
```

`item_id` 与 `report_id` 使用相同的 opaque identifier 约束；单项 `status` 可为上述固定值，未知的未来状态由客户端显示为 `unknown`。`summary` 与 `detail` 仅允许受控纯文本诊断摘要，必须受长度限制；不得返回或渲染本机路径、文件 URL、HTML、CSV、SVG、任意富文本、原始 ROS 消息、指令、凭据或未脱敏现场数据。无效或不属于当前授权报告的 `report_id` 必须返回 `404`；无效 cursor/limit 必须返回受控 `400`，不得泄露报告目录或其他报告的存在性。

#### 地图轨迹证据（Planned）

为了让 Mobile 原生报告与既有 HTML 报告使用同一份已归档的运行证据，`items` 中可以增量包含 `trajectory_refs`。缺失等价于空数组，表示该项尚未归档原生轨迹，不影响原有任务结果展示：

```json
{
  "item_id": "task_01",
  "trajectory_refs": [
    {
      "trajectory_id": "traj_01J8A",
      "label": "T-003 · 一层大厅",
      "status": "available",
      "sample_count": 624,
      "integrity_warning": null
    }
  ]
}
```

`trajectory_id` 与 `report_id` 都是服务端签发的不透明标识；`label` 与 `integrity_warning` 是长度受限的受控纯文本。`status` 只允许 `available`、`incomplete`、`unavailable`；`sample_count` 必须为非负有限整数。未知枚举、非法 identifier 或畸形数据表示该条引用不可安全展示，Mobile 不得猜测、补全或读取报告文件。

Backend 完成实现后提供以下只读报告专属端点：

```text
GET /api/reports/{report_id}/native/trajectories/{trajectory_id}
GET /api/reports/{report_id}/native/trajectories/{trajectory_id}/map.png
GET /api/reports/{report_id}/native/trajectories/{trajectory_id}/samples?cursor=<opaque>&limit=<1..1000>
```

第一端点返回一个历史地图段：`schema_version: 1`、其 `trajectory_id`/`item_id`、受控 `label`、`map`、`display_paths`、`virtual_walls`、`sample_count`、可选 `integrity_warning` 与可选 `samples_next_cursor`。`map` 必须包含受控 `label`、有限且严格大于零的 `resolution_m`、`width_cells`、`height_cells`，以及有限的 `origin_x_m`/`origin_y_m`。每条 `display_paths` 只能为 `actual` 或 `ideal`，包含长度受限 `route_name` 和不超过 2,000 个有限 `x_m`/`y_m` 点；每条路径必须保持同一地图段内的顺序，绝不跨地图连接。`virtual_walls` 是每条至少两个有限点的多段线。显示级路径从同一份完整归档样本确定性生成，只为首屏渲染优化，不能替代原始样本证据。

`map.png` 只返回报告生成时冻结的该地图段底图，必须是受 Backend 尺寸/字节上限约束的 `image/png`；它不是当前 Observation 地图或 Deployment 地图的通用下载入口。JSON 响应绝不包含 URL、文件名、本机路径或文件系统标识，Mobile 只能由已验证 ID 构造上述固定请求路径。

样本端点默认 limit 为 1,000，最大为 1,000；其响应返回 `samples` 与可选不透明 `next_cursor`。每个样本必须包含有限 `x_m`/`y_m`、非负整数 `timestamp_ns`、受控 `route_name` 和严格递增的稳定 `sample_index`。分页不得重复、遗漏或重排样本；Mobile 只在需要精确点选或继续查看时按需读取，不能把当前实时地图或未经验证的点与报告轨迹混合。

无效 report/trajectory identifier、cursor 或 limit 返回受控 `400`。未知、已删除、无权读取或不属于报告的 `trajectory_id` 返回受控 `404`，不得泄露运行目录、其它报告或部署项目的存在性。Backend 必须在报告生成时从既有 HTML 报告使用的轨迹记录与冻结地图资产校验/归档这些数据；不得在请求时解析 HTML、SVG 或从当前运行时地图重新推断历史证据。

#### 迁移、影响与升级条件

- Backend 先在生成新报告时写入受控的结构化 sidecar/存储记录，并仅在完整校验通过时向索引添加 `native_report`；历史 HTML/CSV 可以按需回填，但不是客户端解析历史文件的理由。
- Mobile 在 `native_report` 缺失或不安全时保持不可导航的迁移状态；只在 summary 有效时请求 Planned 详情端点。它不读取、下载、保存或导出报告文件。
- Mobile 仅在已验证的 `trajectory_refs` 存在时按需请求报告专属轨迹端点；它使用冻结底图及同一报告的坐标元数据进行原生渲染，不读取 HTML/SVG、当前 Observation 地图或 Deployment 地图。
- PC Web 不消费此字段或详情端点，不改变现有报告页面、下载与删除行为。
- 既有 `DELETE /api/reports/{filename}` 的 filename 受控删除路径保持不变；`report_id` 不能替代、扩展或绕过它。
- 将本节端点从 Planned 提升为 Existing 前，Backend 必须完成输入/输出校验、404/400 安全语义、旧索引兼容与迁移说明；Mobile 必须验证缺失/畸形/分页/错误状态；PC Web 必须确认忽略新增字段仍保持既有流程。然后在本文档记录三方验证证据与实际权威实现。
