# 地图虚拟墙 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有部署地图画布中用两点绘制、编辑和删除红色虚拟墙，并自动生成随导出地图携带的 `map_walls.yaml`。

**Architecture:** 项目快照以世界坐标保存独立的两点线段；专用虚拟墙模块负责解析、校验和稳定序列化为 `image_relative` YAML。`DeploymentStore` 是唯一写入者，管理项目 JSON 与同目录墙文件的回滚式更新；定位清单只复制已生成的受控文件。浏览器只通过受控 API 提交创建、更新和删除，画布以红色无箭头线段与按需可见的端点手柄呈现。

**Tech Stack:** Python 3.10、PyYAML、`http.server` 路由、原生 Canvas 2D、ES modules、pytest、Node test runner。

**Spec:** `docs/superpowers/specs/2026-09-27-map-virtual-wall-design.md`

## Global Constraints

- 文件名必须固定为 `map_walls.yaml`，根节点为 `virtual_walls`，输出必须包含 `coordinate_mode: image_relative`、`frame_id: map`、`map_origin`、`thickness: 0.1` 和两点 `segments`。
- 绝不改写 `/opt/ry/data/maps` 原始地图、机器人运行目录、ROS 或既有部署向导/左侧导航。
- 虚拟墙不参与行为树、执行链或自动路线人工排序；变更仅使实验预览失效。
- 所有持久化坐标为世界坐标；YAML 写入时相对当前地图原点转换。
- 保持现有地图组件、擦除、平移、缩放和右键编辑交互不变。
- 不创建提交、暂存或推送；由用户决定版本控制操作。

---

### Task 1: 建立虚拟墙文件模型与 YAML 序列化

**Files:**
- Create: `autodrive_console/virtual_walls.py`
- Create: `tests/test_virtual_walls.py`

**Interfaces:**
- Produces `VirtualWallError(ValueError)`。
- Produces `parse_virtual_wall_segments(contents: bytes, origin: Sequence[float]) -> list[dict[str, dict[str, float]]]`，返回世界坐标的 `{start, end}` 段。
- Produces `render_virtual_wall_file(origin: Sequence[float], segments: Sequence[Mapping[str, Mapping[str, float]]]) -> bytes`。
- Produces `validate_segment(start: Mapping[str, object], end: Mapping[str, object]) -> dict[str, dict[str, float]]`，拒绝非有限值和零长度段。

- [ ] **Step 1: 写出 YAML 格式与反向坐标转换的失败测试**

```python
def test_rendered_wall_file_uses_image_relative_segments() -> None:
    contents = render_virtual_wall_file(
        [-38.0, -17.0, 0.0],
        [{"start": {"x": -37.5, "y": -16.25}, "end": {"x": -36.0, "y": -15.0}}],
    )

    assert b"coordinate_mode: image_relative" in contents
    assert b"frame_id: map" in contents
    assert parse_virtual_wall_segments(contents, [-38.0, -17.0, 0.0]) == [
        {"start": {"x": -37.5, "y": -16.25}, "end": {"x": -36.0, "y": -15.0}}
    ]
```

- [ ] **Step 2: 运行测试，确认因模块尚不存在而失败**

Run: `env -u PYTHONPATH pixi run python -m pytest tests/test_virtual_walls.py -q`

Expected: collection/import failure referencing `autodrive_console.virtual_walls`.

- [ ] **Step 3: 以安全 YAML 解析和稳定 YAML 渲染实现最小模型**

```python
def render_virtual_wall_file(origin, segments) -> bytes:
    document = {
        "virtual_walls": {
            "coordinate_mode": "image_relative",
            "frame_id": "map",
            "map_origin": [float(origin[0]), float(origin[1]), float(origin[2])],
            "thickness": 0.1,
            "segments": [_render_segment(origin, segment) for segment in segments],
        }
    }
    return yaml.safe_dump(document, allow_unicode=True, sort_keys=False).encode("utf-8")
```

Implement `_render_segment` as `[world_x - origin_x, world_y - origin_y, 0.0]`; allow `world` and `image_relative` parser modes only; reject unexpected structures, documents over the existing small metadata limit, non-numeric endpoint values and zero-length segments.

