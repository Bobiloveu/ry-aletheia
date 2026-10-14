# Vehicle Software Inventory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Desktop software-inventory tool that reads installed `ry-*` Debian packages, persists an editable vehicle profile and package notes, and exports a complete PNG version matrix.

**Architecture:** A focused Backend inventory service performs a fixed, non-shell `dpkg-query` and merges its read-only package facts with the locally persisted `software_inventory` profile. Dedicated HTTP endpoints expose a controlled snapshot to the legacy Desktop page. The page uses existing app-shell styling and browser Canvas only, so the complete displayed snapshot can be exported locally without a server-side renderer.

**Tech Stack:** Python 3 standard library, existing `SettingsStore` JSON persistence, `http.server` controller, legacy Desktop HTML/CSS/ES modules, Node static tests, pytest.

**Spec:** `docs/superpowers/specs/2026-10-09-vehicle-software-inventory-design.md`

## Global Constraints

- New page belongs to Desktop “系统 → 软件资产”; Mobile has no consumer.
- Only fixed `/usr/bin/dpkg-query --show --showformat … ry-*` may inspect package state; it must use `shell=False`, five-second timeout and empty stdin.
- No package install, uninstall, upgrade, APT action, ROS Topic, Supervisor, localization, navigation, chassis, or safety configuration operation is permitted.
- Package name, version, architecture and installation state are read-only facts. Vehicle profile, maintainer and description are locally editable.
- Persist profile and notes only under `config/console.json: software_inventory`, using the existing atomic settings write path.
- Require vehicle number, VIN, model, project/customer and deployment location before saving or exporting.
- API failures must be user-safe Chinese text and must not expose command lines, paths, stderr or dpkg database content.
- Keep the current dirty workspace intact; do not commit, package, deploy, upgrade, or restart the robot.

---

## File Structure

- `autodrive_console/software_inventory.py`: fixed package query, safe parsing, profile and package-note validation, snapshot composition and save orchestration.
- `autodrive_console/settings.py`: defaults, migration/deep-merge and validation for the persisted inventory namespace.
- `web_console.py`: ownership and GET/POST routes for the inventory service.
- `shared/contracts/software_inventory.md`: Backend/Desktop Web interface and consumers.
- `shared/contracts/README.md`: contract index entry.
- `autodrive_console/web/software-inventory.html`: Desktop inventory page document.
- `autodrive_console/web/software_inventory.js`: fetch, edit, save, request-order and Canvas PNG export behavior.
- `autodrive_console/web/software_inventory.css`: page-specific theme-consistent layout.
- `autodrive_console/web/app_shell.js`: system navigation entry.
- `tests/test_software_inventory.py`: unit behavior for querying, parsing, validation and note merging.
- `tests/test_software_inventory_http.py`: HTTP success/unavailable/validation behavior.
- `frontend/test/legacy-app-module.test.mjs`: static Desktop page and script expectations.

### Task 1: Inventory domain and persisted profile

**Files:**
- Create: `autodrive_console/software_inventory.py`
- Modify: `autodrive_console/settings.py`
- Test: `tests/test_software_inventory.py`

**Interfaces:**
- Consumes: `SettingsStore.load() -> RobotSettings`; `SettingsStore.save(data: dict) -> RobotSettings`.
- Produces: `SoftwareInventory.snapshot() -> dict` and `SoftwareInventory.save(payload: dict) -> dict`, both using `inventory_status`, `vehicle`, `packages`, and `discovered_at`.

- [ ] **Step 1: Write the failing unit tests**

```python
def test_snapshot_uses_fixed_non_shell_dpkg_query_and_merges_notes(tmp_path):
    calls = []
    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return CompletedProcess(argv, 0, "ry-runtime\\t1.2.3\\tamd64\\tii \\n", "")
    inventory = SoftwareInventory(SettingsStore(tmp_path / "console.json"), runner=runner)
    snapshot = inventory.snapshot()
    assert calls[0][0][0] == "/usr/bin/dpkg-query"
    assert calls[0][1]["shell"] is False
    assert snapshot["packages"][0]["package_filename"] == "ry-runtime_1.2.3_amd64.deb"
```

Add tests that reject non-installed and malformed records, return an unavailable snapshot on timeout/nonzero query, validate all five profile fields, reject notes for undiscovered packages, and retain only notes for currently installed packages.

- [ ] **Step 2: Run the unit test module and verify it fails**

Run: `pixi run python -m pytest -q tests/test_software_inventory.py`

Expected: FAIL because `autodrive_console.software_inventory` does not exist.

- [ ] **Step 3: Implement the minimal inventory service and settings support**

Create `SoftwareInventory` with injected `runner`, fixed `DPKG_QUERY` argv, package parser and user-safe `SoftwareInventoryError`. Add a `software_inventory` dictionary with `vehicle` and `package_notes` defaults to `RobotSettings`; deep-merge it on load and save. Validate profile text and notes before the existing atomic write.

- [ ] **Step 4: Run unit tests and verify they pass**

Run: `pixi run python -m pytest -q tests/test_software_inventory.py`

Expected: PASS.

### Task 2: HTTP contract and controlled endpoints

**Files:**
- Modify: `web_console.py`
- Create: `shared/contracts/software_inventory.md`
- Modify: `shared/contracts/README.md`
- Test: `tests/test_software_inventory_http.py`

**Interfaces:**
- Consumes: `SoftwareInventory.snapshot() -> dict`, `SoftwareInventory.save(payload: dict) -> dict`.
- Produces: `GET /api/software-inventory` and `POST /api/software-inventory`, with no-cache JSON responses.

- [ ] **Step 1: Write the failing HTTP tests**

