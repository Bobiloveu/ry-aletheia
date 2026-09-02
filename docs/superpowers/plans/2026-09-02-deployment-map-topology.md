# 部署地图拓扑实施计划

> **供智能执行器使用：** 必须使用 `superpowers:executing-plans` 按任务逐项执行；每个步骤使用复选框跟踪。

**目标：** 为部署建图模块实现三地图阶段绑定、跨地图 Transition、地图内路线、拓扑校验和只读预览，且不触及车端运行时。

**架构：** `DeploymentStore` 保持为唯一 SiteProject 业务与校验层，新增阶段、Transition、路线和拓扑校验的纯数据接口。`web_console.py` 只暴露窄 HTTP API；`deployment.js` 以现有二维画布呈现地图内路线、阶段状态和跨图拓扑，不产生机器人文件或 ROS 操作。

**技术栈：** Python 标准库、现有 `DeploymentStore`、`BaseHTTPRequestHandler`、原生 JavaScript Canvas、既有 CSS 设计令牌、pytest 风格测试。

**规格：** `docs/superpowers/specs/2026-09-02-deployment-map-flow-design.md`

## 全局约束

- 不启动 SLAM、不控制车辆、不修改 `/opt/ry/data/maps`、`/opt/ry/config`、导航或定位启动文件。
- 继续使用项目快照目录 `deployments/<project-id>/` 与原子 JSON 写入。
- PGM 坐标系不跨地图转换；跨图连接只保存 Waypoint 引用和方向。
- 浏览器格栅仅为显示辅助，不能进入 PGM、地图编辑记录或机器人文件。
- 先写失败测试并观察失败，再写最小生产代码；每次实现后运行对应测试。
- 当前 worktree 存在用户未提交改动；不得用 reset、checkout 或宽泛暂存覆盖它们。提交仅限本计划新增的文档与明确修改的部署建图文件。

---

### 任务 1：阶段计划和地图阶段绑定

**文件：**
- 修改：`autodrive_console/deployment.py: DeploymentStore.create/get/set_scene_model/import_map/import_captured_map`
- 修改：`tests/test_deployment.py`

**接口：**
- 消费：`DeploymentStore.get(project_id)` 的 `scene_model`、`map_assets`。
- 产出：`stage_plan(project_id) -> dict`、`assign_map_stage(project_id, map_asset_id, stage) -> dict`。
- 数据：`map_stage_assignments: list[{stage, map_asset_id}]`，状态只在 `stage_plan` 返回值中推导。

- [ ] **步骤 1：写失败测试**

```python
def test_stage_plan_assigns_maps_in_scene_order(tmp_path: Path, monkeypatch):
    store, project, assets = _project_with_maps(tmp_path, monkeypatch, 3)
    store.set_scene_model(project["id"], "indoor_outdoor")
    assert store.stage_plan(project["id"])["current_stage"] == "outdoor"
    store.assign_map_stage(project["id"], assets[0]["id"], "outdoor")
    store.assign_map_stage(project["id"], assets[1]["id"], "lobby")
    plan = store.assign_map_stage(project["id"], assets[2]["id"], "target_floor")
    assert [item["stage"] for item in plan["stages"]] == ["outdoor", "lobby", "target_floor"]
    assert plan["current_stage"] is None
```

- [ ] **步骤 2：运行测试并确认失败**

运行：`pytest tests/test_deployment.py::test_stage_plan_assigns_maps_in_scene_order -v`
预期：因 `stage_plan` 尚不存在而失败。

- [ ] **步骤 3：最小实现**

```python
STAGE_ORDER = {
    "outdoor": ("outdoor",),
    "indoor": ("lobby", "target_floor"),
    "indoor_outdoor": ("outdoor", "lobby", "target_floor"),
}

def stage_plan(self, project_id: str) -> dict[str, Any]:
    document = self.get(project_id)
    stages = self._required_stages(document)
    assignments = self._normalise_stage_assignments(document, stages)
    return self._build_stage_plan(document, stages, assignments)
```

`assign_map_stage` 必须验证场景模型已选择、地图存在、阶段为必需阶段、同一地图不被重复绑定；成功后原子写回项目。导入或建图产物导入后调用同一私有方法，将其自动放入下一个未完成阶段；没有剩余阶段时仅保留地图资产。

- [ ] **步骤 4：运行测试并确认通过**

运行：`pytest tests/test_deployment.py::test_stage_plan_assigns_maps_in_scene_order -v`
预期：通过。

