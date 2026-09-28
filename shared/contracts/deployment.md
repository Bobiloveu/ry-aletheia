# 部署与地图配置

**Status: Existing（已实现）**
**权威实现：** `autodrive_console/deployment.py`、`autodrive_console/mapping.py`、`web_console.py` 和部署 Web UI
**消费者：** `robot_backend` 是项目快照、路线校验和实验导出的权威执行方；PC `web_console` 是部署地图与路线编辑器。Mobile 不是本定位路线/清单契约的消费者，且不得调用其路由。
**兼容性：** 优先增量变更；破坏性变更必须同时更新所有消费者和本文档。

现有部署 API 以 `/api/deployments` 开始。按项目划分的路由覆盖地图导入/上传、可配置部署流程、地图阶段、路线、地图实例、航点、组件模板/组件、虚拟墙和拓扑。地图切换顺序由后端的部署流程与核心标记派生；实施人员不编辑跨图顺序。摆渡层或户外阶段只需在来源图标记唯一过渡点，后端按其地图角色将该点识别为转场锚点。建图会话由 `/api/mapping` 与 `/api/mapping/sessions` 路由控制。

`SiteProject.task_mode` 是创建时写入且不可修改的车辆任务模式，只能为 `single` 或 `multi`。
`POST /api/deployments` 仅接受 `{ "name": "高科一号", "task_mode": "single" }` 或
`{ "name": "高科一号", "task_mode": "multi" }`；不接受默认模式、额外字段或模式更新。
缺少该字段的历史项目在读取时迁移为 `single`。任务编译器配置路由只保存小区名称，不能改变
项目模式。

`SiteProject.deployment_flow` 是有序地图阶段节点数组，每个节点包含 `id`、`type` 和 `label`。PC 工作台以卡片拖拽维护该数组，插入位置由前/后卡片的吸附指示确定；保存前后均由 Backend 重新归一化和校验，浏览器拖拽状态不是权威数据。
`type` 只能是 `outdoor`（户外图）、`ferry`（摆渡层）、`lobby`（电梯大厅）或
`target_floor`（用户楼层）。流程必须包含且仅包含一个 `lobby` 和一个 `target_floor`，且
`target_floor` 必须是末节点；户外图最多一个，摆渡层可重复。旧项目读取时会从
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

地图快照保留提供的 `index.txt`、索引声明的静态 PCD 和可选动态 PCD；资产的 `files.index` 是项目内
索引相对路径，未提供时为 `null`。普通 2D 地图仍可导入编辑，但定位清单/定位 YAML 导出要求
有效 `index.txt` 及其 PCD：先按索引文件名匹配；若索引保留旧文件名且目录中仅有一份有效静态 `.pcd`，
允许自动绑定该唯一文件并在导出索引中写入实际文件名。多个未匹配 PCD 必须阻断，不能猜测瓦片归属。
导出的索引将区块路径改为包内原始 PCD 文件名，并只携带索引引用的静态及可选同名 `_dyn.pcd`；
不将原机器人路径或未索引文件变成运行时依赖。Backend/Web 受此约束，Mobile 无影响。

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

画布的手动 `Waypoint` 中，`kind: "transition"` 通常是**任务过渡点**。当它是 `ferry` 或 `outdoor` 来源图上的唯一过渡点时，Backend 自动将其作为地图转场锚点，并从该地图的执行节点中排除；这不是浏览器可选的第二种模式。其余过渡点是自动路径必经点，后端按当前可达距离和稳定 ID 自动形成 `execution_nodes` 顺序；去程按该顺序、返程严格反序，浏览器不提供人工排列：

- 大厅去程：`lobby_start → lobby_1… → lobby_wait → lobby_elevator_center`；大厅返程：`lobby_return_wait → lobby_r_1… → lobby_return_start`。
- 用户层去程：`target_wait → 1509_1… → target`；用户层返程：`1509_r_1… → target_return_wait → target_return_elevator_center`。因此只要存在用户层过渡点，返程的首个导航点就是最后一个去程过渡点，不能直接跳到候梯点。

手动过渡点生成的条目固定为 `waypoint_task_id: ""`、`is_task_point: false`，因此不生成或引用行为树。过渡点保存的 `yaw` 是去程朝向；返程采用同一点的相反顺序并自动转向 180°，使姿态与返程行驶方向一致。区域和受控设备组件按 `execution_nodes` 的同一位置展开为多个节点；受控设备动作才会引用项目内受控行为树。

