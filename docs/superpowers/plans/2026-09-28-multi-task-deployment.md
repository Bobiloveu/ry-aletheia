# 全小区多任务点部署编译 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变既有引导式建图界面的前提下，让一个全小区部署项目能够以固定的单任务点或多任务点模式，自动从地图、组件和部署流程派生多目标实验预览与 ZIP。

**Architecture:** 保留 `SiteProject`、现有地图标记、自动路线、定位绑定和项目内导出边界；项目创建时保存不可变的 `task_mode`。新增一个只读的路线族派生层，把每个栋单元的共享阶段与每个目标末端分开，再由模式专属编译器生成完整单任务文件或 `multi_tasks/<community>` 子任务树。浏览器仅在原“新建部署项目”区域加入模式选择，并把服务端预览以业务名称呈现。

**Tech Stack:** Python 3 / pytest、现有 `DeploymentStore` 和标准库 ZIP/XML/JSON、原生 ES modules、Node test runner、现有 HTML/CSS。

**Spec:** `docs/superpowers/specs/2026-09-28-multi-task-deployment-design.md`

## Global Constraints

- 不改变现有侧栏、引导式部署步骤、地图工作区、组件编辑器或其视觉结构；只能在新建项目区域添加模式选择、在预览区补充可读业务信息。
- 项目模式只能是 `single` 或 `multi`，创建后不可修改；历史项目读取为 `single`。
- 两种模式都支持多个目标点；浏览器不得提交目标顺序、路线顺序、任务文件名、输出目录或运行时路径。
- `deployment_flow` 是目录派生的唯一依据：仅 `lobby → target_floor` 时只生成 `indoor/` 和 `floor/`；有 `ferry` 才生成根目录 `sub_outdoor_eguard.json`/`_r.json`；有 `outdoor` 才生成 `outdoor/`。
- `typical_floor` 目标使用 `floor/<building>_<unit>_n_n<door>.json`；`floor_override` 使用 `floor/<building>_<unit>_<physical_floor>_<full_room_number>.json`，并总是成对生成 `_r.json`。
- 目标 `1501` 在物理 15 楼必须派生为 `floor=15`、`door=01`；不得通过无校验的最后两位截取推测。
- 所有输出只写在 `deployments/<project_id>/exports/<sha>/`，ZIP 仅供人工下载；不得写入 `/opt/ry/data/tasks/multi_tasks`、机器人行为树目录、定位运行目录，或调用 ROS/Supervisor/任务服务。
- 所有跨 Web/Backend 的模型和 HTTP 变更必须同步更新 `shared/contracts/deployment.md`；Mobile 不消费该能力。
- 当前工作树包含其他人的未提交改动。不要运行 `git add`、`git commit`、`git push`、`git reset`、`git checkout` 或清理命令；每个任务结束只报告改动文件与检查结果。

---

## File Structure

| File | Responsibility |
| --- | --- |
| `autodrive_console/deployment.py` | 保存/迁移不可变项目模式；选择编译器；安全持久化预览并命名 ZIP。 |
| `autodrive_console/task_compiler.py` | 保留并抽取现有单目标室内编译的可复用任务、行为树、定位产物构造函数。 |
| `autodrive_console/task_route_families.py` (new) | 纯函数：从项目事实派生全局/栋单元拓扑、共享路线、目标分支、房号语义、阶段目录需求和冲突检查。 |
| `autodrive_console/multi_task_compiler.py` (new) | 纯函数：根据路线族生成 `multi_tasks/<community>/` 任务对、清单和只读预览。 |
| `web_console.py` | 严格校验创建项目的 `{name, task_mode}` 请求，保持其他任务编译路由边界。 |
| `autodrive_console/web/deployment.html` | 在既有“新建部署项目”面板加入紧凑模式单选组；预览容器保留原位置。 |
| `autodrive_console/web/deployment.js` | 创建时提交模式；只读显示已选模式；用业务名称渲染多任务预览。 |
| `autodrive_console/web/deployment/compiler.css` | 为模式选项与路线族摘要添加复用现有 token 的局部样式，不影响侧栏或工作区。 |
| `shared/contracts/deployment.md` | 记录项目模式、多个目标、文件命名、流程目录派生、HTTP 边界及消费者。 |
| `tests/test_task_route_families.py` (new) | 对路线族、房号、阶段/目录和碰撞规则做纯函数测试。 |
| `tests/test_multi_task_compiler.py` (new) | 对多任务 ZIP 树、公共段去重、标准/非标准层、失败边界做编译器测试。 |
| `tests/test_deployment.py` | 对持久项目迁移、创建 HTTP、预览/下载选择与外部运行目录隔离做集成测试。 |
| `tests/test_task_compiler.py` | 扩展单任务模式的多目标完整链路回归，并保留历史单目标快照。 |
| `frontend/test/deployment-workflow.test.mjs` | 验证模式选择保留向导、模式不可编辑、预览无内部 ID 且不改变页面壳。 |

### Task 1: 项目模式模型与创建 HTTP 边界

