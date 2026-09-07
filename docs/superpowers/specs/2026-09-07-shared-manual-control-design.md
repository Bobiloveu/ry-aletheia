# 共享多端手动控制设计

## 目标

让 Web 与 App 等多个 Aletheia 客户端在车端已确认
`/control_source_state=miniapp` 后共同使用手动控制，而不因另一个
客户端已经建立 Aletheia 会话而被拒绝。任意时刻仍只由
`VehicleControlController` 的唯一 ROS2 发布器向 `/cmd_vel_miniapp`
输出速度。

## 范围与约束

- 多端共享控制是明确批准的行为：最后一条有效方向输入生效。
- 每个客户端仍取得独立、不可猜测的会话 ID；HTTP 状态读取绝不返回他人的 ID。
- 任意客户端的 STOP 立即清空全局运动目标；任一方向输入超时也立即 STOP。
- 一个客户端心跳超时只移除该客户端；其他有效客户端继续保留共享手动状态。
- 明确请求“切换至自动驾驶”必须先 STOP、使全部客户端会话失效、请求
  `navigation`，并只以 `/control_source_state=navigation` 回报为成功。
- 页面关闭只释放当前客户端，不得把仍在线的其他客户端切回自动驾驶。
- 自动化测试运行中仍拒绝新建/加入手动会话；急停 `true` 或 `unknown`
  仍永远禁止非零 Twist。此改动不放宽机器人运动安全边界。
- 不增加账号、排队、角色或跨设备身份认证；当前同网段控制台继续使用现有的
  后端会话 ID 作为能力令牌。

## 后端模型

`VehicleControlController` 将单个 `_session` 改为按 ID 存储的共享会话集合，
并保留一个全局运动输入所有者。每个会话有 `state`、创建时间、最后心跳和
最后输入时间。`miniapp` 控制源已确认时，`POST /enter` 总是创建新的 active
会话；正在等待切入 `miniapp` 时，新请求加入同一等待批次，而不重复发布切源
命令。

任何 active 会话可更新全局方向目标；新方向覆盖旧方向并成为输入所有者。其
输入超过 350 ms 即清空全局目标并输出 STOP。心跳超过 1200 ms 的会话被移除；
若该会话正拥有运动输入，同样先 STOP。任何会话调用 `/stop` 都清空全局目标。

新增 `POST /api/vehicle-control/release` 接收当前 `session_id`，只释放该
客户端并在其拥有当前方向时 STOP。它不改变控制源。现有 `/exit` 改为全局
“切回自动驾驶”动作：先 STOP、无效化全部会话、请求 `navigation`。已有
`/navigation` 端点也使用同一全局动作。

状态响应保留兼容字段 `session.present` 与 `session.state`，并增加
`shared_sessions.active_count`。`manual_ready` 仅表示车端 source 与急停状态
允许共享会话输出；页面必须再结合本地持有的 `session_id` 才显示“当前端可控制”。

## Web 行为

打开页面时，若后端已经处于共享 `miniapp` 状态而本页没有 ID，页面调用
`/enter` 加入会话。页面显示“多人共享控制 · N 个在线端 · 最后指令生效”。
本页停止和方向控制只带自己的 ID；离页使用 `/release`，不影响其他端。显式
点击“切换至自动驾驶”继续使用全局切源动作并在状态确认后显示成功。

## 契约与验证

`shared/contracts/robot_control.md` 更新会话集合、`release` 端点、共享输入
仲裁及 Web/App 消费者影响。后端单元测试覆盖双会话加入、最后输入覆盖、某端
STOP、输入/心跳超时、单端释放和全局切回自动驾驶。Web 检查覆盖共享提示、
`release` 端点和离页行为。完成后运行 `scripts/test-backend.sh`、
`scripts/test-web.sh` 与 `git diff --check`。