闸机与自动门的显示编号（`gate_id` / `door_id`）只供人员识别；`controller_device_id` 是 `DoorControl doorid` 的唯一来源。两类组件均保存 `pre_open_distance_m`（开门前距离）与 `post_open_distance_m`（开门后停靠距离），默认均为 `1.5m`，范围为 `0.5–5m`。执行链把去程动作点自动投射到设备门体两侧：门前距离处开门、门后距离处关门；返程复用同一物理点并反转动作。地图标记和几何调整阶段允许设备号暂为空，以便先落图再在现有组件属性中补填；一旦填写则必须是正整数纯数字。实验预览、行为树生成和下载仍要求其非空且为正整数，缺失时必须阻断，绝不生成猜测的设备号。每个动作路点的 `waypoint_task_id` 必须与 ZIP 中同名 XML（不含 `.xml`）完全一致；闸机遵循 `e_guard_open_go`，自动门遵循 `{building}_{unit}_open_door_go` 等既有任务命名。

受控设备的默认速度模式只定义在 `autodrive_console/task_templates/indoor_elevator_v1/components/component-defaults.json`。其中 `auto_door` 固定为 `task_point`，`gate` 固定为 `narrow_point`；浏览器只读展示，不提供人工选择。Backend 在创建、更新、读取旧项目和编译任务时均加载该文件，锁定项会覆盖历史项目属性，因此修改该 JSON 是后续调整默认策略的唯一入口。`GET /api/deployment-component-defaults` 只读返回当前已验证配置，供 PC Web 展示；Mobile 不是消费者。

任务 JSON 和 `runtime/loc_yaml_path.json` 必须消费同一条地图段执行链，不能分别推导返程。定位清单最终 `floor` 条目的 `init_return` 始终等于该图**返程子任务的首个实际节点**（最后一个去程非固定节点的返程姿态；可能是过渡点、区域边界或设备动作点）；没有任何非固定节点时，才回退为目标层电梯门前呼梯点。大厅执行链同样写入大厅的去/返任务段，但不替代进入大厅时由电梯行为树控制的定位切换锚点。

任务过渡点持久化 `speed_mode`，缺省为 `single_point`；只允许 `task_point`、`single_point`、`slow_point` 和 `narrow_point`。`elevator_in` 与 `backward` 属于受控电梯行为，不能被手动过渡点使用。旧 `kind: "return"` 兼容迁移为不参与任务导出的过渡记录，避免把历史返程选择误插到去程。修改任何任务过渡点都会使现有实验预览失效，必须重新由 Backend 编译。

| Method | Route | Request | Response |
| --- | --- | --- | --- |
| `GET` | `/api/deployment-component-defaults` | 无 | `{ "component_speed_defaults": { "auto_door": { "speed_profile": "task_point", "locked": true }, "gate": { "speed_profile": "narrow_point", "locked": true }, … } }`；只读任务模板配置 |
| `POST` | `/api/deployments/{project_id}/waypoints` | 新建 `kind: "transition"` 时可选 `{ "speed_mode": "single_point", "yaw": 0 }`，未给速度时为 `single_point` | `{ "waypoint": { …, "speed_mode": "…", "yaw": 0 }, "project": { … } }` |
| `POST` | `/api/deployments/{project_id}/waypoints/{waypoint_id}` | 仅手动任务过渡点；可更新非空子集 `{ "speed_mode": "task_point\|single_point\|slow_point\|narrow_point", "yaw": <弧度数值> }` | `{ "waypoint": { … }, "project": { … } }` |

| Method | Route | Request | Response |
| --- | --- | --- | --- |
| `POST` | `/api/deployments/{project_id}/localization-routes/derive` | 严格为空对象 `{}` | `{ "project": { … }, "localization_routes": [ … ] }`；Backend 从场景和地图标记重新生成只读路线 |

Waypoint 与地图组件均可直接删除，即使当前自动路线引用它们。删除在后端事务内先移除标记、再立即从剩余场景事实重新派生路线，浏览器只刷新结果，不参与排序；若删除了起点、目标或电梯等核心标记，后端清空过期路线，部署向导显示待补齐状态，预览保持不可生成，直到重新标记后自动恢复。

实验导出只从项目受控地图快照读取 `map.yaml` 与图像，并在 ZIP 内生成下列两个 JSON 以及受控
地图副本和定位 YAML；它不写机器人运行时目录、不调用 ROS 或 Supervisor，也不改变机器人当前
定位、任务或 ROS 状态。

| 路线条目条件 | 字段 | 派生来源 |
| --- | --- | --- |
| 首项（包括唯一项） | `init_go` | 首项（包括唯一项）使用人工选择的任务起点 `task_start_waypoint_id`；首图使用人工选择的任务起点 |
| 仅非首项 | `init_go` | 后续地图统一使用采图电梯中心坐标系原点 `{x: 0.0, y: 0.0, z: 0.0, yaw: 0.0}`；不使用栅格 YAML 左下角 `origin` |
| 非最终项 | `init_return` | 该图出向链接的受控锚点 |
| 最终项 | `init_return` | 该图返程子任务的首个实际节点；无非固定节点时使用目标层电梯门前呼梯点 |

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
