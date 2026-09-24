# 部署与地图配置

**Status: Existing（已实现）**
**权威实现：** `autodrive_console/deployment.py`、`autodrive_console/mapping.py`、`web_console.py` 和部署 Web UI
**消费者：** `robot_backend` 是项目快照、路线校验和实验导出的权威执行方；PC `web_console` 是部署地图与路线编辑器。Mobile 不是本定位路线/清单契约的消费者，且不得调用其路由。
**兼容性：** 优先增量变更；破坏性变更必须同时更新所有消费者和本文档。

现有部署 API 以 `/api/deployments` 开始。按项目划分的路由覆盖地图导入/上传、可配置部署流程、地图阶段、路线、地图实例、航点、组件模板/组件、虚拟墙和拓扑。旧项目仍可读取转场（MapTransition）记录，但地图切换由有序定位路线与生成的行为树负责，不要求现场人员手动画转场点。建图会话由 `/api/mapping` 与 `/api/mapping/sessions` 路由控制。

`SiteProject.deployment_flow` 是有序地图阶段节点数组，每个节点包含 `id`、`type` 和 `label`。PC 工作台以卡片拖拽维护该数组，插入位置由前/后卡片的吸附指示确定；保存前后均由 Backend 重新归一化和校验，浏览器拖拽状态不是权威数据。
`type` 只能是 `outdoor`（户外图）、`ferry`（摆渡层）、`lobby`（电梯大厅）或
`target_floor`（用户楼层）。流程必须包含且仅包含一个 `lobby` 和一个 `target_floor`，且
`target_floor` 必须是末节点；户外图最多一个，摆渡层可重复。旧项目读取时会从
`scene_model` 自动迁移为默认流程，`scene_model` 仅保留兼容和编译配置识别用途。

| Method | Route | Request | Response |
| --- | --- | --- |
| `POST` | `/api/deployments/{project_id}/deployment-flow` | `{ "flow": [{ "id": "outdoor", "type": "outdoor", "label": "户外图" }, …] }` | `{ "project": { … }, "stage_plan": { … } }` |

`DELETE /api/deployments/{project_id}` 删除一个已存在的部署项目及其项目工作区（地图快照、导出和编辑数据）。后端先校验项目标识并拒绝路径穿越；该动作不触碰机器人运行目录、任务目录、ROS、Supervisor 或其他项目。PC 必须二次确认并明确不可恢复，Mobile 不提供该入口。

该路由只保存项目快照中的流程与阶段绑定，不写机器人运行目录。地图阶段选择、自动分配和拓扑校验均严格使用该数组顺序。

Backend 校验具有权威性：客户端展示并提交用户意图，但不得直接写入部署文件或机器人配置。地图图像、元数据、虚拟墙和拓扑编辑都保留项目/地图所有权。

导入地图后，项目内 `maps/` 快照是后续预览与实验编译的唯一地图来源；浏览器上传的临时目录和原始外部路径都不能成为编译依赖。旧项目读取时会在快照完整的前提下自动迁移该来源记录。

地图快照保留提供的 `index.txt`、索引声明的静态 PCD 和可选动态 PCD；资产的 `files.index` 是项目内
索引相对路径，未提供时为 `null`。普通 2D 地图仍可导入编辑，但定位清单/定位 YAML 导出要求
有效 `index.txt` 及其 PCD：先按索引文件名匹配；若索引保留旧文件名且目录中仅有一份有效静态 `.pcd`，
允许自动绑定该唯一文件并在导出索引中写入实际文件名。多个未匹配 PCD 必须阻断，不能猜测瓦片归属。
导出的索引将区块路径改为包内原始 PCD 文件名，并只携带索引引用的静态及可选同名 `_dyn.pcd`；
不将原机器人路径或未索引文件变成运行时依赖。Backend/Web 受此约束，Mobile 无影响。

## 项目级物理电梯

**Status: Existing（已实现，实验任务编译输入）**
**消费者：** 当前仅 Web Console；Mobile 未实现且不得调用这些路由。

一个 `SiteProject` 以 `physical_elevators` 保存真实电梯的唯一事实。每个实体在同一项目内的
`elevator_id` 必须唯一，并保存 `elevator_protocol`、`min_floor`、`max_floor` 和可选
`unavailable_button_floors`。后者是电梯面板实际不存在的楼层按键（例如 `11`），不是地图楼层；
缺省或空数组保持既有连续按键行为。地图上的
`elevator` 组件只保存 `physical_elevator_id`、门向（`yaw`）、尺寸和 `wait_distance_m`；因此同一
实体可在大厅图和目标层图各有一个落点，而每张地图仍可独立标记电梯门方向。

