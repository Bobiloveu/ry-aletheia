# Deployment Acceptance Report Archive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add first-class deployment acceptance evidence reports, visible optional-preparation state, and resilient desktop plan-input drafts.

**Architecture:** Keep the current controlled execution boundary intact. The backend classifies and safely cleans archived reports, writes a self-contained acceptance evidence file, and persists a small status snapshot from the existing sequence callback. Legacy desktop pages consume the expanded data without changing ROS, Supervisor or mobile behavior.

**Tech Stack:** Python 3.10, standard-library HTTP server, dataclasses, pytest, static HTML/CSS/JavaScript, existing SVG trajectory evidence.

**Spec:** `docs/superpowers/specs/2026-09-04-acceptance-report-archive-design.md`

## Global Constraints

- Browser remains a controlled HTTP client; it never directly controls ROS, Supervisor or files.
- Default acceptance execution has no scene profile and no Supervisor orchestration.
- Selected, frozen preparation runs once before the sequence; restore only rewrites the normal script and never restarts Supervisor nodes.
- Do not redesign the mobile application; preserve its existing report-list parsing.
- Preserve test reports, schema-1/2 plans and report URLs; never stage `log/`, reports, maps or vehicle data.

---

### Task 1: Type-aware archive with safe acceptance cleanup

**Files:**
- Modify: `web_console.py: REPORT_FILENAME, _reports, _archive_report_target, _delete_report`
- Modify: `autodrive_console/acceptance_report.py`
- Test: `tests/test_acceptance.py`, `tests/test_offline_modules.py`

**Interfaces:** `GET /api/reports` preserves existing fields and adds `report_type: "test" | "acceptance"` and `title: str`. Acceptance asset manifests reference only `run_<id>_trajectory` directories inside `reports/`.

- [ ] Write tests that index test and acceptance reports with distinct types/titles, then verify they fail.
- [ ] Add a filename classifier, a validated manifest reader/writer, and type-safe report deletion without changing download URLs.
- [ ] Verify: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run pytest tests/test_acceptance.py tests/test_offline_modules.py -k 'acceptance_report or reports_index or delete_acceptance' -q`.

### Task 2: Self-contained acceptance evidence HTML

**Files:**
- Modify: `autodrive_console/acceptance_report.py`
- Test: `tests/test_acceptance.py`

**Interfaces:** `AcceptanceReportWriter.write(plan)` consumes `item.trajectory.visualizations`, embeds only verified SVG files, and returns HTML/CSV/manifest names.

- [ ] Write tests for inline SVG trajectory evidence, task start/end/duration values, escaping, and absence of random seed; verify failure first.
- [ ] Replace only the acceptance template with the established report visual vocabulary: status, summary, coverage, time, preparation summary, task results, trajectory cards and print styles.
- [ ] Verify: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run pytest tests/test_acceptance.py -k 'acceptance_report' -q`.

### Task 3: Persist runtime-preparation progress

**Files:**
- Modify: `autodrive_console/acceptance_plan.py`, `autodrive_console/acceptance_orchestrator.py`, `autodrive_console/run_manager.py`
- Modify: `shared/contracts/task_execution.md`
- Test: `tests/test_acceptance.py`, `tests/test_trajectory_fallback.py`

**Interfaces:** plan public/storage data exposes `execution_preflight_status = {state, message, updated_at}`. Existing sequence callbacks add allowlisted `preflight_progress` and final restoration events.

- [ ] Write failing tests for ordered preparation phase events and persisted public status after reload.
- [ ] Emit only human-readable, allowlisted state/message from the existing sequence lifecycle and persist it in the orchestrator.
- [ ] Verify: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run pytest tests/test_acceptance.py tests/test_trajectory_fallback.py -k 'preflight_progress or preflight_status' -q`.

### Task 4: Clarify optional preparation and retain desktop drafts

**Files:**
- Modify: `autodrive_console/web/acceptance-test.html`, `autodrive_console/web/acceptance_test.js`, `autodrive_console/web/acceptance_test.css`
- Test: `tests/test_acceptance.py`

**Interfaces:** desktop-only localStorage key `ry-aletheia-acceptance-draft-v1`; UI consumes frozen configuration plus `execution_preflight_status`.

- [ ] Write a failing static test for “可选运行准备”, status output and the versioned draft key.
- [ ] Implement a compact progressive disclosure, unambiguous default copy, semantic status strip, per-input draft persistence/revalidation and clear-on-create behavior.
- [ ] Verify static test, then inspect desktop and narrow-desktop browser render, keyboard focus, error state and no console errors.

### Task 5: Report Center type-aware presentation

**Files:**
- Modify: `autodrive_console/web/reports.html`, `autodrive_console/web/reports.js`, `autodrive_console/web/reports.css`
- Test: `tests/test_acceptance.py`

**Interfaces:** existing Report Center actions retain preview/download/CSV/delete routes and consume `report_type`, `title`.

- [ ] Write a failing static test that requires both “自动测试运行报告” and “部署验收报告” rendering paths.
- [ ] Add restrained Chinese type markers and copy, preserving responsive action layout and all existing actions.
- [ ] Run `node /home/bob/.codex/skills/impeccable/scripts/detect.mjs --json autodrive_console/web/acceptance-test.html autodrive_console/web/acceptance_test.js autodrive_console/web/acceptance_test.css autodrive_console/web/reports.html autodrive_console/web/reports.js autodrive_console/web/reports.css` and address actionable findings.

### Task 6: Documentation and complete regression

**Files:**
- Modify: `README.md`, `PROJECT_OVERVIEW.md`, `shared/contracts/task_execution.md`
- Test: relevant backend and web suites

- [ ] Document both report types, acceptance evidence, optional preparation status and local-only draft recovery.
- [ ] Verify: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ./scripts/test-backend.sh`, `./scripts/test-web.sh`, and `git diff --check`.
- [ ] Review `git status --short` before handoff; retain unrelated existing changes and untracked `log/`.
