# 有序过渡点任务路径设计

**状态：书面规格已确认，可进入实现**

**日期：2026-09-23**

## 1. 背景与问题

部署画布已经允许实施人员在地图上创建 `kind: "transition"` 的过渡点，Backend 也会把坐标、朝向和标签保存到 `SiteProject.waypoints`。但是当前 `indoor_elevator_v1` 实验任务编译器只从起点、目标点和电梯组件派生固定路点，不读取普通 `transition` 点，也不读取项目内旧的通用 `routes`。

因此目前存在三个相互关联的问题：

- 画布显示并保存了过渡点，但任务 JSON 静默遗漏该点；
- 未被定位路线引用的过渡点不参与编译输入指纹，添加或移动它不会使旧预览失效；
- 项目数据只保存过渡点坐标，没有保存同一地图内多个过渡点的任务执行顺序。

本设计让实施人员明确编排每张任务地图上的过渡点顺序。编译器按该顺序生成去程，并在返程中反向复用。它不根据坐标、创建时间、标签或画布顺序猜测路线。

## 2. 范围与既有边界

本设计扩展现有的项目级定位路线和 `indoor_elevator_v1` 实验任务编译器，不引入新的机器人控制通道。

- 仍只生成项目目录内的实验预览和下载包；
- 不写机器人任务目录、行为树运行目录或定位运行配置；
- 不启动或停止 ROS、Supervisor、导航、定位或任务执行；
- 不生成新的速度模式或行为树 XML；
- Mobile 不是该配置和实验导出的消费者，不修改 Mobile；
- 第一阶段仍只支持已批准的室内两图、单电梯、单起点、单目标、往返模型。

本规格仅在“人工过渡点的显式排序”方面修订 `2026-09-05-component-task-compiler-design.md` 中“不要求人工编排地图内路线”的旧约束。起点、电梯候梯点、电梯中心、目标点、子任务边界和行为树名称继续由 Backend 自动派生；实施人员只排列自己创建的可选过渡点。

## 3. 方案选择

采用“定位路线内保存分地图任务路径”的方案，不复用旧 `SiteProject.routes`：

- 定位路线已经拥有楼栋、单元、有序地图绑定、任务起点和任务目标，是任务路径的权威上下文；
- 旧 `routes` 只有地图和 Waypoint ID，没有楼栋、单元、任务用途或唯一性，存在多条记录时无法安全选择；
- 坐标投影、最近邻和创建时间排序都无法理解墙体、绕行方向和现场通道，不得作为生成依据。

## 4. 数据模型与 API

`localization_routes` 的严格请求和持久化对象新增 `task_paths`：

```json
{
  "building": "1",
  "unit": "1",
  "binding_ids": ["lobby-binding", "floor-binding"],
  "task_start_waypoint_id": "waypoint-start",
  "task_target_waypoint_id": "waypoint-target",
  "links": [
    {
      "from_binding_id": "lobby-binding",
      "to_binding_id": "floor-binding",
      "anchor": {
        "kind": "component_center",
        "component_id": "lobby-elevator"
      }
    }
  ],
  "task_paths": [
    {
      "binding_id": "lobby-binding",
      "transition_waypoint_ids": []
    },
    {
      "binding_id": "floor-binding",
      "transition_waypoint_ids": ["waypoint-transition-a", "waypoint-transition-b"]
    }
  ]
}
```

新保存的路线必须满足：

- `task_paths` 是数组，并且每项只能包含 `binding_id` 和 `transition_waypoint_ids`；
- 每个 `binding_id` 在 `task_paths` 中恰好出现一次，集合必须与 `binding_ids` 完全一致，顺序按 `binding_ids` 归一化；
- `transition_waypoint_ids` 是不重复的字符串数组；
- 每个 ID 必须指向当前项目中存在、未由组件自动生成、`kind` 为 `transition` 的 Waypoint；
- Waypoint 的 `map_asset_id` 必须等于该 `binding_id` 绑定的地图；
- 同一路线内一个过渡点只能出现一次；
- 路线涉及地图上的每个手工 `transition` 点必须被对应 `task_paths` 收录，存在未编排点时拒绝保存、预览和导出。

