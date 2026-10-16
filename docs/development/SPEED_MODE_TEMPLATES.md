# 速度模式模板基线

核对日期：2026-10-16。用户指定的后续参考目录为
`/home/bob/Desktop/template/speed_modes`；本文记录该批文件的静态事实与工具当前支持范围。
它不是车端安装清单，也不证明运行中的任务执行器会选择这些树。

## 所有权与当前实现

- Backend 的 `task_compiler.SPEED_MODES` 接受 `normal`、`task_point`、`single_point`、
  `elevator_in`、`backward`、`narrow_point`、`slow_point`。固定线路复用这一输出规则。
- 手动过渡点只接受其中五项，排除受控电梯用的 `elevator_in` 和 `backward`。
  Web 新建默认 `normal`，旧记录/API 缺省仍按 `single_point` 兼容。
- 当前任务条目按 `speed_mode != "normal"` 设置 `is_single_point`；`is_task_point`
  和 `waypoint_task_id` 单独表示动作，不能由速度名称推断。`is_backward` 当前仍输出 false，
  倒车导航由 `backward` 模式表达，不能看到标志为 false 就把模式改掉。
- 设施默认值唯一来源是
  `autodrive_console/task_templates/indoor_elevator_v1/components/component-defaults.json`：
  自动门锁定 `task_point`，闸机锁定 `narrow_point`，窄通道默认 `narrow_point`，
  坡道与慢行区默认 `slow_point`。入站速度附着在到达节点的边，返程按实际反向边派生。
- 工具生成任务 JSON 及取送货、设备、电梯等动作树；本参考目录中的导航速度树没有作为
  运行资源打入部署包。车端执行器负责将模式/单点标志映射到导航 XML，当前缺少其选择逻辑证据。
  Mobile 不消费部署编辑接口；本文更新不改变 HTTP、ROS 或共享模型。

## 参考 XML 的实际配置

下表路径均相对参考目录。“一次+裁剪”指先生成 full_path，跟随失败时重新裁剪同一条
full_path，不代表重新调用全局规划器。规划频率、等待时间都不是视频帧率或车辆线速度。

| 文件 | 规划方式 / planner | controller | goal checker | 末端转向 |
| --- | --- | --- | --- | --- |
| `normal.xml` | 多目标，0.333 Hz / RouteClearance | MppiElevator | general_goal_checker | 无 |
| `high_speed.xml` | 多目标，一次+裁剪 / RouteClearance | GPUMppiHighSpeed | general_goal_checker | 无 |
| `low_speed.xml` | 仅注释，无可执行树 | — | — | — |
| `backward.xml` | 单目标，1 Hz / GridBased | MppiElevatorBackward | 未显式指定 | 无 |
| `taskpoint.xml` | 单目标，一次+裁剪 / RouteClearance | MppiElevator | general_goal_checker | yaw 0.08，避障阈值 0.20 |
| `single_point/single_point.xml` | 单目标，一次+裁剪 / RouteClearance | GPUMppiPerfFast | singlepoint_goal_checker | yaw 0.08，阈值 0.20 |
| `single_point/task_point.xml` | 单目标，一次+裁剪 / RouteClearance | GPUMppiPerfTest | taskpoint_goal_checker | yaw 0.08，阈值 0.08 |
| `single_point/delivery_point.xml` | 单目标，一次+裁剪 / RouteClearance | GPUMppiPerfTest | pointcloud_goal_checker | yaw 0.08，阈值 0.08 |
| `single_point/elevator_in.xml` | 单目标，一次+裁剪 / GridBased | GPUMppiElevatorEntry | elevator_goal_checker | yaw 0.08，阈值 0.01 |
| `single_point/narrow_point.xml` | 单目标，一次+裁剪 / RouteClearanceNarrow | GPUMppiPerfNarrow | general_goal_checker | yaw 0.08，阈值 0.08 |
| `single_point/narrow_follow.xml` | 单目标，一次+裁剪 / RouteClearanceNarrow | GPUMppiElevatorEntry | taskpoint_goal_checker | yaw 0.03，阈值 0.08 |
| `single_point/backward.xml` | 单目标，一次+裁剪 / GridBased | MppiElevatorBackward | general_goal_checker | 节点已注释，不执行 |
| `single_point/taskpoint.xml` | 单目标，1 Hz / GridBased | ElevatorForward | 未显式指定 | 无 |
| `single_point/water_point.xml` | 单目标，一次+裁剪 / RouteClearance | MppiElevator | general_goal_checker | yaw 0.08，阈值 0.20 |

所有裁剪节点的 keep_distance 为 0.3。`normal.xml` 注释写 1 Hz，但有效属性是
0.333 Hz，应以属性为准；外部模板本次没有改写。

