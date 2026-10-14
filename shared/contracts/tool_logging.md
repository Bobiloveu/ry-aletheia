# 工具诊断日志

Status: Existing

## 所有权与消费者影响

- 执行方：Backend `tool_logging.py`、`tool_audit.py` 与 `web_console.py`；文件仅写入工具的 `logs/`。
- Existing 消费者：Desktop Web 工具日志页、Web 移动壳层、Flutter `ToolLogsRepository` / `ToolLogEntry`；Backend 诊断下载。
- 本次影响：保留所有原字段，增加可选诊断上下文；新增浏览器专用上报入口，Flutter 不调用。Flutter 现有解析忽略未知字段，定向验证其原字段兼容，无需改动 Mobile 线协议或引入平台构建依赖。
- 机器人日志仍由 `robot_logs.md` 接口管理；不混入机器人日志正文。

## 现有读取和下载

- `GET /api/tool-logs?scope=all|errors`：`{entries:[...],scope}`，默认最近 200 条，最新在前。
- 每条必填字符串：`time`、`level`、`source`、`message`。可选字符串 `exception`。
- 增量可选字段：`request_id`、`event`、`method`、`path`、`operation`、整数 `status`、数值 `duration_ms`。上下文同时以可读摘要写在 message 中，使旧客户端仍可排障。
- `GET /api/tool-logs/files`、`GET /api/tool-logs/files/{name}/download`、`GET /api/tool-logs/download?scope=all|errors` 维持原下载白名单。
- 正常与错误 JSONL 各 2 MiB，最多 3 份轮转；ERROR/CRITICAL 独立分流。只记录业务边界和故障状态变化，不记录帧、控制脉冲或成功轮询。

## 浏览器诊断（增量）

`POST /api/tool-logs/client-events`，JSON 正文最多 8 KiB：

```json
{"level":"ERROR","event":"operation_failed","page":"/deployment.html","operation":"map_image_export","message":"图片导出失败"}
```

- `level`：`INFO` / `WARNING` / `ERROR`。
- `event`：`browser_error`、`unhandled_rejection`、`resource_error`、`request_failed`、`operation_failed`、`operation_completed`。
- `page`：第一方页面 pathname（最多 240 字符），不得附带查询参数、认证或正文。
- `message`：非空字符串，最多 1200 字符；`operation` 可选，最多 160 字符。
- `202 {recorded:true|false}`：记录成功或重复事件合并；`400`：格式/大小非法；`429`：超过客户端速率预算。
- 客户端和 Backend 均进行有界限流、URL 查询/认证清理；诊断上报本身的失败不能递归上报。浏览器不调用机器人文件、ROS 或任务执行接口。

## 验证

Backend：上下文/脱敏、HTTP 成功与错误/恢复、后台生命周期、上报输入和限流。
Web：早期安装、异常/资源/请求捕获、被捕获的本地失败、重复抑制、无递归与现有功能回归。
Mobile：核对 `ToolLogEntry.fromJson` 原字段及未知字段兼容；原接口和必填字段未变。
