# 部署验收自动返程设计

**状态：** 已实施，待现场 ROS 联调
**范围：** 仅 PC 部署验收；Mobile 不是消费者。

## 目标

部署验收可由操作员选择“自动返程”。选中的计划在用户楼层泄水完成并进入任务协议的等待返程状态时，由 Backend 发布一次既有 ROS Topic `/start_return` 的 `std_msgs/msg/Bool(data=true)`，免除现场人员跟车手工执行 CLI。

## 触发与安全边界

- 触发的唯一依据是 `master_interfaces/TaskStatus.status_code == "103"`。源码状态码表将它定义为 `TaskReturn_Waiting`；不得通过 `400`–`403`、任务名称、路径 XML、延时或 UI 状态推断。
- 开关默认关闭，作为计划冻结字段保存；未勾选的新计划、所有历史计划和普通自动化测试保持原行为。
- 每个验收子任务在下发任务服务前才被 armed，并在任务服务返回后立即撤销资格；该子任务收到第一个 `103` 时最多发布一次。重复 `103`、非 `103`、未 armed、任务已返回和序列结束后的消息均不得发布。
- 浏览器只向既有验收创建 API 提交布尔值，绝不直接访问 ROS、选择 Topic 或构造消息。Backend 固定 Topic、固定消息类型和固定 `true` 值。
- 启用自动返程但无法初始化 Backend ROS 监听/发布器时，计划开始失败且不下发任务。ROS 发布调用异常只记录受控错误日志，绝不虚报“已发送”。ROS 发布本身没有订阅端确认语义，因此页面只能表述“已下发返程信号”。

## 数据与 API

`execution_preflight` 扩展一个冻结字段 `automatic_return: bool`，并以计划 schema 4 持久化。读取 schema 1–3 时补为 `false`，因此历史计划不会获得新的控制策略。公开计划响应只提供 `automatic_return_enabled: bool`，不公开 Topic、消息类型、节点、订阅状态或 ROS 细节。

`POST /api/acceptance/plans` 增量接受 `use_automatic_return: boolean`；其他类型和未知字段均拒绝。开始计划继续经既有 `AcceptanceOrchestrator → RunManager`，不新增浏览器控制 API。

## 后端结构

`ReturnSignalGate` 是纯 Python、线程安全的一次性门：它为一个当前子任务处理状态码并只在 armed 的首个 `103` 返回触发许可。`RosReturnSignalBridge` 拥有单独、短生命周期的 ROS 节点、`/task_status` 订阅和 `/start_return` 发布器；它只把原始状态码交给 Gate，并在获准时发布 `Bool(data=True)`。桥接器由 `RunManager` 仅在启用的验收序列中创建，序列结束时无条件停止；普通测试不创建它。

## 界面

“自动返程”只作为现有“可选运行准备”折叠区中的一个复选项，说明为“泄水完成后进入等待返程时，自动下发返程信号。”冻结计划在既有冻结摘要中显示“自动返程：启用/不启用”。不新增卡片、模态框、动画、颜色或独立操作按钮。

## 验证

1. 计划模型/编排测试：输入布尔值被冻结、历史 schema 默认关闭、错误类型拒绝、公开响应不泄露 ROS 实现。
2. ReturnSignalGate 测试：只接受 armed 的 `103`，每个任务仅一次，重新 arm 的下一任务可再一次。
3. RunManager 测试：仅启用计划创建 bridge、每个子任务 arm、finally 停止；普通测试和关闭选项不创建 bridge。
4. Web 测试：请求载荷携带布尔值，冻结摘要正确，旧页面模块继续可解析。
5. 更新 `shared/contracts/task_execution.md` 的消费者、固定控制边界和验证范围；运行 `scripts/test-backend.sh`、`scripts/test-web.sh`、`git diff --check`。