- [ ] **步骤 5：补充拒绝用例并验证**

```python
def test_stage_assignment_rejects_duplicate_map_and_invalid_stage(tmp_path, monkeypatch):
    store, project, assets = _project_with_maps(tmp_path, monkeypatch, 2)
    store.set_scene_model(project["id"], "indoor")
    store.assign_map_stage(project["id"], assets[0]["id"], "lobby")
    with pytest.raises(DeploymentError, match="已绑定"):
        store.assign_map_stage(project["id"], assets[0]["id"], "target_floor")
    with pytest.raises(DeploymentError, match="不属于当前场景模型"):
        store.assign_map_stage(project["id"], assets[1]["id"], "outdoor")
```

运行：`pytest tests/test_deployment.py -v`。预期：部署 Store 测试均通过。

### 任务 2：跨图 Transition 持久化与校验

**文件：**
- 修改：`autodrive_console/deployment.py: DeploymentStore`
- 修改：`tests/test_deployment.py`

**接口：**
- 消费：任务 1 的 `stage_plan`、已存在 `waypoints`。
- 产出：`add_map_transition(project_id, data) -> dict`、`delete_map_transition(project_id, transition_id) -> None`。
- 数据：`map_transitions` 的 `from_*`、`to_*`、`label`、`behavior_template_ref` 字段。

- [ ] **步骤 1：写失败测试**

```python
def test_transition_links_adjacent_assigned_maps(tmp_path, monkeypatch):
    store, project, maps = _three_stage_project_with_waypoints(tmp_path, monkeypatch)
    transition = store.add_map_transition(project["id"], {
        "from_map_asset_id": maps[0]["id"], "from_waypoint_id": "outdoor-exit",
        "to_map_asset_id": maps[1]["id"], "to_waypoint_id": "lobby-entry",
        "label": "室外至大厅",
    })
    assert transition["from_map_asset_id"] == maps[0]["id"]
    assert store.get(project["id"])["map_transitions"] == [transition]
```

- [ ] **步骤 2：运行测试并确认失败**

运行：`pytest tests/test_deployment.py::test_transition_links_adjacent_assigned_maps -v`
预期：因 `add_map_transition` 尚不存在而失败。

- [ ] **步骤 3：最小实现**

```python
def add_map_transition(self, project_id: str, data: dict[str, Any]) -> dict[str, Any]:
    document = self.get(project_id)
    source = self._waypoint(document, str(data.get("from_waypoint_id", "")))
    target = self._waypoint(document, str(data.get("to_waypoint_id", "")))
    self._validate_transition_direction(document, source, target, data)
    transition = {"id": f"transition-{uuid.uuid4().hex[:12]}", ...}
    document["map_transitions"].append(transition)
    self._write_project(project_id, document)
    return transition
```

校验必须拒绝：同一地图、Waypoint 不存在、Waypoint 与声明地图不符、非相邻阶段、相同阶段重复出向或重复入向连接。删除必须仅移除指定 ID 并在不存在时抛出 `DeploymentError`。

- [ ] **步骤 4：运行测试并确认通过**

运行：`pytest tests/test_deployment.py::test_transition_links_adjacent_assigned_maps -v`
预期：通过。

- [ ] **步骤 5：补充非法连接测试并验证**

```python
def test_transition_rejects_same_map_and_skipped_stage(tmp_path, monkeypatch):
    store, project, maps = _three_stage_project_with_waypoints(tmp_path, monkeypatch)
    with pytest.raises(DeploymentError, match="不同地图"):
        store.add_map_transition(project["id"], _transition(maps[0], "outdoor-exit", maps[0], "outdoor-entry"))
    with pytest.raises(DeploymentError, match="相邻阶段"):
        store.add_map_transition(project["id"], _transition(maps[0], "outdoor-exit", maps[2], "floor-entry"))
```

运行：`pytest tests/test_deployment.py -v`。预期：部署 Store 测试均通过。

### 任务 3：地图内路线与项目拓扑校验

**文件：**
- 修改：`autodrive_console/deployment.py: DeploymentStore`
- 修改：`tests/test_deployment.py`

**接口：**
- 消费：任务 1 阶段、任务 2 Transition、现有 Waypoint 与虚拟墙。
- 产出：`save_route(project_id, data) -> dict`、`delete_route(project_id, route_id) -> None`、`validate_topology(project_id) -> dict`。
- 返回：`{"valid": bool, "errors": list[str], "stages": list[dict], "transitions": list[dict], "routes": list[dict], "virtual_wall_count": int}`。

