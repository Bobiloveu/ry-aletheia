# 受控地图标记导航安全收敛 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让后端独立于浏览器持续、安全地拥有地图标记 Nav2 Goal，并用新鲜的急停确认保护手动运动和自动导航。

**Architecture:** `MapMarkerNavigationController` 只维护受控状态机和 200 ms 安全监控；新的单线程 ROS Action worker 独占 node/executor，并串行处理 Goal、取消和结果。`VehicleControlController` 以有期限的 Topic/服务确认维护急停状态，确认失效即 STOP。现有 REST 路径保持兼容，契约增量描述新的取消未确认状态。

**Tech Stack:** Python 3.10、rclpy、`nav2_msgs.action.NavigateToPose`、pytest、Node test、PyInstaller、Pixi。

**Spec:** `docs/superpowers/specs/2026-10-08-map-marker-navigation-safety-design.md`

## Global Constraints

- 浏览器和 Mobile 绝不直接调用 ROS、发布 `/goal_pose` 或 Twist，不能指定坐标、速度、Action 或行为树。
- 地图、控制源、急停、定位、手动/重定位占用、活动测试任一条件失效时 fail closed；不切换到 `miniapp`，不发布 Twist，不自动重试 Nav2 Goal。
- 取消只使用当前 Goal 的 Nav2 cancel；仅终态确认后才解除导航互锁。`cancellation_unconfirmed` 继续阻止运行、手动控制和重定位。
- 急停 `false` 必须在有手动会话、重定位占用、控制源切换或非零目标时保持新鲜；过期或达到服务失败阈值必须 STOP 并变为 `unknown`。
- 地图标记 API 是 PC Web 增量消费者；Mobile 不消费或展示它。同步更新三份 Existing 契约，只运行 Backend 与 Web 检查。
- 当前工作区已有用户未提交改动。只编辑本计划文件列出的路径，不暂存、还原、格式化或提交无关文件。

---

## File Structure

| 文件 | 职责 |
| --- | --- |
| `autodrive_console/map_marker_navigation.py` | 受控导航状态机、200 ms 监控和唯一 ROS Action worker。 |
| `autodrive_console/vehicle_control.py` | 急停确认新鲜度、异步轮询、过期 STOP 和手动许可。 |
| `web_console.py` | 控制器受控关闭，保留既有 API 映射。 |
| `frontend/src/liveObservation.js` | 显示 `cancelling` / `cancellation_unconfirmed`，不把轮询当作安全机制。 |
| `build_binary.sh`、`packaging/runtime_hooks/ros_runtime_interfaces.py` | 验证并封装 Nav2 Python/ROSIDL 接口。 |
| `tests/test_map_marker_navigation.py` | worker 串行性、后台取消、未确认取消和关闭测试。 |
| `tests/test_vehicle_control.py` | 急停新鲜度、请求超时、失败阈值及 STOP 测试。 |
| `tests/test_runtime_interface_hook.py`、`tests/test_offline_modules.py` | 打包接口与共享契约回归。 |
| `shared/contracts/{realtime_observation,robot_control,task_execution}.md` | 状态、所有权、消费者和互锁事实。 |

### Task 1: 记录并锁定跨端安全契约

**Files:**
- Modify: `shared/contracts/realtime_observation.md`
- Modify: `shared/contracts/robot_control.md`
- Modify: `shared/contracts/task_execution.md`
- Modify: `tests/test_offline_modules.py`

**Interfaces:**
- Produces: `checking|navigating|cancelling|cancellation_unconfirmed|succeeded|cancelled|failed` 的公共语义。
- Produces: Backend + PC Web 为消费者、Mobile 为非消费者，以及取消未确认时的三方互锁规则。

- [ ] **Step 1: 写出会失败的契约断言。** 在 `tests/test_offline_modules.py` 读取三份 Markdown，断言存在 `cancellation_unconfirmed`、200 ms 后端监控、300 秒上限、急停新鲜度、Mobile 非消费者和取消互锁文字。

- [ ] **Step 2: 运行定向 RED。** 运行 `pixi run python -m pytest tests/test_offline_modules.py -k map_marker_navigation -v`；预期当前契约缺少至少一个新状态或后端轮询约束。

- [ ] **Step 3: 只增加事实性契约。** 在实时观测契约定义 GET 快照的增量 phase 与 `can_cancel`；在机器人控制契约定义 worker 的唯一 Nav2 所有权、取消未确认互锁及急停新鲜度；在任务执行契约定义 RunManager 在四个进行/故障阶段均拒绝新运行。标注 Backend/Web 定向验证，Mobile 无消费者。

- [ ] **Step 4: 验证 GREEN。** 重跑步骤 2 的命令，预期 PASS。

### Task 2: 用测试固定急停确认的时限语义

**Files:**
- Modify: `tests/test_vehicle_control.py`
- Modify: `autodrive_console/vehicle_control.py`

**Interfaces:**
- Produces: `VehicleControlConfig.emergency_confirmation_max_age_s`、`emergency_query_interval_s`、`emergency_query_timeout_s`、`emergency_query_failure_limit`。
- Produces: 状态内受控的急停确认时龄/诊断；`manual_ready` 只在新鲜 `normal` 时为真。

