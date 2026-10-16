# 工具日志管理实施计划

> **For agentic workers:** 使用 executing-plans 按下列阶段执行；保留当前工作树中的既有改动，不自动提交、打包或部署。

**Goal:** 使本工具六类日志可以控制容量、自动整理、单独清空和删除历史，并消除大文件下载的内存膨胀。

**Architecture:** 扩展现有 ToolLogStore，保持六类固定白名单。结构化日志沿用 2 MiB/三份轮转，原生追加日志使用后台、有界尾部复制和原 inode 截断，不替换子进程持有的文件描述符；原始输出轮转为尽力快照，独立结构化错误日志保留原有保护。管理与下载使用锁、文件身份和读取租约，避免轮转后误删或下载时截断。

**Tech Stack:** Python 标准库、现有 HTTP Server、原日志页面 JavaScript/CSS、pytest、Node test、agent-browser。

**Spec:** 用户确认历史保留 7 天、总量预算 256 MiB；单个原始日志默认 16 MiB、最多三份历史。范围仅为 Aletheia 工具日志，不涉及机器人日志、报告或录包。

## 约束

- 大文件只读取最新一个容量窗口，不读取完整 1.5 GiB 文件；后台每五秒检查。
- 活跃文件只能原 inode 清空；历史才可删除；拒绝符号链接和目录穿越。
- 同一日志家族生成磁盘下载快照时暂缓轮转，快照生成和管理冲突返回 409；网络传输前释放源租约；未确认或文件身份过期不能删除。
- 保留原 API 必填字段及 Flutter 只读接口；管理字段和路由为增量。
- 页面沿用系统字体、中性灰与系统蓝，无左侧彩色描边；危险操作使用明确确认对话框。
- 仅使用临时目录测试删除和清理，不处理实车现有日志；不自行打包、部署、提交。

## 1. 存储与维护

- [x] 在 `tests/test_tool_log_management.py` 写先失败的测试：O_APPEND 文件描述符在清空/轮转后仍写当前 inode；超大稀疏文件只保留最后容量窗口；过期/总量清理只针对白名单历史；符号链接、下载租约和文件身份冲突受保护。
- [x] 执行 `env -u PYTHONPATH pixi run python -m pytest tests/test_tool_log_management.py -q` 确认失败。
- [x] 扩展 `autodrive_console/tool_logging.py`：`storage_status()`、`save_policy(payload)`、`cleanup(history=False)`、`clear_file(name, file_id)`、`delete_file(name, file_id)`、`open_diagnostic(name)`、后台 `start_maintenance()/stop_maintenance()`。
- [x] 保留 `entries/files/diagnostic_records` 旧字段与顺序；为原始日志增加 `.1` 至 `.3` 历史，增加身份与可操作元数据。
- [x] 通过存储、现有日志及真实追加写入回归。

## 2. HTTP 与下载

- [x] 在 `tests/test_tool_logging_http.py` 增加真实 HTTP 回归：策略保存/校验、清空后继续写入、带身份删除、过期身份/下载冲突、历史批量整理、旧 GET 兼容。
- [x] 更新 `shared/contracts/tool_logging.md` 的消费者影响与增量路由。
- [x] 在 `web_console.py` 接入 `PUT /api/tool-logs/retention`、`POST /api/tool-logs/cleanup`、`POST /api/tool-logs/files/{name}/clear`、`DELETE /api/tool-logs/files/{name}`。
- [x] 单文件和错误日志使用读取租约生成磁盘临时快照，释放源租约后按 64 KiB 分块传输；完整 ZIP 使用可落盘临时文件与逐文件分块复制，不调用整文件 `read_bytes()`。
- [x] 仅在控制台实际取得监听端口后启动后台维护，关闭时有界停止。

## 3. 页面与验证

- [x] `frontend/test/tool-logs-behavior.test.mjs` 先测真实页面脚本的确认/取消、忙碌和失败状态、政策脏表单保护、单飞刷新、清空与历史删除路由差异。
- [x] 更新 `autodrive_console/web/tool-logs.{html,js}` 和 `tool_logs.css`：存储占用与预算、保留设置、立即整理、删除历史、逐文件清空/删除、状态反馈。
- [x] 完成 Backend/Web 最小相关脚本、offline 检查、doctor 与 diff 检查；以临时目录运行原生浏览器 Desktop/窄屏一轮检查，必要修正后一轮确认。
- [x] 使用 requesting-code-review 独立复核文件描述符、租约、生命周期与下载内存边界。
- [x] 更新使用文档并交付源码；现场现有大日志和发布产物保持不动。

## 验证记录

- 日志存储与真实 HTTP 专项：42 项通过（包括 1.5 GiB 稀疏日志、有实际继承追加句柄、真实第二 Python 进程下载租约、权限失败与配置损坏保护）。
- 页面真实脚本边界：9 项通过；完整 Web 863 项、parity 与 Vite 构建通过；offline 109 项通过；Backend/Web doctor 通过。
- 原生浏览器临时服务：1440px 桌面深浅主题、390px 窄屏无横向溢出；确认/取消、清空、单历史与全部历史删除、策略保存与整理验证。模拟 1562 MiB 日志整理为 16 MiB 最新窗口。未访问或删除实车日志。
- 独立复核关闭跨进程旧 FD、下载阻塞轮转、并发 stat 与忙碌期间旧读覆盖四项问题。原始输出 copytruncate 为尽力快照，允许极短窗口丢失少量并发输出。
- Impeccable detector（仅一次）因 HTML parser 依赖缺失降级为正则；未发现规则项。主题、布局与交互以浏览器实测为准，不将降级扫描视为完整对比度认证。
- 全量 Backend 首轮 1647 项通过、1 项旧视频源码断言失败（1257.85 秒）；该断言此前未同步请求新增的 AbortSignal 参数。修正后通过 `PYTEST_ADDOPTS=--lf scripts/test-backend.sh` 失败项重跑；其余生产源码不因该断言修改。新增专项在最终代码上另跑 42 项全通过。
