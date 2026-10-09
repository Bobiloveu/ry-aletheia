# 诊断 ROS Bag 录制设计

## 目标

让实施部署人员在普通测试前通过网页为任意一个指定轮次启用可选 ROS 2 数据包录制。录包必须在该轮任务下发前已成功启动；记录采用快速的 Zstd 文件级压缩，并生成可审计、可删除、可下载的受控归档，供研发分析异常。

## 范围与消费者

- **运行时生产者：** `BagRecordingManager`，由 Backend `RunManager` 在普通测试轮次中调用。
- **Existing 消费者：** Desktop Web 的任务指挥台和新增“诊断录包”页面。
- **非消费者：** Mobile、验收序列、导航/底盘控制、视频、实时观测和已有报告中心。
- 本功能只订阅 ROS 图和启动受控的 `ros2 bag record`；不会发布 Topic、调用服务、修改导航/底盘/定位配置，或改变执行任务的 ROS 控制路径。

## 操作流程

1. 操作者在任务指挥台勾选“本次保留诊断数据包”。
2. 页面读取当前 ROS 图，只列出具有发布者、消息类型唯一且可审计的 Topic；图像、点云和 LaserScan 已迁移至 ShmSDK，必须排除；操作者选择一个或多个 Topic，并在多轮测试中选择一个轮次。
3. 创建测试计划时，Backend 验证轮次范围、Topic 名称和去重规则。到达目标轮次时，Backend 再次读取 ROS 图，确认每个 Topic 的类型与发布者仍符合请求。
4. Backend 验证 ROS 环境并启动受控 recorder。只有 recorder 进程存活、启动宽限期结束且计数审计器已就绪后，才会下发本轮测试任务。
5. 本轮结束、取消或异常后，Backend 受控停止 recorder，等待落盘，读取元数据、哈希文件并形成审计清单。录包失败、退出异常、元数据缺失、选中 Topic 未写入或审计失败时，本轮测试标记失败并保留证据。

录包是可选项；未勾选时普通测试路径的行为保持不变。录包仅适用于普通 `RunManager.start`，不接入验收序列。录包的启动、停止与审查由 Backend 运行线程拥有，浏览器切换页面、刷新、关闭标签页或停止轮询均不会中断录包或改变录制状态。

## 受控 ROS 环境

录包命令不经 Shell 解析，而是以明确参数数组启动。开始前验证：

- `ROS_DISTRO` 已设置；本机当前运行时必须为 `humble`。
- `AMENT_PREFIX_PATH` 非空，并含有当前 ROS 安装前缀。
- `PATH` 中存在可执行 `ros2`，且其解析路径固定写入清单。
- `RMW_IMPLEMENTATION` 与 `ROS_DOMAIN_ID` 被读取并保存为脱敏、受限字段；不接受浏览器传入这些值。
- 所有 recorder、图查询和计数器共享同一份父进程环境快照。未通过预检时拒绝启动该目标轮，不回退到交互 Shell 或默认 ROS 环境。

清单仅记录 ROS 环境中不含凭据的字段和值；不会存储完整环境变量或任何 token。

## 录制与性能策略

命令固定为 ROS 2 Humble 支持的 SQLite3 录包与 Zstd **file** compression：

```text
ros2 bag record --output <controlled-stage/bag> --storage sqlite3 \
  --compression-mode file --compression-format zstd \
  --compression-queue-size 8 --compression-threads 2 \
  --max-cache-size 536870912 <selected topics...>
```

file compression 将压缩移至分段关闭/停止时，降低任务执行期间的实时压缩竞争；512 MiB recorder cache、8 个压缩队列槽和 2 个线程在控制台固定 profile 中使用。浏览器不能编辑命令、路径、缓存、环境或压缩参数。

每个已选 Topic 同时由独立的只读 `rclpy` 计数器订阅。计数器借助 ROS 消息类型动态解析并使用独立 Context；它不发布数据、不调用服务。recorded count 来自 rosbag2 元数据，observed count 来自同一时间窗口的计数器。该差异是“录制链路审查”而非对上游发布端绝对无损的数学证明：没有统一的发布序号协议时，无法证明发布者自身未丢帧。页面和清单必须清楚标示该审查基础。

