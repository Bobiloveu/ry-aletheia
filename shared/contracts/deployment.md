# 部署与地图配置

**Status: Existing（已实现）**
**权威实现：** `autodrive_console/deployment.py`、`autodrive_console/mapping.py`、`web_console.py` 和部署 Web UI
**消费者：** `robot_backend` 是项目快照、路线校验和实验导出的权威执行方；PC `web_console` 是部署地图与路线编辑器。Mobile 不是本定位路线/清单契约的消费者，且不得调用其路由。
**兼容性：** 优先增量变更；破坏性变更必须同时更新所有消费者和本文档。

2026-10-13 多条固定线路汇总影响 Backend 编译/下载与 PC Web 编辑/预览；Mobile 不消费，机器人既有 multi_tasks 文件格式不变。
`single` 仍以 `active_task_line_id` 选择一条线路；`multi` 校验并汇总全部已保存线路，每条用户楼层线路以一个送货目标结束，各户输出独立的 `floor/*[ _r ].json`。公共段语义一致才复用；同名文件的动作、几何、速度、地图或定位内容冲突时阻断，不能覆盖。未保存草稿不参与导出。
多线路预览清单新增 `compiled_task_lines`，每项保留线路 `id/name/start_component_id/steps` 及其在预览 `task_json.subtasks` 中的 `subtask_start/subtask_count`。`waypoint_trace` 增量记录 `task_line_id`，相应 `subtask_task_line_ids` 与子任务数组逐项对应。Web 可显示全部或一条线路，不在两条独立线路之间生成连接；实际动作与节点仍来自 Backend 编译。`active_task_line` 保留当前选中线路兼容字段，不能再作为 multi 包唯一成员。
多任务模式已有同图配送线路后，每次在用户楼层新放置目标组件，Backend 自动复制选中的同图线路（没有同图选中项时沿用同图首条），仅替换最后的配送目标；原有线路与活动选择保持不变。首次保存配送模板也会为该图尚无线路的目标补齐独立线路。未填门牌时以地图名称及可读目标编号命名，补填门牌后更新自动名称；人员自定义的线路名称保留。自动线路仍可通过既有接口单独编辑步骤和动作。没有已保存模板时不猜测取货/仓控意图，须先配置首条线路。
旧 multi 项目首次读取时为已有门牌且尚无线路的楼层目标补齐一次，并保存内部 `target_line_policy_version:1` 迁移标识；随后读取不重建人员显式删除的线路。只增加项目内线路，不改写原有线路或机器人目录。
多户共享末图定位清单沿用既有 multi 代表路线规则：同一 floor 模板的地图路径、init_go 等必须一致；终末 floor 不会在返程重新切入，因此不同户首返程节点可以不同，其共享 init_return 取稳定线路 ID 排序的首条作代表。各户真实首返程节点完整保留在自己的 floor_r 文件与逐线路 trace 中。此例外仅限多线路的终末 floor；公共前图的 init_return、single 与单线路仍按原规则校验，不改变电梯行为树的明确恢复坐标或机器人读取格式。依据既有多任务编译器 _location_manifest_project 与定位设计的终末图语义，不声称已验证车端执行。

2026-10-13 编译一致性校验影响 Backend 固定线路预览/下载和 PC Web 的现有错误展示；
机器人任务读取格式不变，Mobile 不消费。多任务公共源大厅实例的楼栋/单元必须与其定位绑定及
目标楼层一致；全局摆渡实例仍使用空楼栋/单元，编译所需的单元定位副本不改写项目归属。
读取受控栅格前，源 YAML 的正有限 `resolution` 与三个有限数值组成的 `origin` 必须与资产
标定一致；源文件漂移或无效时必须重新导入，编译器不能改写源证据以消除差异。
当前固定线路的边界、可达性及地图编辑使用轴对齐栅格，因此 `origin[2]` 必须为数值零（含 `-0`）；
任何非零值，包括 `2π` 整周角和很小的非零角，均明确报错“不支持旋转栅格”，不归一化源文件。
单纯重新导入同一旋转地图不能解决此限制；须使用 `origin yaw=0` 且地图与任务坐标一致的地图。
此限制仅约束地图栅格原点，不限制起点、组件或任务路点的非零 yaw，也不改写它们。
电梯候梯点与轿厢中心之间的直接进出段复用组件旋转矩形相交判断；若经过闸机、自动门、窄通道、
坡道或慢行区，明确拒绝编译并指出设施，因为既有电梯模板尚不能表达额外设施的动作/速度时序。
不得静默遗漏设施或向批准的电梯时序插入动作；普通导航段仍使用既有设施发现和展开规则。

2026-10-13 固定线路按项目任务模式导出，影响 Backend、PC Web 预览/下载及既有 R6B
多任务文件读取格式；Mobile 不消费部署编译接口。`manifest.task_mode` 使用 `single/multi`，
固定线路身份仍由 `compiler_profile=fixed_task_line_v1` 与 `active_task_line` 表达。
`single` 输出 `tasks/<小区名_线路名>.json`；`multi` 输出既有 `multi_tasks/<community>/`
公共段按已保存的部署阶段角色输出：摆渡层为小区根目录的 `sub_outdoor_eguard[ _r ].json`，
电梯大厅为 `indoor/<building>_<unit>[ _r ].json`；用户楼层为 `floor/<目标文件名>[ _r ].json`。
每个多任务 JSON 均为只有 `change_loc/map_url/pcd_url/subtask_name/waypoints` 的直接子任务，
不将单任务包装改名为多任务。标准层使用 `n_nXX`、非标准层使用具体按钮楼层与门牌；
动态乘梯沿用现有 n_x/x_n 模板，送货状态读取运行时 `delivery_code`，仓控保留线路指定动作。
摆渡层包含电梯组件时，其起点、多个取货点、门口过渡点和乘梯节点仍共同归入摆渡层段，
不因此变为 indoor；仅配置电梯大厅地图阶段时生成 indoor 文件。地图阶段分配、定位绑定与
地图实例角色须一致，固定线路使用的阶段须与保存的流程顺序一致，不跳过已配置阶段。
该分段不增加机器人运行时协议。当前支持一个公共源地图、一个连续用户楼层访问段及一个
末端送货目标；多个用户楼层、多个楼层送货目标或反复切回公共地图的固定线路不能无损表达为
现有可复用分段，必须明确报错，不忽略步骤、不降级为 single。公共源图的多个取货点保持支持。
预览 JSON 可以保留完整 subtasks 供地图审计，ZIP 中只保存真实 multi_tasks 直接子任务文件。
`manifest.multi_task_files` 按公共去程、楼层去程、楼层返程、公共返程记录相对路径；
`route_families.required_outputs/stages` 同步保留实际阶段类型。此映射修正的 Existing 消费者为
Backend 编译与目录发现、PC Web 预览及机器人任务文件读取；Mobile 不消费。目录名沿用既有契约。
新旧模式的输入、清单哈希和缓存均区分，旧实验包不改写，所有新下载须核对与当前模式一致。

2026-10-13 项目重新编辑影响 Backend 与 PC Web，Mobile 不消费部署编辑接口。
新增 `POST /api/deployments/{project_id}/settings`，严格接受 `{name,task_mode}`，返回 `{project}`。
名称必须为字符串，规范化空白后为 1–80 字符；模式只接受 `single` 或 `multi`。
完成部署后仍可修改；项目 ID、地图、标记、共享设备、任务线路与已有导出文件保持原有归属。
实际修改时清空当前预览确认标识，后续导出须重新编译校验；完全未变的保存不使预览失效。
进入编辑、未保存退出均不写入项目。Web 重新开放全部已完成步骤的原有编辑器；
项目第一步包含名称、任务模式及地图阶段流程。所有变更仍通过各自既有保存接口提交。