`taskpoint.xml` 与 `single_point/taskpoint.xml`，以及 `task_point` 与 `taskpoint`
均不是等价名称。两个 backward 树的重规划与恢复方式也不同，不能仅按 basename 合并。
delivery_point 与 task_point 的有效差异是 goal checker；narrow_follow 与 narrow_point
还在 controller 和转向容差上不同。water_point 跟随恢复次数为 20，并有
`ClearPathAndSuccess` 回退；缺少该自定义节点实现时，不能把回退 SUCCESS 当作已物理到达。

转向树均使用角速度 0.30、最小角速度 0.12、scan_timeout 1、time_allowance 20。
只有根目录 taskpoint 与 water_point 显式指定 `/scan`；其余六份转向树没有指定 scan_topic，
必须核验插件默认值，不能假定使用同一传感器。XML 未提供 controller 的实际线速度、
加速度、代价权重或 goal checker 插件内部配置，不能由名字比较车辆快慢或安全距离。

## 未对齐项与后续接入条件

| 差异 | 当前状态 | 接入前需要核实 |
| --- | --- | --- |
| `slow_point` | 源码已支持，参考目录没有同名 XML | 车端实际映射和有效慢行树；不能用空的 low_speed 替代 |
| `low_speed` | 参考文件只有注释，源码未开放 | 补全有效树及执行器映射后再考虑枚举 |
| `high_speed` | 参考树有效，源码未开放 | 多目标 `{goals}` 与 is_single_point 的分派；直接加枚举会按现有规则变为单点 |
| `delivery_point`、`narrow_follow`、`water_point` | 参考树有效，源码未开放 | 执行器映射、controller/checker 可用性及业务用途；water_point 不等于卸货/泄水动作树 |
| `taskpoint` 与两个 backward 路径 | 存在不同有效实现 | 按完整相对路径核验实际选择，不能自动别名 |
| 自定义节点与控制插件 | 仅有 XML 引用，缺少实现及运行配置 | 核验 PrunePathByRobotPose、RotateToGoalYawWithScan、ClearPathAndSuccess 与各 controller/checker |

后续修改先确认模式到完整 XML 路径的车端映射、单点/多点入口和插件配置，再同步 Backend
枚举、组件策略、Web 选项、契约及定向测试。软件静态验证后仍需现场验证导航、恢复、
到点与转向行为。本次不扩展模式、不改车辆参数，也不自动打包或部署。

## 来源指纹

下表记录原始文件的 SHA-256；外部目录变化时应重新解析并更新证据。

| 相对路径 | SHA-256 |
| --- | --- |
| `backward.xml` | `3bb837e1511de54ebab986df724df881808762acce33c6b91bc1bfcfff7b8786` |
| `high_speed.xml` | `9ea6f27932a8959c7bc9e86136e96ffcb7d936c66d373c7a6b2ac3e950bb8054` |
| `low_speed.xml` | `f423fb5b17ae0eda765a22b4eaedc8d706d1da736838b36e555dcff9ccd6cf60` |
| `normal.xml` | `f1e0ee7225338bf8e0ff5c623c3f34786785d8b8ec9209ad24dfb1c3494c369e` |
| `single_point/backward.xml` | `39dfe3786b7272bf591b39c1725fddb830d96d839802dfd28628a0fee543dac9` |
| `single_point/delivery_point.xml` | `4c387a36d8bb4bda8e4340c76f9702d285b36ebe0e9babe5c4eb4791305ca11b` |
| `single_point/elevator_in.xml` | `5ecb99e022892ca81cb227426301a80d8fc968b83c0b40ddac846568b0cf59cf` |
| `single_point/narrow_follow.xml` | `6bdcf625804e6dc2eb871b7244ca85d4c25eea812a100073996c323a324ea8fe` |
| `single_point/narrow_point.xml` | `54b98c2cb1f8c2e8532ba77b905fb4594ce30ce2f5c57f1fc228465e1ed75730` |
| `single_point/single_point.xml` | `57eaf4050612c240da57f302d6279e6afe261a85753ae76415294f054ab5e56f` |
| `single_point/task_point.xml` | `b85e61430324721c0bf25297d183a8f587d7f1ea3c35bbd86862e061fcb71331` |
| `single_point/taskpoint.xml` | `3ca578860feca015651c8d54f37e92434d6b88cce3946d0d527b99c2aee1e6ca` |
| `single_point/water_point.xml` | `7e5a5134bb0526843da3d95febd32125366c470ee1c8ed96d53bf9fd37695752` |
| `taskpoint.xml` | `477d37fadae4fc525bb7002c9d3edda73302bbc67f0c62b3a812cd67ddceaa3e` |
