# 地图标记导航路线与朝向输入设计

**日期：** 2026-10-08\
**状态：** 已确认，实施中

## 目标

PC 实时观测页在受控地图标记导航期间显示 Nav2 实际发布的全局规划路线；操作员可在图层面板默认开启或关闭其可见性。地图标记表单使用角度输入航向，浏览器在请求前转换为后端既有的弧度存储和 Nav2 Goal 语义。浅色主题中的“添加标记”入口必须保持文字可见。

## 现状与根因

车端 `/plan` 的唯一发布者是 `planner_server`，消息类型为 `nav_msgs/msg/Path`，使用 `RELIABLE + VOLATILE`。现有 `MapMarkerNavigationController` 已独占 NavigateToPose Action worker，但没有订阅规划话题。

浏览器当前标记 API 与持久化存储均以弧度表示 yaw。表单的弧度输入与人机界面中的角度预期不一致；将 `-90.656` 直接提交会被后端按弧度归一化为约 `-2.6914`，从而发送错误朝向。已保存的标记不自动改写。

浅色主题由 `html[data-theme="light"]` 激活，而地图标记控件的亮色规则仅匹配 `body.theme-light`。结果控件背景变浅而继承的文字仍为浅色。

## 受控路线数据流

`_RosNavigateToPoseWorker` 仍是唯一的 ROS node 和 executor 所有者。它在自己的 executor 中订阅 `/plan`，但只有在它已获得本次地图标记 Goal 的 Nav2 接受回调后才处理路径。每条路径必须：

- `header.frame_id` 严格为 `map`；
- 每个采样点有有限的 `x/y`；
- 至少含两个采样点；
- 终点到本 Goal 的 `x/y` 距离不超过 0.5 m；
- 在保留首尾点的同时，抽稀至最多 512 点。

这使旧路线、其它导航客户端路线、非 map 路线、畸形点与超大消息不能进入页面。worker 仅以回调把已净化二维点交给 `MapMarkerNavigationController`；浏览器不会连接 ROS、选择话题、传入路线或影响路线订阅。

控制器只在 `navigating` 阶段保存当前 Goal 代际的最新路线。取消开始、未确认取消、任一终态、失败、地图不匹配或新 Goal 前都清空路线。`GET /api/observation/map-marker-navigation` 增量返回 `route: null` 或 `{ "frame_id": "map", "points": [{"x": number, "y": number}] }`。该字段只由 PC 实时页消费，Mobile 不消费或展示它。

## PC 渲染与表单

PC 页面每秒读取既有受控导航状态快照。Pixi 在虚拟墙之后、地图标记之前绘制当前路线为绿色折线；路线不改变地图、点云、车体、虚拟墙、导航状态或控制逻辑。图层面板新增默认勾选的“规划路线”；关闭仅清除可视绘制，仍可保留并安全更新 Backend 快照，重新开启立即绘制最新路线。

表单显示 `yaw（角度）`，只接受有限的 `[-180, 180]` 值，提交时计算 `degrees × π / 180`。REST API、标记 JSON 持久化与 Nav2 Goal 继续使用归一化弧度，避免破坏既有记录或共享 API。当前误建标记由操作员删除并按正确角度重新创建。

浅色主题同时覆盖 `html[data-theme="light"]` 和既有 `body.theme-light`，确保“添加标记”按钮文字具有可读对比度。图层面板增加一项不会挤压、隐藏或改变该按钮的可访问名称。

## 约束与验证

- 不改变 Nav2 行为树、控制器、速度、代价地图、虚拟墙或任何运动安全阈值。
- 不自动发布 Goal、Twist 或执行实车导航；实车验证由操作员从安全位置发起。
- 更新 `shared/contracts/realtime_observation.md` 和 `shared/contracts/robot_control.md`，记录 Backend/PC Web 消费者与 Mobile 非消费者。
- 先写失败测试，覆盖路线归属/上限/终态清除、表单角度转换、默认图层及浅色主题可读性。
- 运行相关 pytest、`pixi run frontend-check`、`scripts/test-backend.sh` 和 `scripts/test-web.sh`。对实车只做只读 ROS 图检查；是否发起新导航由操作员决定。