2026-10-13 固定线路导出命名影响 Backend 产物与 PC Web 下载，Mobile 不消费。
任务 JSON 和 ZIP 以“小区名_线路名”命名，不再暴露线路 ID 哈希前缀。
固定线路行为树使用“动作执行序号_英文用途_线路名.xml”，序号按任务 JSON 中首次执行的顺序
统一补零；取送货包含 `pickup/delivery`、`upper/lower` 和 `open/close/unload`，乘梯动作区分
`outbound/return`。同项目同名或清理后重名的线路增加可读编号，非法路径字符被替换，
文件名按 UTF-8 字节限长；原线路全名仍在清单中保留。所有 `waypoint_task_id` 同步引用新文件名
（不含扩展名），清单哈希同步重算。项目内组件/过渡点 ID 保持稳定；新导出 waypoint_id 按下面的真实节点规则发布。
仅新生成的固定线路实验包采用此规则；旧导出包不改写，历史 single/multi 编译命名保持兼容。

2026-10-13 过渡点命名影响 Backend 与 PC Web，Mobile 不消费。既有手动过渡点更新接口
增加可选 `label`（非空字符串，规范化空白后最多 80 字符），可与速度、朝向一起保存。
Web 新建时按当前地图分配未使用的“过渡点 N”；旧项目中的同名点仅在显示时编号，不改写快照。
地图、任务线路选择列表、流程卡片和预览共用名称；线路仍以原 ID 引用，重命名不改变访问顺序。

2026-10-12 定位绑定自动化影响记录：Existing 消费者为 Backend 与 PC Web，Mobile 不消费。
唯一有效的地图实例已经确定运行角色、楼栋和单元时，Backend 自动建立定位绑定，Web 不再要求
逐图确认。用户楼层的布局模板编号是项目内的稳定标识，由 Backend 分配；保留旧项目已有有效
编号，不将其解释为实际楼层。不完整或冲突的地图实例须回到地图准备阶段修正，不能猜测归属。
旧的定位绑定 API 保留供历史项目兼容；自动绑定不修改车辆运行目录或来源地图。

固定任务线路的增量消费者为 Backend 与 PC Web，Mobile 不消费。`task_lines` 保存多条具名
固定去程，`active_task_line_id` 在 single 中指定本次实验编译的线路，在 multi 中指定新增目标所沿用的模板（全部已保存线路参与编译）。线路只引用当前项目的位置：
`{id,name,start_component_id,steps:[{kind:"transition"|"component",id,action?}]}`。
目标访问的 action 为 `{purpose:"pickup"|"delivery",cargo_id:1|2,operation:"open"|"close"|"unload"}`，
或 `{purpose:"visit"}`；其他节点不接受业务动作。同一位置允许多次访问，访问顺序是人员保存的
业务意图，后端负责可达性、真实切图连接与返程派生。单条线路为 1–512 步，不接受客户端返程。
保存、选择、删除线路使实验预览失效。引用删除后须报告失效，不能自动替换或跳过业务节点。
新项目始终带有空的 `task_lines` 与 `active_task_line_id:null`，必须保存并选择线路才能编译。
只有快照中完全没有 `task_lines` 字段的历史项目保留既有 single/multi 编译行为；字段存在但
为空、选择失效或引用被删除时阻止编译，不静默回退。固定线路编译不改写项目的 `task_mode`，固定线路
预览的 `manifest.task_mode` 遵循项目的 `single/multi`。

2026-10-12 可选电梯大厅阶段影响 Backend 与 PC Web，Mobile 不消费部署流程。当前固定线路支持
同图访问，以及同楼栋单元内唯一关联同一物理电梯的跨图访问。摆渡层若已经包含电梯大厅，
可直接配置“摆渡层 → 用户楼层”，在摆渡图标记电梯落点并关联物理电梯，不要求独立大厅图。
全局摆渡地图的项目归属保持不变；本次编译依据线路所访问楼层及共享物理电梯，解析唯一楼栋单元，
生成该线路的定位副本。归属不唯一、没有共享电梯或其他未批准连接仍报错，不按坐标推断。
线路末步必须是目标点或手动过渡点，通行设施后须有明确出口。
普通 `normal` 过渡点无动作且 `is_single_point:false`；历史缺省速度保留原单点语义。
2026-10-12 历史非固定线路返程修正影响 Backend 编译与 PC 预览：`normal` 手动过渡点在去返程均保留
`normal`，不会继承相邻目标的 `single_point` 停靠速度；区域组件仍按反向边传播内部速度。
不增加字段或枚举，Mobile 不消费该部署契约；验证覆盖执行链、固定与历史任务编译及 Web 展示。
2026-10-13 原路返程修正影响 Backend 编译、PC Web 预览及机器人任务 JSON 读取；Mobile 不消费。
固定线路返程从最后访问位置逆序复用去程各导航段及其实际展开节点，经过同一过渡点、
窄通道首末端点和已批准的电梯连接，不另找捷径或跳过地图。先前目标位置仅作为返程导航锚点，
不重复取货、送货、仓控或任务开始动作。通行设施沿同一物理节点反向经过，入口/出口角色互换，
受控设备依次执行 open_back/close_back，保留通道内部速度；
整单完成只在最终回到起点时发布一次。历史非固定线路继续沿用原有反序返程。
仓控沿用现有 `CargoSingleCommand` 的 `caogo_id` 端口和操作码 0/1/2，不新增人工装货完成等待
或自动关仓协议。开仓成功按现有节点的返回条件处理。

固定线路编译从 YAML 指定的受控图像读取栅格，应用与导出相同的手动擦除与黑白导出规则，并遵守
`negate/free_thresh`；每次编译每张地图只解码一次。路线可达性同时考虑虚拟墙。
`manifest.execution_chain.block_N` 按实际有向导航块保存起终锚点、速度和去返节点；
`manifest.subtask_map_asset_ids` 与任务 JSON 的 subtasks 一一对应，PC 依此显示完整路线，不能跨图连线。
定位清单的显式 `execution_entries` 是 Backend 内部编译入口，不接受客户端提交。

2026-10-13 起点返程朝向修正影响 Backend 固定线路编译、PC Web 预览与机器人任务 JSON 读取；
Mobile 不消费。最终回到起点的节点使用起点保存的完整位姿（x/y/yaw），朝向与出发起点一致，
不翻转 180°。single 与 multi 导出及预览遵循同一规则，项目保存的起点不改写；旧导出须重新生成。

2026-10-13 真实节点与返程影响 Backend 编译、PC Web 预览以及机器人任务 JSON 读取；
Mobile 不消费部署预览，不增加工具链。固定线路新增 `manifest.waypoint_trace`，按任务 JSON
展开顺序每个实际 waypoint 一项，字段固定为 `waypoint_id/map_asset_id/leg/label/role/source_id`。
`leg` 仅为 `outbound` 或 `return`；`source_id` 保留项目原 ID；`role` 表达 entry/exit、
transition、pickup/delivery/visit、start/return_start 或电梯用途。JSON `waypoint_id` 使用统一
补零序号、方向、英文用途及可选安全用户标签，不再包含内部 fl_ 哈希；引用、四段 multi JSON
和 trace 同步发布。`subtask_map_asset_ids` 继续与 subtasks 对齐，跨图不能连线。
编译器以导出后的栅格（含擦除/补墙及 YAML 占据语义）与虚拟墙查找实际可通行路径，自动
展开路径穿过的已放置窄通道及通行设施；不要求它们被选为任务步骤。未经过的不自动加入。
设施发现优先选择带有保守间距的路线，避免点机器人穿过地图噪声细缝；该偏好不更改 Nav2 参数。
间距场最多 900k 单元，细栅格搜索最多 250k 展开；保守间距没有路径时回退到原有精确可达图，
超出搜索预算则明确阻断预览，不静默遗漏设施。窄通道首尾轴线逐栅格及虚拟墙验证直线通行，
不能用区域外绕行证明该轴线可通行。加入设施改变接近路径时，继续检查新导航腿上的通行设施。
窄通道复用长轴两端节点，进入边为 single_point，内部到出口边采用既有组件速度，返程重新
按当前方向生成；所有生成导航腿及电梯候梯点到轿厢落点均验证可达性。
`execution_chain.block_N.leg` 标明当前块方向；块内 outbound 是该块实际方向的有向节点，
return 是此块的局部反向投影，不能拼成固定线路整单返程。整单返程以 subtasks/trace 为准。


