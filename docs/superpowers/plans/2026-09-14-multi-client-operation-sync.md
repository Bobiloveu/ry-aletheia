# Multi-client Operation Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure every open console shows the same shared operational plan or run, while retaining unsaved personal drafts and display preferences locally.

**Architecture:** Existing backend plan/run APIs remain the authoritative source; no ROS, protocol, or API contract changes are required. The acceptance page derives its visible scope from a nonterminal frozen plan and polls the small current-plan resource independently of its catalog; the task dashboard keeps observing the current run when idle so a run created by another operator appears without reload.

**Tech Stack:** Python HTTP backend (unchanged), browser ES modules, Node unit tests, Vite parity/build checks.

**Spec:** User-confirmed collaboration rule on 2026-09-14: synchronize active execution facts across terminals; retain local drafts and visual preferences; never silently overwrite in-progress configuration edits.

## Global Constraints

- Do not change ROS control, deployment execution, or external API schemas.
- `/api/acceptance/plans/current` and `/api/runs/latest` remain the sole sources for active operational truth.
- Local theme, map view, and other personal display preferences remain browser-local.
- A nonterminal frozen acceptance plan must override its page's local creation draft.
- A page must not continuously reload editable configuration documents from another operator and destroy unsaved input.

---

### Task 1: Make shared frozen acceptance plans authoritative in every browser

**Files:**

- Modify: `autodrive_console/web/acceptance_preparation.js`
- Modify: `autodrive_console/web/acceptance_test.js`
- Modify: `autodrive_console/web/acceptance-test.html`
- Modify: `autodrive_console/web/acceptance_test.css`
- Test: `frontend/test/acceptance-preparation.test.mjs`

**Interfaces:**

- Consumes: `GET /api/acceptance/plans/current` response field set: `status`, `scope_type`, `community`, `building`, `unit`, `mode`, and frozen `execution_preflight`.
- Produces: `activeAcceptancePlanSelection(plan)`, returning the shared selection only for a nonterminal frozen plan; `null` otherwise.

- [x] **Step 1: Write the failing test**

```js
test("an active frozen plan owns the acceptance scope instead of a local draft", () => {
  assert.deepEqual(
    activeAcceptancePlanSelection({
      status: "running", scope_type: "building", community: "高科一号",
      building: 3, unit: 1, mode: "full",
      execution_preflight: { scenario_profile_id: null, dependency_plan_enabled: true },
    }),
    { scope: "building", community: "高科一号", buildingUnit: "3:1", mode: "full", scenarioProfileId: "", dependencyPlanEnabled: true },
  );
});
```

- [x] **Step 2: Run test to verify it fails**

Run: `node --test frontend/test/acceptance-preparation.test.mjs`

Expected: FAIL because `activeAcceptancePlanSelection` does not exist.

- [x] **Step 3: Write minimal implementation**

```js
export function activeAcceptancePlanSelection(plan) {
  if (!sharedPlanStatuses.has(plan?.status)) return null;
  return {
    scope: plan.scope_type,
    community: plan.community,
    buildingUnit: plan.scope_type === "building" ? `${plan.building}:${plan.unit}` : "",
    mode: plan.mode,
    scenarioProfileId: plan.execution_preflight?.scenario_profile_id || "",
    dependencyPlanEnabled: plan.execution_preflight?.dependency_plan_enabled === true,
  };
}
```

Use the returned selection on every current-plan refresh, lock plan-creation inputs while shared, and show a concise source-of-truth notice. Continue restoring `localStorage` drafts only when no nonterminal plan exists. Poll only `/api/acceptance/plans/current` on a modest visible-page cadence; retain full catalog/settings reload for initial load and explicit actions.

- [x] **Step 4: Run tests to verify it passes**

Run: `node --test frontend/test/acceptance-preparation.test.mjs`

Expected: PASS, including the new active-plan selection assertion.

### Task 2: Keep the task dashboard aware of runs created elsewhere

**Files:**

- Create: `autodrive_console/web/task_dashboard_sync.js`
- Modify: `autodrive_console/web/app.js`
- Create: `frontend/test/task-dashboard-sync.test.mjs`

**Interfaces:**

- Consumes: current run object returned by `GET /api/runs/latest`.
- Produces: `taskDashboardRefreshDelay(run)` in milliseconds.

- [x] **Step 1: Write the failing test**

```js
test("task dashboard continues a low-rate poll while idle so externally created runs appear", () => {
  assert.equal(taskDashboardRefreshDelay(null), 3000);
  assert.equal(taskDashboardRefreshDelay({ status: "running" }), 1000);
});
```

- [x] **Step 2: Run test to verify it fails**

Run: `node --test frontend/test/task-dashboard-sync.test.mjs`

Expected: FAIL because the module does not exist.

- [x] **Step 3: Write minimal implementation**

```js
export function taskDashboardRefreshDelay(run) {
  return activeRunStatuses.has(run?.status) ? 1000 : 3000;
}
```

Schedule the existing current-run request at that cadence while the page is visible. Do not alter stored UI preferences or write configuration during polling.

- [x] **Step 4: Run tests to verify it passes**

Run: `node --test frontend/test/task-dashboard-sync.test.mjs`

Expected: PASS with 1 s active and 3 s idle intervals.

### Task 3: Verify shared-state behavior and preserve design boundaries

**Files:**

- Verify: `autodrive_console/web/acceptance-test.html`
- Verify: `autodrive_console/web/index.html`
- Verify: `frontend/test/acceptance-preparation.test.mjs`
- Verify: `frontend/test/task-dashboard-sync.test.mjs`

- [x] **Step 1: Run focused tests**

Run: `node --test frontend/test/acceptance-preparation.test.mjs frontend/test/task-dashboard-sync.test.mjs`

Expected: PASS; active plan selection and idle/active dashboard cadence are covered.

- [x] **Step 2: Run required module checks**

Run: `./scripts/test-backend.sh && ./scripts/test-web.sh && git diff --check`

Expected: all backend tests pass, web unit/build check passes, and no whitespace errors occur.

- [x] **Step 3: Visually inspect the acceptance source-of-truth notice**

Run: start the local console, open `acceptance-test.html` with an active plan fixture or live plan, and inspect desktop/mobile layout.

Expected: the notice is subordinate to the existing scope card, active controls are clearly read-only, and normal draft creation has no new visible UI.
