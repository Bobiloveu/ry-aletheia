# 部署建图定位链路 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从部署项目快照生成经路线校验的多地图定位清单、`lift_id_list.json` 和受控地图资产，并让 PC 地图编辑器可清晰配置该路线。

**Architecture:** 保留旧 `map_transitions` 的三阶段任务编译语义，新增独立的项目级 `localization_routes`。每条路线按绑定 ID 定义无分支地图链、人工首图起点、人工末图终点与前图切图锚点；`location_manifest.py` 是唯一的位姿和电梯清单派生器，浏览器不再提交初始化坐标或运行时路径。

**Tech Stack:** Python 3.10、pytest、`DeploymentStore`、标准库 JSON/ZIP、静态 ES modules、Canvas 2D、Node test runner。

**Spec:** `docs/superpowers/specs/2026-09-16-deployment-map-location-chain-design.md`

## Global Constraints

- 不修改既有 `map_transitions`、`map_instances`、实验室内两图任务编译语义、ROS、Supervisor、任务下发或机器人运行时。
- `ferry` 可处于路线任意位置；路线末项必须是 `floor`，不能从地图类型或名称推断顺序。
- 除首图外，`init_go` 必须取该地图 YAML `origin: [x, y, yaw]`；首图 `init_go` 是人工任务起点；末图 `init_return` 是人工任务终点。
- 中间图的 `init_return` 只能由该图的出向切图锚点派生；电梯锚点必须取已关联电梯组件中心与朝向，不能手填覆盖。
- 所有路径继续由 `RuntimeLayout` 生成；浏览器不得传 YAML、PGM、输出目录、机器人绝对路径或初始化坐标。
- `lift_id_list.json` 只收录路线实际引用的电梯锚点，按楼栋、单元、ID 稳定排序；相同 ID 推导到不同楼栋/单元必须阻断导出。
- 旧项目的手填定位位不丢失，但未迁移为定位路线时必须阻断新清单导出。
- UI 使用既有部署编辑器的 Operate 风格；导入文案统一为“导入地图”，绑定表单不再出现初始化位输入。
- 跨 Backend/Web 数据模型变更同步更新 `shared/contracts/deployment.md`；最终运行 `./scripts/test-backend.sh`、`./scripts/test-web.sh`、`git diff --check`。

---

## File Structure

- `autodrive_console/deployment.py`：持久化并校验绑定和新定位路线；不负责生成运行时位姿。
- `web_console.py`：将受控定位路线 HTTP 意图转发给 `DeploymentStore`。
- `autodrive_console/location_manifest.py`：解析项目快照、路线、地图原点、航点和组件，生成两个 JSON 文件及受控资产。
- `autodrive_console/task_compiler.py`：把新增的受控工件带入既有实验包与预览摘要，不扩大室内两图任务范围。
- `autodrive_console/web/deployment.{html,js,css}`：配置身份绑定、定位路线和派生只读摘要。
- `autodrive_console/web/deployment/canvas-renderer.js`：绘制 YAML 地图原点十字坐标系。
- `tests/test_deployment.py`：Store、HTTP、页面结构和项目生命周期测试。
- `tests/test_location_manifest.py`：路线位姿、电梯清单、导出工件与失败边界的纯函数测试。
- `frontend/test/legacy-app-module.test.mjs`：PC 静态模块/文案与受控路线端点测试。
- `shared/contracts/deployment.md`：Backend/Web/Mobile 消费边界、路线结构和导出格式。

---

### Task 1: 持久化并校验独立定位路线

**Files:**
- Modify: `autodrive_console/deployment.py`
- Modify: `web_console.py`
- Test: `tests/test_deployment.py`

**Interfaces:**
- Produces `DeploymentStore.create_localization_route(project_id, data) -> dict[str, Any]`、`update_localization_route(project_id, route_id, data)` 和 `delete_localization_route(project_id, route_id) -> None`。
- Produces `POST /api/deployments/{project_id}/localization-routes`、`POST /api/deployments/{project_id}/localization-routes/{route_id}`、`DELETE` 对应项。
- Changes binding input to exactly `map_asset_id`、`building`、`unit`、`type` 和仅 `floor` 可用的 `floor_template`。