| Method | Route（前缀 `/api/deployments/{project_id}`） | Request / Response |
| --- | --- | --- |
| POST | `/task-lines` | `{name,start_component_id,steps}`；返回 `{task_line,project}` |
| POST | `/task-lines/{id}` | 同上，替换该线路；返回 `{task_line,project}` |
| POST | `/task-lines/{id}/select` | 严格 `{}`；返回 `{project}` |
| DELETE | `/task-lines/{id}` | 返回 `{project}`；不删除位置组件或其他线路 |

现有部署 API 以 `/api/deployments` 开始。按项目划分的路由覆盖地图导入/上传、可配置部署流程、地图阶段、路线、地图实例、航点、组件模板/组件、虚拟墙和拓扑。地图切换顺序由后端的部署流程与核心标记派生；实施人员不编辑跨图顺序。摆渡层或户外阶段只需在来源图标记唯一过渡点，后端按其地图角色将该点识别为转场锚点。建图会话由 `/api/mapping` 与 `/api/mapping/sessions` 路由控制。

`SiteProject.task_mode` 是车辆任务模式，只能为 `single` 或 `multi`；可在项目设置中修改。
`POST /api/deployments` 仅接受 `{ "name": "高科一号", "task_mode": "single" }` 或
`{ "name": "高科一号", "task_mode": "multi" }`；不接受默认模式或额外字段。
`POST /api/deployments/{project_id}/settings` 接受同样的两个字段更新现有项目，
成功返回 `{ "project": { … } }`；非法请求或不存在的项目返回 `400`。
缺少该字段的历史项目在读取时迁移为 `single`。任务编译器配置路由只保存小区名称，不能改变
项目模式。

`SiteProject.deployment_flow` 是有序地图阶段节点数组，每个节点包含 `id`、`type` 和 `label`。PC 工作台以卡片拖拽维护该数组，插入位置由前/后卡片的吸附指示确定；保存前后均由 Backend 重新归一化和校验，浏览器拖拽状态不是权威数据。
`type` 只能是 `outdoor`（户外图）、`ferry`（摆渡层）、`lobby`（电梯大厅）或
`target_floor`（用户楼层）。流程必须包含且仅包含一个 `target_floor`，且
`target_floor` 必须是末节点；电梯大厅为可选阶段，最多一个；户外图最多一个，摆渡层可重复。旧项目读取时会从
`scene_model` 自动迁移为默认流程，`scene_model` 仅保留兼容和编译配置识别用途。

地图实例的 `scope` 由 Backend 从角色派生，不能由浏览器选择：`ferry` 是全小区复用的
`global` 段；`outdoor`、`lobby`、`typical_floor` 与 `floor_override` 都是带楼栋/单元归属的
`unit` 段。特别是 `outdoor/<building>_<unit>.json` 是每栋单元的户外任务文件，因此不得把
不同栋单元的户外地图压缩为同一全局实例。

地图实例不保存人工填写的楼层：地图标记发生在电梯落点配置之前，手填值既不能代表实际面板按钮层，
也不能代表运行时物理楼层。地图实例只收集用途、楼栋和单元；目标层的任务物理楼层由关联电梯组件的
`button_floor` 与项目物理电梯按钮序列自动推导。旧项目已存的 `floor` 仅只读兼容，不能成为新任务的
推导来源或新项目的填写项。

| Method | Route | Request | Response |
| --- | --- | --- |
| `POST` | `/api/deployments/{project_id}/deployment-flow` | `{ "flow": [{ "id": "outdoor", "type": "outdoor", "label": "户外图" }, …] }` | `{ "project": { … }, "stage_plan": { … } }` |

`DELETE /api/deployments/{project_id}` 删除一个已存在的部署项目及其项目工作区（地图快照、导出和编辑数据）。后端先校验项目标识并拒绝路径穿越；该动作不触碰机器人运行目录、任务目录、ROS、Supervisor 或其他项目。PC 必须二次确认并明确不可恢复，Mobile 不提供该入口。

该路由只保存项目快照中的流程与阶段绑定，不写机器人运行目录。地图阶段选择、自动分配和拓扑校验均严格使用该数组顺序。

Backend 校验具有权威性：客户端展示并提交用户意图，但不得直接写入部署文件或机器人配置。地图图像、元数据、虚拟墙和拓扑编辑都保留项目/地图所有权。

导入地图后，项目内 `maps/` 快照是后续预览与实验编译的唯一地图来源；浏览器上传的临时目录和原始外部路径都不能成为编译依赖。旧项目读取时会在快照完整的前提下自动迁移该来源记录。

地图快照保留提供的 `index.txt` 与同目录所有有效 PCD；资产的 `files.index` 是项目内
索引相对路径，未提供时为 `null`。`index.txt` 为可选兼容文件，导出原样保留；定位清单/定位
YAML 导出只要求至少一份有效 PCD，不要求旧索引或特定 PCD 文件名。普通 2D 地图仍可导入编辑。
Backend/Web 受此约束，Mobile 无影响。

## PCD 生成二维地图

**Status: Existing（已实现，项目内离线转换）**
**消费者与变更影响：** Backend 权威执行文件解析、后台分析/投影和确认导入；Desktop Web 将该能力接入
原地图来源向导。Mobile 不是消费者，不增加 ROS Topic、WS 线协议或车辆运行配置写入。

精细点云显示扩展影响 Backend 显示缓存/HTTP 与 Desktop Web 解码和渲染；Mobile 不消费。
保留既有 `source-preview.bin` XYZ 契约，新增 `GET /{id}/source-detail.bin`：旧会话首次查看时在既有
单任务后台门控内生成显示缓存，准备期间返回 202 JSON `{state:"preparing"}`，不阻塞 HTTP 解码。
2026-10-10 完整源点云变更影响 Backend 与 Desktop Web，Mobile 无影响；需要同步提高双方载荷校验上限。
200 返回全部有限坐标点（沿用导入上限 10000000 点，最大 200 MB），每点 20 字节的小端交错记录：float32 XYZ（12 字节）、uint8 RGBA（4 字节，
alpha=255 表示有效原始 RGB，0 表示缺失）、float32 intensity（4 字节，NaN 表示缺失）。
`X-Point-Format: xyz-rgba-intensity-v1`；沿用点数、原点及边界头，并新增 `X-Point-Attributes` JSON
`{rgb:boolean,intensity:boolean,intensity_range:[min,max]|null,display_bounds:[[min,max],…]}`。
RGB 支持 PCL packed float32/uint32 rgb/rgba 和独立 r/g/b；强度字段大小写兼容。坐标非有限的点和属性一同过滤，
不再进行二次抽稀，颜色与坐标逐点对齐；显示范围采用稳健分位数抑制离群点缩小主体，仅用于显示范围参考与初始相机适配，不裁剪源数据。
缓存原子写入且绑定项目/会话；取消拒绝，旧抽样缓存首次读取时在后台重新生成全量缓存，准备期间返回 202；同一后台门控不排无限队列，尚忙时返回准备中供客户端退避。
浏览器保留 RGB、强度/高度着色和点粒大小选择，截取范围显示为可切换的淡透明三维区域及上下限边界，不改写点云颜色；不再提供降低点数的显示模式；原文件及二维投影不变。

新地图来源 `pcd` 与原 `import`、`mapping` 并列。上传仅建立预览会话，确认成功才进入原地图阶段绑定。
PCD 读取采用锁定的 pypcd4，支持 ASCII、binary 与 binary_compressed；转换不启动 ROS 节点或发布地图。
原始点云保留不变，生成的地图保持其 XY 坐标；Z 范围为原点云坐标系的绝对高度，单位米。
自动候选仅推荐水平高度范围，实施人员仍须检查墙体、门洞、通道及未知区域；不是局部坡地的自动地面跟随。

