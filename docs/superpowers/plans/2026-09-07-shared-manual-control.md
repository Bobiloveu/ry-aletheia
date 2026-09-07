# Shared Manual Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable multiple Web/App clients to join shared manual control without creating concurrent ROS2 publishers.

**Architecture:** `VehicleControlController` replaces its single client session with opaque per-client sessions and a global motion owner. The newest valid direction input overrides the global target. The source and velocity publishers remain singleton backend resources.

**Tech Stack:** Python 3, rclpy, static JavaScript, pytest, Vite.

**Spec:** `docs/superpowers/specs/2026-09-07-shared-manual-control-design.md`

## Global Constraints

- Only the backend may publish control source and Twist messages.
- Every nonzero Twist needs miniapp confirmation, an active caller session, and confirmed normal emergency state.
- STOP clears the global target immediately.
- Session IDs remain opaque and are never returned from GET status.

---

### Task 1: Convert the backend state machine to shared sessions

**Files:**

- Modify: `autodrive_console/vehicle_control.py`
- Modify: `tests/test_vehicle_control.py`

**Interfaces:**

- `begin_manual_session()` returns a new caller-specific session ID while existing active sessions remain valid.
- Snapshot adds `shared_sessions.active_count` while retaining `session.present` and `session.state`.

- [ ] Write a failing test that starts two sessions under confirmed miniapp, asserts distinct IDs and active count two, then sends forward from the first and left from the second and asserts the second command owns the global target.
- [ ] Run `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest -q tests/test_vehicle_control.py::<new test>` and confirm the current singleton session rejection fails it.
- [ ] Add `_sessions: dict[str, dict[str, Any]]` and `_motion_session_id`; change lookup, begin, state callbacks, snapshots, heartbeat checks, input watchdog and external takeover cleanup to operate on collections.
- [ ] Ensure input/heartbeat expiry removes only its own client and STOPs only when the expired client owns the latest direction.
- [ ] Run `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pixi run python -m pytest -q tests/test_vehicle_control.py` and commit only the backend and test files.

### Task 2: Add per-client release and preserve global return to navigation

**Files:**

- Modify: `autodrive_console/vehicle_control.py`
- Modify: `web_console.py`
- Modify: `tests/test_vehicle_control.py`

**Interfaces:**

- New `release_manual_session(session_id)` and `POST /api/vehicle-control/release` remove one client without changing source.
- `/exit` and `/navigation` stop, invalidate every session, then request navigation.

- [ ] Write failing tests showing release of the first of two sessions leaves the second usable, while explicit navigation clears both sessions and sets a navigation transition.
- [ ] Run the focused test and confirm missing release behavior fails it.
- [ ] Implement `release_manual_session`; it validates the caller, STOPs only if that caller owns motion, and never publishes a source command. Route it through the HTTP handler.
- [ ] Update global navigation cleanup to invalidate the full collection before publishing STOP and navigation.
- [ ] Run the vehicle-control test file and commit only touched backend, adapter and tests.

### Task 3: Update Web lifecycle and shared contract

**Files:**

- Modify: `autodrive_console/web/manual-control.html`
- Modify: `autodrive_console/web/manual_control.js`
- Modify: `shared/contracts/robot_control.md`
- Modify: `tests/test_offline_modules.py`

**Interfaces:**

- Page displays `多人共享控制 · N 个在线端 · 最后指令生效` from `shared_sessions.active_count`.
- Page leave posts its local session ID to `/release`; explicit automatic-mode action remains global.

- [ ] Write a failing source-level Web test for the shared-control copy, `/release`, and a `sendBeacon` release request.
- [ ] Run the focused offline module test and confirm it fails before the page is changed.
- [ ] Add shared session count UI, preserve local-session-only direction enablement, join confirmed miniapp when the page has no local ID, and switch page leave from exit to release.
- [ ] Update the Existing robot-control contract with last-input-wins, per-client release, global navigation, unchanged emergency limits, and Web/App impact.
- [ ] Run `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ./scripts/test-backend.sh` and `./scripts/test-web.sh`; commit only touched Web, contract and test files.

### Task 4: Final verification

**Files:** Verify only the preceding work.

- [ ] Run `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ./scripts/test-backend.sh && ./scripts/test-web.sh && git diff --check`.
- [ ] Run `git status --short` and confirm user-owned dirty files remain unstaged.
