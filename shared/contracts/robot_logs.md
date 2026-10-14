# 机器人日志下载与实时 stdout 查看

**Status: Existing（已实现）**

| 事实 | 约束 |
| --- | --- |
| 运行时执行方 | `autodrive_console/robot_logs.py`、`autodrive_console/supervisor.py` 与 `web_console.py`。后端只读取当前小车本机的已保存目录，并仅通过已配置的 `supervisorctl` 跟随已验证节点的 stdout。 |
| Existing 消费者 | Desktop Web `/robot-logs.html`。 |
| 非消费者 | Mobile、ROS2、视频运行时、任务执行和“工具日志”页面。它们不得调用本接口或读取此配置。 |
| 数据归属 | 日志始终保留在机器人原目录；浏览器接收用户选中的单文件下载副本并保存到打开网页的电脑。实时查看只把 stdout 流显示在当前浏览器内，不写入小车，也不创建服务端历史队列。 |

## 配置与安全边界

日志源保存于 `config/console.json` 的 `robot_logs.sources`。每项均为 `{id,name,path}`；新条目的 `id` 由 Backend 生成，浏览器不能指定。升级旧配置时会自动提供以下默认源：

| ID | 名称 | 默认目录 |
| --- | --- | --- |
| `drivers` | drivers | `/opt/ry/Log/supervisor-logs/stdout/today/drivers` |
| `modules` | modules | `/opt/ry/Log/supervisor-logs/stdout/today/modules` |
| `lightning` | lightning | `/opt/ry/workspace/lightning_logs` |

目录必须是规范绝对路径，且不能是 `/`、`/etc`、`/proc`、`/sys`、`/dev`、`/run`、SSH 私钥目录或其子目录。可配置目录不等于下载 API 接受任意路径：文件清单和下载接口仅接受后端已保存的 source ID 与 opaque file ID。

只枚举目录第一层的普通文件；不递归、不跟随符号链接、不执行 shell 命令。文件 ID 绑定日志源、文件名和本机 `dev + inode`，不会因同一日志追加而失效；每次下载仍重新验证实际文件身份。日志轮转或替换（inode 变化）、消失、不可读或超过 256 MiB 时拒绝下载，绝不改为下载其它文件。

## HTTP API

| 方法与端点 | 请求 | 响应与兼容规则 |
| --- | --- | --- |
| `GET /api/robot-logs/sources` | 无 | 返回 `sources[]`：`id,name,path,status,message,file_count`。`path` 仅用于 Desktop 的目录管理表单。 |
| `PUT /api/robot-logs/sources` | `{ "sources": [{ "id"?: "…", "name": "…", "path": "…" }] }` | 原子校验并保存完整目录列表。保留已有 ID 可编辑该源；新增项不得带 ID，由 Backend 生成。 |
| `GET /api/robot-logs/sources/{source_id}/files?query=` | 受控 source ID、可选文件名关键词 | 返回 `files[]`：`id,name,size_bytes,modified_at`。只按文件名筛选，不读取日志正文，不返回路径。 |
| `POST /api/robot-logs/downloads` | `{source_id,file_id,ros_time:"beijing"|"raw"}` | 创建一个短时、只含元数据的下载进度记录，返回 `download.id,name,state,sent_bytes,total_bytes,convert_ros_time,error`。不接受路径，不缓存日志正文。 |
| `GET /api/robot-logs/downloads/{download_id}` | 受控 32 位下载 ID | 返回当前下载进度；`state` 为 `prepared`、`streaming`、`completed` 或 `failed`。 |
| `GET /api/robot-logs/downloads/{download_id}/file` | 受控下载 ID | 浏览器实际下载入口；开始后逐块更新进度。一个 ID 只能下载一次。 |
| `GET /api/robot-logs/sources/{source_id}/files/{file_id}/download` | 受控 source/file ID；可选 `ros_time=beijing` | 默认请求是 `ros_time=beijing`：只在下载副本中按旧 RYLog 规则将可识别的 10 位秒、小数秒和 19 位纳秒 ROS 时间转换为北京时间。省略该参数时返回原始文件流。两种方式均无 ZIP、无临时归档、无服务端历史下载队列。 |
| `GET /api/robot-logs/tail?stream={source_id}:{file_id}&stream=…` | 一个或多个受控 source/file ID | 长连接 `application/x-ndjson; charset=utf-8`；每行是 `{stream,text}`，其中 `stream` 仍为浏览器已知的 opaque source/file 标识。后端逐项重新验证当前日志的 `dev + inode`，仅接受形如 `<program>.out.log` 的 Supervisor stdout 文件，再以当前 `supervisorctl status` 中唯一匹配的进程名执行 `tail -f <process> stdout`。一个浏览器页只建立这一条复用流，避免多个实时窗口耗尽同源 HTTP 连接而阻塞页面切换。浏览器永远不能提交进程名、Supervisor URL 或认证信息；日志轮转、文件消失、无匹配或匹配不唯一时拒绝建立流。 |
| `GET /api/robot-logs/sources/{source_id}/files/{file_id}/tail` | 受控 source/file ID | 兼容旧客户端的单条 `text/plain` 实时流；新 Desktop Web 不使用该端点。 |