- [ ] **Step 4: 运行单元测试，确认通过**

Run: `env -u PYTHONPATH pixi run python -m pytest tests/test_virtual_walls.py -q`

Expected: PASS.

- [ ] **Step 5: 补充不合法输入与固定格式测试并复跑**

```python
@pytest.mark.parametrize("start,end", [
    ({"x": 0, "y": 0}, {"x": 0, "y": 0}),
    ({"x": float("nan"), "y": 0}, {"x": 1, "y": 0}),
])
def test_validate_segment_rejects_invalid_geometry(start, end) -> None:
    with pytest.raises(VirtualWallError):
        validate_segment(start, end)
```

Run: `env -u PYTHONPATH pixi run python -m pytest tests/test_virtual_walls.py -q`

Expected: PASS.

### Task 2: 让部署项目拥有、生成并导出虚拟墙

**Files:**
- Modify: `autodrive_console/deployment.py: import, map import, virtual-wall CRUD`
- Modify: `autodrive_console/location_manifest.py: _map_members`
- Modify: `autodrive_console/task_compiler.py: preview input fingerprint facts if required`
- Modify: `tests/test_deployment.py`
- Modify: `tests/test_location_manifest.py`

**Interfaces:**
- Consumes Task 1 parse/render/validate functions.
- Produces `DeploymentStore.add_virtual_wall(project_id, {map_id, start, end})`.
- Produces `DeploymentStore.update_virtual_wall(project_id, wall_id, {start, end})`.
- Produces `DeploymentStore.delete_virtual_wall(project_id, wall_id)`.
- Produces generated project snapshot `<project>/maps/<map-id>/map_walls.yaml` and localization artifact `<runtime-map-dir>/map_walls.yaml`.

- [ ] **Step 1: 写出项目 CRUD 后同目录生成文件的失败测试**

```python
def test_virtual_wall_crud_regenerates_map_relative_wall_file(tmp_path, monkeypatch) -> None:
    store, project, asset = imported_store_with_map(tmp_path, monkeypatch)
    wall = store.add_virtual_wall(project["id"], {
        "map_id": asset["id"],
        "start": {"x": -0.95, "y": -1.95},
        "end": {"x": -0.85, "y": -1.95},
    })
    wall_file = Path(asset["source_yaml"]).with_name("map_walls.yaml")
    assert parse_virtual_wall_segments(wall_file.read_bytes(), asset["origin"])[0]["start"] == wall["start"]

    store.delete_virtual_wall(project["id"], wall["id"])
    assert parse_virtual_wall_segments(wall_file.read_bytes(), asset["origin"]) == []
```

- [ ] **Step 2: 运行测试，确认当前多点 API 与无导出文件不满足新语义**

Run: `env -u PYTHONPATH pixi run python -m pytest tests/test_deployment.py::test_virtual_wall_crud_regenerates_map_relative_wall_file -q`

Expected: FAIL because the store only accepts `points` and does not generate the companion YAML.

- [ ] **Step 3: 实现项目拥有的单段 CRUD 和可回滚文件更新**

```python
def _replace_map_virtual_walls(self, document, asset, replacements):
    previous_json = list(document["virtual_walls"])
    previous_file = wall_path.read_bytes() if wall_path.exists() else None
    document["virtual_walls"] = replacements
    try:
        self._write_bytes(wall_path, render_virtual_wall_file(asset["origin"], walls_for_map))
        self._write_json(self._document_path(document["id"]), document)
    except OSError:
        document["virtual_walls"] = previous_json
        self._restore_wall_file(wall_path, previous_file)
        raise DeploymentError("虚拟墙保存失败，已保留原地图标记")
```

Keep all storage operations inside the project root. On map import, parse a valid existing companion file into project segment records. Convert legacy `kind: forbidden_zone` point arrays into adjacent plus closing segments. Store new records with `id`, `map_asset_id`, `start` and `end`, then update `asset.files.walls` and its SHA-256. Mark the compiler preview invalid after each successful change.

- [ ] **Step 4: 运行 CRUD 与导入迁移测试，确认通过**

Run: `env -u PYTHONPATH pixi run python -m pytest tests/test_virtual_walls.py tests/test_deployment.py -q`