**Files:**
- Modify: `autodrive_console/deployment.py:158-170, 377-390`
- Modify: `web_console.py:600-610`
- Modify: `tests/test_deployment.py`
- Modify: `shared/contracts/deployment.md`

**Interfaces:**
- Consumes: `DeploymentStore.create(name: object)` 和 `POST /api/deployments` 既有边界。
- Produces: `DeploymentStore.create(name: object, task_mode: object = "single") -> dict[str, Any]`；项目文档顶层 `task_mode: Literal["single", "multi"]`；`POST /api/deployments` 仅接受 `{"name": str, "task_mode": "single" | "multi"}`。

- [ ] **Step 1: 写入失败的 Store 迁移与不可变性测试**

```python
def test_project_mode_defaults_legacy_projects_to_single_and_cannot_be_changed(tmp_path):
    store = DeploymentStore(tmp_path / "deployments")
    project = store.create("旧项目")
    payload = store.get(project["id"])
    payload.pop("task_mode")
    store._write_json(store._document_path(project["id"]), payload)

    assert store.get(project["id"])["task_mode"] == "single"
    with pytest.raises(DeploymentError, match="项目模式"):
        store.update_task_compiler_config(project["id"], {"community": "高科一号", "task_mode": "multi"})


def test_project_creation_persists_requested_multi_mode(tmp_path):
    store = DeploymentStore(tmp_path / "deployments")
    assert store.create("全小区", "multi")["task_mode"] == "multi"
```

- [ ] **Step 2: 运行测试，确认当前实现失败**

Run: `pytest tests/test_deployment.py -k 'project_mode_defaults or requested_multi_mode' -v`

Expected: FAIL，因为 `create` 尚未接收模式，读取旧项目也不会产生 `task_mode`。

- [ ] **Step 3: 实现严格模式归一化与 HTTP 请求校验**

```python
TASK_MODES = frozenset({"single", "multi"})

@classmethod
def _normalise_task_mode(cls, value: object) -> str:
    mode = str(value or "single").strip()
    if mode not in TASK_MODES:
        raise DeploymentError("项目模式只能是 single 或 multi")
    return mode

def create(self, name: object, task_mode: object = "single") -> dict[str, Any]:
    mode = self._normalise_task_mode(task_mode)
    document["task_mode"] = mode
```

在 `_migrate_document`（或当前读取归一化入口）中，只在缺少 `task_mode` 时写入 `single`；不得提供更新它的方法。HTTP 创建路由必须拒绝缺少、额外字段、非字符串名称、非字符串模式和无效枚举，并将完整请求传给 `DEPLOYMENTS.create(data["name"], data["task_mode"])`。

- [ ] **Step 4: 添加 HTTP 边界测试**

```python
def test_create_deployment_http_accepts_only_name_and_task_mode(handler):
    handler.rfile = BytesIO(b'{"name":"全小区","task_mode":"multi"}')
    handler.headers = {"Content-Length": "43"}
    handler.do_POST()
    handler.deployment_store.create.assert_called_once_with("全小区", "multi")

@pytest.mark.parametrize("body", [
    b'{"name":"全小区"}',
    b'{"name":"全小区","task_mode":"other"}',
    b'{"name":"全小区","task_mode":"multi","extra":true}',
])
def test_create_deployment_http_rejects_implicit_or_invalid_mode(handler, body):
    handler.rfile = BytesIO(body)
    handler.headers = {"Content-Length": str(len(body))}
    handler.do_POST()
    assert handler._json.call_args.args[1] == HTTPStatus.BAD_REQUEST
```

- [ ] **Step 5: 运行任务测试**

Run: `pytest tests/test_deployment.py -k 'project_mode or create_deployment_http' -v`

Expected: PASS。

- [ ] **Step 6: 更新契约的项目创建段落**

在 `shared/contracts/deployment.md` 的项目模型和 HTTP 表中写明 `task_mode` 仅在创建时传递、遗留项目默认 `single`、不得通过编译器配置接口更改。

- [ ] **Step 7: 检查工作区而不进行 Git 写操作**

Run: `git diff --check`

Expected: exit 0；记录本任务文件列表，不执行暂存或提交。

### Task 2: 自动路线族、目标房号和目录需求的纯函数派生

**Files:**
- Create: `autodrive_console/task_route_families.py`
- Create: `tests/test_task_route_families.py`
- Modify: `autodrive_console/automatic_route.py`
- Modify: `autodrive_console/deployment.py:stage_plan, assign_map_stage, add_map_instance, _normalise_localization_binding`
- Modify: `autodrive_console/web/deployment.js`
- Modify: `frontend/test/deployment-workflow.test.mjs`

