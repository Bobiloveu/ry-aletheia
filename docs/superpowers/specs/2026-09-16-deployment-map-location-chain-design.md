# 部署建图定位链路与地图原点设计

**状态：** 已确认设计，待实施  
**范围：** PC 部署建图、实验定位部署包和 `loc_yaml_path.json`；不改变现有机器人运行时、ROS、Supervisor、Mobile 或已批准的室内两图任务编译器。

## 1. 目标与工程语义

部署包必须从项目受控快照派生多地图定位清单与电梯 ID 清单，使正向、返程的每次切图都有确定的重定位位姿，并使下游电梯组件取得同一份楼栋/单元归属事实。地图类型不定义路线顺序：`ferry` 是可选地图类型，可出现在首图之前、户外图与大厅图之间或任何中间位置；用户楼层 `floor` 是一条定位路线的最后一张地图。

每张地图 YAML 的 `origin: [x, y, yaw]` 是该地图的定位原点事实。它在画布中可见，并作为除首图外每张地图的 `init_go`。它不是默认的人工任务起点。

一条路线的语义如下：

```text
首图：人工任务起点 → 首图 init_return（切图锚点）
后续中间图：YAML origin = init_go → 本图 init_return（切图锚点）
末图（floor）：YAML origin = init_go → 人工任务终点
```

正向由前图的切图锚点切到后图，并以目标图 YAML `origin` 重定位。返程反向切图：从后一张图返回此前图时，以此前图的 `init_return` 重定位。因此中间图的 `init_return` 是该图的前向切图锚点，也是返程重新进入该图的定位点。

最后一张用户楼层图没有后续图时，它的 `init_return` 对地图切换没有作用。为了保持 `loc_yaml_path.json` 的字段完整，导出时使用人工任务终点；部署人员也无需额外设置一个无意义的末图返程位。

## 2. 选择的架构

采用**独立、显式的定位路线链**，而不是从 `outdoor / indoor / ferry / floor` 类型或现有 `map_transitions` 推断顺序。

这优于两种替代方案：

1. 固定类型顺序：无法表达摆渡层任意插入，且会将项目命名习惯误当成运行事实。
2. 继续复用现有 `map_transitions`：其服务于旧任务编译器的阶段模型，当前只允许相邻阶段；放宽它会改变既有编译语义并造成回归风险。

现有 `map_transitions`、`map_instances`、路线、组件和实验室内两图任务编译器保持原样。新路线只服务定位清单导出，因而不会把“可导出定位资料”误报为“已支持所有多地图任务执行”。

## 3. 项目数据模型

保留 `localization_bindings` 作为“项目地图 + 楼栋/单元 + 类型/楼层模板”的身份绑定，但不再持久化手填的 `init_go` 和 `init_return` 坐标。新增项目级 `localization_routes`；每条路线只属于一个 `{building, unit}`：

```json
{
  "id": "localization-route-…",
  "building": "3",
  "unit": "1",
  "binding_ids": ["binding-outdoor", "binding-lobby", "binding-floor"],
  "task_start_waypoint_id": "waypoint-start",
  "task_target_waypoint_id": "waypoint-target",
  "links": [
    {
      "from_binding_id": "binding-outdoor",
      "to_binding_id": "binding-lobby",
      "anchor": {"kind": "waypoint", "waypoint_id": "waypoint-outdoor-exit"}
    },
    {
      "from_binding_id": "binding-lobby",
      "to_binding_id": "binding-floor",
      "anchor": {"kind": "component_center", "component_id": "component-elevator"}
    }
  ]
}
```

约束如下：

- `binding_ids` 是无分支、有顺序且不重复的单链；首图可为 `ferry`、`outdoor`、`indoor` 或其他已批准绑定，末项必须为 `floor`。
- 路线和所引用的绑定拥有同一楼栋、单元；地图、航点、组件必须属于当前项目且位于正确地图上。
- `task_start_waypoint_id` 必须在首图；`task_target_waypoint_id` 必须在末图。它们是人工部署点，绝不被 YAML `origin` 覆盖。
- 每对相邻绑定恰有一条 `link`。锚点可引用人工标记的 `waypoint`，或引用已建组件的中心点。
- 电梯锚点必须引用 `elevator` 组件；导出坐标和朝向由该组件中心及 `yaw` 自动派生，页面不允许手填覆盖。门禁、闸机等组件也可作为组件中心锚点；不具备明确中心语义时使用人工 `waypoint`。
- 末图不含出向 `link`。清单中的末图 `init_return` 由 `task_target_waypoint_id` 派生。

绑定中的旧人工初始化位被视为旧格式。读取时保留其原始项目数据以免丢失，但新定位导出不混用旧值；没有完成定位路线迁移的旧项目会得到明确阻断提示，不能悄悄生成错误包。

## 4. 清单派生规则

对一条路线按 `binding_ids` 顺序生成 `yaml_index`。每项的 `yaml`、`2D_yaml`、`community`、`building`、`unit`、`type` 与 `floor`（仅 `floor`）继续由受控运行时布局生成，浏览器不得提交路径。

对第 `i` 项：

| 条件 | `init_go` | `init_return` |
| --- | --- | --- |
| `i = 0`（首图） | `task_start_waypoint_id` 的 `{x,y,0,yaw}` | 第一个出向 `link.anchor` 的派生位姿 |
| `0 < i < last`（中间图） | 当前地图 YAML `origin` 的 `{x,y,0,yaw}` | 当前出向 `link.anchor` 的派生位姿 |
| `i = last`（用户楼层） | 当前地图 YAML `origin` 的 `{x,y,0,yaw}` | `task_target_waypoint_id` 的 `{x,y,0,yaw}` |

