# 机器人日志下载实施计划

> **For implementation:** 必须按 `executing-plans` skill 逐项执行、验证和记录，不得跳过测试先写整块功能。

**目标：** 在 Desktop Web 新增独立“机器人日志”页面。维护人员可维护当前小车本机日志目录、按文件名筛选并将选中的原始日志逐个下载到打开网页的电脑；不改动既有“工具日志”、ROS、视频、任务、升级或 Mobile。

**架构：** 后端拥有本机路径和受控文件读取权限。`RobotLogStore` 从 `SettingsStore` 中已验证的 `robot_logs.sources` 读取目录，以稳定 source/file ID 代替路径暴露给浏览器；HTTP 仅传控制数据和原始文件流。浏览器用 `fetch` 获取清单、用受控下载 URL 逐个触发浏览器保存，浏览器自身处理保存位置。

**技术栈：** Python 3.10 `http.server`、`pathlib`、现有 `SettingsStore`、原生静态 HTML/CSS/JS、pytest、Pixi frontend check。

---

## 接口与数据模型（先作为契约，再写代码）

`RobotSettings.robot_logs` 的升级安全默认值：

```json
{
  "sources": [
    {"id": "drivers", "name": "drivers", "path": "/opt/ry/Log/supervisor-logs/stdout/today/drivers"},
    {"id": "modules", "name": "modules", "path": "/opt/ry/Log/supervisor-logs/stdout/today/modules"},
    {"id": "lightning", "name": "lightning", "path": "/opt/ry/workspace/lightning_logs"}
  ]
}
```

| API | Request | Response / safety rule |
| --- | --- | --- |
| `GET /api/robot-logs/sources` | — | `sources[]`：`id,name,path,status,message,file_count`；路径只在目录管理响应中出现。 |
| `PUT /api/robot-logs/sources` | `{sources:[{id?,name,path}]}` | 整体原子保存；新条目由后端分配 ID，已有条目保留 ID。无效条目使整个请求失败。 |
| `GET /api/robot-logs/sources/{id}/files?query=` | 受控 source ID；可选 URL-encoded 文件名关键词 | `files[]`：`id,name,size_bytes,modified_at`，绝不包含路径或文件内容。 |
| `GET /api/robot-logs/sources/{id}/files/{file_id}/download` | 受控 source/file ID | 原始文件流 + `Content-Disposition: attachment`；下载前重新解析并验证该文件。 |

限额：单文件 256 MiB；一次浏览器批量下载最多 100 个文件；不递归、不跟随符号链接、不运行 shell。后端对 `not found`、权限、轮转消失和拒绝配置写结构化 Aletheia 工具日志，但不向浏览器泄露服务器路径。没有 ZIP、临时归档或服务器端下载队列。

---

### Task 1：先为日志源配置与文件访问写失败测试

**Files:**
- Create: `tests/test_robot_logs.py`
- Modify: `tests/test_offline_modules.py`

1. 用 `TemporaryDirectory` 建立可读目录、普通文件、嵌套目录、符号链接、缺失目录与权限失败的 fixture；不触碰实际 `/opt/ry` 日志。
2. 写 `SettingsStore` 的预期测试：默认三源、旧 `console.json` 自动补齐、保存/重新加载、空名称、重复 ID、相对路径、`..`、敏感目录和 SSH 私钥路径均拒绝。
3. 写 `RobotLogStore` 的预期测试：元数据排序与文件名 `query` 筛选；清单不含路径；目录、符号链接、路径逃逸、超限文件与轮转后消失文件均不可归档。
4. 写下载测试：原始内容与 `Content-Disposition` 文件名正确；受控文件 ID、超限文件、轮转后消失和客户端中断被安全处理；确认没有创建临时 ZIP 或服务端下载队列。
5. 在 `tests/test_offline_modules.py` 添加静态边界回归：新页面存在并加载共享 shell，`robot-logs.html` 不在 `MOBILE_PAGE_NAMES`，现有 `/api/tool-logs*` 断言不变。

**验证命令：** `pixi run python -m pytest -q tests/test_robot_logs.py`（预期先失败，因为实现尚不存在）。

### Task 2：实现配置模式和受控机器人日志存储层

**Files:**
- Modify: `autodrive_console/settings.py`
- Create: `autodrive_console/robot_logs.py`

1. 在 `settings.py` 定义不可变的三项默认源与 `RobotSettings.robot_logs`，加载旧配置时深度合并默认值；保存时保留该字段，避免升级覆盖操作员配置。
2. 集中实现 `SettingsStore._validate_robot_logs()`：列表长度、名称长度/空白、稳定 ID 格式及唯一性、绝对且规范的路径、禁止根/系统伪文件目录和常见 SSH 私钥目录；使用 `Path` 成分比较而非字符串前缀。
3. 新建 `RobotLogStore`，令其只通过 `SettingsStore` 读取和原子保存 source 配置；新增项 ID 仅由后端生成，配置更新全量验证后再写入。
4. 实现 source 健康探测、非递归普通文件枚举、mtime 降序、文件名大小写不敏感关键词筛选、opaque file ID 映射和每次下载前的 `lstat/resolve/is_relative_to` 复验。
5. 实现每次下载前的安全复验，并以固定大小块将原始文件直接写入 HTTP 响应；不创建 ZIP、临时归档、批量缓存或服务端下载队列。