**Interfaces:**
- Consumes: 正规化 `SiteProject` 的 `deployment_flow`、`map_assets`、`map_instances`、`components`、`localization_bindings`、`localization_routes` 和现有 `automatic_route.derive_localization_routes` 输出。
- Produces: `derive_task_route_families(project: Mapping[str, Any]) -> tuple[TaskRouteFamily, ...]`，其中 `TaskRouteFamily` 有 `building`, `unit`, `stages`, `shared_bindings`, `targets`；`TargetBranch` 有 `component_id`, `map_asset_id`, `full_room_number`, `physical_floor`, `door`, `target_role`, `floor_stem`。地图实例新增后端派生的 `scope: "global" | "unit"`；仅 `ferry` 必为 `global`，`outdoor`、`lobby`、`typical_floor`/`floor_override` 必为 `unit`。

**Topology rule:** `deployment_flow` 只定义阶段类型和顺序，绝不再承担“这一个阶段只能绑定一张地图”的含义。地图角色和实例才声明每张地图属于全局公共段还是某栋单元。旧的单地图 `map_stage_assignments` 保留为导入向导兼容记录；新的自动路线和编译器只读取归一化后的实例拓扑。因此，导入第二栋的大厅或第二个标准层模板不会覆盖第一张地图，也不需要用户补写路线或改变流程顺序。

- [ ] **Step 1: 写入失败的路线族测试夹具与最小断言**

```python
def test_lobby_to_target_flow_requires_only_indoor_and_floor_outputs(two_target_project):
    family = derive_task_route_families(two_target_project)[0]
    assert family.required_outputs == frozenset({"indoor", "floor"})
    assert [target.floor_stem for target in family.targets] == ["1_1_n_n01", "1_1_n_n02"]

def test_target_1501_requires_matching_instance_floor_and_yields_door_01(two_target_project):
    target = derive_task_route_families(two_target_project)[0].targets[0]
    assert (target.physical_floor, target.door, target.full_room_number) == (15, "01", "1501")

def test_flow_with_ferry_and_outdoor_requests_exactly_those_shared_outputs(project_with_all_stages):
    assert derive_task_route_families(project_with_all_stages)[0].required_outputs == frozenset({"ferry", "outdoor", "indoor", "floor"})

def test_global_outdoor_and_ferry_are_reused_for_each_building_unit(community_project):
    families = derive_task_route_families(community_project)
    assert [(family.building, family.unit) for family in families] == [("1", "1"), ("2", "1")]
    assert {family.shared_bindings["outdoor"].map_asset_id for family in families} == {"outdoor-map"}
    assert {family.shared_bindings["ferry"].map_asset_id for family in families} == {"ferry-map"}
```

- [ ] **Step 2: 运行测试，确认模块尚不存在**

Run: `pytest tests/test_task_route_families.py -v`

Expected: FAIL，提示 `ModuleNotFoundError: autodrive_console.task_route_families`。

- [ ] **Step 3: 定义不可变数据结构与受控派生函数**

```python
@dataclass(frozen=True)
class TargetBranch:
    component_id: str
    map_asset_id: str
    full_room_number: str
    physical_floor: int
    door: str
    target_role: Literal["typical_floor", "floor_override"]
    floor_stem: str

def derive_task_route_families(project: Mapping[str, Any]) -> tuple[TaskRouteFamily, ...]:
    flow_types = _validated_flow_types(project)
    instances = _indexed_instances(project)
    targets = _indexed_targets(project)
    return _families_grouped_by_building_and_unit(flow_types, instances, targets, project)
```

实现规则：

1. 不从客户端获取顺序；阶段顺序只来自 `deployment_flow`，节点顺序只来自已有受控自动路线。
2. 以 `(building, unit)` 分组，拒绝没有大厅、没有目标、重复地图角色、跨栋/单元绑定和没有正返程链的分支。
3. 对 `typical_floor`，从物理楼层前缀验证完整房号并保留补零户号；对 `floor_override`，要求完整房号以物理楼层前缀开头且生成显式 `building_unit_floor_fullRoom`。
4. 将目标按稳定业务键 `(physical_floor, door, component_id)` 排序，仅用于确定性产物和清单；这不是 UI 可编辑顺序。
5. 只把 `ferry`、`outdoor`、`lobby`、`target_floor` 实际存在的阶段置入 `required_outputs`，不产生空目录。

- [ ] **Step 4: 让地图实例拓扑支持全局段与多个栋单元段**

将地图实例角色扩展为 `outdoor`、`ferry`、`lobby`、`typical_floor`、`floor_override`，并由后端归一化出下列事实：

```python
GLOBAL_INSTANCE_ROLES = frozenset({"outdoor", "ferry"})
UNIT_INSTANCE_ROLES = frozenset({"lobby", "typical_floor", "floor_override"})

def _normalise_map_instance_scope(role: str, building: object, unit: object, floor: object) -> dict[str, object]:
    if role in GLOBAL_INSTANCE_ROLES:
        return {"scope": "global", "building": "", "unit": "", "floor": None}
    return {
        "scope": "unit",
        "building": _normalise_localization_identifier(building, "楼栋"),
        "unit": _normalise_localization_identifier(unit, "单元"),
        "floor": _normalise_instance_floor(floor),
    }
```

规则必须精确如下：

