# 组件驱动任务编译器设计

**状态：已确认设计，等待实现计划**  
**日期：2026-09-05**

## 1. 目的与安全边界

部署建图的第一期目标是从实施人员标注的真实场景组件，生成一套可审查的机器人任务产物：任务 JSON、站点行为树 XML 和定位 YAML。它替代手工在 Task Editor 中复制子任务、删除重复点、手填电梯行为树名称和修改地图路径的工作。

第一期始终是实验性导出：

- 只在项目受控导出目录生成和预览产物，支持下载；
- 绝不写入 `/opt/ry/data/tasks/origin_tasks`、运行中的 `waypoint_tasks` 或定位配置目录；
- 绝不启动/停止 ROS、Supervisor、导航、定位或任务执行；
- 生成不通过校验时不给出“可执行”结论；
- 原始地图、原始任务、原始 XML 和原始 YAML 均只读。

后续实车对比并批准后，才单独设计“安装/部署”流程。该流程不属于本规格。

## 2. 事实来源与冻结基线

第一期仅以以下用户提供并已核对的真实文件为行为依据：

- `/opt/ry/data/tasks/origin_tasks/高科一号_1_1_15_1509.json`；
- `/opt/ry/data/tasks/waypoints_attributes/waypoint_tasks/gk1_A/*.xml`；
- `/opt/ry/config/localization/config/GK1/rycx_loc_livox.yaml`；
- `/opt/ry/config/localization/config/GK1/rycx_loc_livox_1_1_floor.yaml`；
- `/opt/ry/data/tasks/waypoints_attributes/speed_modes/` 中既有速度模式。

高科一号两份定位 YAML 的已验证差异仅为 `system.map_path`。编译器将把一份受控、版本化的基线快照复制为每张地图的定位 YAML，并只替换 `system.map_path`。每次编译清单记录模板版本和 SHA-256。

不会创造或编辑速度模式 XML。生成 JSON 的 `speed_mode` 只能引用已批准的名称：如 `task_point`、`single_point`、`elevator_in`、`backward`、`narrow_point`、`slow_point`。

## 3. 实施人员输入与工具推导的边界

实施人员只负责地图及真实世界事实：

- 选择场景模型并绑定地图阶段；
- 填写地图实例的楼栋、单元和逻辑楼层；
- 在地图上放置并编辑起点、目标、电梯及以后扩展的现场组件；
- 对电梯填写相同的 `elevator_id`、当前地图楼层、门向和必要服务范围；
- 对目标填写门牌号；项目级填写实际小区名称。

工具负责且不要求人工编排：

- 地图内路线点的顺序；
- 去程/返程镜像；
- 跨地图交接点；
- 子任务边界、子任务名称及任务 JSON 排序；
- 速度模式、行为树文件名和行为树参数；
- 任务、行为树与定位文件之间的路径引用。

现有手工“路线”“交接点”“通用 Waypoint”入口不删除已保存的兼容数据，但不参与正式编译，也不应出现在正式任务生成路径中。

## 4. 编译范围

### 4.1 第一期受支持场景

第一期完整支持由现有样例证实的“室内两图、单电梯、单起点、单目标、往返配送”模型：

`大厅/首层 → 目标楼层 → 目标楼层返程 → 大厅/首层返程`

其结果是四个子任务。该模型生成完整的任务 JSON、六个电梯相关 XML、`start_task.xml`、`task_complete.xml` 及两张地图的定位 YAML。

### 4.2 预留而不伪造的范围

三图室内外模型未来应生成六个子任务，但当前参考资料没有室外到大厅之间的真实切图行为树/重定位规则。第一期必须显示该项为“缺少受控过渡模板”，而不是凭空生成 `SwitchMap` 行为。

闸机、自动门、窄通道、坡道、减速区会继续作为部署组件保存。只有得到对应真实行为树样例和路点顺序后，才各自加入编译规则。当前不会把它们错误映射为电梯动作。

多台电梯、多个目标户、分支路线和多目标批次在第一期必须明确拒绝，并给出可操作诊断；不得任选组件或按画布顺序猜测。

## 5. 电梯几何与方向规则

一个 `elevator_id` 相同的电梯组件集合表示同一物理电梯。每个参与地图必须恰有一个该电梯组件。

- 电梯组件的现有 `yaw`/门向标识定义门外法线；编译器与画布使用同一套坐标转换，不能出现显示门向和生成点位相反的情况；
- 入梯点位于电梯组件中心；
- 候梯点/出梯点位于门外，距门面固定 `1.5 m`；即中心沿门向外法线移动“组件门向半尺寸 + 1.5 m”；
- 车辆进入电梯时车头指向门内；
- 从电梯倒退驶出时保持该车头朝向，使用 `backward`，即运动方向与车头相反；
- 跨图后 `SetUseWheelOdom` 的 `x/y/yaw` 从目标地图对应电梯组件的中心坐标和入梯车头朝向生成；
- 所有派生点都要落在对应地图边界内。候梯点落在地图外、与另一个同类组件冲突或电梯配对不完整，都必须阻止导出。

候梯距离在电梯组件属性中持久化，默认值为 `1.5 m`，允许在真实通道受限时调整；范围和最小安全值在实施时以测试覆盖的后端校验固定。

## 6. 两图往返子任务蓝图

以下序列以目标地图实例的 `building/unit/floor`、目标组件的 `door` 和项目的 `community` 生成任务文件名与 `GetTaskTargetInfo` 上下文。