`origin` 的第三项 `yaw` 必须保留；缺少或非有限的 `origin` 均阻断导出。所有派生点仍经所属地图边界验证。`init_return` 的命名为既有运行时字段，设计不试图改名或改变下游文件结构。

物理电梯按钮层和 `origin_floor` 的现有零基、跳过按钮 `0` 的规则不变。定位路线只提供“使用哪个电梯组件作为锚点”的明确事实，不能从楼层名称、图类型或按钮范围猜测。

### 电梯 ID 清单

同一部署包还生成 `runtime/lift_id_list.json`，格式固定为：

```json
{
  "community": "高科一号",
  "lifts": [
    {"lift_id": "10044", "building": "1", "unit": "1"}
  ]
}
```

`community` 复用任务编译器已保存的小区名。`lifts` 仅从定位路线实际引用的电梯组件锚点派生：组件关联的 `physical_elevator.elevator_id` 成为 `lift_id`，路线身份提供 `building` 与 `unit`。同一 `{lift_id, building, unit}` 只输出一次并按楼栋、单元、ID 稳定排序；同一 `lift_id` 若在路线中推导出不同楼栋或单元，则认为项目事实冲突并阻断导出，绝不猜测归属。未使用电梯的项目输出空数组，不把项目中闲置的物理电梯误写入运行清单。

## 5. PC 部署建图界面

界面采用既有部署编辑器的 Operate 风格：在当前地图工作区内增加紧凑的“定位路线”区，不另建第二套页面，也不改变现有组件、地图导入、路线或旧 Transition 操作。

### 地图原点

- 导入地图时解析并持久化 YAML `origin` 的三项值。
- 当前地图画布始终绘制一个低干扰的原点十字坐标系：`X`、`Y` 轴及朝向标记随地图坐标变换，不随屏幕旋转；悬浮信息显示精确坐标。
- 原点是只读地图事实，不能拖动或修改。

### 定位绑定与路线编辑

- “导入现有 Lightning 地图”统一改为“导入地图”；导入文案不再把一般地图与 Lightning 绑定。
- 绑定编辑只保留身份字段（楼栋、单元、类型、用户楼层模板）；移除手填/点选 `init_go`、`init_return` 坐标控件。
- 路线编辑按顺序展示地图卡片、人工任务起点、各切图锚点和人工任务终点。每项明确标为“YAML 原点”“人工任务点”或“组件中心自动派生”，派生值只读。
- 只有当前图恰有一个电梯组件时，电梯锚点自动选中；有多个时要求部署人员从已建物理电梯组件中选一个，不根据名称猜测。
- 未配置路线、锚点不完整、地图/组件归属错误、末图非用户楼层或旧格式尚未迁移时，预览区就地显示阻断原因和修正入口。

该区域在窄宽度下折叠为纵向顺序，坐标仍以可复制的只读文本呈现；不会以新增大表单挤压地图画布或原有设置。

## 6. 后端、API 与兼容性

`DeploymentStore` 是路线、绑定归属、地图边界、组件/航点类型和链完整性的权威校验者。Web 仅提交受限 ID、顺序和锚点引用，不提交原始坐标、YAML 路径、地图目录或机器人路径。

新增受控的定位路线集合/项 API，语义与既有绑定 API 一致。绑定 API 改为不接受 `init_go`、`init_return`；返回项目中包含路线及后端派生的只读预览摘要。`compile_location_manifest()` 从路线和快照派生最终位姿，而不是信任浏览器数值。

变更 `shared/contracts/deployment.md`：列出 Backend/Web 消费者、Mobile 不消费的边界、路线 JSON、`loc_yaml_path.json` 与 `lift_id_list.json` 的派生顺序、旧项目阻断迁移行为和受控导出路径。它不会新增 ROS topic、WebSocket 协议或机器人运行时写入。

## 7. 错误处理与安全边界

- YAML 缺少合法三元 `origin`、地图文件不完整、路线断链/成环、跨楼栋单元引用、非末图 `floor`、无效人工点、锚点与所属图不一致、多个电梯未选择、旧绑定未迁移，均阻断预览和下载。
- 仅导出项目快照中的地图、PGM 和批准定位 YAML 模板；产物继续位于项目 `exports/` 的实验包中，`robot_runtime_changed` 保持 `false`。
- 不读取或写入机器人当前位置、定位配置、`/opt/ry` 运行时路径、ROS、Supervisor 或任务下发状态。

## 8. 验证策略

1. **纯函数：** YAML 原点 `{x,y,yaw}` 派生、组件中心位姿、首/中/末图位姿规则、末图 `init_return` 回退任务终点、电梯物理楼层换算。
2. **Store/API：** 路线可含任意位置的 `ferry`，禁止分支/循环/重复绑定，约束首尾任务点、链接锚点、地图归属和多电梯显式选择；旧绑定拒绝新导出而不丢失数据。
3. **清单/包：** 户外→大厅→用户楼层、摆渡→户外→大厅→用户楼层、户外→摆渡→大厅→用户楼层均生成正确的 `init_go` 与 `init_return`；同时验证 `lift_id_list.json` 的小区名、路线电梯去重、稳定排序、跨楼栋/单元冲突阻断，且不写机器人运行时。
4. **Web：** 原点十字绘制、通用“导入地图”文案、绑定表单不再出现初始化位输入、单电梯自动选择、多电梯必选、路线错误可见；既有地图画布、组件、旧 Transition 不回归。
5. **最终检查：** `./scripts/test-backend.sh`、`./scripts/test-web.sh`、`git diff --check`；环境相关改动才运行 `./scripts/doctor.sh --profile backend` 与 `./scripts/doctor.sh --profile web`。