- [ ] **Step 1: 为新路线与旧绑定写失败测试**

```python
def test_localization_route_allows_ferry_anywhere_and_derives_references(tmp_path):
    store, project, assets = _project_with_four_maps(tmp_path)
    ferry, outdoor, lobby, floor = [_binding(store, project, asset, kind) for asset, kind in zip(assets, ("ferry", "outdoor", "indoor", "floor"))]
    route = store.create_localization_route(project["id"], {
        "building": "1", "unit": "1",
        "binding_ids": [ferry["id"], outdoor["id"], lobby["id"], floor["id"]],
        "task_start_waypoint_id": _waypoint(store, project, ferry["map_asset_id"], "start")["id"],
        "task_target_waypoint_id": _waypoint(store, project, floor["map_asset_id"], "target")["id"],
        "links": [
            _waypoint_link(ferry["id"], outdoor["id"], ferry["map_asset_id"]),
            _waypoint_link(outdoor["id"], lobby["id"], outdoor["map_asset_id"]),
            _elevator_link(lobby["id"], floor["id"], lobby["map_asset_id"]),
        ],
    })
    assert route["binding_ids"] == [ferry["id"], outdoor["id"], lobby["id"], floor["id"]]

def test_localization_route_rejects_non_floor_tail_and_mismatched_anchor(tmp_path):
    store, project, assets = _project_with_four_maps(tmp_path)
    with pytest.raises(DeploymentError, match="最后"):
        store.create_localization_route(project["id"], _route_payload_with_tail(assets[2]))
    with pytest.raises(DeploymentError, match="切图锚点"):
        store.create_localization_route(project["id"], _route_payload_with_foreign_anchor(assets))

def test_legacy_manual_localization_binding_remains_readable_but_is_marked_for_migration(tmp_path):
    store, project, assets = _project_with_four_maps(tmp_path)
    legacy = _legacy_binding_payload(assets[0]["id"])
    store._write_json(store._document_path(project["id"]), {**project, "localization_bindings": [legacy]})
    saved = store.get(project["id"])
    assert saved["localization_bindings"][0]["init_go"] == legacy["init_go"]
    assert saved["localization_routes"] == []
```

- [ ] **Step 2: 运行定向测试确认 RED**

Run: `pixi run bash -c 'unset PYTHONPATH; python -m pytest -q tests/test_deployment.py -k "localization_route or legacy_manual_localization"'`

Expected: FAIL，因为 `DeploymentStore` 尚无 `create_localization_route`，项目文档也无 `localization_routes`。

- [ ] **Step 3: 以最小边界实现项目模型和 Store 校验**

在 `create()` 与 `get()` 的列表归一化中加入 `localization_routes`。新增如下严格结构，且不修改 `map_transitions`：

```python
{
    "id": "localization-route-<12 hex>",
    "building": "1", "unit": "1",
    "binding_ids": ["localization-…", "localization-…"],
    "task_start_waypoint_id": "waypoint-…",
    "task_target_waypoint_id": "waypoint-…",
    "links": [
        {"from_binding_id": "localization-…", "to_binding_id": "localization-…",
         "anchor": {"kind": "waypoint", "waypoint_id": "waypoint-…"}}
    ],
}
```

实现 `_normalise_localization_route(document, data, identifier=None)`，只接受上面字段。验证所有绑定属于同一 `{building, unit}`、无重复、至少一项、末项为 `floor`、首/末航点分别属于首/末地图、每对相邻绑定恰一条链接。锚点 `waypoint` 必须位于 `from_binding_id` 的地图；锚点 `component_center` 必须引用该图的组件，且电梯组件类型是 `elevator`。检测环、分支、跳链、未知 ID 或重复路线身份时抛出有动作指引的 `DeploymentError`。

将 `_normalise_localization_binding` 的允许字段收窄为：

