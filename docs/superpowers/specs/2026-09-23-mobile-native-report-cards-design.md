# Aletheia Mobile 原生测试报告卡片设计

**日期：** 2026-09-23
**状态：** 已确认设计；Shared 契约拟议为 Planned，等待 Backend 实现后才可成为 Existing。
**范围：** Mobile 原生报告列表与详情页、Debug Gallery、`shared/contracts/task_execution.md` 的跨团队实现约定。
**明确不在范围内：** `frontend/`、PC Web 现有 HTML/CSV 行为、Backend 实现、ROS、报告导出 PNG 与系统相册写入。

## 目标

将 Mobile 的测试报告从“打开 HTML / 下载 CSV 到外部浏览器”改为原生、结构化、可访问的 App 报告体验。操作者在 App 中读取摘要、结论、指标、异常任务、任务明细和已验证的轨迹证据摘要；不解析 HTML，不显示 CSV，也不将报告 URL 交给浏览器。

报告数据必须由车端在报告生成阶段一次性归档。列表读取轻量摘要，详情在操作者进入后按需分段读取，避免重复生成 HTML、客户端解析或一次性传输大报告。

第二期再将同一份原生报告详情渲染为整份纵向 PNG 并请求用户授予系统相册写入权限。本期不新增相册权限、图片编码、文件下载或分享依赖。

## 范围与所有权

| 领域 | 本期责任 | 不变边界 |
| --- | --- | --- |
| Mobile | 定义/消费结构化模型，渲染报告卡片与详情，真实 Gallery 状态、测试 | 不访问浏览器、不解析 HTML/CSV、不上传或改写报告 |
| Shared | 记录 Planned 的新字段、读取端点、分页、兼容性、消费者与迁移条件 | 不将新端点标记为 Existing，直到 Backend 验证实现 |
| Backend | 后续负责人依照 Shared 生成/保存结构化摘要与详情并实现端点 | 不在本期改动；不把路径、HTML、CSV 或原始 ROS 数据暴露给 Mobile |
| PC Web | 继续消费原有 `GET /api/reports` 字段与 HTML/CSV 入口 | 本期不修改 `frontend/`，可忽略增量字段 |

`DELETE /api/reports/<filename>` 的既有受控删除语义保持不变。本期 Mobile 将继续只删除来自车端索引的受限报告；新报告卡片不制造本地文件路径。

## Shared 契约草案

### 兼容的摘要扩展

既有 `GET /api/reports` 不删除 `filename`、`size`、`modified_at`、`csv_filename`、`report_type` 或 `title`。每个报告可增量添加 `native_report`；缺失表示当前车端尚未生成原生数据，不代表报告不存在。

```json
{
  "filename": "validation_20260923_103000.html",
  "size": 3584,
  "modified_at": "2026-09-23T10:30:00+08:00",
  "csv_filename": "validation_20260923_103000.csv",
  "report_type": "test",
  "title": "自动测试运行报告",
  "native_report": {
    "schema_version": 1,
    "report_id": "rpt_01J8W8V5MZ0DJK2D7S6Y",
    "kind": "test",
    "title": "路径验证 · 第 3 次运行",
    "status": "failed",
    "created_at": "2026-09-23T10:30:00+08:00",
    "duration_ms": 184000,
    "summary": {
      "total": 12,
      "passed": 10,
      "failed": 1,
      "blocked": 1,
      "pass_rate": 83.3
    },
    "headline": "第 8 项因定位收敛超时未通过。"
  }
}
```

允许的 `kind`：`test`、`acceptance`。允许的 `status`：`passed`、`failed`、`blocked`、`cancelled`、`incomplete`、`unknown`。未知枚举在 Mobile 中必须保守显示为“数据不完整”，不得猜测“通过”。摘要数字必须为非负有限数；`pass_rate` 可为空，并且不能覆盖由 `passed / total` 可得出的事实。

### 按需详情读取

新增 Planned 的只读端点：

```text
GET /api/reports/{report_id}/native?cursor=<opaque>&limit=50
```

`report_id` 是后端签发、稳定且不透露文件系统路径的标识。`cursor` 也必须不透明；`limit` 默认 50、最大 100。响应的固定元数据不会随分页改变，明细只返回当前页：

```json
{
  "report": {
    "schema_version": 1,
    "report_id": "rpt_01J8W8V5MZ0DJK2D7S6Y",
    "kind": "test",
    "title": "路径验证 · 第 3 次运行",
    "status": "failed",
    "created_at": "2026-09-23T10:30:00+08:00",
    "duration_ms": 184000,
    "summary": {"total": 12, "passed": 10, "failed": 1, "blocked": 1, "pass_rate": 83.3},
    "headline": "第 8 项因定位收敛超时未通过。",
    "context": [
      {"label": "测试计划", "value": "路径验证"},
      {"label": "机器人", "value": "Aletheia-01"}
    ],
    "evidence": [
      {"kind": "trajectory", "label": "轨迹证据已归档", "status": "available"}
    ]
  },
  "items": [
    {
      "item_id": "task_8",
      "title": "定位收敛验证",
      "status": "failed",
      "duration_ms": 30000,
      "summary": "定位收敛超时。",
      "detail": "在受控时限内未达到预期误差范围。"
    }
  ],
  "next_cursor": null
}
```

