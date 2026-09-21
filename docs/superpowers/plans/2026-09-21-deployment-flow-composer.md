# 可配置部署流程编排器实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将固定的“场景模型”下拉框替换为可保存、可迁移、可视化编辑的地图阶段流程，支持户外图、摆渡层、电梯大厅和用户楼层的不同顺序。

**Architecture:** 项目快照新增 `deployment_flow` 有序节点数组；旧 `scene_model` 继续保留用于兼容，并在读取时迁移为默认流程。后端统一从流程数组生成阶段计划、自动分配和拓扑校验；前端用紧凑节点卡片和箭头呈现流程，节点通过拖拽排序，悬浮动作区删除，新增节点通过类型面板完成。

**Tech Stack:** Python `DeploymentStore`、现有 HTTP API、原生 HTML/CSS/ES modules、Node test、pytest。

## Global Constraints

- 只修改 PC Web 与其必要的部署后端；不修改 Flutter/mobile。
- 保留旧项目的 `scene_model` 和已有地图阶段绑定，读取时自动迁移。
- 必须有且仅有一个电梯大厅和一个用户楼层；用户楼层必须是末节点；户外图可选且最多一个；摆渡层可重复。
- 不改变 ROS、机器人运行目录和导出安全边界。

### Task 1: 建立流程模型与迁移规则

**Files:**
- Modify: `autodrive_console/deployment.py`
- Test: `tests/test_deployment.py`

- [x] 写失败测试：旧 `indoor_outdoor` 迁移为 `outdoor → lobby → target_floor`；自定义流程接受 `ferry → outdoor → lobby → target_floor`；非法缺少大厅/用户楼层或用户楼层非末节点被拒绝。
- [x] 运行定向 pytest，确认因缺少 `deployment_flow` API 失败。
- [x] 新增节点常量、规范化和校验函数；创建项目写入默认空流程；`get()` 对旧快照惰性迁移。
- [x] 运行定向 pytest，确认通过并保持既有 scene_model 测试通过。

### Task 2: 让阶段计划、绑定和拓扑读取流程数组

**Files:**
- Modify: `autodrive_console/deployment.py`
- Modify: `web_console.py`
- Test: `tests/test_deployment.py`

- [x] 写失败测试：`set_deployment_flow()` 保存顺序；`stage_plan()` 返回自定义节点；地图导入自动绑定下一个节点；拓扑校验按流程顺序检查首节点起点和末节点目标。
- [x] 将 `STAGE_ORDER` 使用集中替换为流程节点 ID；保留 `set_scene_model()` 作为旧接口适配器。
- [x] 增加 `POST /api/deployments/{id}/deployment-flow`，返回项目和阶段计划。
- [x] 运行受影响的部署测试；旧流程和新流程定向用例通过。

### Task 3: 替换前端场景模型下拉框为图形化流程编辑器

**Files:**
- Modify: `autodrive_console/web/deployment.html`
- Modify: `autodrive_console/web/deployment.js`
- Modify: `autodrive_console/web/deployment.css`
- Create: `autodrive_console/web/deployment/flow-editor.js`
- Test: `frontend/test/deployment-workflow.test.mjs`

- [x] 写失败静态测试：页面存在流程画布、节点类型面板、保存按钮，不再依赖 `sceneModel` select。
- [x] 实现纯函数节点排序/校验和节点渲染；卡片显示类型、序号、说明，连线使用 CSS 箭头。
- [x] 支持新增、悬浮删除、带前后吸附插槽的鼠标拖拽排序和 Motion 风格 FLIP 动效；保存按钮调用 deployment-flow API；项目加载后从 `deployment_flow` 渲染。
- [x] 更新向导文案、地图阶段选择和场景就绪判断，均以 `deployment_flow` 为准。
- [x] 运行前端定向测试和构建。

### Task 4: 编译与导出边界校验

**Files:**
- Modify: `autodrive_console/task_compiler.py`
- Modify: `autodrive_console/deployment.py`
- Test: `tests/test_task_compiler.py`

- [x] 写失败测试：含摆渡层的流程在预览校验中给出明确的阶段信息；缺失电梯大厅/用户楼层时返回可读错误，不出现内部 stage ID。
- [x] 让编译输入携带流程节点和阶段顺序；保留现有室内电梯模板的 lobby/target_floor 语义，摆渡层和户外节点按流程参与拓扑校验。
- [x] 运行任务编译和部署测试，确保旧室内电梯导出不回归。

### Task 5: 完整验证与进程清理

- [x] 运行 `scripts/test-web.sh`（91/91 Node tests、parity、Vite build 通过）。
- [x] 运行受影响的定向 pytest；完整 deployment+compiler 集合为 102 passed，另有一个依赖缺失 `site` 测试项目的既有 HTTP fixture 失败。
- [x] 使用 Impeccable detector 检查修改后的 HTML/CSS/JS。
- [x] 已完成浏览器核验，并确认 `run_vue_preview.sh`、`web_console.py` 和 Vite 进程均已释放。