- [ ] **Step 1: 先添加四个失败测试。** 用现有 fake clock/client 覆盖：(a) 已确认 `false` 在有 active session 时到期会清空目标并发布 STOP，(b) 连续服务失败达到阈值会变 `unknown`，(c) 超过请求期限的旧 future 回调不能把状态恢复为 normal，(d) 新鲜 service `false` 才能在未知后恢复 `manual_ready`。每个测试还断言 `emergency_stop.state` 和 stop burst 的实际值。

- [ ] **Step 2: 运行 RED。** 运行 `pixi run python -m pytest tests/test_vehicle_control.py -k 'emergency and (fresh or expiry or query)' -v`；预期现有无限期 `false` 行为导致断言失败。

- [ ] **Step 3: 实现最小的新鲜度状态机。** 在控制器锁中保存最后确认时间、查询代际、发起时间和失败次数；当存在会话、重定位、miniapp 切换或非零目标时，按间隔发起单个异步服务请求。仅接受未过期且仍匹配的结果。`_advance_safety_locked()` 统一处理确认过期和失败阈值：清空运动、锁存 STOP、将状态置 `unknown`，且不允许旧回调撤销较新的 Topic/服务状态。

- [ ] **Step 4: 运行 GREEN 与已有急停回归。** 先重跑步骤 2，再运行 `pixi run python -m pytest tests/test_vehicle_control.py -v`；预期全部通过。

### Task 3: 以单一 worker 取代跨线程 Nav2 spin

**Files:**
- Modify: `tests/test_map_marker_navigation.py`
- Modify: `autodrive_console/map_marker_navigation.py`

**Interfaces:**
- Produces: `_RosNavigateToPoseWorker.start()`、`request_goal(frame_id, x, y, yaw, callbacks)`、`request_cancel(reason)`、`close()`；worker 是唯一的 ROS node/executor 所有者。
- Produces: transport 事件 `goal_accepted`、`goal_rejected`、`result(status)`、`cancel_unconfirmed(reason)`，不向 HTTP 线程暴露 ROS handle。

- [ ] **Step 1: 添加 worker 的失败测试。** 使用最小 fake rclpy/action client 验证 Goal、cancel 和 result 都在 worker 命令循环运行；测试不得调用两个 `spin_until_future_complete`。覆盖 goal 拒绝、cancel RPC 异常和关闭时销毁 node。断言 controller 在 cancel 后仍为 `cancelling`，不能立即回到可开始状态。

- [ ] **Step 2: 运行 RED。** 运行 `pixi run python -m pytest tests/test_map_marker_navigation.py -k 'worker or cancel' -v`；预期现有 transport 在请求和结果线程分别 spin node，且 cancel 同步返回。

- [ ] **Step 3: 实现 queue 驱动 worker。** 把 `_RosNavigateToPoseTransport` 替换为单 node/executor worker：其线程创建 node、等待 server、发送 Goal、登记 result/cancel future，并用 `spin_once` 与 FIFO 命令队列推进状态。`close()` 先请求有界 cancel，再停 executor 和销毁 node；异常只转换为受控错误文本并写日志。

- [ ] **Step 4: 验证 worker GREEN。** 重跑步骤 2，预期 PASS；再运行 `pixi run python -m pytest tests/test_map_marker_navigation.py -v`。

### Task 4: 让后端自行持续监控并锁住未确认取消

**Files:**
- Modify: `tests/test_map_marker_navigation.py`
- Modify: `tests/test_vehicle_control.py`
- Modify: `autodrive_console/map_marker_navigation.py`
- Modify: `autodrive_console/vehicle_control.py`
- Modify: `web_console.py`

**Interfaces:**
- Produces: `MapMarkerNavigationController.close()` 与 200 ms 生命周期监控。
- Produces: `cancellation_unconfirmed` 持久互锁，`blocks_runs()` 对 `checking`、`navigating`、`cancelling`、`cancellation_unconfirmed` 返回 true。

- [ ] **Step 1: 添加不经浏览器 GET 的失败测试。** 使用可控 clock/event 测试让 Goal 开始后不调用 `status()`；改变 control source、地图校验、定位或推进到 300 秒，断言 worker 收到一次 cancel。再测试 cancel 没有终态直到确认期限：phase 必须为 `cancellation_unconfirmed`、`can_begin/can_cancel` 均 false、`blocks_runs()` true，VehicleControl 的 guard 拒绝手动会话与重定位。

- [ ] **Step 2: 运行 RED。** 运行 `pixi run python -m pytest tests/test_map_marker_navigation.py tests/test_vehicle_control.py -k 'background or unconfirmed or safety_loss' -v`；预期目前只有 `status()` 驱动检查且取消后直接失败。