```python
{"map_asset_id", "building", "unit", "type", "floor_template"}
```

既有含 `init_go` 或 `init_return` 的磁盘绑定不经重新归一化，因此仍可读取；新建/更新不得接受它们。删除绑定、航点或组件前，若任一路线引用它，拒绝删除；保存绑定或路线后调用 `_invalidate_task_compiler_preview()`。

- [ ] **Step 4: 再运行 Store 测试确认 GREEN**

Run: `pixi run bash -c 'unset PYTHONPATH; python -m pytest -q tests/test_deployment.py -k "localization_route or legacy_manual_localization"'`

Expected: PASS。

- [ ] **Step 5: 为 HTTP 路由写 RED 测试**

```python
def test_localization_route_http_forwards_only_project_owned_payload():
    payload = {"building": "1", "unit": "1", "binding_ids": ["a"], "task_start_waypoint_id": "s", "task_target_waypoint_id": "t", "links": []}
    handler = _deployment_handler("/api/deployments/site/localization-routes", payload)
    with patch.object(web_console.DEPLOYMENTS, "create_localization_route", return_value={"id": "route-a"}) as create:
        handler.do_POST()
    create.assert_called_once_with("site", payload)
    assert handler._json.call_args.args[0]["localization_route"] == {"id": "route-a"}
```

- [ ] **Step 6: 添加 HTTP 路由并确认 GREEN**

在 `web_console.py` 的绑定路由旁添加 collection/item 的 POST 和 DELETE 分支，并维持 400 的 JSON/路径错误边界。成功创建返回 `201` 与 `{ "localization_route": route, "project": DEPLOYMENTS.get(project_id) }`；更新返回 `200`；删除返回 `{ "deleted": true }`。所有路由都必须在通用部署路径前解析完整 segment 数。

Run: `pixi run bash -c 'unset PYTHONPATH; python -m pytest -q tests/test_deployment.py -k "localization_route"'`

Expected: PASS。

- [ ] **Step 7: 提交 Task 1**

```bash
git add autodrive_console/deployment.py web_console.py tests/test_deployment.py
git commit -m "feat: add validated deployment localization routes"
```

### Task 2: 从路线派生定位清单和电梯 ID 清单

**Files:**
- Modify: `autodrive_console/location_manifest.py`
- Modify: `autodrive_console/task_compiler.py`
- Test: `tests/test_location_manifest.py`
- Test: `tests/test_deployment.py`

**Interfaces:**
- `compile_location_manifest(project, *, map_root) -> RenderedLocationManifest` 继续返回 `json_bytes`、`artifacts`、`summary`，但 `artifacts` 必含 `runtime/loc_yaml_path.json` 与 `runtime/lift_id_list.json`。
- Produces pure internal helpers `_origin_pose(asset)`、`_resolve_route(project, route, assets)` 与 `_lift_id_document(project, resolved_routes)`。

- [ ] **Step 1: 写清单位姿与电梯清单的失败测试**

```python
def test_manifest_uses_manual_start_then_yaml_origins_and_route_return_anchors(tmp_path):
    project, map_root = _route_project(tmp_path, kinds=("outdoor", "indoor", "floor"))
    rendered = compile_location_manifest(project, map_root=map_root)
    entries = json.loads(rendered.json_bytes)["loc_yaml"][0]["yaml_index"]
    assert entries[0]["init_go"] == {"x": 1.0, "y": 2.0, "z": 0.0, "yaw": 0.1}
    assert entries[1]["init_go"] == {"x": -5.0, "y": -30.0, "z": 0.0, "yaw": 0.3}
    assert entries[1]["init_return"] == {"x": 8.0, "y": 9.0, "z": 0.0, "yaw": 1.57}
    assert entries[2]["init_return"] == {"x": 20.0, "y": 21.0, "z": 0.0, "yaw": 0.0}

def test_manifest_emits_deduplicated_route_elevator_id_list(tmp_path):
    project, map_root = _route_project(tmp_path, with_elevator_anchor=True)
    rendered = compile_location_manifest(project, map_root=map_root)
    lifts = next(item for item in rendered.artifacts if item.relative_path == "runtime/lift_id_list.json")
    assert json.loads(lifts.content) == {"community": "高科一号", "lifts": [{"lift_id": "10044", "building": "1", "unit": "1"}]}

def test_manifest_rejects_legacy_binding_missing_route_and_conflicting_lift_identity(tmp_path):
    project, map_root = _legacy_project(tmp_path)
    with pytest.raises(LocationManifestError, match="迁移"):
        compile_location_manifest(project, map_root=map_root)
    project, map_root = _two_route_same_lift_different_unit_project(tmp_path)
    with pytest.raises(LocationManifestError, match="楼栋"):
        compile_location_manifest(project, map_root=map_root)
```

