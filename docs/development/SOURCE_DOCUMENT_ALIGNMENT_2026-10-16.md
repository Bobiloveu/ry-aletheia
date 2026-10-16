# 源码与文档对齐审查（2026-10-16）

审查对象为当前工作区源码，重点覆盖部署编译、速度模式、手动控制、重定位、地图与路线、
视频、录包、日志及发布边界。本文是静态核对记录，不能替代完整安全审计或实车验证。
此次更新文档、录包与观测页提示语及 Backend 的对应注释，并修复验证时发现的测试资源清理问题；不改变接口、导航策略或控制门控。

## 已纠正的差异

| 源码事实 | 原文档问题 | 更新位置 |
| --- | --- | --- |
| deployment.py 的流程至少一个阶段，用户楼层可选且如有必须最后 | 强制用户楼层，PRODUCT 还强制大厅 | PRODUCT、README、部署契约及部署文档 |
| fixed_multi_export.py 支持四类独立单图，multi 只生成实际阶段文件对 | 总览与开发文档将所有编译限制为室内两图 | PROJECT_OVERVIEW、PROFILES、部署文档 |
| task_compiler.py 的历史包装器支持自动路线中的户外、摆渡公共段 | 将历史室内核心等同整个编译能力 | PROJECT_OVERVIEW、PROFILES、部署契约 |
| 固定线路支持普通导航段设施展开及受管闸机/自动门动作；跨图有明确限制 | 声称设施尚无模板，应一律拒绝 | PROJECT_OVERVIEW、PROFILES |
| 非标准层文件名使用按钮层，physical_floor 单独表示物理索引 | 历史目录示例误用 physical_floor | 部署契约 |
| 新固定线路标识为 ASCII；中文显示名保留 | 契约旧段仍允许 XML 后缀使用中文线路名 | 部署契约、部署文档 |
| 新建线路保留当前草稿、解除线路 ID，不覆盖旧线路 | 部署摘要未说明直接保存与草稿复制 | 部署文档、USER_GUIDE |
| 速度模式输出枚举/标志，导航 XML 选择在车端执行器 | 暗示工具可以证明 normal.xml 的实际选择 | 部署契约、速度模式模板基线 |
| manual_control.js 使用 /vector 组合输入 | 总览仍写 PC 四方向 /command | PROJECT_OVERVIEW、USER_GUIDE |
| vehicle_control.py 在操作期间限频确认急停，接受有效 Topic/服务响应 | 多处仍限定启动 unknown 或只接受 Topic | PROJECT_OVERVIEW、控制契约 |
| PC 实时页有独立受控重定位、地图标记导航 | README 与页面提示将整个实时页概括为只读 | README、USER_GUIDE、观测页 |
| relocalization_config.py 按同域唯一运行实例校验，不锁版本号 | 验证说明残留未知/陈旧版本拒绝 | 实时观测契约 |
| map_snapshot.py 持续订阅，以完整内容摘要去重 | 仍写短订阅且只在切图更新 | PROJECT_OVERVIEW |
| PC 图层包含规划路线，Flutter 也消费 costmap | 图层顺序遗漏路线，模块 README 说 costmap 仅 PC | 实时观测契约、PROJECT_OVERVIEW、live_preprocessor README |
| bag_recording.py 按类型排除传感器数据 | 说明错误声称所有被排除传感器均不走 DDS | 录包页、Backend 注释、任务契约、USER_GUIDE |
| 录包启动及进程清理同时失败时保留 staging 并锁定新录制 | 缺少需维护重启控制台的恢复条件 | 任务契约、USER_GUIDE |
| 无效日志策略暂停自动整理，重新保存有效策略后恢复 | 缺少异常恢复说明与策略文件位置 | 日志契约、PROJECT_OVERVIEW、USER_GUIDE |
| make_upgrade.sh 输出 ros/shm 目录及带相应后缀的文件，不生成说明文件 | 发布路径与安装文件名仍使用旧形式 | README、USER_GUIDE、PROJECT_OVERVIEW |
| video.py 启动时有受限配置迁移，没有 ShmSDK→ROS 自动反向迁移 | 容易把保留配置、换包和输入切换混为一谈 | README、PROJECT_OVERVIEW、视频契约 |
| Nav2 测试须关闭创建的 transport 和控制器 | 模拟 executor 空转，残留工作/监控线程拖慢后续用例并干扰收尾 | test_map_marker_navigation.py |

视频生命周期、带宽统计及 NVENC 可选 VBR 的现有契约与本次核对的实现基本一致，本次没有
据此调整码率、帧率、网络或编码参数。规划路线保留和终态清理、位姿组合与新鲜度策略也沿用现有实现。

## 尚需运行时证据的对齐项

速度模板详见 [基线与来源指纹](SPEED_MODE_TEMPLATES.md)。`slow_point` 已在源码使用，
但用户提供的目录缺少对应 XML；`low_speed.xml` 只有注释。high_speed、delivery_point、
narrow_follow、water_point 尚未开放，taskpoint 与 task_point、不同目录的 backward 不能
自动视作别名。后续需确认车端模式分派、插件注册与配置，再决定源码接入；本次没有猜测映射。

## 验证边界

Backend 与 Web 的最小检查使用 `scripts/test-backend.sh` 和 `scripts/test-web.sh`。
另外核验 14 份参考文件的内容指纹、有效 XML 与占位文件、源码枚举和文档相对链接。
测试线程清理已验证失败到通过：修复前单用例断言通过但存活线程检查失败；修复后该模块
24 项通过且存活导航线程为零。测试使用模拟 ROS，不是实车导航。
本次结果：

- `scripts/test-backend.sh`：1760 项通过，退出码 0，耗时 30.40 秒；保留 3 条既有 TestCase 收集警告。
- `scripts/test-web.sh`：890 项通过，检查与构建退出码 0。
- 参考文件：14 份 SHA-256 匹配，13 份可解析 XML 树及 1 份已注明的占位文件。
- 文档链接：56 个本地文件目标、25 个章节锚点有效；`git diff --check` 通过。

这些检查不证明车端导航树或实际车辆动作已验证。
没有连接小车、生成升级包、部署、提交或推送 Git。
