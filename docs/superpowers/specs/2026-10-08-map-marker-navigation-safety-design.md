# 受控地图标记导航安全收敛设计

**日期：** 2026-10-08\
**状态：** 已确认，待按实施计划落地

## 背景

PC 实时观测允许操作员让空闲车辆前往当前严格验证地图中的手动标记。现有 `MapMarkerNavigationController` 在 HTTP 请求线程发送 Goal、在独立线程等待结果，并在浏览器轮询状态时才检查超时和安全前提。这样会让同一 ROS node 被多个线程 `spin_until_future_complete`，也会让关闭页面或停止轮询后失去超时和安全监控。

现有手动控制把首次确认的 `/is_emergency_stop=false` 长期视为正常。Topic 在底盘重启、DDS 连接异常或锁存状态过期后不再能证明车辆仍处于可运动状态，不能继续作为无限期的安全许可。

## 目标与边界

- 后端持续拥有且监控每个地图标记 Nav2 Goal；浏览器页面、轮询和网络连接均不影响安全取消。
- 单个 ROS worker 独占 Nav2 node 与 executor，串行执行 Goal、结果和取消；HTTP 线程、监控线程和回调线程均不直接 spin ROS node。
- 地图变更、定位异常、急停不正常或不新鲜、控制源变化、手动/重定位占用、活动运行或 300 秒超时，都应请求取消当前 Goal。
- 取消请求后保持车辆互锁，直至收到 Nav2 终态；取消请求无法确认时，记录清晰的受控故障并继续阻止任务运行、手动控制和重定位，绝不把 Goal 当作已停止。
- 手动会话或非零 `/cmd_vel_miniapp` 输出只在新鲜确认的急停状态为 `false` 时允许；确认过期或轮询服务持续不可用时立即清空目标并 STOP。
- 冻结的 onefile 构建显式验证、收集并在启动期可导入 `nav2_msgs`。不扩大 ROS、导航、速度、控制源或浏览器权限。

本次不改变地图标记持久化、坐标输入、任务执行协议、Mobile UI、Nav2 行为树、速度或机器人安全边界；Mobile 仍不是地图标记导航 API 的消费者。

## 架构

### 单一 Nav2 Action worker

新增 `_RosNavigateToPoseWorker`，在第一次 `start()` 时创建唯一的 ROS node、`ActionClient` 和 executor 线程。它的命令队列是唯一可调用 `send_goal_async`、`get_result_async` 与 `cancel_goal_async` 的位置；worker 线程以 `spin_once` 驱动 executor，并将 Goal 接受、结果和取消响应转换为线程安全的控制器事件。控制器只通过 `request_goal(...)`、`request_cancel(reason)` 和 `close()` 与 worker 交互，不能取得 ROS handle 或调用 spin。

一个 Goal 从 `checking` 进入 `navigating`。安全拒绝、操作员取消或时限到达时进入 `cancelling`，但仍保持 Goal 所有权和互锁。只有 worker 收到 Nav2 最终 result，才进入 `succeeded`、`cancelled` 或 `failed`。取消 RPC 异常、未接受或在有界确认窗口内没有终态时进入 `cancellation_unconfirmed`；该状态会写入工具日志、保留故障原因并继续互锁。控制台关闭时先请求取消、停止 worker 的接收循环并在有界等待后销毁 node；不能把 node 销毁表述为 Nav2 已完成取消。

### 不依赖浏览器的安全监控

`MapMarkerNavigationController` 在启动后创建一个后台监控循环，固定每 200 ms 检查当前 Goal。每轮使用既有 fail-closed 检查：无活动测试/验收运行，真实控制源为 `navigation` 且无切换，未占用手动会话和重定位，定位为 `normal`，急停为新鲜 `normal`，并且激活的手动地图身份仍通过 `ObservationManager.verify_active_manual_map_id()`。监控器自己检查 300 秒期限并调用 worker 的取消请求；HTTP `GET` 只返回快照，不能触发或延后安全检查。

`blocks_runs()` 和给 `VehicleControlController` 的 guard 在 `checking`、`navigating`、`cancelling` 与 `cancellation_unconfirmed` 均返回 true。操作员不能以第二个 begin、取消按钮、切换手动控制、重定位、创建测试或部署验收运行绕过未确认取消。任何后续 Nav2 终态会将状态明确收敛为终态；在此之前，受控故障是唯一安全表示。

### 急停状态新鲜度

`VehicleControlController` 记录 Topic 或 `/get_emergency_stop` 成功反馈的单调时间、当前轮询 in-flight 状态和连续服务失败次数。`VehicleControlConfig` 增加固定的确认新鲜度窗口、重查间隔、服务响应期限与最大连续失败次数，均不可由 HTTP 客户端覆盖。

启动仍可使用服务填补 `unknown`，但不再因为已有 `false` 跳过服务查询。存在手动会话、正在切换至 `miniapp`、重定位占用或任何非零运动目标时，控制器以受限的异步服务请求保持确认。一次 `true`、无效值、确认窗口超时或超过连续失败阈值都会原子地置为 `unknown`/`triggered`，清空目标并发布既有三帧 STOP。服务反馈只有在请求代际仍匹配、未超过响应期限且不与更晚 Topic 反馈冲突时才可更新状态。`status()` 的 `emergency_stop` 增量返回确认新鲜度和受控诊断；`manual_ready` 及地图标记导航只接受新鲜 `normal`。

不能连续确认急停状态的旧车在这类占用期间会保持 `unknown`，因此不能开始或维持运动/导航。这是明确的安全兼容性要求，不为旧行为提供无限期 `false` 的降级通道。

### 打包和 API 兼容性

现有地图标记 REST 路径和请求体保持不变。快照可以增量返回 `cancellation_unconfirmed` 与相关 `detail`；PC 前端继续以 `can_cancel` 驱动取消按钮，但只在 `navigating` 时显示可取消，`cancelling` 和未确认取消显示不可操作的受控状态。Mobile 不调用、展示或依赖这些字段。

`build_binary.sh` 在构建 ROS 环境后显式导入 `nav2_msgs.action`，PyInstaller 收集 `nav2_msgs` 及依赖 action 类型支持，并将 `nav2_msgs` 纳入受控 ROSIDL 动态库收集。`ros_runtime_interfaces.py` 允许从已 source 的 `AMENT_PREFIX_PATH` 解析运行所需的 Nav2 Python 接口，仍不得从任意系统路径加载未声明的车辆接口。

## 验证

- 单元测试证明 Nav2 worker 没有跨线程 spin，并序列化 Goal、cancel 与终态；Worker 的取消未确认会保持互锁。
- 控制器测试在不调用 `status()`、不执行浏览器轮询的情况下，监控循环会因超时或安全状态变化取消 Goal。
- 车辆控制测试覆盖正常确认过期、服务连续失败、过期服务回调、未知状态的 STOP 以及恢复为新鲜确认后才重新解锁。
- 打包/运行时 hook 测试覆盖 `nav2_msgs` 导入、收集参数和受控搜索路径。
- 更新 `shared/contracts/realtime_observation.md`、`robot_control.md` 与 `task_execution.md`，注明 Backend 与 PC Web 已同步、Mobile 无消费者；执行 Backend 和 Web 定向检查。实车 Action 仍需由操作员在空闲、安全地图上验证。
