# 部署与地图配置

**Status: Existing（已实现）**
**权威实现：** `autodrive_console/deployment.py`、`autodrive_console/mapping.py`、`web_console.py` 和部署 Web UI
**消费者：** `robot_backend` 是项目快照、路线校验和实验导出的权威执行方；PC `web_console` 是部署地图与路线编辑器。Mobile 不是本定位路线/清单契约的消费者，且不得调用其路由。
**兼容性：** 优先增量变更；破坏性变更必须同时更新所有消费者和本文档。

现有部署 API 以 `/api/deployments` 开始。按项目划分的路由覆盖地图导入/上传、地图阶段、转场、路线、场景模型、地图实例、航点、组件模板/组件、虚拟墙和拓扑。建图会话由 `/api/mapping` 与 `/api/mapping/sessions` 路由控制。

Backend 校验具有权威性：客户端展示并提交用户意图，但不得直接写入部署文件或机器人配置。地图图像、元数据、虚拟墙和拓扑编辑都保留项目/地图所有权。

导入地图后，项目内 `maps/` 快照是后续预览与实验编译的唯一地图来源；浏览器上传的临时目录和原始外部路径都不能成为编译依赖。旧项目读取时会在快照完整的前提下自动迁移该来源记录。

## 项目级物理电梯

**Status: Existing（已实现，实验任务编译输入）**
**消费者：** 当前仅 Web Console；Mobile 未实现且不得调用这些路由。

一个 `SiteProject` 以 `physical_elevators` 保存真实电梯的唯一事实。每个实体在同一项目内的
`elevator_id` 必须唯一，并保存 `elevator_protocol`、`min_floor` 和 `max_floor`。地图上的
`elevator` 组件只保存 `physical_elevator_id`、门向（`yaw`）、尺寸和 `wait_distance_m`；因此同一
实体可在大厅图和目标层图各有一个落点，而每张地图仍可独立标记电梯门方向。

| Method | Route | Request | Response |
| --- | --- | --- | --- |
| `POST` | `/api/deployments/{project_id}/physical-elevators` | `{ "elevator_id": "10014", "elevator_protocol": "bluetooth", "min_floor": 1, "max_floor": 15 }` | `{ "physical_elevator": { … }, "project": { … } }`，`201 Created` |
| `POST` | `/api/deployments/{project_id}/physical-elevators/{physical_elevator_id}` | 同上 | `{ "physical_elevator": { … }, "project": { … } }` |
| `DELETE` | `/api/deployments/{project_id}/physical-elevators/{physical_elevator_id}` | 无 | `{ "deleted": true }` |

后端拒绝重复编号、未知关联、无效服务楼层及正在被地图落点引用的实体删除。旧项目读取时会将
旧组件重复的 `elevator_id` 自动迁移成同一实体；若旧协议或服务范围彼此冲突，实体会带有
`migration_conflict`，实验编译明确拒绝，不能猜测采用其中任一配置。以上路由只修改项目快照，
不写机器人任务、行为树、定位目录，也不调用 ROS 或 Supervisor。

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

除上述六个键外不接受其他键；`binding_ids` 不得为空或重复，必须同属该楼栋/单元，最后一项必须
是 `floor`。起点 Waypoint 必须在首图，目标 Waypoint 必须在末图。`links` 必须恰好为每对相邻
绑定各一项，按顺序连接，不得跳图、分支或成环。每个 `anchor` 只能严格为来源图的
`{ "kind": "waypoint", "waypoint_id": "…" }`，或
`{ "kind": "component_center", "component_id": "…" }`；不接受手填 pose。

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
| 仅非首项 | `init_go` | 只有非首项使用其 YAML `origin` 的 `x`、`y`、`yaw`（`z: 0.0`）；后续地图使用其 YAML `origin` |
| 非最终项 | `init_return` | 该图出向链接的受控锚点 |
| 最终项 | `init_return` | 最终项使用人工选择的任务目标 `task_target_waypoint_id` |

`runtime/loc_yaml_path.json` 的精确顶层结构为
`{ "community": "…", "loc_yaml": [{ "building": "…", "unit": "…", "yaml_index": [ … ] }] }`。
每个 `yaml_index` 条目包含 `type`、`yaml`、`2D_yaml`、`init_go` 和 `init_return`；`floor` 条目额外
包含 `floor`，其值等于绑定的 `floor_template`。`yaml` 和 `2D_yaml` 是包内受控副本将来安装时的固定目标路径，不能由
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
