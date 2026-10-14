# 机器人 Backend 文档

运行时、ROS2、打包和发布事实从 [PROJECT_OVERVIEW](../../PROJECT_OVERVIEW.md) 开始阅读。日常维护使用 [Backend 规则](../../autodrive_console/AGENTS.md)、[共享契约](../../shared/contracts/README.md) 和 [scripts/test-backend.sh](../../scripts/test-backend.sh)。

## Mobile 原生报告归档

`NativeReportArchive` 为 Mobile 提供只读的 schema v1 报告摘要、分页任务详情、冻结地图 PNG、显示级轨迹和按需采样点。新测试与验收报告在既有 HTML/CSV 写入后归档；历史报告仅可从受控结构化轨迹记录及验收资产清单分批回填，绝不解析 HTML、CSV 或 SVG，也不会从当前地图重建历史证据。

原生数据只以 `GET /api/reports` 的可选 `native_report` 和固定的报告专属 `/api/reports/{report_id}/native…` 端点公开。ID、分页、文本、数值、PNG 尺寸和归档资源均在 Backend 校验；畸形请求返回 400，格式正确但未知或跨报告资源返回 404。既有 PC HTML/CSV 流程和按 filename 删除入口保持不变；删除报告时同步删除其 Backend 所有的 native sidecar/冻结 PNG。完整协议见 [任务执行契约](../../shared/contracts/task_execution.md)。
