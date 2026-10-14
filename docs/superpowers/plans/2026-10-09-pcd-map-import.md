# PCD Map Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 在原部署向导中支持上传 PCD、调整高度预览、确认后继续地图部署。

**Architecture:** 有界离线投影核心、持久化后台会话和既有部署向导分工；HTTP 只承担受控上传与会话操作。确认复用地图快照导入。

**Tech Stack:** Python 3.10、pypcd4 1.5.1、NumPy、现有纯 JS 部署界面、pytest / Node test。

**Spec:** docs/superpowers/specs/2026-10-09-pcd-map-import-design.md

## Global Constraints

- 保留现有修改，不提交、不编译、不打包、不升级，不改变机器人运行目录或 ROS 图。
- Backend / Desktop Web 为消费者，Mobile 无接口变化。
- 点数上限 1000 万，展开上限 512 MiB，栅格上限 1600 万格，转换并发为一。
- 保留原始 PCD 和 XY 坐标；未知区域不自动判为可通行。

### Task 1: 离线投影

Files: `autodrive_console/pcd_projection.py`, `tests/test_pcd_projection.py`, `pixi.toml`, `pixi.lock`, `build_binary.sh`。

Interfaces: `ProjectionError(ValueError)`；`analyze_pcd(path: Path) -> dict`；`project_pcd(path: Path, output: Path, parameters: dict) -> dict`。parameters 精确为 z_min/z_max/resolution/min_points/denoise。

- [x] 添加真实 PCD 回归测试，例如 `assert project_pcd(source, out, params)['origin'][:2] == [-2.0, 3.0]`，先运行确认缺失实现失败。
- [x] 实现头部边界检查与三个编码，输出高度分布、推荐候选和有限点统计。
- [x] 实现有界栅格与高度筛选、可选保守邻域去噪及 PGM/YAML 输出；验证最右/上边界点不会丢失。
- [x] 用 `pixi run python -m pytest -q tests/test_pcd_projection.py` 验证。

### Task 2: 后台会话与 HTTP

Files: `autodrive_console/map_projection_jobs.py`, `web_console.py`, `tests/test_map_projection_jobs.py`, `tests/test_map_projection_http.py`, `shared/contracts/deployment.md`。

Interfaces: `MapProjectionJobs(store)` 的 create(project, source)/latest(project)/get(project,id)/preview(project,id,params)/confirm(project,id,label,revision)/cancel(project,id)/preview_path(project,id,revision)。HTTP 使用 spec 中固定路由。

- [x] 先写后台回归：完成预览后 `confirm(..., revision-1)` 拒绝，当前 revision 导入且重复确认地图 id 不变。
- [x] 先运行 `pixi run python -m pytest -q tests/test_map_projection_jobs.py tests/test_map_projection_http.py` 确认缺失实现。
- [x] 实现原子 JSON、后台工作、重启恢复及受控会话路径；逐个新增 HTTP 路由与上传上限。
- [x] 更新契约消费者与 index.txt 实际可选语义；运行相关 deployment、location_manifest 与 HTTP 测试。

### Task 3: 原向导接入

Files: `autodrive_console/web/deployment.html`, `deployment.js`, `deployment.css`, `deployment/workflow.js`, `deployment/session-state.js`, 新 `deployment/pcd-import.js`，对应 `frontend/test/deployment/pcd-import.test.mjs`。

Interfaces: mapSource 新值 pcd，draft.projection 为后台快照。状态依次引导选择文件、等待分析、调整生成、检查确认；最终复用 `renderProject` 与 `nextMapImportDraft`。

- [x] 先增加行为测试：processing 的主动作不可确认；ready 且参数未改才可确认，恢复可回到原步骤。
- [x] 实现局部组件控制器及项目代次防串页、后台轮询、参数失效、图片 revision、按钮 pending 状态。
- [x] 保留原 import 与 mapping 分支和原部署阶段，扩展会话指针以恢复 pcd 来源。
- [x] 用 `pixi run node --test frontend/test/deployment*.test.mjs frontend/test/deployment/*.test.mjs` 验证，再运行所有 Web 单测与 parity（不执行 Vite）。

### Task 4: 交叉审查与交付

- [x] 用真实 HTTP / 浏览器验证完整预览到导入、切页恢复、旧导入与窄屏。
- [x] 审查并发、revision、异常、资源界限和失败不会推进向导；修复发现后重跑受影响检查。
- [x] 更新用户说明并报告通过的检查及现场地图验证边界，不编译升级。


## 验证记录（2026-10-09）

- 新增核心、后台会话、HTTP 回归：47 项通过。
- 最终相关后端回归：298 项通过，覆盖投影、部署、位置清单、离线模块及发布依赖断言。
- Web 全部 Node 单元测试：250 项通过；页面 parity 通过。
- Backend / Web doctor 通过；发布脚本只做 bash 语法检查；相关 diff 检查通过。
- 浏览器使用隔离临时工作区、真实压缩 PCD、真实投影 HTTP：上传、分析、参数修改使预览失效、重新生成、切页恢复、确认导入后继续原部署拓扑步骤均已验证。浅色/深色主题和 390 像素窄屏已检查，浏览器无脚本错误。未连接机器人或修改运行配置。
- 执行过 scripts/test-backend.sh：969 项通过，1 项失败；唯一失败为既有发布依赖断言未包含先前录包功能所需的 sensor_msgs。已修正该断言，包含此测试的最终相关 298 项回归通过；未重复运行八分钟全量套件，不把该次全量结果记为全部通过。
- scripts/test-web.sh 会执行 Vite 编译，依据用户禁止自动编译的要求，改为直接执行它的 Node 单测与 parity 部分。
- 未编译、打包、升级或提交；真实现场 PCD 的截面选择仍需实施人员检查确认。