1. 一个项目最多一张全局 `outdoor` 地图和一张全局 `ferry` 地图；它们只在流程包含同类型阶段时有效。
2. 每个 `(building, unit)` 必须恰有一张 `lobby`；`typical_floor` 每个布局模板一张；`floor_override` 每个物理楼层一张。多栋/单元可以并存，互不覆盖。
3. `stage_plan` 的原单卡片结构保持，但返回每个阶段的 `map_count` 和人类标签；单图项目继续返回原有 `map_asset_id`。当阶段有多张地图时只显示“已配置 N 张地图”，不得展示内部地图 ID、排序控件或要求用户排列。
4. `map_stage_assignments` 只保留为历史项目和当前导入向导的首张地图落点；它不能阻止同角色后续地图导入，不能成为编译输入，也不能删改已经归类的其他地图。
5. 自动路线按每个 `(building, unit)` 将全局 `ferry` 绑定、该单元的 `outdoor`/`lobby`/`floor` 绑定按照 `deployment_flow` 合成；全局摆渡段不是手工复制到每个项目记录，且只能由其公共地图生成一次摆渡文件。
6. 现有页面保留原来的流程卡片、地图导入与地图实例表。仅将“本阶段已有地图”提示由单个名称升级为计数/可读名称列表；不增加路线编辑、目标排序或新的页面层级。

- [ ] **Step 5: 写入并运行全小区拓扑迁移/交互测试**

```python
def test_stage_assignment_compatibility_does_not_block_second_lobby_map(store, community_project):
    second = store.import_map(community_project["id"], _fixture_map("lobby-2"), "2 栋大厅", "lobby")
    instance = store.add_map_instance(community_project["id"], {
        "map_id": second["id"], "role": "lobby", "building": "2", "unit": "1", "floor": 1,
    })
    assert instance["scope"] == "unit"
    assert len([item for item in store.get(community_project["id"])["map_instances"] if item["role"] == "lobby"]) == 2
```

```javascript
test("stage summary groups multiple maps without exposing manual route order", () => {
  assert.match(deploymentSource, /map_count/);
  assert.doesNotMatch(deploymentSource, /manual.*route.*order/i);
});
```

Run: `pytest tests/test_deployment.py -k 'stage_assignment_compatibility or community' -v && node --test frontend/test/deployment-workflow.test.mjs`

Expected: PASS。

- [ ] **Step 6: 增加拒绝测试**

```python
@pytest.mark.parametrize("door, message", [
    ("501", "目标房号与物理楼层不一致"),
    ("150", "目标房号"),
])
def test_invalid_target_room_number_blocks_route_family(two_target_project, door, message):
    two_target_project["components"][-1]["attributes"]["door"] = door
    with pytest.raises(TaskRouteFamilyError, match=message):
        derive_task_route_families(two_target_project)

def test_duplicate_floor_stem_is_rejected(two_target_project):
    two_target_project["components"].append(dict(two_target_project["components"][-1]))
    with pytest.raises(TaskRouteFamilyError, match="输出文件名冲突"):
        derive_task_route_families(two_target_project)
```

- [ ] **Step 7: 将自动路线从“唯一 target”改为为每个目标派生受控分支**

在 `automatic_route.py` 中保留现有单目标路径输出兼容性：当一个地图只有一个目标时，输出字节级结构不变；当同一终点地图有多个 `kind == "target"` 组件时，为每个目标计算不可由浏览器排序的末端分支，并让路线族读取这一派生结果。禁止用创建时间或几何近邻作为顺序。

- [ ] **Step 8: 运行纯函数与现有自动路线回归**

Run: `pytest tests/test_task_route_families.py tests/test_automatic_route.py -v`

Expected: PASS。

- [ ] **Step 9: 检查工作区而不进行 Git 写操作**

Run: `git diff --check`

Expected: exit 0。

### Task 3: 保持历史单目标稳定的单任务点多目标编译

**Files:**
- Modify: `autodrive_console/task_compiler.py`
- Modify: `tests/test_task_compiler.py`
- Modify: `autodrive_console/deployment.py`

**Interfaces:**
- Consumes: `derive_task_route_families()` 的 `TargetBranch` 以及既有 `CompilationPreview`/`Artifact`。
- Produces: `compile_single_task_points(project: dict[str, Any], *, map_root: Path) -> CompilationPreview`；保留 `compile_indoor_elevator` 作为只含一个目标的向后兼容委托入口。

- [ ] **Step 1: 写入失败的多目标单任务输出测试**

