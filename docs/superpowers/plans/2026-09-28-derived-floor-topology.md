# Derived Floor Topology Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove manual map-instance floor entry and derive operational physical-floor data solely from an associated elevator landing.

**Architecture:** Map instances retain only their role and building/unit identity.  A target map's elevator landing supplies the panel button label, while its linked physical elevator converts that label into the zero-based runtime physical floor.  User-facing room notation remains based on the panel label, not the runtime index.

**Tech Stack:** Python deployment store/compiler, browser deployment workspace, pytest, Node test runner.

**Spec:** User-approved in-chat design, 2026-09-28.

## Global Constraints

- Preserve the existing guided deployment UI and styling; remove only the inappropriate manual floor field and related copy.
- Never ask implementation staff to enter a physical-floor value.
- Existing persisted projects remain readable; only newly saved map instances omit manual floor data.
- Runtime physical floors are calculated with the established elevator-button conversion, not inferred from a room number.

---

### Task 1: Store map instances without a manual floor

**Files:**
- Modify: `tests/test_deployment.py`
- Modify: `autodrive_console/deployment.py`

- [ ] Add a store test that submits a legacy `floor` value and asserts the newly persisted unit map instance has no manually controlled floor value.
- [ ] Run the test and confirm it fails because `add_map_instance` persists the request floor.
- [ ] Make `add_map_instance` ignore supplied floors for unit instances, retain building/unit validation, and keep global instances empty.
- [ ] Run the focused store test and confirm it passes.

### Task 2: Derive multi-task branches from elevator landings

**Files:**
- Modify: `tests/test_task_route_families.py`
- Modify: `autodrive_console/task_route_families.py`

- [ ] Add a route-family test with a floor-less target map instance, target elevator button 15, and a physical elevator serving 1–15; assert physical floor `14`, button floor `15`, and room `1501 → 01`.
- [ ] Run the test and confirm it fails because route families require `map_instances[].floor`.
- [ ] Resolve the landing's linked physical elevator, validate the panel button through `physical_floor_index`, and use the button label only for room/file naming.
- [ ] Run the focused route-family tests and confirm they pass.

### Task 3: Keep single-task artifact identity derived

**Files:**
- Modify: `tests/test_task_compiler.py`
- Modify: `autodrive_console/task_compiler.py`

- [ ] Add a compiler test that removes target/lobby instance floors and asserts output identity is still generated from the elevator landing button.
- [ ] Run the test and confirm it fails because the artifact name reads `target_instance['floor']`.
- [ ] Derive the filename floor label from the validated target elevator landing while retaining the established physical runtime floor conversion.
- [ ] Run the focused compiler test and confirm it passes.

### Task 4: Preserve the guided UI while removing manual floor entry

**Files:**
- Modify: `frontend/test/deployment-workflow.test.mjs`
- Modify: `autodrive_console/web/deployment.html`
- Modify: `autodrive_console/web/deployment.js`

- [ ] Add a browser-source behavior test for a floor-less map-instance request and floor-free guidance copy.
- [ ] Run it and confirm it fails against the existing payload/UI copy.
- [ ] Remove the floor control and request property; display a neutral “waiting for elevator landing derivation” summary where an unresolved legacy value would otherwise be shown.
- [ ] Run the focused web test and confirm it passes.

### Task 5: Verify affected consumers

**Files:**
- Modify: `shared/contracts/deployment.md`

- [ ] Document that map-instance floors are derived, with panel button labels separate from zero-based runtime physical floors.
- [ ] Run `scripts/test-backend.sh` and `scripts/test-web.sh`.
- [ ] Run `git diff --check` and inspect the diff for unintentional UI changes.
