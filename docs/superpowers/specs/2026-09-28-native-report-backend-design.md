# Mobile 原生报告 Backend 归档设计

## 目标

为 Flutter Mobile 提供 `shared/contracts/task_execution.md` 规定的原生报告、历史地图轨迹、冻结底图与按需样本 API。新报告在落盘时归档原生数据；历史报告从已有结构化轨迹记录和验收资产清单渐进回填。Mobile 不读取 HTML、CSV、SVG、文件名、运行路径或当前实时地图。

PC Web 继续使用现有 HTML/CSV 预览、下载与 filename 删除行为，不成为新接口消费者。

## 数据来源与归档边界

- 自动测试报告的唯一历史来源是 `run_<id>_trajectory` 中的结构化轨迹 JSON；验收报告的唯一历史来源是其 `.assets.json` 声明的受控轨迹目录及其中的结构化记录。
- 回填绝不解析 HTML 或 SVG，不从当前 Observation/Deployment 地图重新推断历史证据，也不接受客户端提供的路径、地图、坐标或报告内容。
- 每份可验证报告生成一个受控的 native sidecar。sidecar 保存随机、不透明的 `report_id`、稳定 `item_id`/`trajectory_id`、已验证的报告摘要、项目、轨迹段元数据、显示级路径和样本分页信息；不包含文件系统路径或 URL。
- 每个轨迹段在归档时复制/冻结其底图为受限 PNG，并记录其受限资源引用。所有 sidecar 与 PNG 先写临时文件、`fsync` 后原子替换，避免 Mobile 读到半份归档。

## 新报告与历史报告

新自动测试/验收报告完成 HTML/CSV 写入后，调用同一 `NativeReportArchive` 将同源结构化轨迹、地图元数据、理想路线、虚拟墙和采样归档为 schema v1。归档失败不回滚既有 HTML/CSV，但该报告不出现在原生索引，并记录受控诊断。

控制台启动后启动一个单线程、低优先级的回填 worker。它只枚举 reports 根目录下已验证的报告名，逐份检查是否已有有效 sidecar；缺失时从上述结构化来源创建归档。每批次工作量受时间/数量限制并让出执行权，不能延迟 HTTP 监听、测试执行或报告生成。无法验证的历史资料跳过并留下可审计的受控日志；Mobile 在回填完成前保持迁移状态，不接触旧文件格式。

## 只读 API

- `GET /api/reports` 保持所有 Existing 字段不变；仅完整、验证通过的 sidecar 追加 `native_report`。
- `GET /api/reports/{report_id}/native?cursor=&limit=` 只读取该报告的摘要和分页项目，默认 50、最大 100。
- `GET /api/reports/{report_id}/native/trajectories/{trajectory_id}` 返回单一地图段的受限元数据、显示级路径、虚拟墙与样本首页 cursor。
- `GET /api/reports/{report_id}/native/trajectories/{trajectory_id}/map.png` 返回该段冻结的 `image/png`，受固定像素与字节上限约束。
- `GET /api/reports/{report_id}/native/trajectories/{trajectory_id}/samples?cursor=&limit=` 返回按 `sample_index` 严格递增的样本页，默认和最大均按契约限制为 1,000。

所有 ID 都必须符合 backend 签发的不透明 token 格式；畸形 report/trajectory ID、cursor 或 limit 返回受控 400，未知、已删除或不属于该报告的有效 ID 返回 404。响应仅包含契约允许的受控文本、有限数值和坐标，永不包含路径、文件名、URL、HTML、CSV、SVG、ROS 原文、凭据或现场未脱敏数据。

## 生命周期与兼容性

既有报告删除继续以 filename 为唯一入口；删除成功时同一事务范围内删除其 native sidecar 和受控冻结 PNG。`report_id` 永不替代 filename 删除接口。

旧报告、无轨迹报告或无法验证的历史记录没有 `native_report`；既有 PC、下载与 HTML/CSV 流程不受影响。Mobile 将缺失或畸形原生数据视为不可导航的迁移状态，不回退解析文件。新接口不调用 ROS、任务、定位、地图或控制服务。

## 验证与契约升级

Backend 测试覆盖新报告归档、历史回填、冻结底图、显示路径上限、样本稳定分页、JSON 和 PNG 边界、无路径泄漏、400/404、删除联动及 Existing `GET /api/reports` 兼容。PC Web 测试确认忽略增量字段后原有报告流程不变。Mobile 侧以锁定 Flutter 环境验证模型、Repository 和轨迹工作区的缺失、畸形、分页、错误与多地图状态。

所有 Backend、PC 和 Mobile 证据完成后，将 `Mobile Native Reports` 及地图轨迹端点从 `Planned` 提升为 `Existing`，记录 runtime producer、Mobile consumer、PC 非消费者和验证命令。
