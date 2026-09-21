# 部署建图渐进式工作台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (recommended) or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将部署建图页面改造成按当前阶段显示单一工作台的渐进式向导，并修正定位地图把 `index.txt` 当作必需文件的问题。

**Architecture:** 保留现有 API、事件监听所依赖的 DOM id 和地图/路线数据结构。纯工作流继续由 `deployment/workflow.js` 派生；`deployment.js` 增加本地回看阶段状态并据此切换工作台；HTML 为现有面板补充多阶段标记，CSS 将阶段内容组织成单一工作区。导入文件清单在浏览器侧提供即时反馈，Python 定位资产读取器把 `index.txt` 改为可选而继续要求至少一个有效 PCD。

**Tech Stack:** 传统 HTML、CSS、ES modules、Node `node:test`、Python `pytest`、agent-browser。

**Spec:** `docs/superpowers/specs/2026-09-19-deployment-wizard-redesign-design.md`

## Global Constraints

- 不改变部署建图 URL、HTTP API、任务编译数据结构和机器人运行时边界。
- 保留地图画布、组件编辑、定位绑定、定位路线和导出相关既有 DOM id。
- 只有当前阶段工作台可操作；后续阶段锁定，已完成阶段仅可通过阶段按钮回看。
- 定位地图至少需要一个有效 `.pcd`；`index.txt` 存在时原样保留，不存在时不报错、不生成占位文件。
- 任何前端修改完成后运行 `scripts/test-web.sh`；后端定位清单修改运行受影响的 Python 测试。

---

### Task 1: 锁定可选 index 与导入契约

**Files:**
- Modify: `autodrive_console/localization_assets.py`
- Modify: `autodrive_console/location_manifest.py`
- Modify: `autodrive_console/web/deployment.html`
- Test: `tests/test_location_manifest.py`
- Test: `frontend/test/deployment/map-import.test.mjs`

**Interfaces:**
- `read_localization_map(directory, root)` 返回 `LocalizationMap(index_path: Path | None, index_bytes: bytes | None, clouds: tuple[Path, ...])`。
- `compile_location_manifest` 只在 `index_bytes` 非空时加入 `index.txt` artifact。

- [x] **Step 1: 写入缺失 index 但存在 PCD 的回归测试**
- [x] **Step 2: 实现 index 可选、PCD 必需的读取逻辑**
- [x] **Step 3: 更新地图导入说明和前端契约测试**
- [x] **Step 4: 运行定位清单测试**

Run: `pytest -q tests/test_location_manifest.py`

### Task 2: 建立单一当前工作台状态

**Files:**
- Modify: `autodrive_console/web/deployment.js`
- Modify: `autodrive_console/web/deployment/workflow.js`
- Test: `frontend/test/deployment-workflow.test.mjs`

**Interfaces:**
- 新增 `viewedDeploymentStage`，其值为现有步骤 id 或 `null`。
- `activeDeploymentStage()` 返回回看阶段或工作流当前阶段。
- `applyDeploymentStageGating()` 仅显示 active stage，支持 `data-deployment-stages` 的多阶段面板。

- [x] **Step 1: 写工作台可见性和已完成阶段回看测试**
- [x] **Step 2: 添加 active stage 派生与重置规则**
- [x] **Step 3: 将阶段按钮和下一步操作接入回看状态**
- [x] **Step 4: 运行部署工作流测试并检查脚本语法**

Run: `node --test frontend/test/deployment-workflow.test.mjs && node --check autodrive_console/web/deployment.js`

### Task 3: 重排部署建图 DOM 与地图导入工作台

**Files:**
- Modify: `autodrive_console/web/deployment.html`
- Modify: `autodrive_console/web/deployment.css`
- Modify: `autodrive_console/web/deployment.js`
- Test: `frontend/test/deployment-workflow.test.mjs`

**Interfaces:**
- 现有面板保留原 id；为地图画布添加 `data-deployment-stages="annotations localization"`，拓扑相关控制保留在地图阶段。
- 导入文件提示由 `renderMapImportSelection(files)` 统一输出分类、数量和下一步动作。

- [x] **Step 1: 增加导入清单的失败测试和阶段标记断言**
- [x] **Step 2: 将导入控件改成选择文件、清单、导入三段式布局**
- [x] **Step 3: 添加当前工作台、完成摘要和锁定阶段样式**
- [x] **Step 4: 删除重复工具条标记并修复窄屏布局**
- [x] **Step 5: 运行前端单元测试与构建**

Run: `./scripts/test-web.sh`

### Task 4: 浏览器可视化审查与修正

**Files:**
- Modify: `autodrive_console/web/deployment.css`
- Modify: `autodrive_console/web/deployment.html`
- Modify: `autodrive_console/web/deployment.js`

**Interfaces:**
- 使用 agent-browser 打开 `/deployment.html`，分别检查无项目、已有项目地图阶段、标记阶段和定位阻塞状态。

- [x] **Step 1: 启动本地预览并抓取桌面首屏**
- [x] **Step 2: 检查阶段切换、锁定控件、导入清单和错误恢复**
- [x] **Step 3: 在窄屏视口检查横向溢出和按钮可达性**
- [x] **Step 4: 一次性修正发现的视觉问题并复测**

### Task 5: 完整验证

**Files:**
- Modify: `docs/superpowers/plans/2026-09-19-deployment-wizard-redesign.md`

- [x] **Step 1: 运行 `pytest -q tests/test_location_manifest.py tests/test_deployment.py tests/test_task_compiler.py`**
- [x] **Step 2: 运行 `./scripts/test-web.sh`**
- [x] **Step 3: 运行 `git diff --check` 和 `node /home/bob/.codex/skills/impeccable/scripts/detect.mjs --json --path autodrive_console/web/deployment.html --path autodrive_console/web/deployment.css`**
- [x] **Step 4: 记录实际测试结果并交付变更说明**