| Method | Route | Request | Response |
| --- | --- | --- | --- |
| `POST` | `/api/deployments/{project_id}/physical-elevators` | `{ "elevator_id": "10014", "elevator_protocol": "bluetooth", "min_floor": -2, "max_floor": 20, "unavailable_button_floors": [11] }` | `{ "physical_elevator": { … }, "project": { … } }`，`201 Created` |
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

`localization_bindings` 将项目地图绑定为 `outdoor`、`indoor`、`ferry` 或 `floor`。每项只保存
绑定身份字段只有 `map_asset_id`、`building`、`unit`、`type`；`floor` 另有必填的
`floor_template`，它是用户楼层布局模板编号，不是电梯物理楼层。一个楼栋/单元最多各有一个
户外、大厅或摆渡层绑定；用户楼层按布局模板唯一。

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

**Status: Existing（已实现，实验任务编译输入）**
**消费者：** `robot_backend` 校验、派生并生成清单；PC `web_console` 仅提交和编辑项目意图。Mobile 不是消费者，不调用以下路由或读取这些实验产物。

`localization_routes` 是每个楼栋/单元唯一的一条有序路线。定位位姿由 `localization_routes` 推导；
它拥有初始化位姿的来源，不能由 `localization_bindings` 或浏览器提交原始坐标覆盖。路线的严格请求对象为：

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
  ]
}
```

除上述六个键外不接受其他键（旧项目中的 `task_return_waypoint_id` 仅作兼容读取）；`binding_ids` 不得为空或重复，必须同属该楼栋/单元，最后一项必须
是 `floor`。起点和目标 Waypoint 必须分别在首图、末图；可选过渡点仅用于中间场景锚定，不作为返程目标。`links` 必须恰好为每对相邻
绑定各一项，按顺序连接，不得跳图、分支或成环。每个 `anchor` 只能严格为来源图的
`{ "kind": "waypoint", "waypoint_id": "…" }`，或
`{ "kind": "component_center", "component_id": "…" }`；不接受手填 pose。

`floor` 不能出现在路线中间；保存时后端按 `binding_ids` 顺序归一化链接。PC 编辑器可明确
包含/排除同身份绑定、清空未保存草稿或确认删除路线。新绑定不会自动加入已保存路线；所有
成员、顺序和锚点变更只在显式保存/删除后生效。

地图切换不依赖项目级 `map_transitions` 记录。PC 编辑器会在来源地图只有一个电梯组件时自动使用其中心作为返程切图依据；存在多个电梯时要求明确选择实际物理电梯。旧的
`map_transitions` 只读保留，不参与拓扑通过条件，也不会由新界面继续创建。流程中的 `ferry` 只是可配置的中间地图阶段；没有相应地图绑定或批准的编译模板时，导出必须阻断，不能猜测机器人动作。

### 任务过渡点

**Status: Existing（已实现）**
**消费者：** `robot_backend` 验证并编译；PC `web_console` 负责标记、展示和保存速度、去程朝向。Mobile 不读取或写入该字段。

画布的手动 `Waypoint` 中，`kind: "transition"` 是**任务过渡点**，不是定位路线的切图锚点。它可由定位路线引用，但两种用途独立：定位路线锚点只影响定位清单；只有当前室内编译所选的电梯大厅和用户楼层地图上的任务过渡点会进入 `indoor_elevator_v1` 实验任务。每段按项目快照保存顺序走去程、严格反序走返程：

- 大厅去程：`lobby_start → lobby_1… → lobby_wait → lobby_elevator_center`；大厅返程：`lobby_return_wait → lobby_r_1… → lobby_return_start`。
- 用户层去程：`target_wait → 1509_1… → target`；用户层返程：`1509_r_1… → target_return_wait → target_return_elevator_center`。因此只要存在用户层过渡点，返程的首个导航点就是最后一个去程过渡点，不能直接跳到候梯点。

每个生成条目固定为 `waypoint_task_id: ""`、`is_task_point: false`，因此不生成或引用行为树。过渡点保存的 `yaw` 是去程朝向；返程采用同一点的相反顺序并自动转向 180°，使姿态与返程行驶方向一致。

任务 JSON 和 `runtime/loc_yaml_path.json` 必须消费同一条地图段过渡点链，不能分别推导返程。用户楼层存在任务过渡点时，定位清单最终 `floor` 条目的 `init_return` 等于**最后一个去程过渡点**的坐标及其返程朝向（也就是返程子任务的首个导航点）；没有用户楼层任务过渡点时，才回退为目标层电梯门前呼梯点。大厅过渡点同样写入大厅的去/返任务段，但不替代进入大厅时由电梯行为树控制的定位切换锚点。

任务过渡点持久化 `speed_mode`，缺省为 `single_point`；只允许 `task_point`、`single_point`、`slow_point` 和 `narrow_point`。`elevator_in` 与 `backward` 属于受控电梯行为，不能被手动过渡点使用。旧 `kind: "return"` 兼容迁移为不参与任务导出的过渡记录，避免把历史返程选择误插到去程。修改任何任务过渡点都会使现有实验预览失效，必须重新由 Backend 编译。

| Method | Route | Request | Response |
| --- | --- | --- | --- |
| `POST` | `/api/deployments/{project_id}/waypoints` | 新建 `kind: "transition"` 时可选 `{ "speed_mode": "single_point", "yaw": 0 }`，未给速度时为 `single_point` | `{ "waypoint": { …, "speed_mode": "…", "yaw": 0 }, "project": { … } }` |
| `POST` | `/api/deployments/{project_id}/waypoints/{waypoint_id}` | 仅手动任务过渡点；可更新非空子集 `{ "speed_mode": "task_point\|single_point\|slow_point\|narrow_point", "yaw": <弧度数值> }` | `{ "waypoint": { … }, "project": { … } }` |

| Method | Route | Request | Response |
| --- | --- | --- | --- |
| `POST` | `/api/deployments/{project_id}/localization-routes` | 上述严格路线对象 | `{ "localization_route": { … }, "project": { … } }`，`201 Created` |
| `POST` | `/api/deployments/{project_id}/localization-routes/{route_id}` | 同上 | `{ "localization_route": { … }, "project": { … } }` |
| `DELETE` | `/api/deployments/{project_id}/localization-routes/{route_id}` | 无 | `{ "deleted": true }` |

后端在绑定仍被路线引用时阻止更新或删除；在 Waypoint、组件中心或组件生成的 Waypoint 仍被路线
引用时也阻止删除，必须先更新或删除路线。

实验导出只从项目受控地图快照读取 `map.yaml` 与图像，并在 ZIP 内生成下列两个 JSON 以及受控
地图副本和定位 YAML；它不写机器人运行时目录、不调用 ROS 或 Supervisor，也不改变机器人当前
定位、任务或 ROS 状态。

| 路线条目条件 | 字段 | 派生来源 |
| --- | --- | --- |
| 首项（包括唯一项） | `init_go` | 首项（包括唯一项）使用人工选择的任务起点 `task_start_waypoint_id`；首图使用人工选择的任务起点 |
| 仅非首项 | `init_go` | 后续地图统一使用采图电梯中心坐标系原点 `{x: 0.0, y: 0.0, z: 0.0, yaw: 0.0}`；不使用栅格 YAML 左下角 `origin` |
| 非最终项 | `init_return` | 该图出向链接的受控锚点 |
| 最终项 | `init_return` | 存在用户楼层任务过渡点时使用最后一个去程过渡点的返程姿态；否则自动使用目标层电梯门前呼梯点 |

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

编译器以一个 `ry-aletheia.site-project` 为唯一输入所有者，生成室内两图单电梯
场景的实验任务预览。它只能在该项目自己的 `deployments/<project_id>/exports/`
下持久化预览产物；不会写入 `/opt/ry/data/tasks/origin_tasks`、行为树运行目录或
定位运行配置，更不会启动 ROS、Supervisor 或下发任务。

| Method | Route | Request | Response |
| --- | --- | --- | --- |
| `POST` | `/api/deployments/{project_id}/task-compiler/config` | 仅 `{ "community": "高科一号" }` | `{ "task_compiler": { "profile": "indoor_elevator_v1", "identity": { "community": "高科一号", "last_preview_input_sha256": null } } }` |
| `POST` | `/api/deployments/{project_id}/task-compiler/preview` | 空对象 `{}` | `{ "preview": { "status": "ready", "experimental": true, "input_sha256": "…", "task_json": { … }, "manifest": { … }, "derived_points": { … }, "artifacts": [ … ], "warnings": [], "errors": [], "statement": "实验产物，尚未安装到机器人。" } }` |
| `GET` | `/api/deployments/{project_id}/task-compiler/preview` | 无 | 同上；按当前 SiteProject 重新生成并保存项目内预览 |
| `GET` | `/api/deployments/{project_id}/task-compiler/download` | 无 | 仅返回实验 ZIP 附件；`Content-Type: application/zip`、UTF-8 `Content-Disposition`、`Content-Length` 和 `X-Content-Type-Options: nosniff` |

`project_id` 必须是单个既有 SiteProject 标识，客户端不传递输出文件名、导出路径或
运行时路径。配置请求的键必须严格等于 `community`，预览请求必须是空对象；后端仍会
对小区名称、地图、组件和编译输入做权威校验。

返回状态：格式、项目或存储错误为 `400 Bad Request`；项目事实不足、组件无效或当前
场景不属于已批准编译配置时为 `422 Unprocessable Entity`；成功预览与下载为 `200 OK`。
ZIP 是下载到操作员电脑的实验包，不构成安装、发布或机器人运行时写入授权。