Expected: PASS.

- [ ] **Step 5: 写出定位导出必须携带同目录墙文件的失败测试**

```python
def test_location_manifest_exports_generated_virtual_wall_next_to_map_yaml() -> None:
    manifest = compile_location_manifest(project_with_generated_wall, map_root=maps_root)
    names = {artifact.relative_path for artifact in manifest.artifacts}
    assert "runtime/maps/1_1/indoor/map_walls.yaml" in names
```

- [ ] **Step 6: 扩展 `_map_members` 并验证导出**

Read the generated companion from the same validated source-map directory; add it only as `(target / "map_walls.yaml")` and reject a symlink/out-of-root file. Include its bytes in the compiler input facts/fingerprint so changing a wall invalidates preview cache and ZIP artifacts deterministically.

Run: `env -u PYTHONPATH pixi run python -m pytest tests/test_deployment.py tests/test_location_manifest.py tests/test_task_compiler.py -q`

Expected: PASS.

### Task 3: 提供受控 HTTP 更新与删除接口

**Files:**
- Modify: `web_console.py: deployment POST/DELETE routing`
- Modify: `tests/test_deployment.py`
- Modify: `shared/contracts/deployment.md`

**Interfaces:**
- Consumes Task 2 store methods.
- Produces `POST /api/deployments/{project_id}/virtual-walls/{wall_id}`.
- Produces `DELETE /api/deployments/{project_id}/virtual-walls/{wall_id}`.

- [ ] **Step 1: 写出 HTTP 更新和删除的失败测试**

```python
def test_virtual_wall_update_and_delete_routes_return_authoritative_project() -> None:
    response = post_json(f"/api/deployments/{project_id}/virtual-walls/{wall_id}", {
        "start": {"x": 0.1, "y": 0.2}, "end": {"x": 0.4, "y": 0.2},
    })
    assert response.status == HTTPStatus.OK
    assert response.body["virtual_wall"]["end"]["x"] == 0.4
    assert delete(f"/api/deployments/{project_id}/virtual-walls/{wall_id}").body == {"deleted": True}
```

- [ ] **Step 2: 运行测试，确认路由尚不存在而失败**

Run: `env -u PYTHONPATH pixi run python -m pytest tests/test_deployment.py::test_virtual_wall_update_and_delete_routes_return_authoritative_project -q`

Expected: FAIL with unhandled/missing virtual-wall item route.

- [ ] **Step 3: 添加精确路径解析与统一错误响应**

Accept only six slash-separated components for the item route; decode project and wall IDs once; reuse the existing JSON decoder/error boundary. Return `{"virtual_wall": wall, "project": ...}` for update and `{"deleted": true, "project": ...}` for delete. Do not add an arbitrary file-writing route.

- [ ] **Step 4: 更新部署共享契约并运行路由测试**

Document endpoint ownership, two-point schema, snapshot-only write boundary, generated YAML format, PC Web as consumer and Mobile as non-consumer of deployment CRUD.

Run: `env -u PYTHONPATH pixi run python -m pytest tests/test_deployment.py -q`

Expected: PASS.

### Task 4: 在保留现有 UI 的前提下增加红色两点墙画布交互

**Files:**
- Create: `autodrive_console/web/deployment/virtual-walls.js`
- Create: `frontend/test/deployment/virtual-walls.test.mjs`
- Modify: `autodrive_console/web/deployment/canvas-renderer.js`
- Modify: `autodrive_console/web/deployment.js: toolbar state, pointer handlers, redraw and API calls`
- Modify: `autodrive_console/web/deployment.html: existing toolbar only`
- Modify: `autodrive_console/web/deployment.css: scoped virtual-wall affordances only`
- Modify: `frontend/test/deployment-workflow.test.mjs`

**Interfaces:**
- Produces pure `wallHitTest(wall, map, view, canvasPoint, tolerancePx)` returning `"start" | "end" | "segment" | null`.
- Produces pure `moveWallEndpoint(wall, endpoint, worldPoint)` and `translateWall(wall, delta)`.
- `drawDeploymentCanvas` consumes optional `drawVirtualWalls` after map edits and before components.

