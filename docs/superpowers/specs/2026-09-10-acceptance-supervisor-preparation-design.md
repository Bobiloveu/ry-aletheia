# 部署验收 Supervisor 运行准备状态设计

## 目标

当部署验收选择“执行已保存的 Supervisor 依赖编排”时，现场人员在首个任务开始前能看见冻结节点按阶段的实际重启、稳定等待、就绪或失败状态；未选择该编排时，页面不显示该区域。

## 边界与安全

- 仅扩展既有部署验收的受控状态反馈，不新增浏览器到 Supervisor、ROS 或 shell 的控制通道。
- 节点和阶段只来自已保存、并在创建验收计划时冻结的依赖编排；浏览器不提交节点名、命令、动作或等待策略。
- 页面只显示节点名、已冻结阶段、实际 Supervisor 状态和受控进度；不显示命令行、提权配置或日志内容。
- 仅 PC Web 是消费者；Mobile 保持不变。

## 数据模型

`execution_preflight_status` 从现有的 `{ state, message, updated_at }` 增量扩展为：

```json
{
  "state": "restarting_dependencies",
  "message": "正在重启第 1 阶段依赖",
  "updated_at": "2026-09-10T10:00:00+08:00",
  "dependency_progress": {
    "stages": [
      {
        "index": 1,
        "state": "waiting_stable",
        "nodes": [
          { "name": "MODULES:209-lightning", "status": "STARTING" }
        ]
      }
    ]
  }
}
```

`dependency_progress` 为 `null`，除非冻结验收计划启用了依赖编排。每个阶段仅携带 `index`、安全状态枚举和该阶段冻结节点的 `name/status`；它不携带 Supervisor 动作、命令或内部错误栈。旧的持久化计划没有该字段时保持兼容，并在公开响应中正常化为 `null`。

阶段状态闭集为 `pending`、`restarting`、`waiting_stable`、`settling`、`ready`、`blocked`、`cancelled`。节点状态沿用 Supervisor 已有只读状态文本（例如 `RUNNING`、`STARTING`、`STOPPED`、`MISSING`）。

## 后端事件流

1. `AcceptanceOrchestrator.create_plan()` 冻结既有依赖编排；公开计划保留已有计数接口，状态细节只在该计划启用依赖时出现。
2. `RunManager` 在执行前置准备时，把 `RobotGateway` 的阶段快照随既有 `preflight_progress` 事件发送给 `AcceptanceOrchestrator`。
3. `RobotGateway` 在每一阶段的命令下发前、命令接受后、稳定等待中的每次 Supervisor 读取、额外稳定等待和阶段完成时，发出只读快照；已有重启互斥和最终 `RUNNING` 总闸不变。
4. `AcceptanceOrchestrator` 验证并持久化快照，页面轮询当前计划时即可在刷新或换设备后恢复同一进度。

## 页面行为

- 勾选依赖编排但尚未生成计划：不显示节点清单；节点和阶段在生成计划时才由 Backend 冻结，避免浏览器把尚未冻结的运行配置误呈现为本次验收事实。
- 计划生成且依赖已冻结：在验收范围卡的“运行准备”状态下方展示“Supervisor 运行准备”；每阶段按 DOM 顺序显示节点与状态，当前阶段明确显示“重启中”或“等待稳定 RUNNING”。
- 页面每两秒只在验收准备/执行状态刷新；状态来自当前计划持久化快照。节点全部稳定后保留“已就绪”，直到验收完成或恢复结束，便于现场追溯。
- 未勾选或冻结计划未启用依赖编排：整个 Supervisor 状态区保持 `hidden`，不留下占位文案。

## 验证

- Backend：验证状态模型兼容旧计划；验证阶段/节点快照的白名单校验；验证编排执行时的实时快照按阶段推进并被验收计划持久化。
- Web：验证未选择时状态区不渲染；冻结依赖后正确呈现阶段、节点状态与状态语义；确认 Vite 代理、模块解析与既有验收页面不回归。
- 最终运行 `scripts/test-backend.sh`、`scripts/test-web.sh`，并对验收页面执行桌面与窄屏检查。