| Method | Route（前缀 `/api/deployments/{project_id}/map-projections`） | Request / Response |
| --- | --- | --- |
| POST | 前缀本身 | multipart 唯一字段 `file`（单个 `.pcd`）；202 `{projection}` |
| GET | `/latest` | 200 `{projection: object\|null}`，用于切页/刷新恢复 |
| GET | `/{id}` | 200 `{projection}` |
| POST | `/{id}/preview` | JSON `{z_min,z_max,resolution,min_points,denoise}`；202 `{projection}` |
| GET | `/{id}/preview.png?revision=N` | 仅当前 ready/imported 版本 PNG；可选 `display=monochrome`，禁止缓存 |
| GET | `/{id}/source-preview.bin` | 已分析会话的有限点显示样本，最多 100000 个小端 float32 XYZ 三元组，禁止缓存；不接受查询参数 |
| POST | `/{id}/trajectory-preview.bin` | multipart 唯一字段 `file`；200 全部有限点的相对 XY 二进制，8 字节/点；仅预览，不修改会话或地图 |
| POST | `/{id}/confirm` | 严格 JSON `{label,revision}`；201 `{map,project}`，重复确认幂等 |
| DELETE | `/{id}` | 取消结果采用，200 `{projection}`；不删除原始输入 |

`projection` 含 `id/project_id/state/progress/message/revision/analysis/parameters/result/map_asset_id`；
不会返回任意文件路径。`state` 为 `analyzing`、`awaiting_parameters`、`processing`、`ready`、`failed`、
`cancelled`、`imported` 或 `interrupted`。后台状态独立于页面；重启遇到未完成状态标记 interrupted。
`analysis` 含点数、有限点数、`bounds: {x:[min,max],y:[min,max],z:[min,max]}`、
`z_histogram: {edges,counts}`、候选 `{label,z_min,z_max,ground_z,confidence}` 和 warnings。
`result` 含 width/height/resolution_m/origin/selected_points/occupied_cells/parameters/warnings。
`revision` 每次启动投影递增，参数改变后客户端须禁用确认；服务端拒绝不是当前 ready 版本的确认或图片请求。

进度展示的 Existing 消费者为 Backend 与 Desktop Web，Mobile 不消费点云导入流程；此次不新增字段或请求参数。
`progress` 为当前任务 0–100 的阶段完成值，不是时间估算：原生投影在读取、截面筛选、栅格生成、
障碍处理、保存输出时持久化递增进度及用户可读 `message`，仅当前修订可更新。0 表示尚未收到阶段反馈，
Web 显示等待状态；100 仅在完整输出已采用、状态变为 ready 时发布。取消或过期工作线程不得继续更新。
2026-10-10 调整：Web 提供可编辑分辨率，默认 0.05 米/格，尊重用户选择，不再静默自动改细或改粗。
新转换使用 `min_points=1` 保留单点细节；不提供邻居数输入。已保存预览仍按其实际参数展示。
二维点半径默认 0.5 屏幕像素，仅影响预览绘制；缩小时逐格合并障碍证据，避免邻近采样漏掉细墙。
半径不进入投影参数，不改变 PGM、YAML、障碍范围、修订号和确认状态。

轨迹辅助预览扩展的 Existing 消费者为 Backend / Desktop Web；Mobile 不消费，原 ROS/地图导出不变。
新增 `POST /{id}/trajectory-preview.bin`：multipart 唯一字段 `file`，单个 PCD，沿用上传/展开/点数限制。
Backend 校验项目和已分析会话归属，拒绝取消/已导入会话；解析占用同一单任务门控，忙时返回 409。
200 返回全部有限点的二维坐标（不抽样、不连接未知顺序）：小端 float32 XY，每点 8 字节，最大 80 MB；
`X-Point-Format: xy-v1`、`X-Point-Count`、`X-Point-Origin`（float64 JSON `[x,y]`）。
坐标相对此原点，Web 还原到地图世界 XY 后与地图共用缩放/平移变换。
请求不接受查询参数，响应禁止缓存。上传只在临时目录解析，不创建地图资产、不修改投影修订或会话；
轨迹仅保存在当前页面预览内，可隐藏/移除，刷新需重新选择；取消/切换项目后迟到响应不采用。
验证范围为 Backend 投影/会话/HTTP 与 Desktop Web 预览、坐标对齐和生命周期。

上传上限沿用 2 GiB，解析前校验头部及展开大小；点数最多 1000 万、展开最多 512 MiB、栅格最多 1600 万格，单边最多 16384 格。
后台转换同时最多一份，无无限工作队列。已占用返回 409，其余非法输入/版本/所属项目返回 400。
PGM 采用占据 0、自由 254、未知 205；没有输入点支持的 XY 区域保持未知，不能从无点推断可通行。
确认复用 DeploymentStore 的项目快照导入，不自动应用机器人地图、安装任务或重启节点。
生成的 YAML 包含源点云摘要和投影参数指纹，防止不同地图或高度范围被误认作同一资产。
每个会话仅保留当前有效预览，原始点云只保存一份；确认前持久化导入意图，允许进程中断后核对已保存资产并恢复确认。

显示增强的当前消费者仍仅为 Backend 与 Desktop Web，Mobile 不受影响；验证新增 Backend 样本/HTTP
测试与 Desktop Web 点云浏览器、缩放和平移测试。PNG 查询只允许一个有效 `revision` 和可选的单个
`display=monochrome`；黑白显示将占据像素 0 显示为黑色，其余显示为白色，默认 PNG 和保存的 PGM/YAML
保持原语义，白色不代表已验证可通行。

源点云样本在默认后台分析时生成并原子缓存到受控会话的 `source/source-preview.bin`，不在 HTTP 请求时
重新解码 PCD，也不修改或提供原始文件下载。按有限点的原有顺序确定性均匀取样；XYZ 先减去完整有限点
包围盒中心，再转换为 float32，以保留大坐标下的局部细节。响应为 `application/octet-stream`，包含
`X-Point-Count`（样本点数）、`X-Source-Point-Count`（原始点数）、`X-Finite-Point-Count`（有限点数）、
`X-Point-Origin`（float64 JSON `[x,y,z]`）和 `X-Point-Bounds`（原坐标 JSON
`[[xmin,xmax],[ymin,ymax],[zmin,zmax]]`）。样本三元组是相对该中心的显示坐标；绝对高度选择需减去中心 Z。
`analysis.source_preview` 包含同义的 `point_count/source_point_count/finite_point_count/origin/bounds`。
样本跨预览修订保留；已采用分析的 awaiting_parameters/processing/ready/imported/interrupted 会话可读取，
高度投影失败后的 failed 会话也可继续浏览既有分析样本，以便调整高度；分析失败且没有已采用样本时拒绝。
analyzing/cancelled 拒绝；旧会话缺少缓存时返回 400 并明确要求重新上传。项目和会话归属仍由 Backend 校验。

## 地图虚拟墙

**Status: Existing（已实现，地图运行时输入）**
**消费者：** `robot_backend` / 地图运行时读取导出的 `map_walls.yaml`；PC `web_console`
在部署地图画布中编辑。Mobile 只读既有地图渲染时可展示，不写入本契约。

每张导入地图的项目快照可拥有零条或多条 `virtual_walls` 折线。每项包含 `id`、`map_asset_id`
以及世界坐标 `points: [{x,y}, …]`（至少两点）；旧 `{ start: {x,y}, end: {x,y} }` 记录继续兼容。
顶点必须有限、相邻顶点不同且位于所属地图边界内。PC 画布用红色折线展示，操作人员左键持续加点，
双击或 Enter 完成；任意顶点或线段可拖动，删除后系统立刻重新生成该地图墙文件。虚拟墙不参与任务点排序或行为树。虚拟墙会参与所属地图的自动路线可通行性判断：路径不得跨越虚拟墙；若虚拟墙将起点、终点或必经标记隔断，Backend 必须阻断派生并提示操作人员调整墙体或地图标记。墙只约束其 `map_asset_id` 对应的地图，不得影响其他地图的路线推导。

