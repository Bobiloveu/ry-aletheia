# Fixed Task Return Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 修复真实点位命名、窄通道节点、直接返程及返程查看，构建可交付安装包。
**Architecture:** Backend 复用 ExecutionNode 与已批准电梯模板，在固定线路编译中扩展真实通行节点并独立编译回起点路径。Web 按服务端 subtask 地图归属与方向过滤可见路线，展示实际返程节点。
**Tech Stack:** Python/Pytest、原生 JS/Node test、Vite、Pixi、PyInstaller、DEB。
**Spec:** docs/superpowers/specs/2026-10-13-fixed-task-return-design.md

## Global Constraints

- 保持 single/multi 任务布局、行为树端口、地图安全边界，不改现场数据或运行服务。
- 在当前授权工作区增量修改，不提交其他工作；构建产物不纳入版本控制。
- Backend 与 Web 定向验证，Mobile 无部署契约消费，不引入 Flutter 工具链。

### Task 1: 实际任务编译

**Files:** fixed_task_compiler.py、必要的新 Backend 几何辅助模块、tests/test_fixed_task_return.py、shared/contracts/deployment.md。
**Interfaces:** 输入项目和受控 map_root；输出 CompilationPreview，保留 subtasks、subtask_map_asset_ids；新增 manifest.waypoint_trace 数组，字段 waypoint_id,map_asset_id,leg,label,role,source_id，与展开任务节点一一对应。

- [x] 写并运行失败测试：`assert not any('fl_' in w['waypoint_id'] for w in nodes)`；返程不包含取货坐标与去程过渡点；经过窄通道时有长轴 entry/exit，未经过的不生成。
- [x] 复用 build_directed_map_execution_plan 扩展通行组件；以真实可通行路径判断自动窄通道，所有生成腿校验地图和虚拟墙。
- [x] 从最终访问位置编译独立返程，用已批准电梯连接回到起始地图，完成动作附在起点一次；发布可读唯一点名和 trace。
- [x] 运行固定线路、多任务布局、执行链、可达性测试，修正过时的反放返程断言，验证真实项目只读副本。

### Task 2: 返程查看

**Files:** deployment.js、deployment.html、deployment.css、deployment/execution-chain-view.js、task-lines.js、相关 Node tests。
**Interfaces:** 消费 Task 1 的 trace；旧预览可回退到 subtasks/map IDs，不能显示伪造返程。`previewRouteSegments` 仍返回全部路线，过滤仅影响绘制。

- [x] 测试实际 return_ 子任务顺序与 all/outbound/return 三方向筛选，支持同图连续节点与切图无连线。
- [x] 添加可键盘访问的全部/去程/返程按钮，保持原工作台设计；只过滤绘制线、节点和列表，不为切换重复规划。
- [x] 返程列表显示实际编译节点和地图；草稿自动返程文案改为直接回起点，不重复显示取货点。
- [x] 运行相关 Node 测试，Impeccable detector，桌面和窄屏浏览器核验。

### Task 3: 验证、构建与复查

**Files:** 必要验证文档，releases/ 忽略产物。
**Interfaces:** 消费前两项完成源码，输出版本化 ZIP/DEB/SHA256SUMS。

- [x] 独立审查实际导出、返程速度、定位初始化和多任务布局，处理重要问题。
- [x] 运行 scripts/test-backend.sh 定向集、scripts/test-web.sh、test-offline 及构建环境 doctor。
- [x] `./make_upgrade.sh 2.8.1 --shm --deb`，以用户回复调整产物。
- [x] `sha256sum -c SHA256SUMS`，检查 DEB/ZIP 内容、版本、模块与页面资源，核对构建日志，不启动机器人进程。
- [x] 记录实际结果与限制，逐条核对用户要求后完成目标。
