# 实时观测当前地图任务起终点设计

## 目标

PC 实时观测页在已确认的活动地图上展示车端任务的起点与终点。操作者可以在“任务起终点”图层开启时查看这些低干扰标记，右键某个点位后从紧凑菜单选择“前往此起点/终点”。浏览器只提交 Backend 签发的不透明点位 ID；Backend 保持 Nav2、地图校验与车辆安全边界的唯一所有权。

本设计替代顶部“前往任务起点”文件/候选选择器。Mobile 不消费新端点、不显示任务点和导航入口。

## 已确认问题：虚拟墙迟到

`ObservationManager.live_layers()` 已具备以实时 OccupancyGrid 元数据、`map_server` YAML、分辨率、尺寸与原点严格匹配后补取同目录 `map_walls.yaml` 的能力，并且对短暂未命中不作永久负缓存。

但 PC 前端当前只在 `active_map_id` 改变时请求 `/maps/{id}/layers`。缓存快照已到而 map_server YAML/墙文件稍后可验证时，前端没有调用 `POST /api/observation/live-layers`，所以不会补画墙。这是虚拟墙不能及时加载的根因。

## 虚拟墙补偿链路

当底图 metadata 已就绪且当前 `virtualWalls` 为空或尚未与此地图 signature 确认时，前端以有限频率调用 `POST /api/observation/live-layers`，请求仅包含当前地图的 `resolution`、`width`、`height`、`origin` 与 `frame_id`。

- 每个稳定地图 signature 首次立即请求；未匹配时以短周期重试，达到有限等待窗口后退回低频重试。
- 任何地图 ID、几何元数据或 frame 变化都会取消旧 signature 的重试并清空旧墙，防止跨图残留。
- Backend 返回 `matched=true` 后，前端仅替换 `virtualWalls` 并调用静态世界重绘；不重新下载底图、不重置缩放、跟随或点云。
- Backend 仍只在 map_server 指向的 YAML 与实时 OccupancyGrid 精确验证一致时返回墙；歧义、缺失、旧图或错误 YAML 均保持无墙，绝不按相似几何猜测。

## 任务点索引

### 数据事实与策略

现有 `/opt/ry/data/tasks/origin_tasks` 是平铺目录，文件路径本身不包含地图身份；`multi_tasks` 也按业务层级而非地图组织。因此无法在不读取任务 JSON 的情况下可靠识别“当前地图任务”。首次建立索引时读取任务文件不可避免，但它绝不能位于 HTTP handler、页面轮询或右键操作路径中。

新增 Backend 拥有的 `CurrentMapTaskPointIndex`：

- 后台 worker 只读扫描允许的单点与多点任务根，提取每个有效任务段的规范化 `map_url`、首个路点、末个路点及朝向；无效 JSON、无地图、空路点、非有限坐标与非法四元数只形成受控诊断。
- 建立内存索引 `map identity -> task points`，以地图、坐标、航向和 `start|end` 去重。每个公开点仅包含不透明 ID、种类、x/y/yaw 与无文件名的受控标签；不返回文件名、绝对路径、原始 JSON 或 map_url。
- 初次构建与后续受控刷新均由后台执行；HTTP 只返回最后一致快照及 `refreshing` 状态。任务目录的 mtime/文件签名变化后才触发增量重建，绝不随 1 秒实时页轮询重新遍历。
- 索引只读，不能创建、覆盖、移动或删除车端任务文件。

### 同图过滤与目标解析

`GET /api/observation/task-points` 不接受地图路径或坐标。它从 `ObservationManager` 取得当前已确认 map_server YAML 与活动 OccupancyGrid 快照，再仅返回索引中地图身份严格匹配的起点与终点。

`POST /api/observation/task-point-navigation/begin` 只接受 `{ "id": "opaque-id" }`。Backend 在创建 Nav2 Goal 前重新读取该点所属任务、确认文件指纹与已索引数据一致，执行同图校验，并再次执行车辆安全门槛。任务变更、地图切换或文件消失一律 409 拒绝，绝不使用过期索引结果。