```python
def test_inventory_get_returns_snapshot(client, inventory):
    response = client.get("/api/software-inventory")
    assert response.status == 200
    assert response.json["inventory_status"] == "available"

def test_inventory_post_rejects_unknown_package_note(client):
    response = client.post("/api/software-inventory", {"vehicle": VALID_VEHICLE, "package_notes": {"ry-nope": {}}})
    assert response.status == 400
```

Include GET unavailable as `200 inventory_status=unavailable`, POST unavailable as `503`, missing vehicle fields as `400`, and success as the refreshed saved snapshot.

- [ ] **Step 2: Run HTTP tests and verify they fail**

Run: `pixi run python -m pytest -q tests/test_software_inventory_http.py`

Expected: FAIL because the endpoint is unregistered.

- [ ] **Step 3: Register the service and routes**

Instantiate the service from the existing `SETTINGS`. Route only the two exact API paths, decode JSON using the existing request helper, map validation to 400 and discovery unavailability during save to 503. Set no-cache through the existing JSON response path. Document wire shape, ownership, consumer impact and verification in the new contract.

- [ ] **Step 4: Run HTTP tests and verify they pass**

Run: `pixi run python -m pytest -q tests/test_software_inventory_http.py`

Expected: PASS.

### Task 3: Desktop page, editable matrix and navigation

**Files:**
- Create: `autodrive_console/web/software-inventory.html`
- Create: `autodrive_console/web/software_inventory.css`
- Create: `autodrive_console/web/software_inventory.js`
- Modify: `autodrive_console/web/app_shell.js`
- Test: `frontend/test/legacy-app-module.test.mjs`

**Interfaces:**
- Consumes: `GET /api/software-inventory` and `POST /api/software-inventory`.
- Produces: a Desktop-only page with five required vehicle fields, live save result, refresh, read-only package facts and editable note fields.

- [ ] **Step 1: Write failing static module assertions**

```js
assert.match(appShellSource, /software-inventory\.html/);
assert.match(pageSource, /车架号/);
assert.match(scriptSource, /\/api\/software-inventory/);
assert.match(scriptSource, /requestSequence/);
assert.match(scriptSource, /readonly/);
```

Add checks that package facts are rendered as text, save disables duplicate submission and the export action has disabled-state handling.

- [ ] **Step 2: Run the focused Node test and verify it fails**

Run: `node --test frontend/test/legacy-app-module.test.mjs`

Expected: FAIL because the page and script do not exist.

- [ ] **Step 3: Implement the page**

Use the established `app_shell.js`, `styles.css`, `refinement.css` and existing request helper. Render read-only facts with `textContent`; render maintainer and description inputs only for editable notes. Use request sequence IDs so stale refreshes do not overwrite newer state. Keep errors and save results in an `aria-live` element. Add the system navigation entry and page-specific theme-consistent styles.

- [ ] **Step 4: Run focused Node tests and verify they pass**

Run: `node --test frontend/test/legacy-app-module.test.mjs`

Expected: PASS.

### Task 4: Canvas PNG export and end-to-end regression

**Files:**
- Modify: `autodrive_console/web/software_inventory.js`
- Modify: `frontend/test/legacy-app-module.test.mjs`
- Test: `tests/test_software_inventory.py`, `tests/test_software_inventory_http.py`, `frontend/test/legacy-app-module.test.mjs`

**Interfaces:**
- Consumes: the last successful displayed snapshot.
- Produces: one or more local `ry-software-inventory-<vehicle>-<beijing-timestamp>.png` downloads containing brand, generation time, vehicle fields, package count, every displayed row and provenance.

- [ ] **Step 1: Write failing export assertions**

```js
assert.match(scriptSource, /canvas\.toBlob/);
assert.match(scriptSource, /Asia\/Shanghai/);
assert.match(scriptSource, /版本来自本机已安装/);
assert.match(scriptSource, /lastSuccessfulSnapshot/);
assert.match(scriptSource, /pageIndex/);
```

- [ ] **Step 2: Run focused Node test and verify it fails**

Run: `node --test frontend/test/legacy-app-module.test.mjs`

Expected: FAIL because Canvas export and safe multi-page handling do not exist.

- [ ] **Step 3: Implement native Canvas export**

Build rows from only `lastSuccessfulSnapshot`, wrap content, and split at a conservative canvas height. Put Beijing time, all five profile fields, package total, all matrix rows and provenance on each export set. Sanitize the vehicle number to a filename-safe segment, create PNG blobs with `canvas.toBlob`, download each numbered file, and disable export whenever the profile or snapshot is not valid.

- [ ] **Step 4: Run focused tests and verify they pass**

Run: `node --test frontend/test/legacy-app-module.test.mjs`

Expected: PASS.

### Task 5: Requirement audit and affected-module checks

**Files:**
- Modify: implementation and tests only if an audit identifies a concrete gap.

- [ ] **Step 1: Run targeted backend regression**

Run: `pixi run python -m pytest -q tests/test_software_inventory.py tests/test_software_inventory_http.py tests/test_offline_modules.py`

Expected: PASS.

- [ ] **Step 2: Run required Backend verification**

Run: `scripts/test-backend.sh`

Expected: PASS; if the known suite stalls without output, record the exact completed output and do not call it a pass.

- [ ] **Step 3: Run required Web verification**

Run: `scripts/test-web.sh`

Expected: PASS.

- [ ] **Step 4: Run static integrity checks**

Run: `python -m py_compile autodrive_console/software_inventory.py autodrive_console/settings.py web_console.py && git diff --check`

Expected: PASS.

- [ ] **Step 5: Review against the specification**

Check every scope, validation, unavailable-state, user-safe-copy, Canvas export and no-side-effect requirement in `docs/superpowers/specs/2026-10-09-vehicle-software-inventory-design.md`. Confirm no package manager, ROS, Supervisor, build, deployment or robot restart command was used.