- [ ] **步骤 1：写失败测试**

```python
def test_route_is_limited_to_one_map(tmp_path, monkeypatch):
    store, project, maps = _three_stage_project_with_waypoints(tmp_path, monkeypatch)
    route = store.save_route(project["id"], {
        "map_asset_id": maps[1]["id"], "label": "大厅路线",
        "waypoint_ids": ["lobby-entry", "lobby-exit"],
    })
    assert route["waypoint_ids"] == ["lobby-entry", "lobby-exit"]
    with pytest.raises(DeploymentError, match="同一张地图"):
        store.save_route(project["id"], {
            "map_asset_id": maps[1]["id"], "label": "错误路线",
            "waypoint_ids": ["lobby-entry", "floor-entry"],
        })
```

- [ ] **步骤 2：运行测试并确认失败**

运行：`pytest tests/test_deployment.py::test_route_is_limited_to_one_map -v`
预期：因 `save_route` 尚不存在而失败。

- [ ] **步骤 3：最小实现**

```python
def save_route(self, project_id: str, data: dict[str, Any]) -> dict[str, Any]:
    document = self.get(project_id)
    map_id = str(data.get("map_asset_id", ""))
    waypoint_ids = [str(value) for value in data.get("waypoint_ids", [])]
    if len(waypoint_ids) < 2 or len(set(waypoint_ids)) != len(waypoint_ids):
        raise DeploymentError("路线至少需要两个不重复的 Waypoint")
    if any(self._waypoint(document, item)["map_asset_id"] != map_id for item in waypoint_ids):
        raise DeploymentError("路线 Waypoint 必须属于同一张地图")
```

`validate_topology` 必须聚合而非短路报告：缺地图、第一阶段缺 `start`、最终阶段缺 `target`、缺入／出 Transition、Transition 非连续、路线引用损坏、虚拟墙引用不存在。完整三阶段项目应返回 `valid: true`。

- [ ] **步骤 4：运行测试并确认通过**

运行：`pytest tests/test_deployment.py::test_route_is_limited_to_one_map -v`
预期：通过。

- [ ] **步骤 5：写完整拓扑与断链测试并验证**

```python
def test_topology_reports_broken_chain_then_accepts_complete_three_map_project(tmp_path, monkeypatch):
    store, project, maps = _three_stage_project_with_waypoints(tmp_path, monkeypatch)
    broken = store.validate_topology(project["id"])
    assert not broken["valid"]
    assert any("Transition" in error for error in broken["errors"])
    _add_complete_three_map_transitions_and_routes(store, project, maps)
    assert store.validate_topology(project["id"])["valid"]
```

运行：`pytest tests/test_deployment.py -v`。预期：部署 Store 测试均通过。

### 任务 4：HTTP API 与映射会话的阶段归属

**文件：**
- 修改：`web_console.py: do_POST/do_DELETE`
- 修改：`tests/test_deployment.py` 或新建 `tests/test_deployment_http.py`

**接口：**
- 消费：任务 1 至任务 3 的 Store 方法。
- 产出：
  - `GET /api/deployments/<id>/topology`
  - `POST /api/deployments/<id>/map-stages`
  - `POST /api/deployments/<id>/transitions`
  - `POST /api/deployments/<id>/routes`
  - `DELETE /api/deployments/<id>/transitions/<transition-id>`
  - `DELETE /api/deployments/<id>/routes/<route-id>`。

- [ ] **步骤 1：写失败测试**

```python
def test_topology_http_request_uses_store_without_ros(monkeypatch):
    monkeypatch.setattr(web_console.DEPLOYMENTS, "validate_topology", lambda project_id: {"valid": False, "errors": ["缺少地图"]})
    response = _get_json("/api/deployments/site/topology")
    assert response.status == 200
    assert response.json["topology"]["errors"] == ["缺少地图"]
```

- [ ] **步骤 2：运行测试并确认失败**

运行：`pytest tests/test_deployment_http.py::test_topology_http_request_uses_store_without_ros -v`
预期：路径当前被误判为项目 ID 或返回 404。

- [ ] **步骤 3：最小实现**

在项目通用 GET 前解析 `/topology`，返回 `{"topology": DEPLOYMENTS.validate_topology(project_id)}`。在既有部署 POST 路由中，将 JSON 原样交给相应 Store 方法。所有新路由只捕获 `DeploymentError`、`TypeError`、`ValueError`、`JSONDecodeError`，不得导入或调用 `MAPPING`、`VEHICLE_CONTROL`、ROS 或子进程。