现有 `TaskStartNavigationController` 重命名或收敛为任务点导航控制器，保留单一 Action 所有权、300 秒上限、cancel、结果跟踪与测试任务的双向互斥；不发布 Twist、不切控制源、不调用 `/goal_pose`。

## 安全边界

开始前及提交 Nav2 Goal 前都必须满足：

- 没有普通测试或部署验收运行；任务点导航中同样阻止创建运行。
- 无手动控制会话，手动重定位占用为 `idle`。
- 控制源已确认是 `navigation`，急停已确认 `normal`，定位状态为 `normal`。
- 当前 `/map_server` YAML、活动 OccupancyGrid 元数据和索引点的任务地图严格一致。
- Nav2 `/navigate_to_pose` Action Server 接受目标。

拒绝、Action 不可用、取消、超时、定位/急停/控制源状态丢失时必须取消该控制器拥有的 Goal 并返回受控错误；不会重试或以浏览器数据推测 ROS 参数。

## PC 地图交互与视觉

“图层”面板新增 `任务起终点` 复选项，默认开启。该图层位于虚拟墙之上、点云与车体之下：

- 起点使用克制蓝色实心圆与细浅环；终点使用暖琥珀实心圆与细浅环。重合点以双层标记表达，而非堆叠文字。
- 默认不显示文件名、长标签或持续浮层，避免覆盖地图；只在右键命中 16 px 范围时显示紧凑半透明上下文菜单。
- 菜单仅显示“前往此起点”或“前往此终点”和“取消”。选择前往后显示一次受控确认；确认后才调用 begin API。
- 右键菜单随地图点位重新定位；地图拖动、缩放、切图、图层关闭、Esc、页面卸载或服务端进入导航终态时都关闭菜单。
- 所有表面沿用实时页半透明、紧凑圆角、低阴影与浅/深主题 tokens；`prefers-reduced-motion` 下取消弹出位移动画。

任务点图层关闭时不发起任务点刷新。再次开启先使用已取得的同图快照，再请求最新状态；不会影响虚拟墙、点云、costmap 或车体跟随。

## HTTP 契约

新增 PC-only、受控 API：

| 方法 | 端点 | 请求 | 语义 |
| --- | --- | --- | --- |
| `GET` | `/api/observation/task-points` | — | 返回当前已确认地图上的脱敏起点/终点、索引刷新状态与可读状态。 |
| `POST` | `/api/observation/task-point-navigation/begin` | `{ "id": "opaque-id" }` | 重新验证任务、地图和车辆安全状态，再创建一个 Nav2 Goal。 |
| `POST` | `/api/observation/task-point-navigation/cancel` | `{}` | 仅取消当前控制器拥有的 Goal。 |

请求体上限 16 KiB。响应不得包含任务文件名、绝对路径、`map_url`、原始 JSON、原始 ROS feedback、行为树、速度或 Action 参数。`409` 代表状态/地图/文件冲突，`503` 代表 ROS Action 不可用。

`shared/contracts/realtime_observation.md`、`shared/contracts/robot_control.md` 和 `shared/contracts/task_execution.md` 必须更新，标记现有顶部候选 API 已由任务点 API 替代，并记录 PC-only 消费者及 Mobile 不受影响。

## 验证

- Backend：地图先到、map_server 墙信息后到时补画；切图中不残留旧墙；歧义地图保持无墙。
- Backend：索引后台构建不阻塞 HTTP；单点/多点任务均提取起终点；同图严格过滤；无效与变更文件拒绝；不透明 ID；安全门槛、取消、超时及运行互斥。
- Web：任务点图层开关、起终点 Pixi 渲染、重合标记、右键命中/取消/确认、切图清理、虚拟墙补偿与浅深主题/减少动效。
- 完成时运行 `scripts/test-backend.sh`、`pixi run test-offline`、`pixi run frontend-check`、`git diff --check`，并以浏览器检查桌面布局。实车只在操作者明确允许且空旷安全区域中验证一次；实现与测试阶段绝不自行发送运动 Goal。