```python
def test_single_mode_outputs_one_complete_task_per_target(two_target_project):
    two_target_project["task_mode"] = "single"
    preview = compile_single_task_points(two_target_project, map_root=Path(two_target_project["_test_map_root"]))
    task_paths = [a.relative_path for a in preview.artifacts if a.relative_path.startswith("tasks/")]
    assert task_paths == [
        "tasks/高科一号_1_1_15_1501.json",
        "tasks/高科一号_1_1_15_1502.json",
    ]
    assert all(len(json.loads(_artifact(preview, path))["subtasks"]) == 4 for path in task_paths)

def test_existing_one_target_single_project_retains_legacy_task_path(two_map_project):
    assert [a.relative_path for a in _compile(two_map_project).artifacts if a.relative_path.startswith("tasks/")] == [
        "tasks/高科一号_1_1_15_1509.json"
    ]

def test_single_mode_expands_optional_ferry_and_outdoor_before_each_target(all_stage_project):
    all_stage_project["task_mode"] = "single"
    preview = compile_single_task_points(all_stage_project, map_root=Path(all_stage_project["_test_map_root"]))
    payload = json.loads(next(a.content for a in preview.artifacts if a.relative_path.endswith("1501.json")))
    assert [item["subtask_name"] for item in payload["subtasks"]] == [
        "ferry", "outdoor", "elevator_hall", "1501", "1501_r", "elevator_hall_r", "outdoor_r", "ferry_r",
    ]
```

- [ ] **Step 2: 运行测试，确认当前编译器强制唯一目标而失败**

Run: `pytest tests/test_task_compiler.py -k 'single_mode_outputs or retains_legacy_task_path' -v`

Expected: FAIL，当前 `_one_component` 对 `target` 只允许一个组件。

- [ ] **Step 3: 抽取每目标完整任务构造而不改变已有模板语义**

```python
def _compile_complete_target_branch(
    project: dict[str, Any], family: TaskRouteFamily, target: TargetBranch, *, map_root: Path,
) -> BranchCompilation:
    """Build one complete outbound/return JSON and its controlled artifacts."""

def compile_single_task_points(project: dict[str, Any], *, map_root: Path = DEFAULT_MAP_ROOT) -> CompilationPreview:
    branches = [
        _compile_complete_target_branch(project, family, target, map_root=map_root)
        for family in derive_task_route_families(project)
        for target in family.targets
    ]
    return _merge_branches_as_single_preview(project, branches)
```

复用既有 `_task_json`、行为树模板、组件动作、状态码快照与定位清单函数；每个目标的任务 JSON 必须完整展开该路线族实际存在的 `ferry → outdoor → lobby → target_floor` 段及严格逆序返程，缺失的非流程阶段不能出现空子任务。产物相对路径去重：同内容且稳定共享的行为树/定位文件只写一次；相同路径内容不一致时抛出 `CompilationError("输出文件名冲突")`。

- [ ] **Step 4: 扩展输入哈希和清单测试**

```python
def test_single_mode_manifest_lists_each_business_target_without_component_uuid(two_target_project):
    manifest = compile_single_task_points(two_target_project, map_root=Path(two_target_project["_test_map_root"])).manifest
    assert [(item["floor"], item["door"]) for item in manifest["route_families"][0]["targets"]] == [(15, "01"), (15, "02")]
    assert "component-" not in json.dumps(manifest["route_families"], ensure_ascii=False)
```

- [ ] **Step 5: 在 Store 按 `task_mode` 选择单任务编译器**

在 `task_compiler_preview` 与 `task_compiler_bundle` 之间抽取：

```python
def _compile_task_mode(self, document: dict[str, Any], project_id: str) -> CompilationPreview:
    compiler = compile_multi_task_points if document["task_mode"] == "multi" else compile_single_task_points
    return compiler(document, map_root=self._project_dir(project_id) / "maps")
```

保留现有 `compile_indoor_elevator` 调用兼容测试；不要让路由层根据模式做分支。

- [ ] **Step 6: 运行单任务编译回归**

Run: `pytest tests/test_task_compiler.py -v`

Expected: PASS，包括既有单目标四段子任务、行为树状态码和项目快照测试。

- [ ] **Step 7: 检查工作区而不进行 Git 写操作**

Run: `git diff --check`

Expected: exit 0。

### Task 4: 多任务点纯编译器与流程驱动的 ZIP 文件树

**Files:**
- Create: `autodrive_console/multi_task_compiler.py`
- Create: `tests/test_multi_task_compiler.py`
- Modify: `autodrive_console/task_compiler.py`
- Modify: `autodrive_console/deployment.py`

**Interfaces:**
- Consumes: `TaskRouteFamily`、`BranchCompilation`、状态码快照、现有 `Artifact`、`CompilationPreview` 和 `bundle_zip()`。
- Produces: `compile_multi_task_points(project: dict[str, Any], *, map_root: Path = DEFAULT_MAP_ROOT) -> CompilationPreview`；所有任务文件位于 `multi_tasks/<community>/`。

- [ ] **Step 1: 写入“大厅到用户楼层”无多余目录的失败测试**

```python
def test_multi_compiler_lobby_to_floor_emits_only_indoor_and_floor(two_target_project):
    two_target_project["task_mode"] = "multi"
    preview = compile_multi_task_points(two_target_project, map_root=Path(two_target_project["_test_map_root"]))
    paths = {item.relative_path for item in preview.artifacts}
    assert "multi_tasks/高科一号/indoor/1_1.json" in paths
    assert "multi_tasks/高科一号/indoor/1_1_r.json" in paths
    assert "multi_tasks/高科一号/floor/1_1_n_n01.json" in paths
    assert "multi_tasks/高科一号/floor/1_1_n_n01_r.json" in paths
    assert not any("sub_outdoor_eguard" in path or "/outdoor/" in path for path in paths)
```

