# 手动场景诊断录包设计

## 目标

在既有自动化测试轮次录包之外，提供一个由操作者明确开始和停止的手动场景录包会话。它用于记录人工遥控、静止观察或感知复现场景；不发送任务、不发布控制 Topic、不改变底盘、导航、定位或 Supervisor 配置。

## 范围与边界

- Backend 继续由 `BagRecordingManager` 独占 recorder 子进程、DDS 计数器、审查和归档目录。
- 手动会话与自动化测试录包互斥。任一活动 recorder 存在时，另一个入口拒绝启动并说明原因。
- 手动会话不依赖浏览器连接或页面可见性。切换页面、刷新或关闭标签页都不停止录制。
- 所选 Topic 继续只能来自 `GET /api/bag-recordings/topics` 的受控发现结果；共享内存图像、点云和 LaserScan 继续排除。
- 手动会话只能录制 1–32 个 Topic。场景名称可选，长度受限的纯文本；空名称由 Backend 生成时间名称。
- 时长只能为 5、10、15 或 20 分钟，默认 15 分钟。达到期限由 Backend 自动停止、审查并归档。

## 数据模型

`ManualRecordingRequest` 是受控输入：`{topics: string[], durationMinutes: 5|10|15|20, label?: string}`。浏览器不得传递 ROS 命令、文件路径、压缩参数、环境变量、计时结束时间或归档 ID。

`ActiveRecording` 扩展以下受控元数据：

- `source`: `test_attempt | manual`
- `label`: 清洗后的人工场景名称或空字符串
- `deadline_monotonic`: 仅在运行期使用，不写入请求

归档清单和摘要添加 `source`、可选 `label`、`duration_limit_seconds` 与实际 `duration_seconds`。自动化测试历史清单缺失这些字段时按 `source=test_attempt` 兼容；其既有展示保持不变。

## Backend 生命周期与接口

新增单例 `ManualRecordingController`，只封装手动会话状态和定时停止；实际 start/stop 仍委托 `BagRecordingManager`。它用锁保护一个 active session；开始前验证请求、复查 Topic、验证 ROS Humble 运行环境、启动 recorder 和计数器。成功后启动一个 daemon timer，截止时调用同一停止路径。显式停止和超时停止竞争时只允许一个调用完成审查和归档。

接口：

- `GET /api/bag-recordings/manual`：返回受控状态 `{state: idle|recording|finalizing, label?, topic_count?, started_at?, deadline_at?, remaining_seconds?}`。
- `POST /api/bag-recordings/manual`：仅接受上述请求结构；成功创建会话并返回状态。运行中或存在测试录包时返回受控冲突。
- `POST /api/bag-recordings/manual/stop`：不接受请求体；将当前会话交给审查流程并返回 `finalizing` 状态。空闲时返回受控冲突。

自动化 `RunManager` 在准备其目标轮录包前检查没有手动会话；手动控制器在开始前检查 `RunManager` 没有活动录包。该互斥只保护 recorder，不阻塞未启用录包的普通测试，也不控制车辆。

## Web 流程

`/bag-recordings.html` 增加“手动场景录制”卡片：可选场景名称、时长选择、Topic 选择入口、所选摘要、开始按钮，以及录制中的倒计时和“停止并审查”。配置入口复用 Topic 页面，但区分 `manual` 和 `test` 草稿，防止覆盖测试轮次配置。手动草稿只有 Topics；没有目标轮次。

归档清单把手动包显示为“手动场景”，展示名称、实际持续时间和审查状态；自动测试归档继续显示其用例与轮次。界面不显示原始命令、环境变量、绝对路径或 ROS 内部错误码。

## 失败、恢复与审查

启动任一前置条件失败时不会形成活动会话。超时、显式停止、关闭控制台和 recorder 异常均走 `BagRecordingManager.stop` 的同一审查和原子发布路径；控制台异常退出留下的 staging 目录按既有规则恢复为未完成归档。倒计时只作为界面提示，Backend deadline 是唯一权威。

## 验证

- Backend 单元测试：手动请求校验、开始/停止、截止自动停止、开始竞争、显式停止与 timer 竞争、自动测试录包互斥、历史清单兼容。
- HTTP 单元测试：三条手动会话接口的成功、冲突和状态响应。
- Web 模块测试：独立草稿、用户文案、运行中状态和不暴露命令/环境。
- 定向 Backend/Web 检查；仅在用户另行授权后打包、上传、升级，并在车端验证实际 recorder。
