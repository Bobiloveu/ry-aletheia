# 行为树状态码注册表设计

**状态：已确认，待实施**\
**日期：2026-09-27**\
**范围：** `indoor_elevator_v1` 的受控行为树、任务编译器和只读车辆执行状态分类；不改变 ROS Topic、任务下发或部署 UI。

## 1. 目标

将最新的任务状态码表收敛到一份可审计 JSON。行为树只在实际行为节点的前后发布对应状态；任务编译器和 `VehicleExecutionStatusMonitor` 从同一注册表读取数值，避免 XML 码值更新后 PC 状态显示仍按旧码解释。

当前消费者为 Backend 编译器、Backend 状态监控器、验收自动返程信号门和 R6B 多点配送事件收集器；PC Web 继续只消费已有的 `{ phase, label }` 快照，不新增 UI 或 API；Mobile 不是该状态配置的消费者。

## 2. 不变边界

- 只生成实验预览 ZIP 中的 XML，不写入机器人运行目录，不发布 ROS 消息，不执行行为树。
- `PublishTaskStatus` 仍由车端行为树发布至既有 `/task_status`；Aletheia 只读取其结果。
- 状态码不从项目表单、组件属性或浏览器请求获得；唯一权威来源为受控模板目录中的 JSON。
- 不为不存在的业务动作伪造状态。当前没有泄水、图片上传、楼栋进出或多点到达行为树，因此 `400–403`、`500`、`600–601`、`700–701` 仅登记在注册表，不插入 XML。

## 3. 注册表

新增 `autodrive_console/task_templates/indoor_elevator_v1/task-status-codes.json`：

```json
{
  "schema": 1,
  "codes": {
    "task_start": 100,
    "outdoor_tasking": 101,
    "indoor_tasking": 102,
    "task_return_waiting": 103,
    "task_complete": 109,
    "elevator_waiting": 200,
    "elevator_in": 201,
    "elevator_taking": 202,
    "elevator_outing": 203,
    "elevator_outed": 204,
    "elevator_arrived": 209,
    "door_waiting": 300,
    "gate_in": 301,
    "gate_out": 302,
    "auto_door_in": 303,
    "auto_door_out": 304,
    "door_waiting_open": 305,
    "door_waiting_close": 305,
    "clamp_water_waiting": 400,
    "clamp_water": 401,
    "place_water_waiting": 402,
    "place_water": 403,
    "photo_upload": 500,
    "building_in": 600,
    "building_out": 601,
    "multi_task_start": 700,
    "multi_task_arrived": 701
  }
}
```

加载器要求 `schema: 1`、全部键完整、数值为三位正整数。重复值只允许已声明的 `door_waiting_open` / `door_waiting_close` 均为 `305`；其他重复值或缺失键阻断编译和状态分类初始化。每次读取重新解析文件，允许受控配置变更在下一次编译/状态查询生效；生成 ZIP 的 manifest 记录该 JSON 的 SHA-256。

## 4. 行为树插入规则

状态发布的位置由 XML 行为节点决定，令牌由编译器替换：

| 模板 | 插入位置 | 令牌 |
| --- | --- | --- |
| `start_task.xml` | `Sequence` 的首个实际运行节点前 | `STATUS_TASK_START` |
| `elevator_in_n_x.xml`、`elevator_in_x_n.xml` | 每次 `ElevatorCaller` 紧前 | `STATUS_ELEVATOR_WAITING` |
| 同上 | `ElevatorCaller` 紧后、开门/进梯确认前 | `STATUS_ELEVATOR_ARRIVED` |
| 同上 | `RetryUntilSuccessful` 成功后 | `STATUS_ELEVATOR_IN` |
| `elevator_out_n_x.xml`、`elevator_out_x_n.xml` | 进入跨层乘梯流程、`RetryUntilSuccessful` 前 | `STATUS_ELEVATOR_TAKING` |
| 同上 | `ElevatorCaller` 紧前/紧后 | `STATUS_ELEVATOR_WAITING` / `STATUS_ELEVATOR_ARRIVED` |
| `close_elevdoor_n.xml`、`close_elevdoor_x.xml` | `ElevatorDoorKeeper` 紧前/紧后 | `STATUS_ELEVATOR_OUTING` / `STATUS_ELEVATOR_OUTED` |
| `gate_open_*` | `DoorControl executeid="2"` 紧前/重试成功后 | `STATUS_DOOR_WAITING` / `STATUS_GATE_IN` |
| `gate_close_*` | `DoorControl executeid="3"` 紧前/重试成功后 | `STATUS_DOOR_WAITING` / `STATUS_GATE_OUT` |
| `auto_door_open_*` | `DoorControl executeid="2"` 紧前/重试成功后 | `STATUS_DOOR_WAITING` / `STATUS_AUTO_DOOR_IN` |
| `auto_door_close_*` | `DoorControl executeid="3"` 紧前/重试成功后 | `STATUS_DOOR_WAITING` / `STATUS_AUTO_DOOR_OUT` |
| `task_complete.xml` | 完成 Sequence 中 | `STATUS_TASK_COMPLETE` |