服务端是唯一写文件方。每次新增、更新或删除都会原子重写项目快照地图 YAML 旁的**固定文件名**
`map_walls.yaml`，采用机器人兼容的 `virtual_walls.coordinate_mode: image_relative`、
`frame_id: map`、地图 `origin` 和 `segments`。它从不写原始外部地图目录或机器人运行目录。
实验预览/下载将该文件作为同名地图伴随文件输出；墙变动会使已有实验预览失效，必须重新编译。
导入已有兼容 `map_walls.yaml` 时会读取其线段；历史 `forbidden_zone.points` 闭合多边形读取时迁移为
相邻闭合线段。无法解释的旧记录保持原样而不猜测几何。

| Method | Route | Request | Response |
| --- | --- | --- | --- |
| `POST` | `/api/deployments/{project_id}/virtual-walls` | `{ "map_id": "…", "points": [{"x": 1.2,"y": 3.4}, {"x": 5.6,"y": 3.4}, …] }` | `{ "virtual_wall": { … }, "project": { … } }`，`201 Created` |
| `POST` | `/api/deployments/{project_id}/virtual-walls/{wall_id}` | `{ "points": [{…}, {…}, …] }`；兼容旧 `{ "start": {…}, "end": {…} }` | `{ "virtual_wall": { … }, "project": { … } }` |
| `DELETE` | `/api/deployments/{project_id}/virtual-walls/{wall_id}` | 无 | `{ "deleted": true, "project": { … } }` |

## 地图擦除与补墙

**Status: Existing（增量扩展）**
**消费者与影响：** Backend `DeploymentStore` 校验/持久化，`location_manifest` 栅格化并导出，
固定任务编译器使用同一栅格做可达性校验；PC Web 负责原图预览、Worker 美化识别和 PNG 导出。
Mobile 不消费项目地图编辑记录，不增加其依赖。来源地图与车端运行地图均不直接修改。

`POST /api/deployments/{project_id}/map-edits` 的 `action:add` 继续使用
`kind:brush_erase|polygon_erase`、世界坐标 `points` 与笔刷 `radius_m/shape`，增加可选
`mode:erase|wall`。缺省 `erase` 保持历史擦白行为；`wall` 将所绘区域设为黑色障碍。
不执行整图取反；每笔/每个框选独立保存模式，按记录顺序覆盖，撤销恢复上一操作。
导航 PGM 写入擦除 `254`、补墙 `0`；原始画布、美化输入和导出均应用同一顺序。
非法模式拒绝保存/导出。补墙或擦除使当前美化和实验预览失效，按需重新生成；其他地图缓存保留。

## 项目级物理电梯

**Status: Existing（已实现，实验任务编译输入）**
**消费者：** 当前仅 Web Console；Mobile 未实现且不得调用这些路由。

一个 `SiteProject` 以 `physical_elevators` 保存真实电梯的唯一事实。每个实体在同一项目内的
`elevator_id` 必须唯一，并保存 `elevator_protocol`、`min_floor`、`max_floor` 和可选
`unavailable_button_floors`。后者是电梯面板实际不存在的楼层按键（例如 `11`），不是地图楼层；
缺省或空数组保持既有连续按键行为。地图上的
`elevator` 组件只保存 `physical_elevator_id`、门向（`yaw`）、尺寸和 `wait_distance_m`；因此同一
实体可在大厅图和目标层图各有一个落点，而每张地图仍可独立标记电梯门方向。

新建项目的梯控协议模板固定从 `mqtt`（`MQTT`）和 `lora`（`LORA`）开始；未填写
`elevator_protocol` 的新物理电梯默认使用首项 `mqtt`。项目已保存的协议目录保持原样，避免
擅自改写既有设备的通信方式。

| Method | Route | Request | Response |
| --- | --- | --- | --- |
| `POST` | `/api/deployments/{project_id}/physical-elevators` | `{ "elevator_id": "10014", "elevator_protocol": "mqtt", "min_floor": -2, "max_floor": 20, "unavailable_button_floors": [11] }` | `{ "physical_elevator": { … }, "project": { … } }`，`201 Created` |
| `POST` | `/api/deployments/{project_id}/physical-elevators/{physical_elevator_id}` | 同上 | `{ "physical_elevator": { … }, "project": { … } }` |
| `DELETE` | `/api/deployments/{project_id}/physical-elevators/{physical_elevator_id}` | 无 | `{ "deleted": true }` |

后端拒绝重复编号、未知关联、无效服务楼层及正在被地图落点引用的实体删除。旧项目读取时会将
旧组件重复的 `elevator_id` 自动迁移成同一实体；若旧协议或服务范围彼此冲突，实体会带有
`migration_conflict`，实验编译明确拒绝，不能猜测采用其中任一配置。以上路由只修改项目快照，
不写机器人任务、行为树、定位目录，也不调用 ROS 或 Supervisor。

电梯落点必须另存本地图实际可按的 `button_floor`。物理楼层从零开始，按
`min_floor…max_floor` 的**实际面板按键顺序**计算，并跳过按钮 `0` 和
`unavailable_button_floors`：例如 `-2…20` 且 `[11]` 缺失时，序列为
`-2, -1, 1, …, 10, 12, …, 20`，`12` 的物理层为 `12`、`15` 为 `15`。
缺失按键必须是服务范围内、不为 `0` 的唯一整数；后端拒绝将已有地图落点的 `button_floor`
改为缺失按键。因此不得从地图实例楼层推测物理层，也不得使用“地图楼层 + 1”。
一个实验任务中的 `origin_floor` 是**任务最初起点地图**关联电梯落点的物理层；编译时只解析一次，
所有包含 `SetBlackboard output_key="origin_floor"` 的去程、返程及关门行为树必须使用完全相同的值。
目标地图的物理层只用于任务目标 `{floor}`，不得覆盖 `origin_floor`。

## 项目级定位运行绑定

**Status: Existing（已实现，实验任务编译输入）**
**消费者：** `robot_backend` 负责校验与派生，`web_console` 提交和展示项目意图；Mobile 未实现且不是此契约的消费者，不得调用这些路由。

`localization_bindings` 将项目地图绑定为 `outdoor`、`indoor`、`ferry` 或 `floor`。只要地图已有唯一的
部署拓扑实例，Backend 会从实例角色自动派生绑定 `type`（`outdoor`、`ferry`、`lobby`、`typical_floor` /
`floor_override` 分别对应 `outdoor`、`ferry`、`indoor`、`floor`）以及楼栋/单元；PC 不显示、提交或允许修改
这些重复字段。`floor` 唯一保留必填的 `floor_template`，它是用户楼层布局模板编号，不是电梯物理楼层。
只有缺少部署拓扑实例的历史项目才可提交 `building`、`unit`、`type` 作为迁移兼容输入。一个楼栋/单元最多各有一个
户外和大厅绑定按楼栋/单元唯一；新建摆渡层绑定由 Backend 归一化为全局空楼栋/单元，历史按楼栋/单元保存的摆渡绑定继续只读兼容；用户楼层按布局模板唯一。

| Method | Route | Request | Response |
| --- | --- | --- | --- |
| `POST` | `/api/deployments/{project_id}/localization-bindings` | 仅绑定身份字段；`floor` 可附加 `floor_template`，不接受位姿、YAML、地图路径或输出目录 | `{ "localization_binding": { … }, "project": { … } }`，`201 Created` |
| `POST` | `/api/deployments/{project_id}/localization-bindings/{binding_id}` | 同上 | `{ "localization_binding": { … }, "project": { … } }` |
| `DELETE` | `/api/deployments/{project_id}/localization-bindings/{binding_id}` | 无 | `{ "deleted": true }` |

后端要求绑定引用当前项目地图。新建或更新绑定拒绝 `init_go`、`init_return`、`yaml`、
`2D_yaml`、`loc_yaml_path.json`、运行时路径及其他未批准字段。旧记录中的 `init_go` / `init_return` 只读兼容；只有旧手填位姿而没有 `localization_routes` 的项目不能导出新的定位
清单，必须先迁移为路线，后端不会猜测或复用旧位姿。

