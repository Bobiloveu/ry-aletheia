# 部署建图 Canvas 模块化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将部署建图页面的组件定义、几何计算与 Canvas 绘制拆为可验证模块，同时保持现有页面交互、接口和任务生成不变。

**Architecture:** `deployment.js` 保留为页面入口、状态容器、DOM 与网络编排；新增的 ES modules 只能通过显式参数工作。先将静态组件定义和纯坐标/命中计算提取为可由 Node 测试的模块，再由渲染器接收只读快照完成绘制，最后使入口页作为 module 加载并加入静态守卫。

**Tech Stack:** 原生浏览器 ES modules、Canvas 2D、Node 内置测试器、Vite 7。

**Spec:** `docs/superpowers/specs/2026-09-08-deployment-canvas-modularization-design.md`

## Global Constraints

- 保持 `/deployment.html` URL、全部既有 DOM ID、中文文案、请求方法与请求体、任务编译与部署数据行为不变。
- 不修改 `web_console.py`、Backend、`shared/contracts/`、ROS Topic、WebSocket 协议、`deployment.css`、`app_shell.css` 或 `app_shell.js`。
- 不创建、编辑或删除实际项目、地图、任务文件或机器人运行目录的数据；浏览器验证仅请求静态资源。
- 不引入 npm 依赖，不提交 `frontend/node_modules` 或 `autodrive_console/web-vue/`。

---

### Task 1: 组件定义模块

**Files:**
- Create: `autodrive_console/web/deployment/component-specs.js`
- Create: `frontend/test/deployment/component-specs.test.mjs`
- Modify: `autodrive_console/web/deployment.js:1-224`

**Interfaces:**
- Produces `DEFAULT_COMPONENT_TEMPLATES`, `COMPONENT_SPECS`, `componentName(component)`, `protocolOptions(project, category)`, `protocolTitle(project, protocol)`.
- `protocolOptions` receives a project explicitly and returns normalized `[id, label]` pairs without reading global page state.

- [ ] **Step 1: Write failing component-definition tests**

```js
import { strict as assert } from "node:assert";
import test from "node:test";
import {
  componentName,
  protocolOptions,
  protocolTitle,
} from "../../../autodrive_console/web/deployment/component-specs.js";

test("component definitions retain deployment labels and fallbacks", () => {
  assert.equal(componentName({ kind: "elevator" }), "电梯");
  assert.equal(componentName({ kind: "unknown", label: "自定义" }), "自定义");
  assert.deepEqual(protocolOptions({}, "elevator_protocols"), [["bluetooth", "蓝牙"], ["4g", "4G"]]);
  assert.equal(protocolTitle({}, "bluetooth"), "蓝牙");
});
```

- [ ] **Step 2: Run the focused test before implementation**

Run: `cd frontend && node --test test/deployment/component-specs.test.mjs`

Expected: FAIL because `deployment/component-specs.js` does not exist.

- [ ] **Step 3: Implement the stateless exports**

Move the existing `DEFAULT_COMPONENT_TEMPLATES`, `COMPONENT_SPECS`, `componentName`, protocol lookup behavior from `deployment.js` without changing field definitions or labels. Use the project parameter in `protocolOptions` and `protocolTitle`; export immutable constant references only.

- [ ] **Step 4: Replace entry-file references and verify**

At the top of `deployment.js`, import the exports. Replace `protocolOptions(category)` with `protocolOptions(selectedProject, category)` and `protocolTitle(protocol)` with `protocolTitle(selectedProject, protocol)`. Delete the duplicated local declarations.

Run: `cd frontend && node --test test/deployment/component-specs.test.mjs`

Expected: PASS.

### Task 2: 纯 Canvas 几何模块

**Files:**
- Create: `autodrive_console/web/deployment/canvas-geometry.js`
- Create: `frontend/test/deployment/canvas-geometry.test.mjs`
- Modify: `autodrive_console/web/deployment.js:673-723,1686-1804,2060-2260`

**Interfaces:**
- Produces `mapPointToCanvas(point, map, view)`, `canvasPointToMap(point, map, view)`, `isPointOnMap(point, map)`, `componentDimensions(component, scale)`, `componentLocalPoint(component, canvasPoint, map, view)`, `isComponentHit(component, canvasPoint, map, view)`, `isResizeHandleHit(component, canvasPoint, map, view)`, `isRotateHandleHit(component, canvasPoint, map, view)`, and `zoomAt(view, canvasPoint, deltaY)`.
- Each function receives maps, views and points as arguments; none references DOM, Canvas context, module globals or network APIs.

- [ ] **Step 1: Write failing geometry regression tests**

```js
const map = { origin: [10, 20], width: 100, height: 80, resolution_m: 0.05 };
const view = { scale: 40, x: 12, y: 24 };
const world = { x: 11.5, y: 22 };
assert.deepEqual(canvasPointToMap(mapPointToCanvas(world, map, view), map, view), world);
assert.equal(isPointOnMap({ x: 10, y: 20 }, map), true);
assert.equal(isPointOnMap({ x: 16, y: 20 }, map), false);
assert.equal(isComponentHit({ x: 11, y: 21, yaw: 0, attributes: { width_m: 1, height_m: 1 } }, mapPointToCanvas({ x: 11, y: 21 }, map, view), map, view), true);
```

Include a rotated component case and assert that `zoomAt` clamps scale to `5..500` while retaining the pointer's world position.