- [ ] **步骤 4：运行测试并确认通过**

运行：`pytest tests/test_deployment_http.py::test_topology_http_request_uses_store_without_ros -v`
预期：通过。

- [ ] **步骤 5：验证 API 输入拒绝行为**

```python
def test_transition_http_rejects_invalid_store_input():
    response = _post_json("/api/deployments/site/transitions", {"from_waypoint_id": "missing"})
    assert response.status == 400
    assert "error" in response.json
```

运行：`pytest tests/test_deployment_http.py -v`。预期：HTTP 测试均通过。

### 任务 5：二维阶段向导、路线编辑与只读拓扑预览

**文件：**
- 修改：`autodrive_console/web/deployment.html`
- 修改：`autodrive_console/web/deployment.js`
- 修改：`autodrive_console/web/deployment.css`

**接口：**
- 消费：任务 4 的拓扑、阶段、Transition、路线 API；已有画布坐标、Waypoint 和虚拟墙数据。
- 产出：阶段选择、Transition 连接、地图内路线选择、当前地图路线绘制、只读预览面板。

- [ ] **步骤 1：写失败的界面行为检查**

```javascript
// 在浏览器控制台或轻量 DOM 测试中：
renderTopology({ valid: false, errors: ["第 2 段缺少入口 Transition"], stages: [] });
console.assert(document.querySelector("#topologyPreview").textContent.includes("缺少入口 Transition"));
```

- [ ] **步骤 2：运行检查并确认失败**

运行：`node --check autodrive_console/web/deployment.js`，并在本地页面调用上段检查。
预期：因 `renderTopology` 与 `#topologyPreview` 尚不存在而失败。

- [ ] **步骤 3：最小实现**

在现有地图导入面板下添加简洁的“地图阶段”选择和“部署拓扑预览”面板。新增 Transition 工具只能从当前地图选源点，再切换到紧邻下一阶段地图选目标点；路线工具只能暂存当前地图 Waypoint，保存时调用 `/routes`。`drawMap()` 新增当前地图 route 的半透明折线绘制；不得绘制跨图坐标连线，Transition 仅以标签／列表显示。

- [ ] **步骤 4：运行界面检查并确认通过**

运行：`node --check autodrive_console/web/deployment.js`，在浏览器完成以下最小流程：打开项目、选择三地图模型、导入三张地图、各自添加标记、创建两条 Transition、创建一条大厅路线、打开拓扑预览。
预期：画布只绘制当前地图路线，预览显示三段状态及跨图链路。

- [ ] **步骤 5：按 Impeccable 进行一次界面质量检查**

运行：

```bash
node /home/bob/.codex/skills/impeccable/scripts/detect.mjs --json \
  autodrive_console/web/deployment.html \
  autodrive_console/web/deployment.css \
  autodrive_console/web/deployment.js
```

修复检测到的本期 UI 问题，然后只进行一次桌面和窄宽度截图复查。

### 任务 6：回归验证与交付审查

**文件：**
- 修改：`docs/superpowers/plans/2026-09-02-deployment-map-topology.md`，勾选已完成步骤。

**接口：**
- 消费：任务 1 至任务 5 的实现。
- 产出：可复现的验证记录，不产生机器人部署文件。

- [ ] **步骤 1：运行 Python 语法检查**

运行：`python3 -m py_compile autodrive_console/deployment.py autodrive_console/mapping.py web_console.py`。
预期：退出码为 0。

- [ ] **步骤 2：运行部署建图测试**

运行：`pytest tests/test_deployment.py tests/test_mapping.py tests/test_deployment_http.py -v`。
预期：全部通过；若环境没有 pytest，明确记录阻塞原因，并运行等价的标准库测试／最小可复现脚本。

- [ ] **步骤 3：运行前端和差异检查**

运行：

```bash
node --check autodrive_console/web/deployment.js
git diff --check
```

预期：两个命令均退出 0。

- [ ] **步骤 4：需求逐项核对**

核对规格中的阶段顺序、Stage 绑定、Transition、地图内路线、拓扑错误、只读预览、
不写机器人路径、格栅不入图和现有建图会话隔离；将未实现项明确列为后续范围。

- [ ] **步骤 5：完成分支处理**

在确认所有验证结果后，使用 `superpowers:finishing-a-development-branch` 按其流程汇报状态并选择集成方式；不得把无关的既有未提交改动包含在提交中。