- [ ] **Step 2: 运行清单测试确认 RED**

Run: `pixi run bash -c 'unset PYTHONPATH; python -m pytest -q tests/test_location_manifest.py -k "route or lift"'`

Expected: FAIL，因为现有渲染器仍读取人工 `init_go`/`init_return`，且没有 `lift_id_list.json`。

- [ ] **Step 3: 实现纯派生器，不信任浏览器位姿**

令 `_assets()` 保留每个项目资产的 `origin`、尺寸和分辨率，并实现：

```python
def _origin_pose(asset: dict[str, Any]) -> dict[str, float]:
    origin = asset.get("origin")
    if not isinstance(origin, list) or len(origin) != 3:
        raise LocationManifestError("地图 YAML origin 无效")
    x, y, yaw = (float(value) for value in origin)
    if not all(isfinite(value) for value in (x, y, yaw)):
        raise LocationManifestError("地图 YAML origin 无效")
    return {"x": x, "y": y, "z": 0.0, "yaw": yaw}
```

`_resolve_route()` 必须按路线顺序生成条目：首项 `init_go=task_start`，后项 `init_go=_origin_pose(asset)`；非末项 `init_return=link.anchor`，末项 `init_return=task_target`。`waypoint` 锚点直接复制受控航点 `{x,y,0,yaw}`；`component_center` 从组件 `{x,y,yaw}` 生成同一结构。对每个结果运行地图边界与有限数校验。

从被解析的 `component_center/elevator` 锚点获得物理电梯 ID，生成 UTF-8、两空格缩进且末尾换行的 `runtime/lift_id_list.json`。同一元组去重；相同 ID 对应多个 `{building, unit}` 抛出 `LocationManifestError`。不引用电梯时输出 `{ "community": ..., "lifts": [] }`。

删除 `_binding()` 对人工初始位的要求；它只验证绑定身份。`compile_location_manifest()` 在路线为空且发现旧人工初始化位时报告“定位绑定需要迁移为定位路线”；路线为空但无绑定仍报告“缺少定位绑定”。

- [ ] **Step 4: 运行纯函数测试确认 GREEN**

Run: `pixi run bash -c 'unset PYTHONPATH; python -m pytest -q tests/test_location_manifest.py'`

Expected: PASS。

- [ ] **Step 5: 让既有实验包带入新工件并写回归测试**

在 `task_compiler.py` 保持 `compile_indoor_elevator()` 的任务限制不变，只使用 `location_manifest.artifacts` 作为 ZIP 允许成员。将预览摘要补充 `location_manifest.lift_count` 和两个相对文件名；不得暴露项目/上传绝对路径。

```python
def test_task_compiler_bundle_contains_both_controlled_location_json_files(tmp_path):
    store, project = _compiler_ready_store_with_route(tmp_path)
    _, body = store.task_compiler_bundle(project["id"])
    with ZipFile(io.BytesIO(body)) as archive:
        assert "runtime/loc_yaml_path.json" in archive.namelist()
        assert "runtime/lift_id_list.json" in archive.namelist()
```

Run: `pixi run bash -c 'unset PYTHONPATH; python -m pytest -q tests/test_deployment.py tests/test_location_manifest.py -k "location_manifest or task_compiler_bundle"'`