现有 `POST /api/deployments/{project_id}/localization-routes` 与更新路由继续使用，不新增浏览器直写文件接口。Backend 是归一化、引用完整性和顺序校验的唯一权威方。

## 5. 兼容与迁移

旧项目读取时允许定位路线缺少 `task_paths`：

- 路线涉及的地图没有手工过渡点时，按每个绑定的空数组兼容，现有任务输出保持不变；
- 路线涉及的地图存在手工过渡点时，不猜测顺序，预览和导出返回可操作的阻断错误，要求用户打开定位路线完成编排；
- 下一次保存路线时，Web 必须提交完整、规范化的 `task_paths`；
- 旧 `SiteProject.routes` 和 `map_transitions` 继续只读兼容，不自动迁移为任务路径，也不参与编译。

删除仍被 `task_paths` 引用的 Waypoint 必须被 Backend 阻止。新增、删除或重新排序过渡点，以及更新其坐标或朝向，都必须清空 `last_preview_input_sha256`。

## 6. Web 操作流程

定位路线编辑器按 `binding_ids` 顺序为每张地图显示一个任务路径段：

```text
大厅：起点 → [过渡点，可排序] → 电梯
目标层：电梯 → [过渡点，可排序] → 目标点
```

- 起点、电梯和目标点是只读的固定端点，不允许拖出或替换；
- 当前地图上的手工过渡点进入“待编排”区；
- 用户把过渡点加入路径，并通过拖动或键盘“上移/下移”明确顺序；
- 过渡点卡片显示名称、坐标和方向，避免只凭 UUID 操作；
- 未编排点、重复点、错误地图引用和失效引用直接在所属地图段显示；
- 路线不完整时禁用保存后的任务预览/导出路径，并指明需要处理的地图和过渡点；
- 保存成功后重新读取 Backend 归一化结果，画布路径和编译预览均使用该结果，不依赖浏览器临时数组。

任务预览应逐点展示最终顺序，并把过渡点标为“纯导航 · 无行为树 · single_point”，方便实施人员在下载前核对。

## 7. 编译规则

编译器从当前楼栋/单元唯一定位路线解析大厅和目标层的 `task_paths`，把过渡点坐标与朝向转换为现有任务 JSON 的标准 pose。

四个子任务的路点顺序为：

1. 大厅去程：起点 → 大厅过渡点正序 → 首层候梯点 → 首层电梯中心；
2. 目标层去程：目标层候梯/出梯点 → 目标层过渡点正序 → 目标点；
3. 目标层返程：目标层过渡点倒序 → 目标层候梯点 → 目标层电梯中心；
4. 大厅返程：首层候梯/出梯点 → 大厅过渡点倒序 → 起点。

每个过渡点生成的字段固定为：

```json
{
  "waypoint_task_id": "",
  "is_task_point": false,
  "speed_mode": "single_point",
  "is_backward": false,
  "is_single_point": true,
  "pose": {
    "position": { "x": 0.0, "y": 0.0, "z": 0.0 },
    "orientation": { "x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0 }
  },
  "waypoint_id": "waypoint-transition-a"
}
```

其中：

- `waypoint_task_id` 为空，不生成、引用或复制任何行为树 XML；
- `speed_mode` 固定为已批准的 `single_point`；
- `is_task_point` 为 `false`，表示纯导航经过点；
- `waypoint_id` 保留项目中的原始 Waypoint ID，便于从任务 JSON 追溯画布标记；
- `pose` 使用保存的 `x/y/yaw`，四元数按现有 `_pose` 规则生成；
- 去返程复用相同坐标和朝向，仅列表顺序反转，不擅自反转车头方向；
- 过渡点不新增任何 ZIP 成员，行为树产物集合保持不变。