- [ ] **Step 3: 实现后台监控和终态收敛。** Goal 被 worker 接受时启动 daemon monitor；每 200 ms 在锁外执行既有安全/地图检查，再在锁内按 generation 确认当前 Goal。发生拒绝或超时时提交一次 cancel 并记录原因。只有 Nav2 result callback 终结状态；取消确认窗口超过后进入 `cancellation_unconfirmed` 并保留 guard。将 `MapMarkerNavigationController.close()` 接入 `_close_console_resources()`，在车辆控制资源关闭前先请求导航回收。

- [ ] **Step 4: 验证 GREEN。** 重跑步骤 2 的测试，再运行 `pixi run python -m pytest tests/test_map_marker_navigation.py tests/test_vehicle_control.py -v`。

### Task 5: 保持 PC 可见、但不赋予浏览器安全职责

**Files:**
- Modify: `frontend/src/liveObservation.js`
- Modify: `frontend/test/live-observation-map.test.mjs`

**Interfaces:**
- Consumes: 既有 GET snapshot 的增量 phase/detail/can_cancel。
- Produces: `cancelling` 与 `cancellation_unconfirmed` 的只读状态文字；不会因轮询停止改变后端导航状态。

- [ ] **Step 1: 添加失败的静态行为测试。** 在 live-observation test 断言导航轮询只读取状态，`can_cancel === true` 才启用取消；`cancelling` 和 `cancellation_unconfirmed` 显示 `detail` 并不发新的 begin/cancel。

- [ ] **Step 2: 运行 RED。** 运行 `pixi run frontend-check -- --test-name-pattern='map marker'`（若脚本不支持参数则运行 `pixi run frontend-check`）；预期当前渲染未识别未确认取消。

- [ ] **Step 3: 最小化前端改动。** 保留当前仅在 `can_cancel` 为 true 时的一秒刷新；在菜单中显示后端 detail，禁用 action，且不生成客户端超时、ROS 调用或状态推断。保持 Mobile early return。

- [ ] **Step 4: 验证 GREEN。** 重跑步骤 2，预期 PASS。

### Task 6: 让冻结构建具备 Nav2 接口

**Files:**
- Modify: `build_binary.sh`
- Modify: `packaging/runtime_hooks/ros_runtime_interfaces.py`
- Modify: `tests/test_runtime_interface_hook.py`
- Modify: `tests/test_offline_modules.py`

**Interfaces:**
- Produces: 构建前 `import nav2_msgs.action` 检查、PyInstaller `--collect-all nav2_msgs` 和 Nav2 ROSIDL 库收集。
- Produces: runtime hook 只从 source 的 AMENT 路径加载批准的 `nav2_msgs` Python 包。

- [ ] **Step 1: 添加失败测试。** 断言 hook 在存在 `nav2_msgs` 的 AMENT prefix 返回 site-packages，并排除无批准前缀；断言构建脚本验证 action import、收集 nav2 package 和类型支持库。

- [ ] **Step 2: 运行 RED。** 运行 `pixi run python -m pytest tests/test_runtime_interface_hook.py tests/test_offline_modules.py -k 'nav2 or runtime_interface' -v`；预期 `nav2_msgs` 缺失。

- [ ] **Step 3: 实现受控收集。** 使 runtime package allowlist 包含 `nav2_msgs`；构建前显式 import `nav2_msgs.action`；把 `nav2_msgs` 加入 ROSIDL 库循环和 `--collect-all` 参数，保持 `master_interfaces` 的车端运行时加载边界。

- [ ] **Step 4: 验证 GREEN。** 重跑步骤 2，预期 PASS。

### Task 7: 完成受影响模块验证与审查

**Files:**
- Modify only if a failure exposes a requirement gap: files listed above.

- [ ] **Step 1: 运行 Backend 检查。** `./scripts/test-backend.sh`。预期通过；如果环境缺少 ROS/FVM 以外依赖，记录实际失败命令与首个阻断错误，不把它报告为通过。

- [ ] **Step 2: 运行 Web 检查。** `./scripts/test-web.sh`。预期 Node 检查和生产构建通过；不生成或提交 `autodrive_console/web-vue/`。

- [ ] **Step 3: 检查差异完整性。** 运行 `git diff --check`，检查变更只涉及本计划声明的路径和既有用户改动的必要相邻行。确认三份契约的消费者影响均为 Backend + PC Web、Mobile 非消费者。

- [ ] **Step 4: 提交前审查。** 按仓库现有提交粒度单独暂存本功能的测试、实现、契约和文档；不要把工作区现有无关改动加入提交。提交信息：`fix: harden map marker navigation safety`。

## Plan Review

- Spec coverage: Task 1 覆盖 API、消费者和互锁事实；Tasks 2–4 覆盖急停新鲜度、单 worker、无浏览器监控和未确认取消；Task 5 覆盖 PC 可见性；Task 6 覆盖 frozen 包；Task 7 覆盖最小相关验证。
- Placeholder scan: 所有步骤指定了具体文件、行为和命令；没有待定接口或泛化“补错误处理”的步骤。
- Type consistency: Controller 只依赖 worker 的 request/event 接口；VehicleControl 只通过既有 callable guard 观察 `blocks_runs()`；REST 保留当前路径及 `can_cancel` 字段。
