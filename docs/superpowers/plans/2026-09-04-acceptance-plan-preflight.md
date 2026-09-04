# Deployment Acceptance Plan Preflight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Let a deployment-acceptance plan use one optional saved scenario profile and one optional saved Supervisor dependency plan before the whole sequence, without altering existing mission dispatch or mobile behavior.

**Architecture:** The plan freezes the selected scenario identity and an owned copy of the current Supervisor plan. `AcceptanceOrchestrator` validates and passes that context to `RunManager.start_sequence`. The run manager applies the selected scenario and restarts the selected dependencies once before the first item, then every item keeps the existing task sync, ROS service, trajectory and readiness checks without repeating restart work. Restoration is performed once in the sequence `finally` path and only restores the startup script.

**Tech Stack:** Python 3.10, existing `ScenarioSetupStore`, `RobotGateway`, `RunManager`, native HTML/CSS/JS and pytest.

**Spec:** User-confirmed deployment acceptance extension, 2026-09-04.

## Global Constraints

- Do not create a ROS node, Topic, Service, executor, task-dispatch path or mobile UI.
- Reuse existing `ScenarioSetupStore`, `RobotGateway`, `RunManager` and `/start_execute_tasks` ownership.
- The configured preflight applies once per frozen plan, never once per item.
- On completion, cancellation, blocked preparation or unexpected sequence failure, restore only the scenario startup script; do not start, stop or restart Supervisor nodes as part of restoration.
- The normal test flow and per-case scene binding behavior must remain unchanged.
- Browser input may select only an existing saved scenario profile and whether to use the currently saved dependency plan; it may not submit paths, Supervisor node names or arbitrary steps.

---

### Task 1: Freeze and validate plan-level preflight

**Files:**
- Modify: `autodrive_console/acceptance_plan.py`
- Modify: `autodrive_console/acceptance_orchestrator.py`
- Modify: `web_console.py`
- Test: `tests/test_acceptance.py`

- [ ] Write a failing test proving that the create request stores a selected profile and a deep-copied enabled dependency plan, then start passes the frozen context to `start_sequence`.
- [ ] Run `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest -q tests/test_acceptance.py -k plan_preflight` and confirm it fails because the new request fields/context do not exist.
- [ ] Add a versioned, backwards-readable `execution_preflight` plan field; accept schema 1 as no-preflight and write schema 2 for new plans.
- [ ] Allow only `scenario_profile_id` and `use_dependency_plan` as new create input. Verify the ID against `ScenarioSetupStore`; take the dependency snapshot only from the current validated `SettingsStore` value.
- [ ] Re-run the targeted tests and confirm pass.

### Task 2: Execute plan preflight exactly once

**Files:**
- Modify: `autodrive_console/run_manager.py`
- Modify: `autodrive_console/robot_gateway.py`
- Test: `tests/test_trajectory_fallback.py`

- [ ] Write a failing run-manager test with two frozen cases showing one scenario application, one dependency restart, no per-item restart, and one final restore.
- [ ] Run the targeted test and confirm it fails on current behavior.
- [ ] Add an explicit sequence context passed only by acceptance. Apply scenario, settle, and invoke the frozen dependency plan before the loop. Each child uses the existing sync/readiness gates without orchestration or case-bound scenario application.
- [ ] Guarantee sequence `finally` restores a successfully applied profile once, including cancel/error paths, and never restarts during restoration.
- [ ] Re-run run-manager and acceptance tests.

### Task 3: Operate UI and contract

**Files:**
- Modify: `autodrive_console/web/acceptance-test.html`
- Modify: `autodrive_console/web/acceptance_test.js`
- Modify: `autodrive_console/web/acceptance_test.css`
- Modify: `shared/contracts/task_execution.md`
- Test: `tests/test_acceptance.py` or `tests/test_offline_modules.py`

- [ ] Write a failing static/UI test for the optional scenario selector, dependency checkbox and frozen-plan summary.
- [ ] Add a compact preflight form before plan creation. It reads existing `/api/scenario-setup` and `/api/settings`, defaults to no scenario/no dependency plan, and cannot submit arbitrary process data.
- [ ] Display the frozen preflight in the generated plan and use confirmation copy that says it is run once before the whole plan and restored without restart after it ends.
- [ ] Document Backend/Web consumers and Mobile non-consumer status in the shared task execution contract.
- [ ] Run backend tests, web test/build, Impeccable detector and `git diff --check`.