`derived_points` 和预览逐点来源信息必须包含这些过渡点，以便 Web 显示来源。编译输入指纹必须包含：有序 ID、每个过渡点的地图、坐标、朝向和类型。任何一项变化都必须产生新的指纹。

## 8. 错误处理与安全失败

以下情况以 `422 Unprocessable Entity` 阻止任务预览和下载，不允许静默忽略：

- 相关地图存在未编排的手工过渡点；
- `task_paths` 缺少或重复绑定；
- 过渡点不存在、类型不是 `transition`、来自错误地图或由组件自动生成；
- 同一路线重复引用同一过渡点；
- 坐标、朝向或地图边界无效；
- 路线、绑定、起点、目标点或电梯配置本身无效。

错误信息必须包含地图名称和过渡点名称或 ID，并给出“打开定位路线并完成过渡点排序”的恢复动作。Web 不得把失败预览显示为可下载状态。

## 9. 预览失效与数据一致性

以下 Backend 写操作必须调用统一的编译预览失效逻辑：

- 新增或删除手工 Waypoint；
- 保存、更新或删除定位路线；
- 修改过渡点坐标或朝向（若后续提供该 API）；
- 修改地图绑定或删除相关地图；
- 既有会影响编译器的组件、实例、电梯和地图修改。

下载接口继续每次从当前项目重新编译，不能只信任浏览器缓存或旧导出目录。导出目录仍按完整输入 SHA-256 隔离；清单必须记录有序任务路径和最终任务 JSON 的散列。

## 10. 实现边界

预计受影响模块：

- `shared/contracts/deployment.md`：更新 Existing 定位路线请求、兼容规则和实验编译语义；
- `autodrive_console/deployment.py`：归一化和验证 `task_paths`、保护引用、预览失效；
- `autodrive_console/task_compiler.py`：解析有序过渡点、插入去返程任务、更新输入指纹；
- `autodrive_console/web/deployment.html`、`deployment.js`、相关 CSS：路线排序和预览展示；
- Backend 与 Web 定向测试。

不修改 ROS Topic、任务下发服务、Supervisor、Mobile、验收计划或运行时安装逻辑。

## 11. 测试与验收

Backend 测试必须覆盖：

- 单个和多个过渡点按显式顺序进入大厅、目标层去程；
- 返程严格使用相反顺序；
- 每个过渡点的空 `waypoint_task_id`、`is_task_point: false` 和 `single_point`；
- 过渡点不生成额外 XML；
- 坐标、朝向和原始 Waypoint ID 保持一致；
- 重复、遗漏、错误地图、错误类型、失效 ID 和组件生成点被拒绝；
- 删除被路径引用的点被拒绝；
- 添加、删除和重新排序使旧预览失效；
- 顺序或几何变化会改变输入指纹；
- 没有过渡点的旧项目继续生成原有任务序列；
- 有未编排过渡点的旧项目得到明确阻断错误；
- 下载 ZIP 中的任务 JSON 与预览完全一致。

Web 测试和浏览器检查必须覆盖：

- 两张地图分别显示固定端点和过渡点列表；
- 拖动与键盘排序产生相同 payload；
- 保存后使用 Backend 返回顺序重新渲染；
- 未编排点时无法进入成功预览/下载状态；
- 任务预览显示正序、倒序、无行为树和 `single_point`；
- 浅色/深色主题、桌面和窄屏下路径卡片可读且不横向溢出。

完成前运行 `scripts/test-backend.sh` 和 `scripts/test-web.sh`，并用当前“高科1号”项目生成一次受控预览，逐点确认目标层过渡点同时出现在去程和返程中。

## 12. 非目标

- 自动寻路、避障或按坐标推测过渡点顺序；
- 将旧通用 `routes` 自动提升为任务路径；
- 为过渡点生成行为树；
- 为过渡点提供非 `single_point` 的速度配置；
- 在返程中自动修改过渡点朝向；
- 扩展到户外、摆渡层、多电梯、多目标或分支任务；
- 自动安装、下发或执行生成的任务。