- [ ] **Step 2: 写入多目标、覆盖楼层和可选阶段的失败测试**

```python
def test_multi_compiler_second_target_adds_only_a_floor_pair(two_target_project):
    preview = compile_multi_task_points(two_target_project, map_root=Path(two_target_project["_test_map_root"]))
    assert _task_paths(preview) == {
        "multi_tasks/高科一号/indoor/1_1.json",
        "multi_tasks/高科一号/indoor/1_1_r.json",
        "multi_tasks/高科一号/floor/1_1_n_n01.json",
        "multi_tasks/高科一号/floor/1_1_n_n01_r.json",
        "multi_tasks/高科一号/floor/1_1_n_n02.json",
        "multi_tasks/高科一号/floor/1_1_n_n02_r.json",
    }

def test_multi_compiler_floor_override_501_uses_explicit_pair(override_project):
    assert _task_paths(compile_multi_task_points(
        override_project, map_root=Path(override_project["_test_map_root"])
    )) >= {
        "multi_tasks/高科一号/floor/1_1_5_501.json",
        "multi_tasks/高科一号/floor/1_1_5_501_r.json",
    }

def test_multi_compiler_adds_ferry_and_outdoor_only_when_flow_contains_them(all_stage_project):
    assert _task_paths(compile_multi_task_points(
        all_stage_project, map_root=Path(all_stage_project["_test_map_root"])
    )) >= {
        "multi_tasks/高科一号/sub_outdoor_eguard.json",
        "multi_tasks/高科一号/sub_outdoor_eguard_r.json",
        "multi_tasks/高科一号/outdoor/1_1.json",
        "multi_tasks/高科一号/outdoor/1_1_r.json",
    }
```

- [ ] **Step 3: 运行测试，确认模块不存在**

Run: `pytest tests/test_multi_task_compiler.py -v`

Expected: FAIL，提示 `ModuleNotFoundError`。

- [ ] **Step 4: 实现模式专属产物生成**

```python
MULTI_ROOT = "multi_tasks"

def _task_pair(prefix: str, stem: str, outbound: dict[str, Any], inbound: dict[str, Any]) -> tuple[Artifact, Artifact]:
    return (
        _artifact(f"{prefix}/{stem}.json", _task_json_bytes(outbound)),
        _artifact(f"{prefix}/{stem}_r.json", _task_json_bytes(inbound)),
    )

def compile_multi_task_points(project: dict[str, Any], *, map_root: Path = DEFAULT_MAP_ROOT) -> CompilationPreview:
    families = derive_task_route_families(project)
    artifacts = _compile_shared_segments_once_per_family(project, families, map_root)
    artifacts += _compile_floor_pairs_per_target(project, families, map_root)
    return _preview_from_multi_artifacts(project, families, artifacts, map_root)
```

实现细节：

1. 对每个路线族只生成一次共享段；`ferry` 输出固定根文件对，`outdoor` 和 `lobby` 分别输出对应栋单元的正返程对。
2. 每个目标只输出楼层任务对；不得因第二个目标复制 `indoor`、`outdoor` 或摆渡文件。
3. 所有任务内仍由既有组件执行链生成速度点、闸机/自动门开关、梯控和状态码行为树；不能生成只包含地图切换但丢失受控组件动作的子任务。
4. 复用 `compile_location_manifest`，但将运行时辅助定位产物保持在项目实验包命名空间，并在清单标注 `robot_runtime_changed: false`。
5. 清单写入 `task_mode: "multi"`、路线族、业务楼栋/单元/楼层/户号、目录派生、每个产物 SHA-256、受控输入和状态码配置指纹；浏览器可展示其中人类字段，不能展示组件 UUID 或随机文件名。
6. `task_json` 预览字段固定为 `{"mode": "multi", "route_families": list(manifest_route_families)}`，不得伪装成一份完整单任务 JSON。

- [ ] **Step 5: 写入安全失败与 ZIP 内容测试**

```python
def test_multi_compiler_rejects_collision_before_zip_write(two_target_project):
    _make_targets_share_floor_stem(two_target_project)
    with pytest.raises(CompilationError, match="输出文件名冲突"):
        compile_multi_task_points(two_target_project, map_root=Path(two_target_project["_test_map_root"]))

def test_multi_bundle_never_contains_absolute_or_runtime_install_paths(two_target_project):
    preview = compile_multi_task_points(two_target_project, map_root=Path(two_target_project["_test_map_root"]))
    archive = zipfile.ZipFile(BytesIO(bundle_zip(preview)))
    assert all(not name.startswith("/") and "/opt/ry/" not in name for name in archive.namelist())
```

- [ ] **Step 6: 让 `DeploymentStore` 使用模式专属下载名**

```python
filename = f"{safe_zip_stem(document['task_compiler']['identity']['community'])}_{document['task_mode']}_experimental.zip"
```

