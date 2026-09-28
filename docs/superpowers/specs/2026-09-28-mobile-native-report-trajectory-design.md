# Aletheia Mobile 原生报告地图轨迹设计

**日期：** 2026-09-28
**状态：** 已完成设计，等待用户审阅
**范围：** `shared/contracts/task_execution.md` 的 Planned 原生报告扩展与 Flutter Mobile 原生报告详情。
**不在范围内：** Backend、PC Web、既有 HTML/CSV 报告行为、ROS、PNG 长图导出、相册保存与报告分享。

## 目标

Mobile 原生报告必须包含现有 HTML 报告已有的全部受控事实，而不能成为只含通过率的摘要页。除结论、统计、任务或轮次、执行时间、反馈、验收覆盖和配送链路证据外，App 必须原生展示每个已归档地图段的冻结底图、实际轨迹、理想路线、虚拟墙、采样点和轨迹完整性告警。

HTML 与 App 不互相解析或转换。Backend 在报告生成阶段从同一份已验证的轨迹记录与冻结地图资产构造结构化原生证据；PC Web 继续按原流程生成/预览/下载 HTML 与 CSV。Mobile 只读取 Planned 原生端点，不打开浏览器、WebView、HTML、CSV、SVG 或任意文件路径。

## 事实基线与边界

现有 HTML 报告已经从轨迹记录的 `segments`、地图元数据、实际点位、理想路线、虚拟墙与完整性告警生成证据图。单个任务或轮次可跨多个地图，且同一地图可以重复进入；因此 Mobile 不能将跨图段的点连接为一条线，也不能使用当前实时观测地图替代历史证据。

| 领域 | 新责任 | 不变边界 |
| --- | --- | --- |
| Backend | 在报告落盘时验证并归档结构化原生证据，按报告身份提供只读内容和报告专属 PNG | 不从 Mobile 接受路径、地图、坐标、报告内容或命令；不改变任务执行和 HTML/CSV 行为 |
| Shared | 为 Planned 原生报告声明字段、端点、分页、大小限制、错误语义与消费者 | 未完成三方验证前不提升为 Existing |
| Mobile | 原生模型、详情卡、手势地图、采样检查器、可达状态与测试 | 不从当前 Observation/Deployment API 拼装历史报告；不缓存为报告文件 |
| PC Web | 忽略新字段，继续现有 HTML/CSV 流程 | 不接入原生轨迹端点 |

报告内的地图/轨迹所有权是 `report_id`。`trajectory_id` 和 cursor 均由 Backend 签发且不透明；它们不编码报告目录、运行 ID、部署项目 ID、文件名或 ROS 标识。任何响应不得包含本机路径、外部 URL、HTML、CSV、SVG、原始 ROS 消息、凭据或未脱敏现场数据。

## 数据模型

原生报告详情的每个 `item` 增加 `trajectory_refs`。每个引用只够让列表确认有无证据，不载入图像或点列：

```json
{
  "trajectory_id": "traj_01J8A",
  "label": "T-003 · 一层大厅",
  "status": "available",
  "sample_count": 624,
  "integrity_warning": null
}
```

`status` 只允许 `available`、`incomplete`、`unavailable`。`sample_count` 是非负有限整数。`integrity_warning` 缺省或为长度受限的纯文本。未知值在 Mobile 中按 `unavailable` 显示，不能猜测轨迹真实存在。

读取一条 `trajectory_id` 后，Backend 返回单一历史地图段：

```json
{
  "schema_version": 1,
  "trajectory_id": "traj_01J8A",
  "item_id": "task_003",
  "label": "T-003 · 一层大厅",
  "map": {
    "label": "一层大厅",
    "resolution_m": 0.05,
    "width_cells": 2048,
    "height_cells": 1536,
    "origin_x_m": -25.0,
    "origin_y_m": -18.0
  },
  "display_paths": [
    {"route_name": "实际轨迹", "kind": "actual", "points": [{"x_m": 1.2, "y_m": 3.4}]},
    {"route_name": "理想路线", "kind": "ideal", "points": [{"x_m": 1.0, "y_m": 3.0}]}
  ],
  "virtual_walls": [[{"x_m": 0.0, "y_m": 0.0}, {"x_m": 4.0, "y_m": 0.0}]],
  "sample_count": 624,
  "integrity_warning": null,
  "samples_next_cursor": "cursor_01"
}
```

地图尺寸、原点、分辨率和全部坐标必须为有限数；分辨率、宽高必须严格大于零。`display_paths` 仅用于首屏绘制，每条路径最多 2,000 点，保留端点、路径顺序和地图切段，不跨段连线。它是 Backend 从同一原始采样点按确定性算法生成的显示级简化，不改变或替代原始采样证据。

实际原始采样由分页端点返回：

```text
GET /api/reports/{report_id}/native/trajectories/{trajectory_id}/samples?cursor=<opaque>&limit=<1..1000>
```

每个采样点具有有限 `x_m`、`y_m`、正整数或零 `timestamp_ns`、长度受限的 `route_name` 和稳定 `sample_index`。同一段内采样按 `sample_index` 严格递增；分页不得重复、遗漏或重排。Mobile 只在用户点选、查看细节或需要提高磁吸精度时继续读取页面，已经加载的数据保持稳定。

