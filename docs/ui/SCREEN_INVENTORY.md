# Aletheia Screen Inventory

此清单由 `mobile/lib/debug_ui/gallery_manifest.dart` 自动生成。
每一行都是可在仅 Debug Gallery 中复现的真实页面或真实组件状态。

| 一级模块 | 页面 | Route | 状态 | 真实触发条件 | Gallery | Screenshot |
| --- | --- | --- | --- | --- | --- | --- |
| 设置 | 应用设置 | `/settings` | 本机偏好与版本信息 | 从一级设置入口打开 | 可预览 | [已生成](screens/settings/app-settings-ready.png) |
| 设置 | 检查更新 | `/settings/update` | 当前开发版本未接入在线服务 | 从设置的检查更新入口打开 | 可预览 | [已生成](screens/settings/update-ready.png) |
| 设置 | 问题与建议 | `/settings/feedback` | 已填写并附加截图 | 从设置打开问题反馈 | 可预览 | [已生成](screens/settings/feedback-draft.png) |
| 设置 | 问题与建议 | `/settings/feedback` | 截图与诊断摘要已选择 | 填写反馈后继续查看附加信息 | 可预览 | [已生成](screens/settings/feedback-attachments.png) |
| 首页 | 首页 | `/robot` | 未连接 | 首次打开或主动断开连接 | 可预览 | [已生成](screens/robot/disconnected.png) |
| 首页 | 首页 | `/robot` | 正在恢复连接 | 保存的机器人地址正在验证 | 可预览 | [已生成](screens/robot/restoring.png) |
| 首页 | 首页 | `/robot` | 正在连接 | 用户提交机器人地址后 | 可预览 | [已生成](screens/robot/connecting.png) |
| 首页 | 首页 | `/robot` | 已连接，健康正常 | 连接和健康检查均成功 | 可预览 | [已生成](screens/robot/connected.png) |
| 首页 | 首页 | `/robot` | 连接失败 | 地址不可达或服务未响应 | 可预览 | [已生成](screens/robot/connection-failed.png) |
| 首页 | 首页 | `/robot` | 网络异常 | 已连接后的网络请求失败 | 可预览 | [已生成](screens/robot/network-error.png) |
| 首页 | 首页 | `/robot` | 健康状态异常 | 健康检查返回异常状态 | 可预览 | [已生成](screens/robot/health-warning.png) |
| 观测 | 实时观测 | `/observation` | 需要连接机器人 | 未连接时打开观测 | 可预览 | [已生成](screens/observe/disconnected.png) |
| 观测 | 实时观测 | `/observation` | 正在准备地图 | 进入观测且地图尚未返回 | 可预览 | [已生成](screens/observe/loading.png) |
| 观测 | 实时观测 | `/observation` | 等待活动地图 | 服务可用但未提供地图 | 可预览 | [已生成](screens/observe/empty-map.png) |
| 观测 | 实时观测 | `/observation` | 观测暂不可用 | 观测服务暂不可用 | 可预览 | [已生成](screens/observe/unavailable.png) |
| 观测 | 实时观测 | `/observation` | 读取失败 | 地图请求失败 | 可预览 | [已生成](screens/observe/error.png) |
| 观测 | 实时观测 | `/observation` | 地图、位置、点云正常 | 地图与遥测已收到 | 可预览 | [已生成](screens/observe/live-map.png) |
| 观测 | 实时观测压力场景 | `/observation` | 原始全尺寸地图；60 Hz 位姿、8 Hz / 3,000 点云 | 仅 Debug Gallery：验证地图渲染与持续遥测压力 | 可预览 | 待生成 |
| 观测 | 实时观测 | `/observation` | 日间模式 | 在设置中切换日间模式后进入观测 | 可预览 | [已生成](screens/observe/live-daylight.png) |
| 观测 | 实时观测 | `/observation` | 位置或点云断流 | 独立遥测流断开或超过新鲜度阈值 | 可预览 | [已生成](screens/observe/telemetry-interrupted.png) |
| 观测 | 相机 | `/observation` | 正在读取视频状态 | 进入相机工作区 | 可预览 | [已生成](screens/observe/video-loading.png) |
| 观测 | 相机 | `/observation` | 没有可用视频流 | 视频状态成功但没有流 | 可预览 | [已生成](screens/observe/video-empty.png) |
| 观测 | 相机 | `/observation` | 视频流等待可用 | 视频流存在但尚未上线 | 可预览 | [已生成](screens/observe/video-waiting.png) |
| 观测 | 相机 | `/observation` | 视频流离线 | 视频流返回 offline | 可预览 | [已生成](screens/observe/video-offline.png) |
| 观测 | 相机 | `/observation` | 六路视频可选，主画面正常 | 视频服务返回多个 online 流 | 可预览 | [已生成](screens/observe/video-ready.png) |
| 观测 | 相机 | `/observation` | 视频状态读取失败 | 视频状态接口请求失败 | 可预览 | [已生成](screens/observe/video-error.png) |
| 工具 | 工具 | `/tools` | 未连接 | 未选择可用机器人 | 可预览 | [已生成](screens/tools/disconnected.png) |
| 工具 | 工具 | `/tools` | 可用工具入口 | 机器人已连接 | 可预览 | [已生成](screens/tools/connected.png) |
| 工具 | 运行配置 | `/tools/runtime` | 受控参数与依赖编排 | 连接机器人后打开运行配置 | 可预览 | [已生成](screens/tools/runtime-settings-ready.png) |
| 工具 | 场景前置配置 | `/tools/scenario-setup` | 方案可预览，当前常规配置 | 连接机器人后打开场景前置配置 | 可预览 | [已生成](screens/tools/scenario-setup-ready.png) |
| 工具 | 场景前置配置 | `/tools/scenario-setup` | 已有方案待恢复 | 手动应用场景方案后 | 可预览 | [已生成](screens/tools/scenario-setup-pending-restore.png) |
| 工具 | 场景前置配置 | `/tools/scenario-setup` | 受控文件预览 | 在受控目录浏览器中选择文件 | 可预览 | [已生成](screens/tools/scenario-setup-file-preview.png) |
| 工具 | 控制台服务 | `/tools/maintenance` | 服务运行中 | 连接机器人后打开控制台服务 | 可预览 | [已生成](screens/tools/maintenance-ready.png) |
| 工具 | 测试 | `/tools/testing` | 需要连接机器人 | 从工具进入测试但未连接 | 可预览 | [已生成](screens/tools/test-disconnected.png) |
| 工具 | 测试 | `/tools/testing` | 正在加载测试内容 | 已连接且用例目录未返回 | 可预览 | [已生成](screens/tools/test-cases-loading.png) |
| 工具 | 测试 | `/tools/testing` | 无法读取测试内容 | 用例目录请求失败 | 可预览 | [已生成](screens/tools/test-cases-error.png) |
| 工具 | 测试 | `/tools/testing` | 暂无测试任务 | 测试内容存在但尚无运行记录 | 可预览 | [已生成](screens/tools/test-empty.png) |
| 工具 | 测试任务 | `/tools/testing` | 排队中 | 任务状态为 queued | 可预览 | [已生成](screens/tools/test-queued.png) |
| 工具 | 测试任务 | `/tools/testing` | 准备中 | 任务状态为 preparing | 可预览 | [已生成](screens/tools/test-preparing.png) |
| 工具 | 测试任务 | `/tools/testing` | 执行中 | 任务状态为 running | 可预览 | [已生成](screens/tools/test-running.png) |
| 工具 | 测试任务 | `/tools/testing` | 运行停滞，等待人工处置 | 轨迹监测返回 alert=true | 可预览 | [已生成](screens/tools/test-stall-alert.png) |
| 工具 | 测试任务 | `/tools/testing` | 轮次已生成地图轨迹证据 | 测试轮次完成且服务端已写入 SVG 证据 | 可预览 | [已生成](screens/tools/test-trajectory-evidence.png) |
| 工具 | 运行依赖 | `/tools/testing` | 等待 Supervisor 预检 | 测试已创建，尚未返回本机 Supervisor 快照 | 可预览 | [已生成](screens/tools/supervisor-waiting.png) |
| 工具 | 运行依赖 | `/tools/testing` | Supervisor 节点全部运行 | 全部必需节点返回 RUNNING | 可预览 | [已生成](screens/tools/supervisor-ready.png) |
| 工具 | 运行依赖 | `/tools/testing` | 可选节点正在重试 | 可选 Supervisor 节点返回 BACKOFF，必需节点仍正常 | 可预览 | [已生成](screens/tools/supervisor-optional-warning.png) |
| 工具 | 运行依赖 | `/tools/testing` | 必需节点异常 | 必需 Supervisor 节点返回 FATAL、STOPPED 或 MISSING | 可预览 | [已生成](screens/tools/supervisor-required-failure.png) |
| 工具 | 运行依赖 | `/tools/testing` | 人工恢复后的依赖复检 | 运行进入 awaiting_recovery，依赖正在恢复或重试 | 可预览 | [已生成](screens/tools/supervisor-recovery.png) |
| 工具 | 测试任务 | `/tools/testing` | 等待恢复 | 任务状态为 awaitingRecovery | 可预览 | [已生成](screens/tools/test-awaiting-recovery.png) |
| 工具 | 测试任务 | `/tools/testing` | 恢复中 | 任务状态为 recovering | 可预览 | [已生成](screens/tools/test-recovering.png) |
| 工具 | 测试任务 | `/tools/testing` | 正在中止 | 任务状态为 cancelling | 可预览 | [已生成](screens/tools/test-cancelling.png) |
| 工具 | 测试任务 | `/tools/testing` | 已中止 | 任务状态为 cancelled | 可预览 | [已生成](screens/tools/test-cancelled.png) |
| 工具 | 测试任务 | `/tools/testing` | 已完成 | 任务状态为 completed | 可预览 | [已生成](screens/tools/test-completed.png) |
| 工具 | 测试任务 | `/tools/testing` | 受阻 | 任务状态为 blocked | 可预览 | [已生成](screens/tools/test-blocked.png) |
| 工具 | 测试任务 | `/tools/testing` | 失败 | 任务状态为 failed 或 unknown | 可预览 | [已生成](screens/tools/test-failed.png) |
| 工具 | 测试内容 | `/tools/testing/cases` | 需要连接机器人 | 从工具进入测试内容但未连接 | 可预览 | [已生成](screens/tools/cases-disconnected.png) |
| 工具 | 测试内容 | `/tools/testing/cases` | 加载中 | 目录请求尚未完成 | 可预览 | [已生成](screens/tools/cases-loading.png) |
| 工具 | 测试内容 | `/tools/testing/cases` | 加载失败 | 目录请求失败 | 可预览 | [已生成](screens/tools/cases-error.png) |
| 工具 | 测试内容 | `/tools/testing/cases` | 空目录 | 已连接但没有测试内容 | 可预览 | [已生成](screens/tools/cases-empty.png) |
| 工具 | 测试内容 | `/tools/testing/cases` | 可选择与编辑 | 目录请求成功 | 可预览 | [已生成](screens/tools/cases-ready.png) |
| 工具 | 测试内容 | `/tools/testing/cases` | 内容校验提示 | 机器人端返回测试内容校验提示 | 可预览 | [已生成](screens/tools/cases-validation.png) |
| 工具 | 运行记录 | `/tools/logs` | 需要连接机器人 | 从工具进入记录但未连接 | 可预览 | [已生成](screens/tools/logs-disconnected.png) |
| 工具 | 运行记录 | `/tools/logs` | 加载中 | 记录请求尚未完成 | 可预览 | [已生成](screens/tools/logs-loading.png) |
| 工具 | 运行记录 | `/tools/logs` | 加载失败 | 记录请求失败 | 可预览 | [已生成](screens/tools/logs-error.png) |
| 工具 | 运行记录 | `/tools/logs` | 没有记录 | 记录请求成功但为空 | 可预览 | [已生成](screens/tools/logs-empty.png) |
| 工具 | 运行记录 | `/tools/logs` | 全部记录 | 记录请求成功 | 可预览 | [已生成](screens/tools/logs-all.png) |
| 工具 | 运行记录 | `/tools/logs` | 异常筛选 | 用户选择异常筛选 | 可预览 | [已生成](screens/tools/logs-errors.png) |
| 工具 | 报告 | `/tools/reports` | 需要连接机器人 | 从工具进入报告但未连接 | 可预览 | [已生成](screens/tools/reports-disconnected.png) |
| 工具 | 报告 | `/tools/reports` | 加载中 | 报告请求尚未完成 | 可预览 | [已生成](screens/tools/reports-loading.png) |
| 工具 | 报告 | `/tools/reports` | 加载失败 | 报告请求失败 | 可预览 | [已生成](screens/tools/reports-error.png) |
| 工具 | 报告 | `/tools/reports` | 没有报告 | 报告请求成功但为空 | 可预览 | [已生成](screens/tools/reports-empty.png) |
| 工具 | 报告 | `/tools/reports` | 报告列表 | 报告请求成功 | 可预览 | [已生成](screens/tools/reports-ready.png) |
| 全局组件 | 确认对话框 | `/__debug/ui-gallery` | 开始测试确认 | 用户准备执行测试 | 可预览 | [已生成](screens/states/dialog-start.png) |
| 全局组件 | 确认对话框 | `/__debug/ui-gallery` | 中止测试确认 | 用户中止正在进行的测试 | 可预览 | [已生成](screens/states/dialog-cancel.png) |
| 全局组件 | 确认对话框 | `/__debug/ui-gallery` | 恢复测试确认 | 用户恢复受阻的测试 | 可预览 | [已生成](screens/states/dialog-recovery.png) |
| 全局组件 | 底部操作区 | `/__debug/ui-gallery` | Material BottomSheet | 需要在不离开当前页的情况下呈现操作 | 可预览 | [已生成](screens/states/bottom-sheet.png) |
| 全局组件 | 即时反馈 | `/__debug/ui-gallery` | SnackBar | 非阻塞的短暂结果反馈 | 可预览 | [已生成](screens/states/snackbar.png) |
| 全局组件 | 权限提示 | `/__debug/ui-gallery` | 权限尚未授予 | 未来能力请求系统权限前 | 可预览 | [已生成](screens/states/permission.png) |
| 全局组件 | 离线提示 | `/__debug/ui-gallery` | 网络不可用 | 通用网络不可用状态 | 可预览 | [已生成](screens/states/offline.png) |
| 全局组件 | 空状态 | `/__debug/ui-gallery` | 无内容 | 通用无数据占位 | 可预览 | [已生成](screens/states/empty-state.png) |

## 维护规则

- 新增页面或关键 UI 状态时，先在 Gallery Manifest 增加一项。
- 为该项选择真实页面或组件的 Mock Provider 状态，不重复实现页面。
- 执行 `flutter test --update-goldens test/debug_ui/gallery_golden_test.dart` 后重新生成本文档。