定位配置模板由项目单独管理。PC 端可通过 `POST /api/deployments/{project_id}/localization-template`
上传 UTF-8 YAML；模板必须包含唯一 `system.map_path` 与 `system.init_pose.x/y/yaw`。模板保存在项目
工作区，后续每次实验预览/导出都以该模板为基线，只受控替换地图路径和路线派生的初始化位姿；未上传时使用
批准的 profile 默认模板。模板不会写入机器人运行目录。

## 项目级定位路线与定位清单

**Status: Existing（自动派生，实验任务编译输入）**
**消费者：** `robot_backend` 校验、派生并生成清单；PC `web_console` 只展示自动推导结果。Mobile 不是消费者，不调用以下路由或读取这些实验产物。

`localization_routes` 是每个楼栋/单元唯一的一条有序路线，也是 Backend 从项目事实生成的审计快照。地图成员与顺序来自创建项目时的 `deployment_flow`、`map_stage_assignments` 与定位绑定；起点、目标、电梯和中间设施来自地图标记。每个手动任务过渡点和每个非固定组件都是服务端自动路径的**必经锚点**：服务端从当前锚点按可达地图路径距离及稳定 ID 选择下一个节点，随后继续到目标。组件不需要预先落在“电梯到目标”的最短线或最短栅格路径上；标记组件会使路线经过它。浏览器不提交路线对象、端点、锚点或节点顺序，也不得用创建时间或坐标近邻猜测顺序。

自动派生要求每段有唯一的核心标记和可验证的物理电梯关系。任务过渡点或组件不可达、方向性组件与前后路径矛盾、区域尺寸无效，或相邻必经锚点/终点之间地图不连通时，后端拒绝派生并返回具体地图、标记和恢复操作；不会开放人工排序作为绕过方式。

持久化路线形状（只读）为：

```json
{
  "building": "1",
  "unit": "1",
  "binding_ids": ["localization-a", "localization-b"],
  "task_start_waypoint_id": "waypoint-start",
  "task_target_waypoint_id": "waypoint-target",
  "links": [
    {
      "from_binding_id": "localization-a",
      "to_binding_id": "localization-b",
      "anchor": { "kind": "waypoint", "waypoint_id": "waypoint-transfer" }
    }
  ],
  "execution_nodes": [
    {"binding_id": "localization-a", "node_refs": [{"kind": "transition", "id": "waypoint-transfer"}]},
    {"binding_id": "localization-b", "node_refs": [{"kind": "component", "id": "component-slow-zone"}]}
  ]
}
```

该形状由 Backend 生成；旧项目中的 `task_return_waypoint_id` 仅作兼容读取。`binding_ids` 不得为空或重复，必须同属该楼栋/单元，最后一项必须
是 `floor`。起点和目标 Waypoint 必须分别在首图、末图；可选过渡点仅用于中间场景锚定，不作为返程目标。`links` 必须恰好为每对相邻
绑定各一项，按顺序连接，不得跳图、分支或成环。每个 `anchor` 只能严格为来源图的
`{ "kind": "waypoint", "waypoint_id": "…" }`，或
`{ "kind": "component_center", "component_id": "…" }`；不接受手填 pose。

`execution_nodes` 是 Backend 为每张绑定地图**自动派生并持久化**的非固定任务节点顺序，供预览和审计读取，浏览器不得人工编辑。它恰有每个
`binding_ids` 一项，记录 `{ "binding_id": "…", "node_refs": [ … ] }`；`node_refs` 中每项只能是
`{ "kind": "transition", "id": "手动任务过渡点 ID" }` 或
`{ "kind": "component", "id": "组件 ID" }`。Backend 使用场景地图顺序、可通行地图路径和稳定 ID，完整收录该图每个手动任务过渡点与非固定组件；引用必须属于该绑定地图且不得重复。
`start`、`target`、`elevator` 是固定锚点，不能加入此列表。旧项目若地图上没有这些中间节点，可以不带此字段读取；自动派生会覆盖历史的人工 `execution_nodes`。若任一标记不可达、跨图、重复、未知或引用固定锚点，后端拒绝派生，并指出地图、节点和恢复操作；绝不要求人员按创建顺序、坐标或拖拽列表编排路径。

设施组件不显示常驻穿越箭头。起点和目标点的 `yaw` 是任务到达/出发朝向，画布必须以同样高对比方向标识显示，便于在放置或旋转后即时核验。电梯、闸机、自动门、减速区、坡道和窄通道的 `yaw` 则是设施几何朝向，而不是人工指定的任务正反方向。闸机和自动门的最长边是物理门面，执行链沿该门面法线生成入口和出口；自动路径中前一、后一节点必须分别处于法线的相反两侧，系统据此决定去程进入侧和离开侧。若路线没有从门体两侧穿过，预览会阻断并要求回到地图调整组件位置或尺寸，绝不要求人员旋转箭头或手动改顺序。减速区和坡道按旋转覆盖矩形与实际路线的边界相交生成节点；窄通道按旋转后的最长边穿越，侧别由自动路径选择。手动任务过渡点也显示其保存的去程姿态方向；设施的旋转、缩放手柄仍只是编辑控件。

执行链是 Backend 和 PC Web 的 Existing 共享数据模型：Backend 是唯一写入者，PC 只读展示节点 ID 与顺序。Mobile 不是消费者，不读写此字段。修改地图组件几何、属性、手动过渡点坐标/朝向/速度或场景地图阶段，都会使现有实验预览失效，并要求重新自动派生。

`floor` 不能出现在路线中间；保存时后端按 `binding_ids` 顺序归一化链接。PC 编辑器可明确
包含/排除同身份绑定、清空未保存草稿或确认删除路线。新绑定不会自动加入已保存路线；所有
成员、顺序和锚点变更只在显式保存/删除后生效。

地图切换不依赖项目级 `map_transitions` 记录。电梯大厅到用户层自动使用实际电梯组件；摆渡和户外来源图的唯一既有 `transition` 标记则由 Backend 归类为转场锚点。该归类只由地图角色和保存的流程决定，PC 不会提交或编辑跨图顺序。流程中的 `ferry` 没有全局地图、户外段没有对应栋单元地图，或任何核心标记缺失时，导出必须阻断，不能猜测机器人动作。

### 任务过渡点

**Status: Existing（已实现）**
**消费者：** `robot_backend` 验证并编译；PC `web_console` 负责标记、展示和保存速度、去程朝向。Mobile 不读取或写入该字段。

画布的手动 `Waypoint` 中，`kind: "transition"` 通常是**任务过渡点**。当它是 `ferry` 或 `outdoor` 来源图上的唯一过渡点时，Backend 自动将其作为地图转场锚点，并从该地图的执行节点中排除；这不是浏览器可选的第二种模式。其余过渡点在历史非固定线路中是自动路径必经点，后端按当前可达距离和稳定 ID 自动形成 `execution_nodes` 顺序；历史去程按该顺序、返程严格反序，浏览器不提供人工排列。固定线路使用保存的去程步骤，返程按去程已展开节点逆序经过这些过渡点，不重复业务动作。以下是历史模式的节点规则：

- 大厅去程：`lobby_start → lobby_1… → lobby_wait → lobby_elevator_center`；大厅返程：`lobby_return_wait → lobby_r_1… → lobby_return_start`。
- 用户层去程：`target_wait → 1509_1… → target`；用户层返程：`1509_r_1… → target_return_wait → target_return_elevator_center`。因此只要存在用户层过渡点，返程的首个导航点就是最后一个去程过渡点，不能直接跳到候梯点。

2026-10-12 PC Web 展示修正：手动过渡点在原始与美化视图均显示保存的朝向，选中后可拖动方向手柄；未配置任务线路或地图任务角色时也能显示、编辑朝向和速度。返程提示仍依据实际任务角色显示。此项以及目标快捷弹窗的动作移除只影响 Web 展示，不改变 Waypoint/组件字段、Backend 校验、历史编译行为或 Mobile 消费。

手动过渡点生成的条目固定为 `waypoint_task_id: ""`、`is_task_point: false`，因此不生成或引用行为树。过渡点保存的 `yaw` 是去程朝向；历史非固定线路返程采用同一点的相反顺序并自动转向 180°，使姿态与返程行驶方向一致。区域和受控设备组件按 `execution_nodes` 的同一位置展开为多个节点；受控设备动作才会引用项目内受控行为树。