Expected: PASS。

- [ ] **Step 6: 提交 Task 2**

```bash
git add autodrive_console/location_manifest.py autodrive_console/task_compiler.py tests/test_location_manifest.py tests/test_deployment.py
git commit -m "feat: derive deployment localization manifests from routes"
```

### Task 3: 在部署画布上显示 YAML 原点并收敛绑定表单

**Files:**
- Modify: `autodrive_console/web/deployment.html`
- Modify: `autodrive_console/web/deployment.js`
- Modify: `autodrive_console/web/deployment.css`
- Modify: `autodrive_console/web/deployment/canvas-renderer.js`
- Test: `tests/test_deployment.py`
- Test: `frontend/test/legacy-app-module.test.mjs`

**Interfaces:**
- `drawDeploymentCanvas()` receives `drawMapOrigin` and calls it after the map image but before waypoints/components.
- `saveLocalizationBinding()` sends only binding identity fields.
- `originPose(activeMap)` returns `{x, y, z: 0, yaw}` from the saved asset origin for read-only UI display.

- [ ] **Step 1: 用页面结构和模块测试固定目标 UI（RED）**

```python
def test_deployment_page_uses_generic_map_import_and_has_no_manual_localization_pose_inputs():
    html = (ROOT / "autodrive_console/web/deployment.html").read_text(encoding="utf-8")
    assert "导入地图" in html
    assert "Lightning 地图" not in html
    assert 'id="localizationGoX"' not in html
    assert 'id="localizationReturnX"' not in html
    assert 'id="localizationRouteDialog"' in html
```

```javascript
test("deployment renderer draws a map-origin callback before localization markers", () => {
  const source = readFileSync(deploymentRendererPath, "utf8");
  assert.match(source, /drawMapOrigin\?\.\(\)/);
  assert.match(source, /drawMapOrigin\?\.\(\)[\s\S]*drawLocalizationMarkers\?\.\(\)/);
});
```

- [ ] **Step 2: 运行网页结构测试确认 RED**

Run: `pixi run node --test frontend/test/legacy-app-module.test.mjs && pixi run bash -c 'unset PYTHONPATH; python -m pytest -q tests/test_deployment.py -k deployment_page'`

Expected: FAIL，因为旧页面仍显示 Lightning 文案、手填去返位和无路线编辑器。

- [ ] **Step 3: 依照 Impeccable Operate 约束实现绑定与原点 UI**

在编辑 UI 前读取 `/home/bob/.codex/skills/impeccable/reference/craft-floor.md`，沿用既有深色部署工作台、紧凑卡片和语义色，不新增第二个页面或大尺寸表单。

将“导入现有 Lightning 地图”及空状态替换为“导入地图”。从 `localizationBindingDialog` 删除“在地图标记去程/返程位”、八个坐标输入及相关 JS 事件；对话框只保存地图角色、楼栋、单元和可选用户楼层模板。

实现：

```javascript
function originPose(map) {
  const [x, y, yaw] = Array.isArray(map?.origin) ? map.origin : [];
  return { x: Number(x), y: Number(y), z: 0, yaw: Number(yaw) };
}

function saveLocalizationBinding() {
  const payload = {
    map_asset_id: activeMap.id,
    building: $("localizationBuilding").value,
    unit: $("localizationUnit").value,
    type: $("localizationBindingType").value,
  };
  if (payload.type === "floor") payload.floor_template = $("localizationFloorTemplate").value;
  // existing controlled POST remains unchanged apart from this body
}
```

在 `drawMap()` 中传入 `drawMapOrigin`。该回调通过 `mapPointToCanvas(originPose(activeMap), activeMap, mapView)` 绘制低干扰十字、带正向箭头的 X/Y 轴和“YAML 原点”短标签；它使用地图坐标，不随鼠标或屏幕坐标旋转。`canvas-renderer.js` 在裁剪到地图边界后、航点与组件之前调用它，避免盖住组件或被画布外绘制。

