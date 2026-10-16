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

## 2026-10-15 日志管理增量（Existing）

影响 Backend、Desktop Web 和移动 Web 日志页；Flutter 仍只消费原条目与下载接口，原必填字段、路径和响应类型不变，不增加 Flutter 工具链要求。机器人业务日志、报告、录包不在管理范围内。

- `GET /api/tool-logs/files` 保留 `files`，增加 `storage={total_size_bytes,limit_bytes,policy,last_cleanup_at,last_error}`；策略为 `{retention_days:7,max_total_mib:256,max_file_mib:16}`。
- 每文件保留原字段，增量 `kind:current|archive`、`file_id`、`can_clear`、`can_delete`。身份不包含路径，只用于避免清单过时后误删已经轮转的文件。
- `PUT /api/tool-logs/retention` 接收 `{policy:{retention_days,max_total_mib,max_file_mib}}`；天数 1～365、总量 128～4096 MiB、单文件 2～32 MiB，均为整数且总量至少六个单文件容量；保存后立即整理并返回新 storage。
- `POST /api/tool-logs/cleanup` 接收 `{mode:expired|history,confirm:true}`。expired 按既定策略整理，history 删除全部白名单历史。必须明确确认，不清空当前文件。
- `POST /api/tool-logs/files/{name}/clear` 和 `DELETE /api/tool-logs/files/{name}` 接收 `{file_id,confirm:true}`，分别只允许清空当前文件和删除历史文件。
- 格式/范围无效为 400，文件不存在为 404，身份已变或正在生成下载快照为 409，I/O 故障为受控 500；不自动重试破坏性请求。
- 策略持久化到 `config/tool_logging.json`。已有文件不可读、无效、为符号链接或超过 4096 字节时暂停自动整理并返回 last_error；重新保存有效策略后恢复，不静默覆盖异常文件。
- 默认结构化日志仍 2 MiB/三份历史；原始追加日志在后台按容量保留最新窗口后原 inode 截断，历史最多三份，再按七天和总量预算清理。当前文件不按历史过期规则删除；每五秒检查，写入或下载期间允许短时超出预算。
- 下载按打开时的长度分块读取，单文件与完整 ZIP 均用磁盘临时快照，禁止将整个大日志读进 Python 内存。快照生成期间以跨进程共享租约暂缓该家族轮转；网络传输不持有活跃日志租约，避免慢客户端阻止清理。日志写者使用短时跨进程互斥，另一进程轮转后重新打开当前 inode。

原始子进程日志采用 copytruncate 尽力快照：复制与截断之间的少量并发输出可能丢失；结构化业务与错误日志独立加锁轮转。首次整理旧的超大原始文件也只保留最新单文件容量窗口，旧内容不会整份归档。Linux 生产环境使用 POSIX flock 提供跨进程保护。

## 2026-10-15 视频带宽记录（Existing）

Backend 视频运行器同时向受控 `video-runtime.log` stdout 与 JSONL 工具日志的 `video` 模块
记录网关统计带宽：总 Mbps / MB/s、逐路 Mbps、连接数和采样时间窗。稳定观看每三十秒
记录一次；无观看连接不重复打印，连接/计数变化和统计失败/恢复时记录状态。
沿用原 `time/level/source/message` 字段，不增加 Web/Mobile 必填字段或调用接口。
统计口径、回环请求总期限与媒体隔离边界见 `video.md` 的“视频带宽日志”节。