闸机与自动门的显示编号（`gate_id` / `door_id`）只供人员识别；`controller_device_id` 是 `DoorControl doorid` 的唯一来源。两类组件均保存 `pre_open_distance_m`（开门前距离）与 `post_open_distance_m`（开门后停靠距离），默认均为 `1.5m`，范围为 `0.5–5m`。执行链把去程动作点自动投射到设备门体两侧：门前距离处开门、门后距离处关门；历史非固定线路返程复用同一物理点并反转动作；固定线路返程复用去程两侧物理动作点并逆序执行，开门后关门。地图标记和几何调整阶段允许设备号暂为空，以便先落图再在现有组件属性中补填；一旦填写则必须是正整数纯数字。实验预览、行为树生成和下载仍要求其非空且为正整数，缺失时必须阻断，绝不生成猜测的设备号。每个动作路点的 `waypoint_task_id` 必须与 ZIP 中同名 XML（不含 `.xml`）完全一致；闸机遵循 `e_guard_open_go`，自动门遵循 `{building}_{unit}_open_door_go` 等既有任务命名。

受控设备的默认速度模式只定义在 `autodrive_console/task_templates/indoor_elevator_v1/components/component-defaults.json`。其中 `auto_door` 固定为 `task_point`，`gate` 固定为 `narrow_point`；浏览器只读展示，不提供人工选择。Backend 在创建、更新、读取旧项目和编译任务时均加载该文件，锁定项会覆盖历史项目属性，因此修改该 JSON 是后续调整默认策略的唯一入口。`GET /api/deployment-component-defaults` 只读返回当前已验证配置，供 PC Web 展示；Mobile 不是消费者。

目标点 `attributes.arrival_action` 是历史 single/multi 编译模式的兼容字段，Existing 消费者为 Backend 与 PC Web；只允许 `place_water`（泄水）或 `auto_cargo`（卸货），新建默认 `place_water`。PC Web 的地图快捷编辑不再提供此动作下拉框，编辑位置属性时原样保留已有值；固定任务线路的取货、送货、仓位及执行方式由每次目标访问的 `action` 决定，不读取此位置级旧动作。历史编译器必须令最终目标路点的 `waypoint_task_id` 与此值完全一致，并在预览/ZIP 内生成同名 XML。两份行为树由 `task_templates/indoor_elevator_v1/` 受管：状态码通过 `task-status-codes.json` 解析；`{delivery_code}`、`{cargo_id}` 等单花括号字段则保留给运行时黑板。`auto_cargo` 在目标完成后发布到达状态 `701`，但不得发布整体完成 `109`，因为当前任务仍须执行返程子任务，最终完成只能由末尾 `task_complete.xml` 发出。升级旧项目时，历史的 `deliver`、`wait`、`return` 或缺失值统一迁移为 `place_water`，因为旧编译器无论界面选择为何都实际输出该动作；未知的新写入必须拒绝，不能猜测动作。Mobile 不消费此字段。

任务 JSON 和 `runtime/loc_yaml_path.json` 必须消费同一条地图段执行链，不能分别推导返程。定位清单最终 `floor` 条目的 `init_return` 始终等于该图**返程子任务的首个实际节点**。固定线路的首节点来自去程导航段的逆序节点（过渡点、区域边界、设备动作点或电梯候梯点），与实际导出的返程 JSON 一致。历史非固定线路继续取最后一个去程非固定节点的返程姿态，没有该节点时回退到目标层电梯门前呼梯点。大厅执行链同样写入大厅的去/返任务段，但不替代进入大厅时由电梯行为树控制的定位切换锚点。

任务过渡点持久化 `speed_mode`，只允许 `normal`、`task_point`、`single_point`、`slow_point` 和 `narrow_point`。PC Web 新建手动过渡点显式保存 `normal`（常规通过）；旧项目或 API 请求缺失速度时仍按 `single_point`（单点停靠）兼容读取。`normal` 导出的 `is_single_point` 为 `false`，继续保持 `is_task_point: false` 和 `waypoint_task_id: ""`，以选择既有 `speed_modes/normal.xml` 连续导航且不执行动作；其余速度保持既有单点标志。`elevator_in` 与 `backward` 属于受控电梯行为，不能被手动过渡点使用。旧 `kind: "return"` 兼容迁移为不参与任务导出的过渡记录，避免把历史返程选择误插到去程。修改任何任务过渡点都会使现有实验预览失效，必须重新由 Backend 编译。本次枚举与 Web 新建默认值影响 Existing Backend 和 PC Web，验证其过渡点保存/读取、任务编译和 Web 控件；Mobile 不是消费者，不增加移动端依赖。

| Method | Route | Request | Response |
| --- | --- | --- | --- |
| `GET` | `/api/deployment-component-defaults` | 无 | `{ "component_speed_defaults": { "auto_door": { "speed_profile": "task_point", "locked": true }, "gate": { "speed_profile": "narrow_point", "locked": true }, … } }`；只读任务模板配置 |
| `POST` | `/api/deployments/{project_id}/waypoints` | 新建 `kind: "transition"` 时可选 `{ "speed_mode": "normal", "yaw": 0 }`，PC Web 显式提交 `normal`，API 未给速度时仍为 `single_point` | `{ "waypoint": { …, "speed_mode": "…", "yaw": 0 }, "project": { … } }` |
| `POST` | `/api/deployments/{project_id}/waypoints/{waypoint_id}` | 仅手动任务过渡点；可更新非空子集 `{ "label": "出门2", "speed_mode": "normal\|task_point\|single_point\|slow_point\|narrow_point", "yaw": <弧度数值> }`；名称为非空字符串，规范化空白后最多 80 字符 | `{ "waypoint": { … }, "project": { … } }` |

| Method | Route | Request | Response |
| --- | --- | --- | --- |
| `POST` | `/api/deployments/{project_id}/localization-routes/derive` | 严格为空对象 `{}` | `{ "project": { … }, "localization_routes": [ … ] }`；Backend 从场景和地图标记重新生成只读路线 |

Waypoint 与地图组件均可直接删除，即使当前自动路线引用它们。删除在后端事务内先移除标记、再立即从剩余场景事实重新派生路线，浏览器只刷新结果，不参与排序；若删除了起点、目标或电梯等核心标记，后端清空过期路线，部署向导显示待补齐状态，预览保持不可生成，直到重新标记后自动恢复。

实验导出只从项目受控地图快照读取 `map.yaml` 与图像，并在 ZIP 内生成下列两个 JSON 以及受控
地图副本和定位 YAML；它不写机器人运行时目录、不调用 ROS 或 Supervisor，也不改变机器人当前
定位、任务或 ROS 状态。

2026-10-12 导出栅格规则（使用人员已确认）：针对 `negate: 0` 的地图，部署包中的 PGM 在应用已保存
擦除后，将灰色未知值 `205` 转为白色自由值 `254`，与现场 P2 黑白地图一致；黑色障碍和其余像素保持原值。
这是导航语义转换：导出文件中的这些白格按自由空间读取，而不是仅改变预览颜色。项目原始快照、点云投影
结果和美化识别输入仍保留未知格；不将美化 PNG、自动轮廓或界面组件写入导航 PGM。YAML 的分辨率、原点、
阈值与其余元数据保持原值，虚拟墙继续通过同目录 `map_walls.yaml` 输出。`negate: 1` 的外部地图不套用此转换。
当前消费者为 Backend 导出编译器与小车地图读取器；Desktop Web 沿用现有部署包下载接口，Mobile 不消费此导出。
已保存的人工擦除按原始画布的连续图像坐标栅格化：方形笔刷逐采样点绘制、不额外连接；圆形笔刷为圆头线段，
框选为非零绕数填充。像素边界的部分覆盖按 source-over 累积，达到半格时写为 254，避免将笔刷包围盒或细长
框选边角全部擦白。此修正不修改 API 或擦除记录结构；原始 Canvas 抗锯齿与导航二值栅格的极少数边界像素
可能存在差异，不能将浏览器抗锯齿灰度作为新的导航未知值写入导出。
验证覆盖 P2/P5、擦除、源文件不变、标定和伴随墙文件、实际 ZIP 内容；不增加 API 字段或客户端依赖。