- [ ] **Step 4: 运行 RED 测试并做最小修正至 GREEN**

Run: `pixi run node --test frontend/test/legacy-app-module.test.mjs && pixi run bash -c 'unset PYTHONPATH; python -m pytest -q tests/test_deployment.py -k deployment_page'`

Expected: PASS。

- [ ] **Step 5: 对本任务文件运行前端质量检测**

Run: `node /home/bob/.codex/skills/impeccable/scripts/detect.mjs --json autodrive_console/web/deployment.html autodrive_console/web/deployment.js autodrive_console/web/deployment.css autodrive_console/web/deployment/canvas-renderer.js`

Expected: 不报告可修复的布局、语义或可访问性问题；若环境缺少解析依赖，记录 `DEGRADED` 而不将其误报为通过。

- [ ] **Step 6: 提交 Task 3**

```bash
git add autodrive_console/web/deployment.html autodrive_console/web/deployment.js autodrive_console/web/deployment.css autodrive_console/web/deployment/canvas-renderer.js tests/test_deployment.py frontend/test/legacy-app-module.test.mjs
git commit -m "feat: show deployment map origins"
```

### Task 4: 构建紧凑定位路线编辑器与派生状态展示

**Files:**
- Modify: `autodrive_console/web/deployment.html`
- Modify: `autodrive_console/web/deployment.js`
- Modify: `autodrive_console/web/deployment.css`
- Test: `frontend/test/legacy-app-module.test.mjs`
- Test: `tests/test_deployment.py`

**Interfaces:**
- Consumes `project.localization_routes` and Task 1 routes API.
- Produces `localizationRoutePayload()` with `building`、`unit`、`binding_ids`、`task_start_waypoint_id`、`task_target_waypoint_id` and `links` only.
- `renderLocalizationRoutes()` renders read-only derived `init_go` / `init_return` source labels; actual coordinates remain backend derived.

- [ ] **Step 1: 为单电梯自动选择和多电梯显式选择写失败测试**

```javascript
test("deployment route editor uses controlled route endpoints and no raw pose fields", () => {
  const source = readFileSync(deploymentPath, "utf8");
  assert.match(source, /\/localization-routes/);
  assert.match(source, /component_center/);
  assert.match(source, /task_start_waypoint_id/);
  assert.doesNotMatch(source, /localizationGoX|localizationReturnX/);
});
```