`context` 只允许标签和值的受控文本；`evidence` 仅表示证据类型、展示标签和可用状态，不能返回任意路径、下载 URL、HTML、CSV、SVG 或原始传感器内容。`items` 的 `status` 使用同一保守枚举。后端必须对 `report_id` 校验归属与存在性；未知或已删除报告返回当前项目统一的 JSON 错误格式。Mobile 不缓存网络响应为“报告文件”。

### 迁移

1. Backend 先在新生成的报告旁写入经过校验的原生摘要/详情数据；历史报告可逐步补建，不能在请求时解析 HTML。
2. `GET /api/reports` 只在原生数据完整时加入 `native_report`。
3. Backend 为报告详情提供分页读取与定向测试后，Shared 才将该端点从 Planned 提升为 Existing。
4. Mobile 在原生摘要缺失或 schema 不支持时显示迁移说明，绝不回退浏览器或 HTML/CSV。
5. PC Web 无须改动，继续使用旧字段与现有文件入口。

## Mobile 信息架构与视觉设计

### 报告列表

- 页面标题为“测试报告”，副文案说明“以车端结构化结果为准”。删除任何“在浏览器打开”“下载 HTML”“下载 CSV”文案和图标。
- 每张卡片以报告类型图标、标题、语义状态 pill 开始；不使用营销式大图、渐变、玻璃层或装饰性图表。
- 卡片次行显示生成时间和总耗时。第三行固定为三项轻量指标：任务数、通过、异常（失败与阻塞）。有异常时只显示一行 `headline`。
- 卡片整面点击进入详情，采用已有即时按压反馈；删除保留在明确的 overflow 操作内并继续二次确认。
- 原生摘要缺失的旧报告使用稳定的 `unknown` 状态卡片，说明“车端尚未提供原生报告数据”，不提供浏览器回退。

### 原生报告详情

- 详情页保留系统返回路径，使用当前二级页面的短、低位移转场；页面不使用长 HTML WebView。
- 顶部总览是结论、类型、生成时间、耗时。其后是 2×2 或可换行的关键指标区，不以大量小卡片分散注意力。
- “异常任务”只在异常存在时展示，默认优先于“全部任务”。每一项只显示标题、状态、时长和一条受控原因；详情文本按需展开，不直接塞入列表。
- “全部任务”依赖服务端 cursor 分页。滚动到底才读取下一页，已经显示的项目不会在后续页到达时重新排序。
- 轨迹证据只显示已归档/不可用等摘要，不在本期重新引入地图、SVG 文件或浏览器预览。
- 保持 Aletheia 的深色 HMI 和日光白蓝主题、系统字体、44pt 以上的点按目标、Dynamic Type、`MediaQuery.disableAnimationsOf`。状态改变只使用既有局部状态过渡，不对报告列表逐项做循环、stagger 或大面积动画。

## 状态、错误与安全

| 状态 | App 行为 |
| --- | --- |
| 列表加载 | 保持正式 loading UI；不显示旧缓存为当前事实 |
| 无报告 | 显示无报告引导 |
| 网络失败 | 明确错误和重试；不打开浏览器 |
| 原生数据缺失 | 显示车端待同步卡片；不伪造报告内容 |
| 详情加载/分页 | 只在详情局部显示进度，不遮挡已经阅读的结果 |
| 详情失败/已删除 | 保留已看到的稳定内容，显示可重试或返回列表的明确操作 |
| 删除 | 继续使用受控的服务端报告删除与明确确认；成功后刷新列表 |

所有错误必须来自受控的后端错误文本或 App 本地固定文案；页面不接受路径、文件 URL、HTML 或任意富文本作为显示内容。

## Debug Gallery、测试与验收

Gallery 必须使用正式 `ReportsScreen` / 新详情组件与 fake Provider，新增下列状态：

1. 原生报告列表，含通过和存在异常的摘要卡片。
2. 原生报告详情完整状态。
3. 详情加载、详情错误与分页追加。
4. 旧报告/车端未升级的原生数据缺失状态。
5. 深色、日光和 Reduce Motion 下的同一正式组件。

测试覆盖：JSON 模型的保守解析、未知枚举与非法数字、只读详情 URL 编码、cursor 分页顺序、列表/详情 loading-error-legacy UI、删除确认与非浏览器回退。验证仅运行受影响的 Mobile 测试和 `scripts/test-mobile.sh`；既有 Gallery Golden 基线问题单独记录，不重录或提交失败图片。

## 非目标与后续阶段

- 本期不实现 PNG 长图渲染、相册权限、保存到系统文件、分享或下载队列。
- 第二期复用原生详情数据和正式详情组件，以离屏、受限分辨率的长图渲染器导出 PNG；只在操作者明确点击导出时请求权限并保存到系统相册。
- 本期不修改 PC Web、后端实现、HTML/CSV 历史归档、机器人任务执行、ROS 或控制接口。
