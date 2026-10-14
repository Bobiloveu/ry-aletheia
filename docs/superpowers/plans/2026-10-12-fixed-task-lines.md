# Fixed Task Lines Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 保存多条固定去程任务线路，自动派生返程，并去掉重复的定位确认。

**Architecture:** 地图实例自动供应定位绑定；新增项目内线路访问列表，位置与每次访问动作分离。选中线路由独立编译模块复用当前通行设施、电梯与地图导出能力，历史项目仍走原编译器。

**Tech Stack:** Python、现有 HTTP 项目 API、原生 ES modules、BehaviorTree XML、pytest、Node test。

**Spec:** `docs/superpowers/specs/2026-10-12-fixed-task-lines-design.md`

## Global Constraints

- 不构建、不部署、不控制机器人、不修改来源地图。
- 消费者只有 Backend 与 PC Web，Mobile 不增加依赖。
- 仓位 1/2；open/close/unload 分别为现有操作码 0/1/2。
- normal 过渡点无动作、非单点停靠。
- 旧项目有效绑定、模板标识和没有 task_lines 字段时的编译行为保留。

## Task 1: 自动定位绑定

Files: `autodrive_console/deployment.py`, `tests/test_automatic_localization_bindings.py`, `shared/contracts/deployment.md`。

- [x] 先运行真实 DeploymentStore 回归，确认读取有效地图实例时缺少绑定。
- [x] 加入 `_ensure_topology_localization_bindings(document) -> bool`，读取迁移与实例保存调用。
- [x] 旧绑定保留；标准层先分配首个空闲数字布局键，覆盖层使用另一个稳定键。
- [x] 验证重复读取不改文件、有效历史模板不变、冲突实例不猜测身份。
- [x] 检查前端自动绑定无确认入口，保留无实例旧项目兼容入口。

## Task 2: 线路意图持久化

Files: new `autodrive_console/task_lines.py`, `autodrive_console/deployment.py`, `web_console.py`, new `tests/test_task_lines.py`。

- [x] 测试当前项目引用、重复访问、多个线路独立保存、线路选择、删除悬空引用和未知字段拒绝。
- [x] 纯函数 `normalise_task_line(project, data, identifier=None) -> dict` 校验线路名称、起点、1–512 个引用与目标动作。
- [x] Store 提供 `save_task_line(project_id, data, line_id=None)`、`select_task_line(project_id, line_id)`、`delete_task_line(project_id, line_id)`；只写项目快照并使预览失效。
- [x] HTTP 路径 `/task-lines`、`/task-lines/{id}` 和 `/task-lines/{id}/select`；结构化返回更新项目。

## Task 3: 常规过渡与有向通行块

Files: `task_path.py`, `execution_chain.py`, `task_compiler.py`, transition Web controls and tests。

- [x] 编译回归先证明 normal 被拒绝或错误标成单点停靠。
- [x] 扩展批准的过渡速度；normal 输出 `is_single_point: false`、空动作。
- [x] 提取有向块展开入口，允许项目内显式引用子集与重复经过，保留旧自动执行链完整性校验。
- [x] 验证设备开/关反向配对、区域速度沿边反向、位置和方向约束。

## Task 4: 固定线路编译

Files: new `autodrive_console/fixed_task_compiler.py`, `deployment.py`, `location_manifest.py` when needed, new `tests/test_fixed_task_compiler.py`。

- [x] 先测试两取货点、两送货点、重复常开门过渡点，独立上下仓与动作。
- [x] 将线路拆成地图内有向块与真实连接的切图块；起点只执行一次 start，末次返程只执行一次 complete。
- [x] 每次仓控访问生成独立 task ID/XML，保留 caogo_id 端口，取货不发布配送到达。
- [x] 电梯复用既有操作顺序，固定参数使用 SetBlackboard；每次地图切换与行为树文件命名唯一。
- [x] 自动返程反转通行块与设备动作，移除全部目标仓控，并从同一节点序列生成定位首返点。
- [x] 预览/ZIP 编译当前选中线路；没有 task_lines 字段的历史项目继续使用原编译器。
- [x] 拒绝跨项目、缺失引用、不可达或未批准地图连接；验证 ZIP 中每个动作引用都存在。

## Task 5: 内联线路配置界面

Files: new `web/deployment/task-lines.js`, `deployment.html`, `deployment.js`, scoped CSS and Node tests。

- [x] 有序列表支持选择/新建/保存多条线路、起点选择、再次添加同一点、上移下移删除。
- [x] 目标访问显示用途、仓位、执行方式；过渡点仅显示 normal 等导航设置。
- [x] 独立只读返程预览明确不重复仓控；地图上显示当前线路访问顺序。
- [x] 自动定位信息折叠展示，取消逐图确认主操作；高级定位模板替换仍可访问。
- [x] 工作流进入线路配置，保存并校验后进入实验预览；错误定位到具体线路节点。

## Task 6: 验证与交付

- [x] 运行受影响 Backend 检查与 `scripts/test-backend.sh`；记录现有静态源码断言失败，不通过修改无关代码隐藏它。
- [x] 在 frontend 运行 `pixi run --frozen --no-install node --test`；不运行会构建的脚本。
- [x] 独立测试服务中检查桌面与窄窗口、保存恢复、切换线路、键盘操作、无重复定位弹窗。
- [x] 核对实际导出 XML/JSON/PGM、任务动作引用和返程节点；不启动机器人、不发布文件。

## 实际验证记录

- 相关 Backend 检查：415 passed，排除一项已知静态源码断言。完整 scripts/test-backend.sh：1154 passed、1 failed（tests/test_deployment.py:2341 仍查找旧变量 mapImage.onerror；现有实现为 image.onerror）。
- Web：460 passed，未运行构建。
- 独立服务 18921 使用临时项目/地图与真实 HTTP Handler，未访问 ROS 或机器人运行目录。
- 浏览器验证桌面/390px 窄窗口无横向溢出、多线路保存/选择、重复访问和独立仓位、未保存编辑阻止编译、键盘操作、真实编译预览、原始/美化切换。
- 对固定线路 ZIP/动作引用、跨楼层往返、A→B→C→A 回环、实际 YAML 图像、擦除及 negate 参数进行回归。
- 当前跨图支持范围为同楼栋单元内唯一共享物理电梯；其他连接明确拒绝。没有增加人工装货完成等待或自动关仓。
- 独立只读审查发现嵌套图像路径引用丢失；先复现失败，再同步修正导出 YAML，新增回归通过。
- 真实 HTTP ZIP：33 成员、31 路点、19 动作引用全部解析、5 次仓控、整单完成仅 1 次。

## 可选电梯大厅增量修正

- [x] 前后端取消独立大厅阶段必选；保存/重读流程不恢复旧的大厅阶段。
- [x] 全局摆渡图若包含电梯，固定线路依据实际访问楼层与共享物理电梯生成单位定位副本，去返乘梯复用原树，不改项目归属。
- [x] 摆渡图手动过渡点开放线路速度/朝向设置，修正仅大厅/用户层可导出的旧提示。
- [x] 缺失/歧义连接、真实 Store 与 ZIP 回归；浏览器实际保存两阶段流程通过。
