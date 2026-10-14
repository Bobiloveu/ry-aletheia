# 地图标记导航路线与朝向输入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 PC 实时地图上安全显示当前地图标记导航的 Nav2 规划路线，并以角度输入修复标记终点朝向错误。

**Architecture:** 保持 `_RosNavigateToPoseWorker` 对 ROS node/executor 的唯一所有权，在已接受的自有 Goal 期间读取并净化 `/plan`。控制器按 Goal 代际保存受限路线，既有状态 API 将其交给 PC 页面；Pixi 绘制路线，图层开关只控制显示。浏览器把角度转换为既有 REST 弧度语义。

**Tech Stack:** Python 3.10、rclpy、Nav2 `NavigateToPose`、`nav_msgs/msg/Path`、PixiJS、Node test、pytest。

**Spec:** `docs/superpowers/specs/2026-10-08-map-marker-route-visualization-design.md`

## Global Constraints

- `/plan` 只由 Backend ROS worker 读取；Web 与 Mobile 绝不连接 ROS、指定路线、发布 Goal 或 Twist。
- 只接受 `map` frame、有限坐标、与当前自有 Goal 终点相符的路径；最多公开 512 个二维点。
- 取消、终态、失效安全条件、切图和新 Goal 都必须清除路线；图层开关不能影响 Backend 监控或取消。
- yaw 表单只接收 `[-180, 180]` 角度，API 与持久化继续使用弧度；历史标记保持不变。
- 不改变 Nav2 行为树、控制器、速度、代价地图、虚拟墙或 Mobile UI。
- 当前工作区含有无关未提交改动；只编辑本计划列出的路径，绝不暂存、还原或提交其他文件。

---

### Task 1: 锁定受控路线契约

**Files:**
- Modify: `shared/contracts/realtime_observation.md`
- Modify: `shared/contracts/robot_control.md`
- Modify: `tests/test_offline_modules.py`

**Interfaces:**
- Produces: `GET /api/observation/map-marker-navigation` 的增量 `route` 快照。
- Consumes: `/plan` 的 `nav_msgs/msg/Path`，仅 Backend ROS worker 消费。

- [ ] **Step 1: 写失败的契约测试。** 断言两份契约提到 `/plan`、`map` frame、512 点、Goal 终点匹配、终态清除、PC Web 消费者和 Mobile 非消费者。
- [ ] **Step 2: 运行 RED。** 运行 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest tests/test_offline_modules.py -k map_marker -v`；预期缺少路线事实而失败。
- [ ] **Step 3: 增加受控事实。** 在实时观测契约写明 `route` 结构、路线层位置与默认开关；在机器人控制契约写明 worker 独占订阅和清除规则。
- [ ] **Step 4: 运行 GREEN。** 重跑步骤 2；预期通过。

### Task 2: 在控制器中保存并清除已验证路线

**Files:**
- Modify: `tests/test_map_marker_navigation.py`
- Modify: `autodrive_console/map_marker_navigation.py`

**Interfaces:**
- Produces: `_normalize_route(frame_id, poses, goal_x, goal_y) -> tuple[tuple[float, float], ...]`。
- Produces: `MapMarkerNavigationController.status()["route"]`，值为 `None` 或 map-frame 二维点快照。

- [ ] **Step 1: 写失败的 pytest。** 用现有 `_Transport` fake 交付一条 map 路线，断言状态公开抽稀后的点；为非 map frame、目标不匹配和取消/终态各断言路线被拒绝或清除。
- [ ] **Step 2: 运行 RED。** 运行 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest tests/test_map_marker_navigation.py -k route -v`；预期缺少 route callback 或快照字段失败。
- [ ] **Step 3: 最小实现。** 增加有限坐标、终点距离、512 上限和首尾保留的路线规范化；为每个 Goal 分配代际，只接受 `navigating` 的同代路线，并在所有清理路径重置路线。
- [ ] **Step 4: 运行 GREEN。** 重跑步骤 2，再运行 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest tests/test_map_marker_navigation.py -v`。

### Task 3: 由唯一 ROS worker 获取 `/plan`

**Files:**
- Modify: `tests/test_map_marker_navigation.py`
- Modify: `autodrive_console/map_marker_navigation.py`

**Interfaces:**
- Produces: `_RosNavigateToPoseWorker.send_goal(..., route_callback=...)`。
- Consumes: `nav_msgs.msg.Path`，使用 worker 已拥有的 node/executor。

- [ ] **Step 1: 写失败的 worker 测试。** fake node 记录 `create_subscription(Path, "/plan", ...)`；在 Goal 接受前发路径时断言没有 callback，接受后只把当前 ticket 的路径交给 callback，result 后清除 active ticket。
- [ ] **Step 2: 运行 RED。** 运行 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest tests/test_map_marker_navigation.py -k 'worker and plan' -v`；预期订阅和回调行为缺失。
- [ ] **Step 3: 最小实现。** worker 在 `_run()` 只创建一次 Path subscription；Goal 接受后登记 active ticket，Path callback 仅转交给 ticket 的 route callback，result 或关闭时清空 active ticket。不得创建第二个 node、executor 或浏览器路径。
- [ ] **Step 4: 运行 GREEN。** 重跑步骤 2 和整个标记导航测试文件。

### Task 4: 渲染路线并修复角度和浅色控件

**Files:**
- Modify: `frontend/live-observation.html`
- Modify: `frontend/src/liveObservation.js`
- Modify: `frontend/src/liveObservation.css`
- Modify: `frontend/test/live-observation-map.test.mjs`

**Interfaces:**
- Consumes: `mapMarkerNavigationStatus.route` 的 map-frame二维点。
- Produces: 默认勾选的 `navigationRouteVisible`；`renderNavigationRoute()`；角度到弧度转换。

- [ ] **Step 1: 写失败的 Node 测试。** 断言 HTML 有默认勾选的“规划路线”，源码有独立 Pixi 路线层和可见性渲染，表单文本为 yaw（角度）并在请求前乘 `Math.PI / 180`，浅色主题选择器覆盖标记按钮。
- [ ] **Step 2: 运行 RED。** 运行 `pixi run node --test frontend/test/live-observation-map.test.mjs`；预期断言失败。
- [ ] **Step 3: 最小实现。** 在虚拟墙与标记之间插入绿色 Pixi 折线路线层；状态轮询和开关改变时重绘。默认启用开关，关闭只隐藏；改变表单为 `[-180,180]` 角度并转换为弧度；修复浅色主题文字对比度。
- [ ] **Step 4: 运行 GREEN。** 重跑步骤 2，随后运行 `pixi run frontend-check`。

### Task 5: 集成验证与现场交接

**Files:**
- Verify only: `autodrive_console/map_marker_navigation.py`, `frontend/src/liveObservation.js`, contracts and their tests.

- [ ] **Step 1: 运行后端检查。** 执行 `./scripts/test-backend.sh`，确认退出码为零。
- [ ] **Step 2: 运行 Web 检查。** 执行 `./scripts/test-web.sh`，确认退出码为零。
- [ ] **Step 3: 构建并检查运行时。** 依项目发布流程构建含本次文件的升级包，在不发导航 Goal 的情况下检查 Backend 导入与 `/plan` 的 ROS 类型/发布者。
- [ ] **Step 4: 现场验证边界。** 由操作员在安全区域发起一个地图标记导航；确认路线只在该 Goal 存在时绘制、开关可隐藏、到达/取消后清除，并目视核验终点角度。记录结果但不由实施者自动发 Goal。
