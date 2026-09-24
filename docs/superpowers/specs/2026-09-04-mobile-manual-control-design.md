# 移动端手动操作设计

**日期：** 2026-09-04
**状态：** 已完成设计，待用户审核
**范围：** 仅 Flutter Mobile；不修改 PC Web、Backend、ROS Topic 或既有控制协议。

## 1. 目标

为已连接的机器人提供原生移动端手动操作能力。操作员可以安全地建立既有的 `miniapp` 手动会话、使用触摸摇杆发送四向受控运动命令、停止并退出会话、查看真实急停状态、在满足后端条件时请求解除急停，并查看或保存既有底盘参数。

此功能是独立的 `manual_control` feature，不属于首页、观测或普通测试运行。它复用 Backend 已有的 `/api/vehicle-control*` API；Backend 仍是 ROS、控制权、速度限制、看门狗、急停状态和命令发布的唯一权威。

## 2. 边界与非目标

### 2.1 必须遵守

- App 不直连 ROS，不发布 `/cmd_vel_miniapp`、`/control_source_cmd`、`/control_source_state`、`/is_emergency_stop` 或 `/command`。
- App 仅调用已有受控 HTTP 接口，不新增、猜测或改写 Backend API。
- 运动许可只以 `GET /api/vehicle-control` 返回的最新 `manual_ready`、会话状态、实际控制源和急停状态为准；客户端不得乐观假定已可控。
- `emergency_stop.state` 为 `triggered` 或 `unknown` 时，App 必须禁用一切非零运动输入。
- 离开页面、指针取消、摇杆松开、路由切换、App 进入 `inactive`、`hidden`、`paused` 或 `detached`、连接失效时，客户端立即调用 `stop`；若持有会话，再尽力调用 `exit`。网络失败不降低 Backend 看门狗和急停门控的权威性。
- 任何页面状态都不得显示“急停已解除”或“运动已生效”，除非后端最新状态已经明确确认。

### 2.2 不在本期范围

- 不新增或修改 PC Web 页面、Backend、ROS2 node、Topic、速度/控制权语义。
- 不实现任意速度向量、对角线运动、航点导航、`place` 控制、远程任意命令、后台控制、离线控制或自动接管。
- 不把操作入口升为第五个底部导航项；仍由“工具”进入，防止误触与工作流混淆。
- 不替代物理急停，也不在移动端伪造“触发急停”能力。现有 API 仅可在真实急停触发时请求软件解除。

## 3. 用户流程与状态

### 3.1 进入与会话

1. 从 `/tools` 的“手动操作”卡片进入 `/tools/manual-control`。
2. 页面读取控制状态，完整呈现 loading、未连接、不可用、急停触发、急停未知、可开始和操作中状态。
3. 用户点“开始操作”后调用 `POST /api/vehicle-control/enter`；只有后端确认会话、实际控制源与 `manual_ready` 后，摇杆才可用。
4. 操作中发送 `heartbeat`，并以固定安全频率刷新控制状态。刷新结果使用 operation epoch，旧请求不可覆盖新 endpoint 或已退出会话状态。
5. 用户点“结束操作”时先 `stop` 再 `exit`，页面回到只读状态。

### 3.2 摇杆

- 摇杆只映射 `forward`、`backward`、`left`、`right` 与 `stop` 五种现有命令；不生成客户端速度数值。
- 中心区域为死区；离开死区后按占优轴选择四个方向，切换方向时先提交新的既有 `command`。
- `PointerDown` 立即响应，`PointerMove` 以一比一视觉跟随拖动；采用 pointer capture，手指离开原控件仍可正确处理。
- `PointerUp`、`PointerCancel`、失焦或任何安全禁用转换时立即发送 `stop`，摇杆回中心。视觉回弹使用短、无过冲的弹簧；启用减少动态效果时改为短淡入淡出/静态归位。
- 触摸反馈仅表达当前方向和停止，不以装饰性动画掩盖网络或车端延迟。

### 3.3 急停与设置

- 顶部安全卡常驻显示 `normal`、`triggered` 或 `unknown`，并显示后端消息。
- `triggered` 时提供“请求解除急停”入口：用户需长按确认；请求期间呈现 waiting 状态。只有后端状态变为 `normal` 才显示成功，超时/失败/未知保持禁止运动并显示原因。
- 普通“停止运动”与“解除急停”是不同动作、不同文案和不同视觉层级。
- 速度档调用既有 `/speed` 端点，使用后端给出的实际速度状态，不在 App 本地持久化一套速度真相。
- `press`、`movement_acc`、`stop_acc` 放在二级“高级底盘参数”页面/Sheet；显示范围、当前值、保存中和保存失败。保存前显示确认，后端返回值才是最终状态。

