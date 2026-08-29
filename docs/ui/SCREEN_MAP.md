# Aletheia Screen Map / UI Overview

固定预览规格：iPhone 17 逻辑尺寸 402 × 874，Pixel Ratio 3，深色主题，标准字体比例。

正式一级信息架构：**首页 / 观测 / 工具 / 设置**。
测试、用例、日志和报告属于“工具”下的二级流程。
详细 Route、状态和触发条件请参阅 [Screen Inventory](SCREEN_INVENTORY.md)。

## 首页

<table>
<tr>
<td><a href="screens/robot/disconnected.png"><img src="screens/robot/disconnected.png" width="180" alt="首页 · 未连接"><br><strong>首页</strong><br>未连接</a></td><td><a href="screens/robot/restoring.png"><img src="screens/robot/restoring.png" width="180" alt="首页 · 正在恢复连接"><br><strong>首页</strong><br>正在恢复连接</a></td><td><a href="screens/robot/connecting.png"><img src="screens/robot/connecting.png" width="180" alt="首页 · 正在连接"><br><strong>首页</strong><br>正在连接</a></td>
</tr>
<tr>
<td><a href="screens/robot/connected.png"><img src="screens/robot/connected.png" width="180" alt="首页 · 已连接，健康正常"><br><strong>首页</strong><br>已连接，健康正常</a></td><td><a href="screens/robot/connection-failed.png"><img src="screens/robot/connection-failed.png" width="180" alt="首页 · 连接失败"><br><strong>首页</strong><br>连接失败</a></td><td><a href="screens/robot/network-error.png"><img src="screens/robot/network-error.png" width="180" alt="首页 · 网络异常"><br><strong>首页</strong><br>网络异常</a></td>
</tr>
<tr>
<td><a href="screens/robot/health-warning.png"><img src="screens/robot/health-warning.png" width="180" alt="首页 · 健康状态异常"><br><strong>首页</strong><br>健康状态异常</a></td>
<td></td>
<td></td>
</tr>
</table>

## 观测

<table>
<tr>
<td><a href="screens/observe/disconnected.png"><img src="screens/observe/disconnected.png" width="180" alt="实时观测 · 需要连接机器人"><br><strong>实时观测</strong><br>需要连接机器人</a></td><td><a href="screens/observe/loading.png"><img src="screens/observe/loading.png" width="180" alt="实时观测 · 正在准备地图"><br><strong>实时观测</strong><br>正在准备地图</a></td><td><a href="screens/observe/empty-map.png"><img src="screens/observe/empty-map.png" width="180" alt="实时观测 · 等待活动地图"><br><strong>实时观测</strong><br>等待活动地图</a></td>
</tr>
<tr>
<td><a href="screens/observe/unavailable.png"><img src="screens/observe/unavailable.png" width="180" alt="实时观测 · 观测暂不可用"><br><strong>实时观测</strong><br>观测暂不可用</a></td><td><a href="screens/observe/error.png"><img src="screens/observe/error.png" width="180" alt="实时观测 · 读取失败"><br><strong>实时观测</strong><br>读取失败</a></td><td><a href="screens/observe/live-map.png"><img src="screens/observe/live-map.png" width="180" alt="实时观测 · 地图、位置、点云正常"><br><strong>实时观测</strong><br>地图、位置、点云正常</a></td>
</tr>
<tr>
<td><a href="screens/observe/live-daylight.png"><img src="screens/observe/live-daylight.png" width="180" alt="实时观测 · 日间模式"><br><strong>实时观测</strong><br>日间模式</a></td><td><a href="screens/observe/telemetry-interrupted.png"><img src="screens/observe/telemetry-interrupted.png" width="180" alt="实时观测 · 位置或点云断流"><br><strong>实时观测</strong><br>位置或点云断流</a></td><td><a href="screens/observe/video-loading.png"><img src="screens/observe/video-loading.png" width="180" alt="相机 · 正在读取视频状态"><br><strong>相机</strong><br>正在读取视频状态</a></td>
</tr>
<tr>
<td><a href="screens/observe/video-empty.png"><img src="screens/observe/video-empty.png" width="180" alt="相机 · 没有可用视频流"><br><strong>相机</strong><br>没有可用视频流</a></td><td><a href="screens/observe/video-waiting.png"><img src="screens/observe/video-waiting.png" width="180" alt="相机 · 视频流等待可用"><br><strong>相机</strong><br>视频流等待可用</a></td><td><a href="screens/observe/video-offline.png"><img src="screens/observe/video-offline.png" width="180" alt="相机 · 视频流离线"><br><strong>相机</strong><br>视频流离线</a></td>
</tr>
<tr>
<td><a href="screens/observe/video-ready.png"><img src="screens/observe/video-ready.png" width="180" alt="相机 · 六路视频可选，主画面正常"><br><strong>相机</strong><br>六路视频可选，主画面正常</a></td><td><a href="screens/observe/video-error.png"><img src="screens/observe/video-error.png" width="180" alt="相机 · 视频状态读取失败"><br><strong>相机</strong><br>视频状态读取失败</a></td>
<td></td>
</tr>
</table>