- [ ] **Step 1: 写出纯几何失败测试**

```javascript
test("wall hit testing distinguishes endpoints from a red wall segment", () => {
  const wall = { start: { x: 0, y: 0 }, end: { x: 2, y: 0 } };
  assert.equal(wallHitTest(wall, map, view, { x: 100, y: 100 }, 10), "start");
  assert.equal(wallHitTest(wall, map, view, { x: 140, y: 100 }, 10), "segment");
});
```

- [ ] **Step 2: 运行测试，确认辅助模块不存在而失败**

Run: `pixi run frontend-check -- --test frontend/test/deployment/virtual-walls.test.mjs`

Expected: module-resolution failure for `deployment/virtual-walls.js`.

- [ ] **Step 3: 实现纯几何与无箭头红线渲染**

```javascript
export function wallHitTest(wall, map, view, point, tolerancePx) {
  const start = mapPointToCanvas(wall.start, map, view);
  const end = mapPointToCanvas(wall.end, map, view);
  if (Math.hypot(point.x - start.x, point.y - start.y) <= tolerancePx) return "start";
  if (Math.hypot(point.x - end.x, point.y - end.y) <= tolerancePx) return "end";
  return pointToSegmentDistance(point, start, end) <= tolerancePx ? "segment" : null;
}
```

Render each saved segment as `#dc2626` solid round-capped line. Only the selected segment gets two small red circular endpoint handles; do not draw a directional arrow.

- [ ] **Step 4: 运行几何与现有前端测试，确认通过**

Run: `pixi run frontend-check -- --test frontend/test/deployment/virtual-walls.test.mjs frontend/test/deployment-workflow.test.mjs`

Expected: PASS.

- [ ] **Step 5: 接入现有工具栏和 pointer lifecycle**

Add one scoped `data-waypoint-kind="virtual_wall"` toolbar button. In this mode, first primary click stores `virtualWallDraft.start`; pointer movement redraws a temporary red segment; second click creates a segment and leaves the tool active. Existing component/waypoint hit-testing remains first, then selected-wall handles/line, then placement.

On pointer-up, submit exactly one update for an endpoint or translated line. `Escape` clears only the unsaved draft. Right-click a wall selects it and offers the existing-style compact delete action; Delete/Backspace acts only when focus is not an editable field. On API error, reload the project snapshot before redrawing and show the existing map hint error style.

- [ ] **Step 6: 写出交互回归测试并验证**

Assert source behavior for: two clicks POST `{start,end}`; movement preview does not call POST; endpoint and line drags use the update endpoint; deletion uses DELETE; no arrow drawing token appears in the virtual-wall renderer; Escape preserves saved walls; existing component placement code remains reachable.

Run: `pixi run frontend-check`

Expected: PASS with the complete Web test suite and Vite build.

### Task 5: 端到端核验与人工交付检查

**Files:**
- Modify only files identified by failures in Tasks 1–4.
- Verify: `docs/superpowers/specs/2026-09-27-map-virtual-wall-design.md`
- Verify: `docs/superpowers/plans/2026-09-27-map-virtual-wall.md`

**Interfaces:**
- Consumes all prior task behavior.
- Produces reproducible test evidence and a diff limited to the planned deployment/backend/web/contract files.

- [ ] **Step 1: 运行受影响 Backend 完整检查**

Run: `./scripts/test-backend.sh`

Expected: exit code 0; record any pre-existing warnings separately from failures.

- [ ] **Step 2: 运行受影响 Web 完整检查**

Run: `./scripts/test-web.sh`

Expected: exit code 0.

- [ ] **Step 3: 检查导出内容与工作区卫生**

Run: `git diff --check && git status --short`

Expected: no whitespace errors; no generated ZIP, map snapshots, logs, caches, runtime files, staged changes or commits introduced by this work.

- [ ] **Step 4: 按规范逐项复核**

Verify: file name and YAML fields are exact; generated map file is next to exported `map.yaml`; walls are red and arrow-free; first/second left click semantics work; both endpoint and line dragging work; deleting a segment regenerates the companion file; source `/opt/ry/data/maps` stays unchanged; existing deployment navigation/layout remains untouched.