```python
def test_route_editor_markup_exposes_derived_sources_and_not_raw_runtime_paths():
    html = (ROOT / "autodrive_console/web/deployment.html").read_text(encoding="utf-8")
    assert 'id="localizationRouteDialog"' in html
    assert 'id="localizationRouteLinks"' in html
    assert "YAML 原点" in html
    assert "定位 YAML 路径" not in html
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `pixi run node --test frontend/test/legacy-app-module.test.mjs && pixi run bash -c 'unset PYTHONPATH; python -m pytest -q tests/test_deployment.py -k route_editor'`

Expected: FAIL，因为页面尚没有定位路线对话框与路线端点调用。

- [ ] **Step 3: 实现路线交互，不创建重复地图工作台**

在定位绑定卡片旁加入“编辑定位路线”入口和 `localizationRouteDialog`。实现以下小函数，均只读 `selectedProject` 或调用 Task 1 受控 API：

```javascript
function localizationRoutes() { return Array.isArray(selectedProject?.localization_routes) ? selectedProject.localization_routes : []; }
function bindingsForIdentity(building, unit) { return localizationBindings().filter((item) => item.building === building && item.unit === unit); }
function routeAnchorOptions(mapAssetId) { /* manual waypoints and map-owned component centers */ }
function localizationRoutePayload() { /* no x/y/z/yaw fields */ }
async function saveLocalizationRoute() { /* POST collection/item then renderProject */ }
function renderLocalizationRoutes() { /* show map order and derived-source labels */ }
```

路线对话框必须：

1. 仅列出同一楼栋/单元的绑定；允许通过上移/下移确定顺序，且明确显示末项必须为“用户楼层”。
2. 让部署人员从首图已有 `start` 航点和末图已有 `target` 航点中选择人工任务点。
3. 为每对相邻地图选择一个前图锚点：普通航点、组件中心或电梯组件中心。只有该图恰有一个合格电梯组件时，预选该组件；多个时显示必选下拉与阻断文案。
4. 在每张卡片中显示只读来源：首图“人工任务起点”，中间/末图“YAML 原点”，有后继图“组件中心自动派生”或“人工切图点”，末图“人工任务终点”。不展示可编辑坐标。
5. 在窄屏下按地图顺序竖排，按钮与选择器不覆盖现有地图画布、拓扑或任务编译预览。

在预览摘要中显示路线完整性和即将生成的 `loc_yaml_path.json`、`lift_id_list.json`，但只显示相对文件名与派生状态。

- [ ] **Step 4: 运行 UI 单元/结构测试确认 GREEN**

Run: `pixi run node --test frontend/test/legacy-app-module.test.mjs && pixi run bash -c 'unset PYTHONPATH; python -m pytest -q tests/test_deployment.py -k "route_editor or deployment_page"'`

Expected: PASS。

- [ ] **Step 5: 执行一次受限视觉检查**

启动本地 Web 开发服务并在桌面与窄宽度各检查一次：绑定表单无坐标字段、路线卡片能顺序阅读、原点十字不遮挡电梯组件、多电梯提示清晰。一次集中修复发现的问题后复查一次；不做开放式视觉迭代。

- [ ] **Step 6: 提交 Task 4**

```bash
git add autodrive_console/web/deployment.html autodrive_console/web/deployment.js autodrive_console/web/deployment.css frontend/test/legacy-app-module.test.mjs tests/test_deployment.py
git commit -m "feat: configure deployment localization routes"
```

### Task 5: 更新契约并执行跨模块回归

**Files:**
- Modify: `shared/contracts/deployment.md`
- Modify: `tests/test_deployment.py`
- Modify: `tests/test_location_manifest.py`

**Interfaces:**
- Documents Backend as authoritative route/manifest producer, PC Web as route editor, Mobile as non-consumer.
- Documents the exact two generated JSON payloads and the migration block boundary.

- [ ] **Step 1: 写契约/产物完整性失败测试**

```python
def test_deployment_contract_documents_route_derived_init_poses_and_lift_list():
    contract = (ROOT / "shared/contracts/deployment.md").read_text(encoding="utf-8")
    assert "localization_routes" in contract
    assert "lift_id_list.json" in contract
    assert "YAML `origin`" in contract
    assert "Mobile" in contract
```

- [ ] **Step 2: 运行测试确认 RED**

Run: `pixi run bash -c 'unset PYTHONPATH; python -m pytest -q tests/test_deployment.py -k deployment_contract'`

Expected: FAIL，因为 Existing 契约仍描述手填 `init_go` / `init_return`。

- [ ] **Step 3: 更新 Existing 契约**

在 `shared/contracts/deployment.md`：

- 将 `localization_bindings` 的 API 负载改为身份字段；明确旧手填初始化位项目可读但不能生成新定位包。
- 增加 `localization_routes` 的集合/项路由、严格请求结构、路线末项、锚点和删除引用保护。
- 记录 `loc_yaml_path.json` 的首/中/末图派生表与 `runtime/lift_id_list.json` 的精确 JSON 结构、去重/冲突规则。
- 明确 Backend/Web 消费该模型，Mobile 不调用这些路由；实验导出不写机器人运行时、不调用 ROS/Supervisor。

- [ ] **Step 4: 运行所有受影响检查**

Run: `./scripts/test-backend.sh`

Expected: PASS。

Run: `./scripts/test-web.sh`

Expected: PASS。

Run: `git diff --check`

Expected: 无输出，退出码 0。

- [ ] **Step 5: 提交 Task 5**

```bash
git add shared/contracts/deployment.md tests/test_deployment.py tests/test_location_manifest.py
git commit -m "docs: define deployment localization route contract"
```
