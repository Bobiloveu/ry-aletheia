# Frontend Platform Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a testable shared frontend platform layer and migrate Robot Logs to it without changing runtime behavior.

**Architecture:** Plain browser ES modules under `autodrive_console/web/platform/` are the single source for framework-independent HTTP and formatting utilities. Robot Logs is the first traditional-page consumer; its entry becomes a module while its state, DOM handling, endpoints, and shell remain unchanged.

**Tech Stack:** Browser ES modules, native `fetch`, Node built-in test runner, Vite 7.

**Spec:** `docs/superpowers/specs/2026-09-08-frontend-platform-foundation-design.md`

## Global Constraints

- Preserve current URLs, request methods, request bodies, DOM IDs, user-visible Chinese copy, WebSocket/ROS contracts, and safety boundaries.
- Do not modify `web_console.py`, `shared/contracts/`, `app_shell.css`, `app_shell.js`, `refinement.css`, or generated `web-vue/` output.
- Add no package dependency and never commit `node_modules`.

---

### Task 1: Shared HTTP and formatting modules

**Files:**
- Create: `autodrive_console/web/platform/http.js`
- Create: `autodrive_console/web/platform/format.js`
- Create: `frontend/test/platform/http.test.mjs`
- Create: `frontend/test/platform/format.test.mjs`
- Modify: `frontend/package.json`

**Interfaces:**
- Produces `RequestError(message, { status, payload, url })` and `requestJson(url, options = {}, { fetchImpl = globalThis.fetch } = {})`.
- Produces `formatFileSize(value)` and `formatUnixSeconds(value, locale = "zh-CN")`.

- [ ] **Step 1: Write failing HTTP and formatting tests**

```js
assert.deepEqual(await requestJson("/api/value", {}, { fetchImpl }), { ready: true });
await assert.rejects(() => requestJson("/api/value", {}, { fetchImpl: errorResponse }), RequestError);
assert.equal(formatFileSize(1024), "1.0 KiB");
assert.equal(formatUnixSeconds("invalid"), "未知时间");
```

- [ ] **Step 2: Run the unit suite before modules exist**

Run: `cd frontend && node --test`  
Expected: FAIL with missing `autodrive_console/web/platform` modules.

- [ ] **Step 3: Implement only the exported interfaces**

```js
export async function requestJson(url, options = {}, { fetchImpl = globalThis.fetch } = {}) {
  const response = await fetchImpl(url, { cache: "no-store", ...options });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new RequestError(payload.error || `请求失败（HTTP ${response.status}）`, { status: response.status, payload, url });
  return payload;
}
```

`formatFileSize` must retain Robot Logs' `B`/`KiB`/`MiB` output; `formatUnixSeconds` rejects non-finite seconds rather than converting them to Unix epoch.

- [ ] **Step 4: Verify unit tests and integrate them into `npm run check`**

Set `test:unit` to `node --test`, prepend `npm run test:unit &&` to `check`, then run `pixi run frontend-check`.

### Task 2: Robot Logs platform migration

**Files:**
- Modify: `autodrive_console/web/robot_logs.js`
- Modify: `autodrive_console/web/robot-logs.html`
- Modify: `frontend/check-parity.mjs`

**Interfaces:**
- Consumes `requestJson`, `formatFileSize`, and `formatUnixSeconds` from `./platform/`.
- Preserves `/api/robot-logs/sources`, `/api/robot-logs/sources/<id>/files`, `/api/robot-logs/downloads`, and `/api/robot-logs/downloads/<id>`.

- [ ] **Step 1: Add a failing static migration guard**

The parity check must require `type="module" src="/robot_logs.js"`, the two platform imports, and the existing Robot Logs endpoints.

- [ ] **Step 2: Replace only local helper definitions with imports**

```js
import { requestJson } from "./platform/http.js";
import { formatFileSize, formatUnixSeconds } from "./platform/format.js";
```

Replace `formatBytes`/`formatTime` calls, retain state, event handlers, polling, DOM IDs, request options, and messages.

- [ ] **Step 3: Switch the page entry script to an ES module**

```html
<script type="module" src="/robot_logs.js"></script>
```

Keep the `app_shell.js` tag and all markup unchanged.

- [ ] **Step 4: Verify parity, build, and browser-static loading**

Run `scripts/test-web.sh`, then use the local console to load `/robot-logs.html` without saving, downloading, or deleting data. Confirm no module/resource 404 and that existing empty/error states remain readable.

### Task 3: Document source ownership

**Files:**
- Create: `docs/development/frontend-asset-ownership.md`

- [ ] **Step 1: Record the runtime source root and editable source for every routed page**

Document `web-vue` ownership for runtime settings, observation, and dashboard; document `web` ownership for deployment, mapping, manual control, acceptance, reports, cases, and logs.

- [ ] **Step 2: Record the legacy CSS order and public platform ownership**

List `styles.css → refinement.css → page_views.css → page CSS → app_shell.css`, and state that new public utilities belong in `autodrive_console/web/platform/`.

- [ ] **Step 3: Run final checks and commit one focused change**

Run `git diff --check`, `pixi run frontend-check`, and `scripts/test-web.sh`; commit only source, test, and documentation files from this plan.

## Plan Self-Review

- The scope is limited to a platform pilot, so deployment and observation remain independently reviewable follow-up work.
- Each new exported function has automated behavior coverage before production code.
- No task changes a shared protocol, backend route, or unsafe robot boundary.