审查阈值：

| 条件 | 结论 |
| --- | --- |
| 所选 Topic 缺失、bag 不可读、hash 不符、recorder 非正常退出或计数器不可用 | `failed` |
| `recorded >= observed` 或估算丢失率 ≤ 1% | `passed` |
| 估算丢失率 > 1% 且 ≤ 5% | `warning` |
| 估算丢失率 > 5% | `failed` |

若计数器的 QoS 无法连接或运行异常，不能标成通过；保留包并标记审计失败。启动宽限期内进程退出同样阻止任务调用。

## 数据所有权、完整性与恢复

数据根目录为 `WORKSPACE/bag_recordings`，独立于 `reports`。一次录制先写入 `bag_recordings/.staging/<opaque-id>/`，其中包含 `bag/`、recorder stderr/stdout 和运行中状态。停止后：

1. 以 rosbag2 `Info.read_metadata` 验证 `metadata.yaml`，确认 storage、compression、每个所选 Topic 与消息数。
2. 对 staging 内每个普通文件计算 SHA-256 和字节数；拒绝链接、目录逃逸或文件清单外路径。
3. 以临时文件、`fsync` 和原子 rename 写入 `manifest.json`。
4. 将完整 staging 目录原子 rename 为最终目录。

最终名称为 `bag_YYYYMMDD_HHMMSS_<safe-case-alias>_T-<round>_<opaque-id>`；用户不可提供路径或文件名。清单包括 schema、ID、显示名、run/case/round、选中 Topic 类型、时间、固定录制 profile、环境指纹、每文件 hash/大小、总大小、rosbag metadata count、计数器 count、审计结果与错误。

控制台启动时扫描遗留 staging 目录，将其标记为 `incomplete` 归档，绝不静默删除或伪装成可用数据。用户删除只能删除 Backend 发现的、具有受控 ID、位于归档根目录下且非活动的目录；符号链接、路径遍历和活跃目录一律拒绝。

## HTTP API

所有 API 仅给 Desktop Web 使用；Mobile 非消费者。

| Endpoint | 行为 |
| --- | --- |
| `GET /api/bag-recordings/topics` | 查询当前 ROS 图并返回可选择的 `{name,type,publisher_count}`，仅含有发布者和唯一类型的公开 Topic。 |
| `GET /api/bag-recordings` | 返回归档受控摘要：ID、名称、用例、轮次、时间、总大小、审计状态与错误。 |
| `GET /api/bag-recordings/{id}` | 返回已过滤的完整清单详情。 |
| `GET /api/bag-recordings/{id}/download` | 以受控 tar 流下载归档，不接受路径。 |
| `DELETE /api/bag-recordings/{id}` | 删除一个非活动受控归档。 |
| `POST /api/runs` 增量字段 `bagRecording` | `null` 或 `{attemptIndex:number,topics:string[]}`；其它字段不变。 |

`POST /api/runs` 的 `bagRecording` 只会在指定轮次触发；服务端拒绝空列表、重复 Topic、超过 32 个 Topic、隐藏 Topic、非法 Topic 名、失效/多类型/无发布者 Topic 及不在 `1..count` 的轮次。

## 用户界面

任务指挥台新增“诊断录包（可选）”卡片：开关、目标轮次、刷新可录 Topic、搜索和多选、所选数量以及审计阈值说明。未选择 Topic 时不能提交开启状态。测试结果表对目标轮次展示录包名称、大小和审计状态。

新增“诊断录包”导航页：显示归档名称、用例、轮次、时间、大小、压缩方式和审计结论；可打开审计详情、下载、删除。删除需要页面明确确认。该页不展示 ROS 环境变量原文、命令行或内部绝对路径。

## 验证

- Backend 单元测试覆盖 request 校验、环境预检、固定命令、目标轮次独占启动、启动失败不下发任务、停止/审计、完整性阈值、归档恢复、路径约束和删除。
- Web 模块测试覆盖 request payload、关闭时不传录包、轮次/Topic 表单校验及归档显示状态。
- 更新 `shared/contracts/task_execution.md`，明确消费者、API、数据边界和验证影响。
- 运行定向 Backend 与 Web 测试；依照用户要求，不构建离线升级包、不部署或重启车端程序。