这里“紧前/紧后”指同一个 `Sequence` 的相邻兄弟节点；不得在 `GetTaskTargetInfo`、地图切换、`ChangeUssStatus` 或不包含设备调用的树中插入状态码。

## 5. 编译与状态监控

新增纯 Python 注册表模块，暴露：

```python
def task_status_codes() -> dict[str, int]: ...
def task_status_code(name: str) -> str: ...
def task_status_xml_values() -> dict[str, str]: ...
def task_status_phase_by_code() -> dict[str, str]: ...
```

编译器对所有基础 XML 与组件 XML 合并 `task_status_xml_values()`；任一遗留硬编码 `status_code="数字"` 均视为不合规。状态监控分类器从 `task_status_phase_by_code()` 生成正式事件码到既有 phase 的映射：

- `task_complete → completed`；
- `elevator_waiting/in/taking/outing/arrived → calling_elevator/entering_elevator/riding_elevator/exiting_elevator/riding_elevator`；
- `gate_in/gate_out → opening_gate/closing_gate`；
- `auto_door_in/auto_door_out → opening_access_door/closing_access_door`；
- `clamp_water_*`、`place_water_* → draining_or_unloading`；
- 其余已登记但没有独立 PC phase 的码 → `task`。

`elevator_outed` 在当前稳定 phase 集合中映射为 `task`，不扩展公共 API 枚举；在其后若导航仍处于出梯物理速度段，既有运动优先级继续显示 `exiting_elevator`。

自动返程信号门使用 `task_status_code("task_return_waiting")` 判断返程等待事件；R6B 多点收集器使用 `task_status_code("multi_task_arrived")` 判断配送点抵达事件。它们不发布、不改写任何状态，只跟随同一 JSON 的当前数值；配置读取失败时保守地拒绝该事件，绝不误发返程或误将配送点判为通过。

## 6. 错误与兼容

- JSON 无法读取、未知 schema、缺键、非整数、非法范围或未批准重复值时，任务预览以受控错误阻断；状态监控保留上一次成功加载的映射，首次加载失败则退化为现有文件名语义和通用任务状态，不把车辆报为不可用。
- 已导出的 XML 和运行中的任务不会被改写；重新生成预览/导出才使用新码。
- 状态码 JSON 变更会改变编译输入 SHA 与 manifest 中的配置 SHA，确保产物可追溯。

## 7. 验收

- 每棵当前 XML 模板在 XML 结构解析后只在上表指定节点的相邻位置出现所需状态令牌；无关树没有额外 `PublishTaskStatus`。
- 编译后 XML 没有未替换的 `STATUS_*` 令牌，也没有硬编码状态数字；各 XML 使用 JSON 当前值。
- 修改测试副本 JSON 中 `gate_in`、`auto_door_out`、`elevator_waiting` 后，重新编译 XML 与状态分类器同时使用新码。
- 无效配置阻断编译；运行监控的首次/热加载失败遵循第 6 节的安全降级。
- 运行 `scripts/test-backend.sh`、`scripts/test-web.sh`；Web 不因该后端协议变更改动页面结构。