下载逻辑只从 `CompilationPreview.artifacts` 和 `bundle_zip` 取数据，绝不检索或写入 `/opt/ry/data/tasks/multi_tasks`。

- [ ] **Step 7: 运行多任务编译器和 Store 集成测试**

Run: `pytest tests/test_task_route_families.py tests/test_multi_task_compiler.py tests/test_deployment.py -k 'multi or task_compiler_bundle or preview_writes_only_project_owned' -v`

Expected: PASS。

- [ ] **Step 8: 检查工作区而不进行 Git 写操作**

Run: `git diff --check`

Expected: exit 0。

### Task 5: 任务预览持久化、HTTP 路由与审计负载

**Files:**
- Modify: `autodrive_console/deployment.py:331-370, 1182-1205`
- Modify: `web_console.py:365-385, 610-630`
- Modify: `tests/test_deployment.py`

**Interfaces:**
- Consumes: 两种模式的 `CompilationPreview`。
- Produces: 统一 `GET/POST .../task-compiler/preview` 和下载 API 的模式安全预览；HTTP 响应含 `task_mode`、人类可读 `route_families`，但不含外部运行路径。

- [ ] **Step 1: 写入失败的 HTTP 预览模式测试**

```python
def test_store_preview_exposes_multi_mode_without_runtime_paths(tmp_path, multi_project):
    preview = store.task_compiler_preview(multi_project["id"])
    assert preview["task_mode"] == "multi"
    assert preview["route_families"][0]["targets"][0] == {"building": "1", "unit": "1", "floor": 15, "door": "01"}
    assert "/opt/ry/data/tasks/multi_tasks" not in json.dumps(preview, ensure_ascii=False)
```

- [ ] **Step 2: 运行测试，确认当前预览没有模式/路线族字段**

Run: `pytest tests/test_deployment.py -k 'preview_exposes_multi_mode' -v`

Expected: FAIL。

- [ ] **Step 3: 在 `_preview_payload` 中显示审计摘要而非内部标识**

```python
return {
    "status": "ready",
    "experimental": True,
    "input_sha256": preview.input_sha256,
    "task_mode": preview.manifest["task_mode"],
    "route_families": preview.manifest["route_families"],
    "artifacts": [
        {"path": artifact.relative_path, "sha256": artifact.sha256, "size_bytes": len(artifact.content)}
        for artifact in preview.artifacts
    ],
}
```

在编译异常映射中保持 `CompilationError → 422`，项目/输入边界问题保持 `400`；GET 与 POST 预览必须都调用同一模式选择函数。

- [ ] **Step 4: 添加预览失效测试**

```python
@pytest.mark.parametrize("mutation", ["target_component", "virtual_wall", "map_edit", "deployment_flow"])
def test_relevant_multi_mode_input_mutation_invalidates_preview(store, multi_project, mutation):
    before = store.task_compiler_preview(multi_project["id"])["input_sha256"]
    _mutate_project_fact(store, multi_project, mutation)
    assert store.get(multi_project["id"])["task_compiler"]["identity"]["last_preview_input_sha256"] is None
    assert store.task_compiler_preview(multi_project["id"])["input_sha256"] != before
```

- [ ] **Step 5: 运行 API/持久化测试**

Run: `pytest tests/test_deployment.py -k 'task_compiler_http or multi_mode or preview_writes_only_project_owned or invalidates_preview' -v`

Expected: PASS。

- [ ] **Step 6: 检查工作区而不进行 Git 写操作**

Run: `git diff --check`

Expected: exit 0。

### Task 6: 保持原界面的模式选择与可读多任务预览

**Files:**
- Modify: `autodrive_console/web/deployment.html:105-140`
- Modify: `autodrive_console/web/deployment.js:330-465, 2800-2860`
- Modify: `autodrive_console/web/deployment/compiler.css`
- Modify: `frontend/test/deployment-workflow.test.mjs`

**Interfaces:**
- Consumes: 创建 API `{"name", "task_mode"}` 和预览 `{task_mode, route_families, artifacts}`。
- Produces: `readSelectedProjectMode() -> "single" | "multi"`，创建后只读模式标签，以及 `renderTaskCompilerPreview()` 的业务摘要。

- [ ] **Step 1: 写入失败的 DOM/源码行为测试**

```javascript
test("project creation keeps guided shell and submits an explicit task mode", () => {
  assert.match(deploymentPage, /name=["']taskMode["']/);
  assert.match(deploymentSource, /task_mode:\s*readSelectedProjectMode\(\)/);
  assert.match(deploymentPage, /id=["']deploymentGuide["']/);
  assert.match(deploymentPage, /id=["']deploymentFlowCanvas["']/);
});

test("compiler preview exposes business targets without internal component ids", () => {
  assert.match(deploymentSource, /楼\s*\$\{target\.floor\}.*\$\{target\.door\}户/);
  assert.doesNotMatch(deploymentSource, /component_id.*taskCompilerPreview/);
});
```

- [ ] **Step 2: 运行测试，确认模式 UI 尚不存在**

Run: `node --test frontend/test/deployment-workflow.test.mjs`