## 工具

<table>
<tr>
<td><a href="screens/tools/disconnected.png"><img src="screens/tools/disconnected.png" width="180" alt="工具 · 未连接"><br><strong>工具</strong><br>未连接</a></td><td><a href="screens/tools/connected.png"><img src="screens/tools/connected.png" width="180" alt="工具 · 可用工具入口"><br><strong>工具</strong><br>可用工具入口</a></td><td><a href="screens/tools/runtime-settings-ready.png"><img src="screens/tools/runtime-settings-ready.png" width="180" alt="运行配置 · 受控参数与依赖编排"><br><strong>运行配置</strong><br>受控参数与依赖编排</a></td>
</tr>
<tr>
<td><a href="screens/tools/scenario-setup-ready.png"><img src="screens/tools/scenario-setup-ready.png" width="180" alt="场景前置配置 · 方案可预览，当前常规配置"><br><strong>场景前置配置</strong><br>方案可预览，当前常规配置</a></td><td><a href="screens/tools/scenario-setup-pending-restore.png"><img src="screens/tools/scenario-setup-pending-restore.png" width="180" alt="场景前置配置 · 已有方案待恢复"><br><strong>场景前置配置</strong><br>已有方案待恢复</a></td><td><a href="screens/tools/scenario-setup-file-preview.png"><img src="screens/tools/scenario-setup-file-preview.png" width="180" alt="场景前置配置 · 受控文件预览"><br><strong>场景前置配置</strong><br>受控文件预览</a></td>
</tr>
<tr>
<td><a href="screens/tools/maintenance-ready.png"><img src="screens/tools/maintenance-ready.png" width="180" alt="控制台服务 · 服务运行中"><br><strong>控制台服务</strong><br>服务运行中</a></td><td><a href="screens/tools/test-disconnected.png"><img src="screens/tools/test-disconnected.png" width="180" alt="测试 · 需要连接机器人"><br><strong>测试</strong><br>需要连接机器人</a></td><td><a href="screens/tools/test-cases-loading.png"><img src="screens/tools/test-cases-loading.png" width="180" alt="测试 · 正在加载测试内容"><br><strong>测试</strong><br>正在加载测试内容</a></td>
</tr>
<tr>
<td><a href="screens/tools/test-cases-error.png"><img src="screens/tools/test-cases-error.png" width="180" alt="测试 · 无法读取测试内容"><br><strong>测试</strong><br>无法读取测试内容</a></td><td><a href="screens/tools/test-empty.png"><img src="screens/tools/test-empty.png" width="180" alt="测试 · 暂无测试任务"><br><strong>测试</strong><br>暂无测试任务</a></td><td><a href="screens/tools/test-queued.png"><img src="screens/tools/test-queued.png" width="180" alt="测试任务 · 排队中"><br><strong>测试任务</strong><br>排队中</a></td>
</tr>
<tr>
<td><a href="screens/tools/test-preparing.png"><img src="screens/tools/test-preparing.png" width="180" alt="测试任务 · 准备中"><br><strong>测试任务</strong><br>准备中</a></td><td><a href="screens/tools/test-running.png"><img src="screens/tools/test-running.png" width="180" alt="测试任务 · 执行中"><br><strong>测试任务</strong><br>执行中</a></td><td><a href="screens/tools/test-stall-alert.png"><img src="screens/tools/test-stall-alert.png" width="180" alt="测试任务 · 运行停滞，等待人工处置"><br><strong>测试任务</strong><br>运行停滞，等待人工处置</a></td>
</tr>
<tr>
<td><a href="screens/tools/test-trajectory-evidence.png"><img src="screens/tools/test-trajectory-evidence.png" width="180" alt="测试任务 · 轮次已生成地图轨迹证据"><br><strong>测试任务</strong><br>轮次已生成地图轨迹证据</a></td><td><a href="screens/tools/supervisor-waiting.png"><img src="screens/tools/supervisor-waiting.png" width="180" alt="运行依赖 · 等待 Supervisor 预检"><br><strong>运行依赖</strong><br>等待 Supervisor 预检</a></td><td><a href="screens/tools/supervisor-ready.png"><img src="screens/tools/supervisor-ready.png" width="180" alt="运行依赖 · Supervisor 节点全部运行"><br><strong>运行依赖</strong><br>Supervisor 节点全部运行</a></td>
</tr>
<tr>
<td><a href="screens/tools/supervisor-optional-warning.png"><img src="screens/tools/supervisor-optional-warning.png" width="180" alt="运行依赖 · 可选节点正在重试"><br><strong>运行依赖</strong><br>可选节点正在重试</a></td><td><a href="screens/tools/supervisor-required-failure.png"><img src="screens/tools/supervisor-required-failure.png" width="180" alt="运行依赖 · 必需节点异常"><br><strong>运行依赖</strong><br>必需节点异常</a></td><td><a href="screens/tools/supervisor-recovery.png"><img src="screens/tools/supervisor-recovery.png" width="180" alt="运行依赖 · 人工恢复后的依赖复检"><br><strong>运行依赖</strong><br>人工恢复后的依赖复检</a></td>
</tr>
<tr>
<td><a href="screens/tools/test-awaiting-recovery.png"><img src="screens/tools/test-awaiting-recovery.png" width="180" alt="测试任务 · 等待恢复"><br><strong>测试任务</strong><br>等待恢复</a></td><td><a href="screens/tools/test-recovering.png"><img src="screens/tools/test-recovering.png" width="180" alt="测试任务 · 恢复中"><br><strong>测试任务</strong><br>恢复中</a></td><td><a href="screens/tools/test-cancelling.png"><img src="screens/tools/test-cancelling.png" width="180" alt="测试任务 · 正在中止"><br><strong>测试任务</strong><br>正在中止</a></td>
</tr>
<tr>
<td><a href="screens/tools/test-cancelled.png"><img src="screens/tools/test-cancelled.png" width="180" alt="测试任务 · 已中止"><br><strong>测试任务</strong><br>已中止</a></td><td><a href="screens/tools/test-completed.png"><img src="screens/tools/test-completed.png" width="180" alt="测试任务 · 已完成"><br><strong>测试任务</strong><br>已完成</a></td><td><a href="screens/tools/test-blocked.png"><img src="screens/tools/test-blocked.png" width="180" alt="测试任务 · 受阻"><br><strong>测试任务</strong><br>受阻</a></td>
</tr>
<tr>
<td><a href="screens/tools/test-failed.png"><img src="screens/tools/test-failed.png" width="180" alt="测试任务 · 失败"><br><strong>测试任务</strong><br>失败</a></td><td><a href="screens/tools/cases-disconnected.png"><img src="screens/tools/cases-disconnected.png" width="180" alt="测试内容 · 需要连接机器人"><br><strong>测试内容</strong><br>需要连接机器人</a></td><td><a href="screens/tools/cases-loading.png"><img src="screens/tools/cases-loading.png" width="180" alt="测试内容 · 加载中"><br><strong>测试内容</strong><br>加载中</a></td>
</tr>
<tr>
<td><a href="screens/tools/cases-error.png"><img src="screens/tools/cases-error.png" width="180" alt="测试内容 · 加载失败"><br><strong>测试内容</strong><br>加载失败</a></td><td><a href="screens/tools/cases-empty.png"><img src="screens/tools/cases-empty.png" width="180" alt="测试内容 · 空目录"><br><strong>测试内容</strong><br>空目录</a></td><td><a href="screens/tools/cases-ready.png"><img src="screens/tools/cases-ready.png" width="180" alt="测试内容 · 可选择与编辑"><br><strong>测试内容</strong><br>可选择与编辑</a></td>
</tr>
<tr>
<td><a href="screens/tools/cases-validation.png"><img src="screens/tools/cases-validation.png" width="180" alt="测试内容 · 内容校验提示"><br><strong>测试内容</strong><br>内容校验提示</a></td><td><a href="screens/tools/logs-disconnected.png"><img src="screens/tools/logs-disconnected.png" width="180" alt="运行记录 · 需要连接机器人"><br><strong>运行记录</strong><br>需要连接机器人</a></td><td><a href="screens/tools/logs-loading.png"><img src="screens/tools/logs-loading.png" width="180" alt="运行记录 · 加载中"><br><strong>运行记录</strong><br>加载中</a></td>
</tr>
<tr>
<td><a href="screens/tools/logs-error.png"><img src="screens/tools/logs-error.png" width="180" alt="运行记录 · 加载失败"><br><strong>运行记录</strong><br>加载失败</a></td><td><a href="screens/tools/logs-empty.png"><img src="screens/tools/logs-empty.png" width="180" alt="运行记录 · 没有记录"><br><strong>运行记录</strong><br>没有记录</a></td><td><a href="screens/tools/logs-all.png"><img src="screens/tools/logs-all.png" width="180" alt="运行记录 · 全部记录"><br><strong>运行记录</strong><br>全部记录</a></td>
</tr>
<tr>
<td><a href="screens/tools/logs-errors.png"><img src="screens/tools/logs-errors.png" width="180" alt="运行记录 · 异常筛选"><br><strong>运行记录</strong><br>异常筛选</a></td><td><a href="screens/tools/reports-disconnected.png"><img src="screens/tools/reports-disconnected.png" width="180" alt="报告 · 需要连接机器人"><br><strong>报告</strong><br>需要连接机器人</a></td><td><a href="screens/tools/reports-loading.png"><img src="screens/tools/reports-loading.png" width="180" alt="报告 · 加载中"><br><strong>报告</strong><br>加载中</a></td>
</tr>
<tr>
<td><a href="screens/tools/reports-error.png"><img src="screens/tools/reports-error.png" width="180" alt="报告 · 加载失败"><br><strong>报告</strong><br>加载失败</a></td><td><a href="screens/tools/reports-empty.png"><img src="screens/tools/reports-empty.png" width="180" alt="报告 · 没有报告"><br><strong>报告</strong><br>没有报告</a></td><td><a href="screens/tools/reports-ready.png"><img src="screens/tools/reports-ready.png" width="180" alt="报告 · 报告列表"><br><strong>报告</strong><br>报告列表</a></td>
</tr>
</table>