| 路线条目条件 | 字段 | 派生来源 |
| --- | --- | --- |
| 首项（包括唯一项） | `init_go` | 首项（包括唯一项）使用人工选择的任务起点 `task_start_waypoint_id`；首图使用人工选择的任务起点 |
| 仅非首项 | `init_go` | 后续地图统一使用采图电梯中心坐标系原点 `{x: 0.0, y: 0.0, z: 0.0, yaw: 0.0}`；不使用栅格 YAML 左下角 `origin` |
| 非最终项 | `init_return` | 该图出向链接的受控锚点 |
| 最终项 | `init_return` | 单线路为该图返程子任务的首个实际节点；多户共享末图时按上文稳定代表线路规则 |

导出的每张定位 YAML 的 `system.init_pose.x`、`system.init_pose.y`、
`system.init_pose.yaw` 必须与该路线条目的 `init_go` 完全一致；首图因此使用人工任务起点，
后续地图使用电梯中心坐标系原点。模板中的高度、横滚和俯仰保持基线配置，不由浏览器覆盖。

电梯中心锚点的机器人朝向为电梯门外法线的反方向；组件 `yaw` 表示局部 X 轴，因此门外
法线为 `(-sin(yaw), cos(yaw))`。此朝向与任务电梯中心点及返程 XML 重定位一致。
一般切图仍可使用航点或其他组件中心；`indoor_elevator_v1` 室内编译额外要求所选大厅资产
准确绑定 `indoor`、目标层资产准确绑定对应 `floor` 模板，并且大厅到楼层直接通过所选的
物理电梯组件中心衔接，以确保任务路径、定位清单和电梯 ID 清单一致。

`runtime/loc_yaml_path.json` 的精确顶层结构为
`{ "community": "…", "loc_yaml": [{ "building": "…", "unit": "…", "yaml_index": [ … ] }] }`。
每个 `yaml_index` 条目包含 `type`、`yaml`、`2D_yaml`、`init_go` 和 `init_return`；`floor` 条目额外
包含 `floor`，其值等于绑定的 `floor_template`。为保持既有运行时样例兼容，楼层条目的字段顺序固定为
`type`、`floor`、`yaml`、`2D_yaml`、`init_go`、`init_return`。`yaml` 和 `2D_yaml` 是包内受控副本将来安装时的固定目标路径，不能由
客户端传入。

`runtime/lift_id_list.json` 的精确结构为
`{ "community": "…", "lifts": [{ "lift_id": "…", "building": "…", "unit": "…" }] }`。它只收集
路线实际使用的电梯组件中心所关联的物理电梯，按楼栋、单元、`lift_id` 排序并去重；同一
`lift_id` 若出现在不同楼栋/单元，导出失败而不猜测归属。

## Planned（规划中）

新的部署数据格式在成为跨客户端输入前，必须在 `shared/schemas` 中说明。Planned 字段在 Backend 暴露并完成校验前，始终保持 Planned 状态。

## Experimental task compiler

**Status: Experimental（已实现预览，不可部署）**
**权威实现：** `DeploymentStore` 的项目内实验导出与 `web_console.py` HTTP 路由
**消费者：** 当前仅 Web Console；Mobile 保持不变，在明确实现前不得调用以下路由。

编译器以一个 `ry-aletheia.site-project` 为唯一输入所有者。`task_mode=single` 为每个
已标记目标生成一条完整的去返任务；`task_mode=multi` 按每个栋/单元的地图实例与自动定位路线生成可复用的
`multi_tasks/<community>/sub_outdoor_eguard[ _r ].json`（仅有摆渡层时，整个小区只一对）、
`multi_tasks/<community>/outdoor/<building>_<unit>[ _r ].json`（仅有户外阶段时，每栋单元一对）、
`multi_tasks/<community>/indoor/<building>_<unit>[ _r ].json`，以及每户的
`multi_tasks/<community>/floor/<building>_<unit>_n_n<door>[ _r ].json`。一个项目可包含多个栋、
单元和目标地图；旧的单张 `map_stage_assignments` 仅用于导入向导，不能覆盖或决定其他栋单元的
编译路线。标准层门牌按物理楼层和两位户号派生（例如 `1501 → n_n01`）；非标准层使用
`<building>_<unit>_<physical_floor>_<full_room_number>`。没有摆渡层或户外阶段时不会创建对应目录。
路线、目录、文件名和目标顺序都由后端从已保存的地图、流程和组件事实派生，浏览器不传递它们。

`multi_tasks/<community>/` 中的每个任务文件是一个直接的子任务对象，精确字段为
`change_loc`、`map_url`、`pcd_url`、`subtask_name` 和 `waypoints`；它不是带 `subtasks` 数组的
完整任务组 JSON。该格式与现有多任务运行时读取方式一致。

任何包含户外或摆渡阶段的多任务预览必须验证对应的自动入口、唯一转场、地图执行链及设施动作；缺少任一事实时以 `422` 阻断预览，不能输出不完整的 ZIP。它只能在该项目自己的 `deployments/<project_id>/exports/`
下持久化预览产物；不会写入 `/opt/ry/data/tasks/origin_tasks`、行为树运行目录或
定位运行配置，也不会写入 `/opt/ry/data/tasks/multi_tasks`，更不会启动 ROS、Supervisor 或下发任务。

每次预览先在该项目 `exports/` 下的同级临时目录写齐全部产物和 `manifest.json`，再以输入
SHA-256 目录一次发布；写入失败不会公开半成品 `exports/<sha>/`。多任务 `manifest.json` 的
`route_families` 使用可读阶段名称、栋单元与房号事实，绝不包含组件 ID；同时包含
`input_fingerprints`（流程、地图、地图实例、组件、虚拟墙、擦除编辑、定位、物理电梯、模板及
状态码注册表的 SHA-256）和 `task_status_codes_sha256`，供人工审计。Web 只渲染可读路线摘要，
不会将这些散列或任何内部标识当作操作信息展示给实施人员。

| Method | Route | Request | Response |
| --- | --- | --- | --- |
| `POST` | `/api/deployments/{project_id}/task-compiler/config` | 仅 `{ "community": "高科一号" }` | `{ "task_compiler": { "profile": "indoor_elevator_v1", "identity": { "community": "高科一号", "last_preview_input_sha256": null } } }` |
| `POST` | `/api/deployments/{project_id}/task-compiler/preview` | 空对象 `{}` | `{ "preview": { "status": "ready", "experimental": true, "task_mode": "single\|multi", "route_families": [ … ], "input_sha256": "…", "task_json": { … }, "manifest": { … }, "derived_points": { … }, "artifacts": [ … ], "warnings": [], "errors": [], "statement": "实验产物，尚未安装到机器人。" } }` |
| `GET` | `/api/deployments/{project_id}/task-compiler/preview` | 无 | 同上；按当前 SiteProject 重新生成并保存项目内预览 |
| `GET` | `/api/deployments/{project_id}/task-compiler/download` | 无 | 仅返回实验 ZIP 附件；`Content-Type: application/zip`、UTF-8 `Content-Disposition`、`Content-Length` 和 `X-Content-Type-Options: nosniff` |

`project_id` 必须是单个既有 SiteProject 标识，客户端不传递输出文件名、导出路径或
运行时路径。配置请求的键必须严格等于 `community`，预览请求必须是空对象；后端仍会
对小区名称、地图、组件和编译输入做权威校验。

返回状态：格式、项目或存储错误为 `400 Bad Request`；项目事实不足、组件无效或当前
场景不属于已批准编译配置时为 `422 Unprocessable Entity`；成功预览与下载为 `200 OK`。
ZIP 是下载到操作员电脑的实验包，不构成安装、发布或机器人运行时写入授权。