`status` 为 `available`、`missing` 或 `unavailable`。不可读或缺失的一个源不得阻断其它源。Desktop 的“下载时将 ROS 时间转为北京时间”开关默认开启；关闭后下载原始文件。转换仅接受 UTF-8 文本，非 UTF-8 文件会被明确拒绝，操作者可关闭开关重新下载原始文件。每次下载在打开文件后固定本次快照字节数：开始前的日志追加会作为当前内容下载，传输期间的新增内容留给下一次下载，避免响应长度与文件内容不一致。批量下载严格逐文件进行：页面轮询显示“小车 → 浏览器”的当前文件与总进度，当前文件完成后才开始下一项。进度记录最多 100 项、15 分钟后自动清理，只保存元数据，不持有文件或历史传输队列。浏览器可按自身策略要求用户允许多文件下载。

Desktop 可按日志行持续打开实时日志卡片，卡片沿两列网格向下排列；每张卡可暂停、继续、清空、关闭，并固定复用最近 240 行的显示节点。当前浏览器会话会保存已打开卡片及其暂停状态；切换到其它页面后返回日志页会自动恢复，关闭浏览器标签页或会话后不再保留。所有未暂停卡片共享一条 NDJSON 实时连接，后端各自跟随对应 Supervisor stdout 并以受控标识分发，避免多个卡片耗尽浏览器同源连接。stdout 按动画帧批量刷新；渲染繁忙时读取循环等待已排队内容完成，利用浏览器与网络背压控制积压，不跳过、截断或改写任何日志字符。单条长期无换行内容会被分段显示，每段完整保留原始字符，未完成尾段最多暂存 16 KiB。后端跟踪活跃跟随流，关闭、切页或断开浏览器时立即终止对应 `supervisorctl tail -f` 子进程并释放资源。所有未手动暂停的日志卡都持续自动跟随最新输出；日志底部向下滚动会交给页面，以便进入后续卡片，滚动查看旧内容不会改变该卡的实时跟随状态。页面只清除终端 ANSI 控制符，并将可识别时间、日志等级和正文分列、分色显示；它不会回写、转换或篡改原始 Supervisor 输出。受 Supervisor 管理页保护的 `:9001` 地址与认证信息不属于浏览器接口，也不得被嵌入或代理为通用管理页面。

## 变更影响与验证

本次多窗口实时查看变更影响 Existing 消费者 Desktop Web 及其 Backend tail 资源跟踪：Desktop 使用新增的多路复用 tail 端点并保存当前浏览器会话的窗口状态，旧单条 tail 端点保留给兼容客户端。Mobile 仍非消费者，无需 Mobile 工具链验证。

| 变更 | 必需验证 |
| --- | --- |
| source 结构、路径边界、文件 ID、下载或实时 tail 端点 | Backend 测试、Desktop Web 回归、本契约。 |
| 仅 Desktop 视觉/文案 | Web 检查；无需 Mobile 工具链。 |
| 新增 Mobile 日志功能 | 先独立建立 Mobile 权限、隐私与下载契约；当前 Mobile 不是消费者。 |

现有 `/api/tool-logs*` 仍只服务 Aletheia 自身诊断日志，不能与本接口合并或用本接口读取工具私有日志。