| 顺序 | 子任务 | 到达点 | 到达前速度模式 | 到达后行为树 |
| --- | --- | --- | --- | --- |
| 1 | 大厅去程 | 起点 | `task_point` | `start_task` |
| 1 | 大厅去程 | 首层候梯点 | `single_point` | `{building}_{unit}_elevator_in_n_x` |
| 1 | 大厅去程 | 首层电梯中心 | `elevator_in` | `{building}_{unit}_elevator_out_n_x` |
| 2 | 目标层去程 | 目标层候梯/出梯点 | `backward` | `{building}_{unit}_close_elevdoor_x` |
| 2 | 目标层去程 | 目标点 | `single_point` | `place_water` |
| 3 | 目标层返程 | 目标点返程起点 | `single_point` | 无附加行为树 |
| 3 | 目标层返程 | 目标层候梯点 | `task_point` | `{building}_{unit}_elevator_in_x_n` |
| 3 | 目标层返程 | 目标层电梯中心 | `elevator_in` | `{building}_{unit}_elevator_out_x_n` |
| 4 | 大厅返程 | 首层候梯/出梯点 | `backward` | `{building}_{unit}_close_elevdoor_n` |
| 4 | 大厅返程 | 起点 | `single_point` | `task_complete` |

`speed_mode` 的语义严格为“从上一点到当前点”的运动控制策略；它不等价于该点到达后的行为树。第一条记录没有运动段，但保留已批准的稳定值以维持任务执行器兼容。

任务 JSON 必须复用样例的字段形状：顶层 `task_group_name` 与 `subtasks`，子任务中的 `change_loc/map_url/pcd_url/subtask_name/waypoints`，以及路点中的 `waypoint_task_id/is_task_point/speed_mode/is_backward/is_single_point/pose/waypoint_id`。位姿写为标准四元数。

## 7. 受控 XML 生成

每个导出站点生成一个独立 `waypoint_tasks/<site-id>/` 目录：

- `start_task.xml` 使用已确认的室内启动语义：`SetUseWheelOdom use_wheel_odom="true"`；
- `{building}_{unit}_elevator_in_n_x.xml`：`origin_floor` 写大厅电梯的物理楼层；
- `{building}_{unit}_elevator_out_n_x.xml`：写大厅物理楼层，切换到目标图并引用目标图定位 YAML；
- `{building}_{unit}_close_elevdoor_x.xml`：复用已确认目标层关门语义；
- `{building}_{unit}_elevator_in_x_n.xml`：`origin_floor` 写目标楼层电梯的物理楼层；
- `{building}_{unit}_elevator_out_x_n.xml`：写目标物理楼层，切换到大厅图并引用大厅定位 YAML 与自动派生重定位位姿；
- `{building}_{unit}_close_elevdoor_n.xml`：写大厅物理楼层；
- `task_complete.xml` 复用已确认完成语义。

XML 是由版本化模板作受限替换得到，不执行任意模板、命令、脚本或用户输入的 XML 片段。所有替换值必须经过 XML 转义、数值范围校验和受控路径校验。

## 8. 定位 YAML 生成

每张任务地图在导出包中拥有一个独立 YAML，例如：

`localization/rycx_loc_livox_{building}_{unit}_{stage}.yaml`

YAML 的源模板由编译器配置中指向的、版本化的批准基线快照提供。只允许替换 `system.map_path` 为该任务地图 `map_url` 的父目录。生成器不得隐式读取或复制当前运行中的定位配置。

## 9. 用户体验与存储

部署页在地图与组件满足基础条件后显示“任务编译预览”区域：

- 以只读时间线显示子任务及每个派生路点的来源组件、坐标、朝向、速度模式和行为树；
- 以阻断错误/非阻断警告分开展示，说明如何恢复；
- 提供 JSON、XML、YAML 与编译清单的下载入口；
- 明确标记“实验产物，尚未安装到机器人”；
- 保存编译快照和输入指纹，用户切页后仍能恢复预览；输入变更后使旧快照过期，不能误下载为最新结果。

正式界面不出现人工创建路线、交接点、子任务排序的控制；这不改变既有 API 或历史项目数据。

## 10. 数据/API 边界

实现会把项目任务身份、受控编译配置和编译快照写入 `SiteProject`，并采用显式 schema 迁移。新增 API 仅用于：预检、生成预览、读取导出快照和下载实验产物。

浏览器不访问 ROS、地图文件系统或行为树目录。所有路径解析、输入校验、模板替换和文件生成由 Backend 在项目导出根内完成。跨端 API 契约改变前必须更新 `shared/contracts/` 的消费者与影响记录；Mobile 不改动。

## 11. 校验与测试

测试必须覆盖：

- 高科一号样例的四子任务结构、速度模式顺序、XML 名称和地图顺序；
- 门向旋转四个象限时的候梯点、中心点、入梯/倒车朝向；
- `1.5 m` 候梯距离和地图边界拒绝；
- 电梯 ID 配对、楼层/单位/目标门牌/起点/目标缺失；
- 单电梯、单起点、单目标限制；
- XML 中 `origin_floor`、`SwitchMap`、定位 YAML 和重定位位姿替换；
- YAML 仅修改 `system.map_path`，模板散列可追溯；
- 路径遍历、非法 XML 字符、无效四元数、导出目录逃逸；
- 输入变更使旧预览失效；
- 不写运行目录、源任务、源 XML、源 YAML；
- Backend 单元测试和 Web 生产构建。

首个导出包必须逐字段与 `高科一号_1_1_15_1509.json` 及相应 XML/YAML 人工对照，再进入本地任务执行器验证；通过前不宣称可实车部署。

## 12. 非目标

- 自动部署、运行时安装或覆盖文件；
- 自行生成速度模式；
- 猜测室外/大厅过渡的行为树；
- 修改 ROS 控制、安全边界、导航、定位或 Supervisor；
- 修改 Mobile、实时观测、验收、报告或任务执行既有逻辑；
- 用画布绘制顺序、组件标签或默认坐标猜测真实路由。