Expected: FAIL，缺少 `taskMode` 控件和提交字段。

- [ ] **Step 3: 在既有创建项目卡片内加入紧凑单选项**

```html
<fieldset id="taskModeChoices" class="task-mode-choices">
  <legend>任务模式</legend>
  <label><input type="radio" name="taskMode" value="single" checked /> 单任务点模式</label>
  <label><input type="radio" name="taskMode" value="multi" /> 多任务点模式</label>
</fieldset>
```

不要移动任何 `aside`、`deploymentGuide`、地图工作区或阶段面板。项目已创建时显示只读文本“任务模式：单任务点模式/多任务点模式”，不提供切换按钮。

- [ ] **Step 4: 更新创建与预览渲染逻辑**

```javascript
function readSelectedProjectMode() {
  return document.querySelector('input[name="taskMode"]:checked')?.value === "multi" ? "multi" : "single";
}

body: JSON.stringify({ name: $("projectName").value, task_mode: readSelectedProjectMode() }),
```

`renderTaskCompilerPreview` 对 multi 使用“路线族 / 栋单元 / 楼层 / 户号 / 共享段 / 用户层任务”列表；对 single 使用“完整任务”列表。使用 `target.floor` 和 `target.door`，绝不读取或呈现 `component_id`、散列、绝对路径。只给局部字段添加 CSS，复用 `--border`、`--surface`、`--accent` 等既有变量。

- [ ] **Step 5: 添加模式不可编辑和错误提示测试**

```javascript
test("existing project displays mode as read-only fact", () => {
  assert.match(deploymentSource, /任务模式：/);
  assert.doesNotMatch(deploymentPage, /id=["']changeTaskMode["']/);
});
```

- [ ] **Step 6: 运行 Web 测试**

Run: `node --test frontend/test/deployment-workflow.test.mjs`

Expected: PASS。

- [ ] **Step 7: 检查工作区而不进行 Git 写操作**

Run: `git diff --check`

Expected: exit 0。

### Task 7: 契约完成、全量回归和人工浏览器验收

**Files:**
- Modify: `shared/contracts/deployment.md`
- Modify: `tests/test_deployment.py`
- Modify: `tests/test_task_compiler.py`
- Modify: `tests/test_multi_task_compiler.py`
- Modify: `frontend/test/deployment-workflow.test.mjs`

**Interfaces:**
- Consumes: Tasks 1–6 的稳定 API、项目模型、预览结构和 ZIP 产物。
- Produces: 可由 Backend/Web 消费者独立核对的 Existing 契约，以及通过完整测试的交付候选。

- [ ] **Step 1: 扩充 `shared/contracts/deployment.md` 的最终契约内容**

明确写入：项目创建 `task_mode` 枚举与不可变性、旧项目迁移、双模式多目标语义、`1501 → 15/01` 规则、标准层/覆盖层文件对、`deployment_flow` 到可选目录映射、预览 JSON 的 `task_mode`/`route_families`、项目内导出与不写运行目录边界、Backend/Web/Mobile 消费者矩阵。

- [ ] **Step 2: 写入合同关键句回归测试**

```python
def test_deployment_contract_documents_multi_task_boundary():
    contract = Path("shared/contracts/deployment.md").read_text(encoding="utf-8")
    assert "`task_mode`" in contract
    assert "`sub_outdoor_eguard.json`" in contract
    assert "`1501 → floor=15 / door=01`" in contract
    assert "Mobile 非消费者" in contract
```

- [ ] **Step 3: 运行合同与聚焦回归测试**

Run: `pytest tests/test_deployment.py tests/test_task_compiler.py tests/test_task_route_families.py tests/test_multi_task_compiler.py -v`

Expected: PASS。

- [ ] **Step 4: 运行项目规定的完整检查**

Run: `scripts/test-backend.sh`

Expected: PASS（仅记录既有、非本次引入的警告）。

Run: `scripts/test-web.sh`

Expected: PASS，含构建成功。

Run: `git diff --check`

Expected: exit 0。

- [ ] **Step 5: 用现有本地服务做人工浏览器验收**

使用 `agent-browser` 打开部署建图页，按以下可观察项检查并截图：

1. 左侧导航、顶部引导进度、地图工作区与既有页面一致；模式控件只位于新建项目卡片。
2. 新建 `multi` 项目后，模式可见但没有切换入口；流程 `电梯大厅 → 用户楼层` 不显示新的人为路线排序 UI。
3. 标记两个目标后，预览按“15 楼 01 户 / 15 楼 02 户”展示；页面不出现 `component-`、UUID、SHA 或绝对运行路径。
4. 下载多任务 ZIP 后仅检查 ZIP 内容：有 `multi_tasks/<community>/indoor/` 与 `floor/`，没有 `outdoor/` 和 `sub_outdoor_eguard*`。

- [ ] **Step 6: 交付前复核**

列出修改文件、测试命令及实际结果、人工验收截图路径和任何保留限制。不要执行 Git 暂存、提交、推送或运行目录安装；由用户决定后续 Git 与现场安装操作。