**验证命令：** `pixi run python -m pytest -q tests/test_robot_logs.py tests/test_offline_modules.py`。

### Task 3：把 HTTP API 与下载生命周期接入控制台

**Files:**
- Modify: `web_console.py`
- Modify: `tests/test_robot_logs.py`

1. 在模块初始化处创建一个使用 `SETTINGS` 与 `LOGGER` 的 `RobotLogStore`；不得改动 `ToolLogStore` 的 allowlist 和任何 `/api/tool-logs*` 路由。
2. 在 `do_GET` 添加 sources/files/download 三条受控路由，在 `do_PUT` 以单一路径分发 acceptance criteria 与 robot sources。配置请求体有小的 JSON 长度上限；未知 source/file/非法 JSON 返回 400 或 404，不回显路径。
3. 新建 `_download_robot_log_file()`：下载开始前重新验证文件，再写正确的内容类型、`Content-Disposition` 和 `Content-Length`，并以固定块写到 `wfile`；浏览器断开、`BrokenPipeError` 和读文件失败均按现有日志策略处理，不创建 ZIP 或临时文件。
4. 保持页面 Desktop-only：添加 `/robot-logs.html` 的显式静态路由；不加入 `MOBILE_PAGE_NAMES`、`MOBILE_VUE_PAGES` 或 Flutter 导航。
5. 在 HTTP handler 测试中覆盖正常原始文件下载头/内容、配置保存、源不存在、非法 body、下载中断和不泄露路径。

**验证命令：** `pixi run python -m pytest -q tests/test_robot_logs.py tests/test_offline_modules.py`。

### Task 4：实现独立、可维护的 Desktop 日志下载页面

**Files:**
- Create: `autodrive_console/web/robot-logs.html`
- Create: `autodrive_console/web/robot_logs.js`
- Create: `autodrive_console/web/robot_logs.css`
- Modify: `autodrive_console/web/app_shell.js`
- Modify: `tests/test_offline_modules.py`

1. 使用现有 shell、颜色 token、表单、表格和 focus style；新增侧栏“机器人日志”入口，active route 支持该页，不改变工具日志入口含义。
2. 提供清晰的目录管理区：名称与本机目录成对编辑、添加、删除、保存；只显示简短的敏感目录限制与当前保存/校验状态，不出现 SSH/SFTP 概念。删除先有明确二次确认，保存失败时保留用户输入。
3. 将源状态放在可点击选择器中；不可读源显示原因和“刷新”，不会阻断其它源。选择源后加载文件清单。
4. 文件表格只显示文件名、大小、修改时间；关键词实时筛选或刷新时以 `query` 请求；支持全选当前筛选结果、单选、保留选中数量与累计大小。
5. “下载选中日志”依次触发每个受控下载 URL，保留原始日志文件名。页面先明确提示浏览器会逐个下载所选文件；按钮 busy 时不可重复提交，错误不清除选择。下载由浏览器保存到当前网页电脑，不请求或显示机器人保存目录。
6. 遵循 Impeccable 的 UI 约束：信息密度适中、风险操作与普通检索分区、键盘可达、窄桌面宽度不截断关键操作；不对 Mobile 页面和原工具日志作视觉重构。

**验证命令：** `pixi run frontend-check`；静态测试；在本机启动控制台后浏览器验证可读/不可读、配置校验、文件筛选和原始日志下载。

### Task 5：契约、文档、打包与完整回归

**Files:**
- Create: `shared/contracts/robot_logs.md`
- Modify: `shared/contracts/README.md`
- Modify: `README.md`
- Modify: `PROJECT_OVERVIEW.md`
- Modify: `tests/test_offline_modules.py`
- Verify only: `ry-aletheia.spec`

1. 将新接口写入 `robot_logs.md`（Status: Existing only after implementation），明确 Backend 为执行方、Desktop Web 为唯一 Existing 消费者、Mobile 非消费者，包含字段、状态、大小限制、路径隐私、浏览器下载和兼容性规则；在 contracts index 链接。
2. 在 README/PROJECT_OVERVIEW 说明它与工具日志分离、如何管理来源、浏览器下载行为及不会影响机器人运行；不记录真实现场日志或私密路径以外的默认配置事实。
3. 确认 PyInstaller spec 已通过整个 `autodrive_console/web` 目录收集新静态文件，无需把日志、下载临时文件、缓存或构建产物写入 spec/仓库。
4. 运行 `git diff --check`，再执行 `scripts/test-backend.sh`、`scripts/test-web.sh` 与 `./scripts/doctor.sh --profile backend`、`./scripts/doctor.sh --profile web`。若任何检查失败，先定位根因，禁止把失败称为通过。
5. 手工回归：工具日志仍可查看/下载；报告下载、任务、视频、实时观测与升级 API 不受影响；配置重启后仍存在；页面关闭后不留下任何下载临时文件。

**完成标准：** 每个新 API 与配置安全边界有自动化覆盖，完整 backend/web 检查通过，实际浏览器将每个原始日志下载到浏览器客户端，既有工具日志没有被改写或混入机器人日志。