- [ ] **Step 2: Run the focused test before implementation**

Run: `cd frontend && node --test test/deployment/canvas-geometry.test.mjs`

Expected: FAIL because `deployment/canvas-geometry.js` does not exist.

- [ ] **Step 3: Implement geometry functions with existing formulae**

Copy the current coordinate, rotation, resize-handle and rotate-handle maths literally into pure functions. `zoomAt` must use the existing multipliers `1.12` and `0.89`, then calculate `x` and `y` using the old/new-scale pointer anchoring formula.

- [ ] **Step 4: Adapt the page entry through thin wrappers**

Import the geometry functions in `deployment.js`. Keep existing function names as wrappers where event handlers expect them, with wrappers converting a `PointerEvent` via `canvas.getBoundingClientRect()` and forwarding the explicit values. Replace duplicated component hit/handle and wheel formulas with geometry calls.

Run: `cd frontend && node --test test/deployment/canvas-geometry.test.mjs`

Expected: PASS with the original map interaction math represented in tests.

### Task 3: Canvas renderer module

**Files:**
- Create: `autodrive_console/web/deployment/canvas-renderer.js`
- Modify: `autodrive_console/web/deployment.js:651-1132`

**Interfaces:**
- Produces `drawDeploymentCanvas(snapshot)`.
- `snapshot` includes `{ context, canvasBox, activeMap, mapImage, liveMapImage, mappingPreview, project, view, selectedComponent, routeDraft, eraser }` and pure helpers `{ mapPointToCanvas, componentDimensions, componentName }`.
- The renderer makes no network requests, DOM queries, global reads or state mutations.

- [ ] **Step 1: Add a static contract test before moving drawing code**

Extend `frontend/test/deployment/canvas-geometry.test.mjs` with an import assertion for `drawDeploymentCanvas` from the yet-missing renderer module.

Run: `cd frontend && node --test test/deployment/canvas-geometry.test.mjs`

Expected: FAIL with module-not-found.

- [ ] **Step 2: Extract drawing helpers behind the snapshot**

Move `drawGrid`, erase overlays, route drawing, elevator-door marker, component symbol drawing and `drawMap` into `canvas-renderer.js`. Preserve existing colors, strokes, alpha values, label sizing, selected-component handles and map-image fallback. Convert all reads of former globals to `snapshot` fields or helper calls.

- [ ] **Step 3: Keep an entry-point drawing adapter**

In `deployment.js`, replace the old draw implementation with a small `drawMap()` adapter that creates the required snapshot and invokes `drawDeploymentCanvas(snapshot)`. Existing calls to `drawMap()` and all event handlers remain unchanged.

- [ ] **Step 4: Verify geometry and whole Web check**

Run:

```bash
cd frontend
node --test test/deployment/component-specs.test.mjs test/deployment/canvas-geometry.test.mjs
cd ..
scripts/test-web.sh
```

Expected: all tests pass and Vite build succeeds.

### Task 4: Module page entry and regression guards

**Files:**
- Modify: `autodrive_console/web/deployment.html:deployment.js script tag`
- Modify: `frontend/check-parity.mjs`
- Modify: `docs/development/frontend-asset-ownership.md`

**Interfaces:**
- `/deployment.html` loads `deployment.js` as an ES module and preserves `app_shell.js` loading.
- Parity guard requires the module tag, all three deployment module imports and existing deployment endpoints (`/api/deployments`, `/api/mapping/sessions`, `/task-compiler/preview`).

- [ ] **Step 1: Add failing static migration guard**

Add checks requiring:

```js
'type="module" src="/deployment.js"'
'from "./deployment/component-specs.js"'
'from "./deployment/canvas-geometry.js"'
'from "./deployment/canvas-renderer.js"'
```

Run: `cd frontend && node check-parity.mjs`

Expected: FAIL before the HTML tag and imports are updated.

- [ ] **Step 2: Switch only the deployment entry script tag**

Use:

```html
<script type="module" src="/deployment.js"></script>
<script src="/app_shell.js"></script>
```

Do not change markup or CSS load order.

- [ ] **Step 3: Record the deployment module boundary**

Update `frontend-asset-ownership.md` to list the three `web/deployment/` modules under the `/deployment.html` row and explain that only the entry file owns page state and API calls.

- [ ] **Step 4: Final verification and focused commit**

Run:

```bash
git diff --check
pixi run frontend-check
scripts/test-web.sh
python3 web_console.py
```

With the local console running, issue only GET requests to `/deployment.html`, `/deployment.js`, and each module URL; all must return HTTP 200. Stop the local console afterwards. Commit only the module sources, tests, entry page, parity guard and ownership document:

```bash
git add autodrive_console/web/deployment.js autodrive_console/web/deployment.html autodrive_console/web/deployment frontend/check-parity.mjs frontend/test/deployment docs/development/frontend-asset-ownership.md
git commit -m "refactor(web): modularize deployment canvas"
```

## Plan Self-Review

- Spec coverage: Tasks 1–3 implement all stated module boundaries; Task 4 verifies the ES module page integration and documents ownership.
- Scope: API/DOM/state/CSS migration is explicitly deferred, so the change remains one independently testable Canvas batch.
- Naming: imports, exports and test paths consistently use `deployment/`, `canvas-geometry` and `canvas-renderer`.
- No placeholder scan: the plan uses concrete file paths, function signatures, test cases and commands; there are no deferred implementation markers.