## 端点与资源语义

既有端点不变：

```text
GET /api/reports/{report_id}/native?cursor=<opaque>&limit=<1..100>
```

该响应仍分页返回普通项目；其中 `trajectory_refs` 仅为轻量索引。新增的按需端点为：

```text
GET /api/reports/{report_id}/native/trajectories/{trajectory_id}
GET /api/reports/{report_id}/native/trajectories/{trajectory_id}/map.png
GET /api/reports/{report_id}/native/trajectories/{trajectory_id}/samples?cursor=<opaque>&limit=<1..1000>
```

`map.png` 只返回报告生成时冻结的底图，`Content-Type` 必须为 `image/png`，尺寸和字节数由 Backend 设定上限；它不是部署地图或 Observation 当前地图的通用下载接口。Mobile 只能向上述固定端点发起请求，不能消费 JSON 中的 URL 字段。App 可以在内存中保留正在查看的图像与轨迹，但不会保存为用户报告文件。

未知、已删除、无权读取或不属于 `report_id` 的 `trajectory_id` 均返回受控 `404`。非法 report/trajectory identifier、cursor 或 limit 返回 `400`。畸形归档记录不会部分暴露：Backend 将其标记为该段 `incomplete` 或不给出原生报告摘要。原生数据缺失保持现有迁移状态；Mobile 不回退读取 HTML/CSV。

## Mobile 体验与渲染

报告详情保持现有 Apple 工业 HMI 信息层级：

1. 结论、状态、生成时间、耗时和通过/失败/阻塞统计。
2. HTML 对应的运行事实：测试或验收范围、前置配置、覆盖、任务或轮次结果、受控反馈与配送链路证据。
3. 每项的地图轨迹证据卡。每张卡只在用户展开后加载一个 `trajectory_id`，默认将完整地图段和显示级轨迹置入可视区域。
4. 点选轨迹后显示采样检查器：北京时间、路线名、X/Y 米制坐标和采样序号；不推断偏差、导航状态或安全结论。

地图使用 `CustomPaint`，图层固定为：冻结 PNG 底图 → 米制格栅 → 虚拟墙 → 理想路线 → 实际轨迹 → 当前采样点。所有层共享地图元数据导出的同一世界坐标到屏幕变换。切换地图段立刻以不透明画布替换，不能让上一张地图或轨迹残影透出。

单指拖动仅在地图工作区内平移，不带动页面滚动；双指缩放以手势中心为锚点。手势直接更新渲染变换，不加入装饰性动效。系统启用 Reduce Motion 时保留所有地图手势和即时视觉反馈，但取消表面转场与弹性效果。

## 状态与容错

| 情形 | 行为 |
| --- | --- |
| 原生报告缺失/版本未知 | 报告列表显示迁移状态，不能进入伪造的详情 |
| 单条轨迹未归档 | 保留任务事实，显示“未采集到可验证轨迹” |
| `integrity_warning` | 清晰标记“轨迹证据不完整”，仍展示已验证的部分 |
| 地图段/PNG/采样请求失败 | 不清空其他内容；仅该段显示受控错误与重试 |
| 报告或轨迹 404 | 返回报告列表并刷新；不得继续显示为最新证据 |
| 分页追加失败 | 保留已经读取的采样，不拼接重复或无序点 |
| 实时地图变化 | 无影响；报告始终使用自身冻结底图和坐标 |

## Debug Gallery、测试与验收

必须以正式报告详情页和正式 `CustomPaint` 工作区建立 Gallery 状态：完整轨迹、多地图段、无轨迹、不完整轨迹、底图失败、采样分页错误、日光/深色和 Reduce Motion。Mock 只能替换 Provider 数据，不能复制页面。

测试至少验证：

- 与 HTML 报告同源的字段映射，包含测试和验收报告的全部既有受控事实；
- 模型拒绝非法 schema、枚举、数值、坐标、地图尺寸、越界/重排样本和不透明 ID 违规；
- 所有请求只命中固定 report-scoped 端点，cursor/limit 编码正确；
- 世界坐标投影、格栅、路线、虚拟墙、轨迹和点选磁吸共用变换，切图不连线；
- 缩放、平移与页面滚动正确交接；
- 缺失、`404`、加载、分页失败和完整性告警保持证据诚实；
- 现有报告、HTML/CSV、PC Web 及报告删除语义不回归。

Backend 将 Planned 契约提升为 Existing 前，必须为报告归档、端点鉴权、400/404、样本分页和冻结地图一致性提供测试证据；Mobile 必须完成上述模型、Repository、工作区和 Gallery 验证；PC Web 必须确认忽略增量字段仍保持既有 HTML/CSV 流程。

## 非目标与后续

本期不渲染报告长图、不申请照片权限、不保存 PNG、不分享、不离线下载，也不扩展现有实时 Observation 或 Deployment API。后续 PNG 导出只能复用同一原生详情数据与正式组件，在用户明确请求时离屏渲染整份报告；不得以截图、HTML 或浏览器打印替代。