## 4. 信息架构与视觉规范

页面顺序为：

```text
连接与安全状态
  → 开始/结束操作
  → 速度档
  → 摇杆与当前指令
  → 急停处理（仅触发/未知时突出）
  → 高级底盘参数
```

- 使用新的白—蓝日间主题：蓝色表达可操作与当前选中，绿色仅表达健康/已确认，琥珀色用于注意，红色仅表达急停或危险阻断。
- 使用系统字体、清晰的大标题和紧凑说明；所有关键触控目标不小于 44pt。
- 摇杆是页面主视觉和唯一直接操控元素；次要设置收纳在 Sheet，防止覆盖操作区。
- 不使用循环装饰动画、强渐变或叠层玻璃效果。必要的 Sheet、按钮按压、摇杆归位都应可中断、符合减少动态效果与高对比度设置。
- 横屏保留安全状态、结束操作和摇杆的同屏可见性；不依赖屏幕旋转来暴露关键停止入口。

## 5. 移动端架构

新增 `mobile/lib/features/manual_control/`，遵循既有 Repository → Riverpod Controller → Production Page 的依赖方向：

```text
ManualControlPage
  → ManualControlController (不可变状态、轮询、心跳、lifecycle、安全收尾)
  → ManualControlRepository (JSON 解析、受控 API 调用)
  → AletheiaApiClient
  → 既有 /api/vehicle-control* Backend API
```

领域模型至少包括控制快照、会话状态、急停状态、底盘参数、允许动作和用户可见错误。后端只在 `enter` 响应中返回会话 ID，普通轮询状态不返回 ID；因此领域模型只判断后端是否允许运动，`ManualControlController` 单独持有当前会话 ID，二者同时成立才发送非零命令。Controller 独立于 `live_observation`、测试运行及连接控制器，不复用其私有状态；只通过公开的当前 endpoint 与连接状态协调。

路由只新增 `/tools/manual-control`；`ToolsScreen` 增加二级入口。App Shell 仍保持四个主入口。

## 6. 契约与文档

- `shared/contracts/robot_control.md` 更新为 Mobile Existing 消费者，并记录 Mobile 使用的接口、客户端安全收尾和明确非能力。
- `mobile/README.md`、`mobile/docs/ARCHITECTURE.md`、`mobile/docs/DEVELOPMENT_WORKFLOW.md`、`mobile/docs/DESIGN_SYSTEM.md`、`docs/UI_SPEC.md` 更新移动端控制页的边界、路由、主题与验证方式。
- 不更新 PC 实现说明，不改变 Backend 契约语义；若发现现有接口缺少实现本设计所需字段，停止开发并提出 Backend 契约变更，而不是在 App 端猜测。

## 7. 测试与验收

### 自动化

- Repository：控制状态、非 2xx、超时和字段兼容性解析。
- Controller：enter/heartbeat/command/stop/exit 顺序，停止幂等、连接切换 epoch、页面离开与生命周期收尾、急停门控、解除急停等待确认、设置保存失败。
- Widget：loading、未连接、可开始、控制中、急停触发、急停未知、解除等待、错误状态；摇杆死区、方向映射、`pointer up/cancel` 停止与高触控区。
- Gallery：新增真实 production Page 的 mock 状态、关键 Golden，并重新生成 Screen Inventory/Map。

### iPhone 模拟器实时检查

使用可用 `iPhone 17 Pro` Simulator 运行 Debug Gallery 和正常 App，逐项确认：

1. 白蓝主题、动态字体、横竖屏、Safe Area 和 44pt 触控区；
2. 摇杆按下、拖动、方向切换、松开、取消和减少动态效果；
3. 开始/结束操作、急停触发/未知/等待/失败等 mock 状态；
4. 退出页面、切后台再恢复时 UI 不保留可运动的假状态。

模拟器不连接 ROS，不证明车辆运动安全。涉及真实 `enter`、运动、控制源与急停解除的验证必须由现场安全观察员、物理急停和车端日志完成，并以 Backend 的既有实车验收标准为准。

## 8. 完成标准

- 仅 Mobile 与必要契约/文档发生变更，PC Web 与 Backend diff 为零。
- 所有非零输入都经过已有 Backend 会话和急停门控；任何客户端收尾路径优先停止。
- 新页面在真实入口、Debug Gallery、iPhone 模拟器的横竖屏状态下可用。
- `scripts/test-mobile.sh`、新增定向测试、`fvm flutter analyze`、`git diff --check` 通过；不提交构建产物、Golden 失败图片、日志或签名材料。