## 设置

<table>
<tr>
<td><a href="screens/settings/app-settings-ready.png"><img src="screens/settings/app-settings-ready.png" width="180" alt="应用设置 · 本机偏好与版本信息"><br><strong>应用设置</strong><br>本机偏好与版本信息</a></td><td><a href="screens/settings/update-ready.png"><img src="screens/settings/update-ready.png" width="180" alt="检查更新 · 当前开发版本未接入在线服务"><br><strong>检查更新</strong><br>当前开发版本未接入在线服务</a></td><td><a href="screens/settings/feedback-draft.png"><img src="screens/settings/feedback-draft.png" width="180" alt="问题与建议 · 已填写并附加截图"><br><strong>问题与建议</strong><br>已填写并附加截图</a></td>
</tr>
<tr>
<td><a href="screens/settings/feedback-attachments.png"><img src="screens/settings/feedback-attachments.png" width="180" alt="问题与建议 · 截图与诊断摘要已选择"><br><strong>问题与建议</strong><br>截图与诊断摘要已选择</a></td>
<td></td>
<td></td>
</tr>
</table>

## 全局组件

<table>
<tr>
<td><a href="screens/states/dialog-start.png"><img src="screens/states/dialog-start.png" width="180" alt="确认对话框 · 开始测试确认"><br><strong>确认对话框</strong><br>开始测试确认</a></td><td><a href="screens/states/dialog-cancel.png"><img src="screens/states/dialog-cancel.png" width="180" alt="确认对话框 · 中止测试确认"><br><strong>确认对话框</strong><br>中止测试确认</a></td><td><a href="screens/states/dialog-recovery.png"><img src="screens/states/dialog-recovery.png" width="180" alt="确认对话框 · 恢复测试确认"><br><strong>确认对话框</strong><br>恢复测试确认</a></td>
</tr>
<tr>
<td><a href="screens/states/bottom-sheet.png"><img src="screens/states/bottom-sheet.png" width="180" alt="底部操作区 · Material BottomSheet"><br><strong>底部操作区</strong><br>Material BottomSheet</a></td><td><a href="screens/states/snackbar.png"><img src="screens/states/snackbar.png" width="180" alt="即时反馈 · SnackBar"><br><strong>即时反馈</strong><br>SnackBar</a></td><td><a href="screens/states/permission.png"><img src="screens/states/permission.png" width="180" alt="权限提示 · 权限尚未授予"><br><strong>权限提示</strong><br>权限尚未授予</a></td>
</tr>
<tr>
<td><a href="screens/states/offline.png"><img src="screens/states/offline.png" width="180" alt="离线提示 · 网络不可用"><br><strong>离线提示</strong><br>网络不可用</a></td><td><a href="screens/states/empty-state.png"><img src="screens/states/empty-state.png" width="180" alt="空状态 · 无内容"><br><strong>空状态</strong><br>无内容</a></td>
<td></td>
</tr>
</table>

## 复查流程

1. Debug 运行时打开 `/__debug/ui-gallery`，逐项检查。
2. 运行 Golden Test 更新截图。
3. 重新生成 Inventory 与 Screen Map，审查本次 diff。
