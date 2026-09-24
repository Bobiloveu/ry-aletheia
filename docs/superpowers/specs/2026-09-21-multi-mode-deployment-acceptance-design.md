# 多模式部署验收设计

## 目标

在现有部署验收页面中增加任务模式选择，使同一套验收编排同时支持：

- R6S 单点任务：读取现有正式单点任务目录，调用 `/start_execute_tasks`。
- R6B 多点配送：只读取 `/opt/ry/data/tasks/multi_tasks`，调用 `/start_multi_tasks_execute`，支持一个或多个 `tasks_seqs` 目的地。

单点和多点计划必须独立冻结、独立执行、独立报告，不能在一份计划内混用两种 ROS 服务。

## 任务模式与范围

计划增加不可变的 `execution_mode`：`single_r6s` 或 `multi_r6b`。现有计划缺少该字段时按 `single_r6s` 兼容读取。

两种模式都保留现有验收范围：

- `community`：全小区，覆盖所有可用物理楼宇单元。
- `building`：指定 `(building, unit)` 物理楼宇单元。

两种范围都保留 `full` 和 `sample` 计划方式。多点模式的“全量”覆盖冻结计划中的配送点；标准 `n_nXX` 模板按操作员为对应栋单元填写的电梯按键最低/最高层展开，具体楼层文件仍按文件名提供单个配送点。

## R6B 多点目录模型

多点目录根固定为 `/opt/ry/data/tasks/multi_tasks`，每个小区必须按以下结构只读扫描：

```text
{community}/
├── floor/{building}_{unit}_n_nXX.json
├── floor/{building}_{unit}_n_nXX_r.json
├── floor/{building}_{unit}_{physical_floor}_{door}.json
├── floor/{building}_{unit}_{physical_floor}_{door}_r.json
├── indoor/{building}_{unit}.json
├── indoor/{building}_{unit}_r.json
├── outdoor/{building}_{unit}.json
├── outdoor/{building}_{unit}_r.json
├── sub_outdoor_eguard.json
└── sub_outdoor_eguard_r.json
```

R6B 发任务测试以 `floor/` 中成对的正返程文件为必需来源；`indoor/`、`outdoor/` 和返程 gate 文件均为可选，只有显式启用 `out_eguard` 才校验 `sub_outdoor_eguard.json`。具体楼层文件 `{physical_floor}_{door}` 直接提供请求楼层和门牌，标准 `n_nXX` 模板才生成实际业务楼层。

目录扫描结果提供社区、物理楼宇单元、标准楼层模板、专用门牌文件和正返程配对状态。标准模板不是单个业务楼层；创建请求为包含模板的栋单元提交 `floor_ranges`（最低/最高电梯按键），计划按电梯按钮序列（跳过 0）展开每个模板的业务 `floor`、`door`。专用文件转换为对应的业务楼层；若与模板展开目的地重合，专用文件优先。冻结的业务楼层和门牌随后用于调用 ROS 服务。

计划创建时校验每个目的地：楼层正程和返程必须可由标准模板或专用完整门牌文件解析；专用文件的物理楼层和门牌直接来自文件名。室内/室外文件不是普通发任务测试的前置条件，只有选择摆渡层去程时才要求对应 gate 文件。目录和 JSON 文件只读，不生成或修改机器人任务文件。

## 多点计划编排

R6B 页面在选择小区、栋单元和链路模式后不要求人工填写配送点；对于标准模板，操作员只填写每个模板栋单元的电梯按键最低/最高值。计划创建时由 Backend 在展开后的有效配送点中随机生成/抽样货舱类型、链路 UUID 和配送码。计划预览显示冻结后的结果。每个点包含：

- 业务楼层和门牌；
- `cargo_type`：`1` 上舱、`2` 下舱、`0` 双舱、`-1` 不自动；
- 验收系统生成的唯一 `delivery_code`。

页面支持单点计划和多点链路计划；推荐默认提供“组合验收”预设：先执行代表性单点，再执行至少一条包含同栋连续点的多点链路。多点链路按表格顺序发送，不把多个点伪装成多个旧任务。计划冻结 `out_eguard`、`return_origin` 和每个点的货舱/配送码。

## 执行模型

`TestCase`/执行请求增加模式和请求载荷，旧单点调用保持原签名兼容。R6B 执行器使用现有 `master_interfaces/srv/StartMultiTasksExecute` 的强类型 `MultiTaskDestination[]`，不再把多点请求编码为旧版 JSON 字符串。

多点执行同步监听既有 `/task_status`，以 `task_uuid`、状态码 `701` 和配送码消息确认每个点的配送状态；服务整体返回成功不能掩盖未收到的配送点事件。未执行点记录为 `skipped`，取消、超时、服务异常和人工恢复状态沿用现有验收状态机。R6B 货舱实际动作仍由导航侧 `auto_cargo.xml` 和既有任务系统完成，Aletheia 不重复实现 `CargoCommand`。

## 前端交互

部署验收页面第一步增加“任务模式”：

- `单点任务（R6S）`：保留现有目录、范围、全量/抽样和计划表。
- `多点配送（R6B）`：切换到 `multi_tasks` 目录能力、随机配送点生成、单点/链路/组合编排、货舱类型、摆渡层和最终返程选项。

模式、范围和运行准备在计划生成时冻结；活动计划禁止切换。计划表显示链路及其子配送点，实时状态显示当前链路、当前点和配送码。终态报告显示模式、范围、链路、每点结果、目录文件证据、轨迹和未执行原因。

## 兼容性与安全边界

- 现有 R6S API、页面、计划文件和报告继续可读；旧计划缺少模式时按 `single_r6s`。
- `/api/acceptance/catalog` 增加模式化多点目录信息，现有字段保持不变。
- `/api/acceptance/plans` 增加 `execution_mode` 及 R6B 计划字段；服务端拒绝与模式不匹配的字段。
- Mobile 不是验收消费者，不新增 Mobile 能力。
- 共享契约 `shared/contracts/task_execution.md` 必须记录新增字段、目录来源、ROS 服务和消费者影响。
- 验收只读正式目录和 `multi_tasks`，不写任务文件、行为树、地图或运行配置。

## 验收判定

计划内所有执行项通过才判定计划通过。R6B 链路项只有在服务成功、所有预期配送点收到对应 `701` 配送码事件且没有跳过点时才通过。抽样报告必须明确“本次抽样”，全量报告只对冻结的计划点集合负责。
