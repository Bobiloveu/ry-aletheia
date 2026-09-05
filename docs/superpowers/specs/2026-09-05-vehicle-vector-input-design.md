# 车辆手动控制连续向量输入设计

## 目标

在不改变 PC Web 现有四方向按钮行为的前提下，为 Flutter App 的触摸摇杆增加连续的“前后 + 转向”输入。右上等斜向输入表示差速/转向底盘的前进转弯弧线，而非横向平移。

本设计同时补齐 Mobile 对既有车辆控制参数的受控配置能力，并将接口、安全边界、消费者和验证要求记录到 Shared Contract。

## 范围与非目标

范围：

- Backend 新增受控 HTTP 向量输入，不新增 ROS Topic。
- Mobile 使用该接口驱动连续双轴摇杆。
- Mobile 提供线速度、转向速度以及底盘压力、运动加速度、停止加速度的受控配置。
- 统一更新 `shared/contracts/robot_control.md`、Mobile 架构/设计说明与 UI 规范。

非目标：

- 不修改 PC Web 的四方向控制页面、布局或请求方式。
- 不允许 Web 或 Mobile 直接发布 ROS Twist、控制源 Topic 或急停 Topic。
- 不支持横向移动、路径导航、地点控制、自动驾驶参数写入或绕过 Backend 的安全状态机。
- 不改变现有 `/api/vehicle-control/command`、`/stop`、`/exit` 的语义。

## 契约与数据流

新增 Existing HTTP 接口：

```http
POST /api/vehicle-control/vector
Content-Type: application/json

{
  "session_id": "opaque-session-id",
  "linear_ratio": 0.82,
  "angular_ratio": -0.64
}
```

`session_id` 仍由 `POST /enter` 返回，客户端不得猜测、恢复或复用失效会话。

`linear_ratio` 和 `angular_ratio` 必须是有限数值，范围均为 `[-1.0, 1.0]`。它们不是 ROS 速度单位，也不是客户端安全限值：Backend 使用当前已验证的 `speed.linear_mps` 与 `speed.angular_radps` 换算实际目标：

```text
target_linear  = linear_ratio  × configured_linear_mps
target_angular = angular_ratio × configured_angular_radps
```

其中 `configured_linear_mps` 与 `configured_angular_radps` 只可经既有 `/speed` 接口在 0.10–1.00 范围内更新。`(0, 0)` 必须走与现有 STOP 相同的清除运动目标和零 Twist 路径，但保持会话；Mobile 在回到中心、松手、取消或失去可用状态时仍优先调用既有 `/stop`。

Backend 必须把向量目标与旧的命令目标作为互斥状态保存。之后修改速度档时，若当前是向量目标，必须以保存的两个 ratio 重新换算；若当前是旧命令目标，维持既有四方向重算行为。任何急停、控制源变化、输入/心跳超时、退出、异常或 `(0,0)` 都必须清除两类目标并使用 `stop_acc` 发布零 Twist。

接口沿用所有现有 `VehicleControlController` 前置条件：有效活动会话、实际 `/control_source_state=miniapp`、`/is_emergency_stop=false`、没有切换等待且 ROS2 控制器可用。失败状态码和返回状态对象与其他受控动作保持一致；不允许无界重试。

## 方向与车体坐标

Mobile 摇杆的视觉坐标以“车头向上”为基准，不能以地图朝向或屏幕旋转猜测车体方向。

| 摇杆位移 | `linear_ratio` | `angular_ratio` | 行为 |
| --- | --- | --- | --- |
| 上 | 正 | 0 | 前进 |
| 下 | 负 | 0 | 后退 |
| 左 | 0 | 正 | 左转 |
| 右 | 0 | 负 | 右转 |
| 右上 | 正 | 负 | 前进并右转 |
| 左上 | 正 | 正 | 前进并左转 |
| 右下 | 负 | 负 | 后退并右转 |
| 左下 | 负 | 正 | 后退并左转 |

摇杆采用连续 1:1 双轴输入：半径限制在控件边界内；中心死区只防止微小误触，不把其余区域量化为八个方向。手指位置转换为比例后立即发送，Controller 在按住期间以不慢于 Backend 350ms 输入看门狗的周期续传。进入中心死区时立即 STOP，不等待手指离开屏幕。

## Mobile 控制台设计

页面定位为“移动驾驶台”，而非多张堆叠信息卡：

1. 顶部仅保留返回、连接/急停状态和退出手动控制。
2. 中央为有车头指向标识的连续双轴摇杆。旋钮跟随手指；有效输入的视觉与触觉反馈只能表达当前指令，不做循环装饰动画。
3. 常用速度区同时提供线速度和转向速度，并显示精确值。
4. 底盘压力、运动加速度、停止加速度进入“底盘参数”高级面板；提供范围说明、滑杆、精确数值输入、未保存状态和显式保存操作。保存失败时保留编辑值并展示车端错误。
5. `normal` 急停状态为紧凑状态指示；`triggered` 或 `unknown` 时展示不可忽略的锁定说明。只有 `triggered` 可请求解除，且仅 Backend 返回实际 `false` 后可显示解除成功。
6. 竖屏让摇杆成为主焦点；横屏把操控区与速度/状态区并列，确保不会压缩、拉伸或遮挡关键操作。
7. 白天模式使用既定白蓝系统色，深色模式保持克制的深色控制台层次；系统动态字体、44pt 最小可点击面积、可访问性语义与减少动态效果偏好均须保留。

## 消费者与兼容性

| 消费者 | 变更 | 兼容性要求 |
| --- | --- | --- |
| Backend (`VehicleControlController`、HTTP handler) | 新增比例向量目标和 `/vector` 路由 | 旧 `/command`、`/speed`、`/stop`、`/exit` 必须保持行为不变。 |
| PC Web 手动控制 | 不改请求、不改页面 | 继续只发四方向 `command`；它无需调用 `/vector`。 |
| Flutter Mobile | 新摇杆调用 `/vector`；补齐五项既有参数 | 只经 HTTP 调用 Backend，保留 STOP→EXIT 生命周期。 |
| Shared Contract | 将接口和映射标记为 Existing | 后端、PC 和 Mobile 以后均以此文档为事实来源。 |

## 可靠性与验收

- Backend 单元测试：八个代表性方向及任意比例的换算、速度档更新后向量重新换算、`(0,0)` STOP、非法/非有限 ratio 拒绝、急停/未知/失效会话/错误控制源拒绝、超时与退出均清除向量。
- HTTP 测试：`/vector` 仅接受完整 JSON 对象并返回现有状态/错误模型；旧 `/command` 路由回归通过。
- Mobile 单元和组件测试：车体坐标映射、右上输入、中心 STOP、松手 STOP、后台 STOP→EXIT、急停锁定、五项参数范围和显式保存。
- Mobile UI：纵向与横向 widget 测试、日间/暗色 Golden、iPhone 模拟器实际检查；仅在模拟器通过后继续外部设备验证。
- 回归：`pixi run test`、`pixi run test-offline`、`scripts/test-web.sh`（PC 消费接口未改但需保持可用）、`scripts/test-mobile.sh`。网络代理不能影响本地 Flutter widget test server。

## 实施边界

不提交构建产物、缓存、日志、签名材料、地图或失败 Golden 图片。实现采用测试先行；任何契约改动必须与受影响消费者的验证一起完成。
