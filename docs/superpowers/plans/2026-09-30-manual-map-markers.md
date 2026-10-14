# 手动地图标记与受控前往 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用持久化、按已验证地图隔离的手动标记替换实时观测页的任务目录起终点扫描，并安全地前往操作员选择的标记。

**Architecture:** 后端新增独立的标记存储，使用 `ObservationManager` 已严格验证的内部地图资产 ID 隔离数据，浏览器从不接收地图路径或地图 ID。现有 Nav2 控制器改为解析手动标记，并在开始及发送 Goal 前重新确认当前地图和所有驾驶安全条件；PC Web 以一次性按需读取的“地图标记”图层与紧凑输入浮层管理标记。

**Tech Stack:** Python 3.10、标准库 JSON/文件原子替换、ROS 2 Nav2 Action（既有封装）、HTTP JSON、Vite/原生 ES Modules、PixiJS、pytest、Node test runner。

**Spec:** `docs/superpowers/specs/2026-09-30-manual-map-markers-design.md`

## Global Constraints

- 完全停止读取、遍历或解析任务目录来获得实时页标记；不得依赖 `task_directory`、多任务目录或任务 JSON。
- 标记只绑定 Backend 已严格确认的当前地图内部资产 ID；浏览器请求和响应均不得传递 `map_id`、地图路径或 ROS 参数。
- 别名为去首尾空白后的 1–48 个 Unicode 字符；`x/y` 为绝对值不超过 100,000 的有限米制数；`yaw` 为绝对值不超过 10,000 的有限弧度数，持久化时规范化为 `[-π, π)`；每张地图最多 500 个标记。
- 标记配置文件固定为 `config/live_map_markers.json`，版本字段为 `schema: 1`，使用临时文件、`fsync`、原子替换写入；只保存标记，不保存地图路径、任务数据、ROS 信息或凭据。
- 导航的运行互斥、`navigation` 控制源、非急停、正常定位、无手动会话/重定位、严格地图确认、Nav2 可用性、300 秒超时与取消逻辑必须全部保留；不得发布 Twist、切换控制源或修改任务文件。
- API 仅由 PC Web 消费；Mobile 继续是非消费者，页面不增加移动端入口。
- 不创建构建产物、升级包或 DEB，不部署到小车，不进行未经操作员确认的实车导航。
- 工作区已有未提交的其他改动；只暂存本计划涉及文件，除非用户明确要求，否则不提交。

---

## File Structure

- `autodrive_console/manual_map_markers.py`：新建；持久化标记的纯 Python 校验、按图查询、创建、删除与原子保存，不导入 ROS 或任务目录模块。
- `autodrive_console/observation.py`：扩展已验证活动地图的内部 ID 访问及严格二次确认，供标记 API 和导航控制器使用。
- `autodrive_console/map_marker_navigation.py`：新建；将现有 Nav2 安全控制器改为仅消费 `ManualMapMarkerStore` 的记录。
- `web_console.py`：替换旧任务起终点初始化、GET/POST 路由和错误处理，构造标记存储与新导航控制器。
- `tests/test_manual_map_markers.py`：新建；覆盖持久化模型、边界和地图隔离。
- `tests/test_map_marker_navigation.py`：新建；覆盖安全前往、地图二次确认、取消和无任务目录耦合。
- `tests/test_live_observation_realtime.py`、`tests/test_offline_modules.py`：更新 HTTP/静态集成断言。
- `frontend/live-observation.html`：将图层、添加标记浮层和右键菜单替换为“地图标记”语义。
- `frontend/src/liveObservation.js`：将任务点状态、渲染、右键行为和轮询替换为按需标记管理。
- `frontend/src/liveObservation.css`：新增紧凑半透明标记表单、菜单与删除样式，移除旧任务点类。
- `frontend/test/live-observation-map.test.mjs`：更新静态行为断言。
- `shared/contracts/realtime_observation.md`、`shared/contracts/robot_control.md`、`shared/contracts/task_execution.md`：把旧任务点协议替换为手动标记协议，并记录 Backend/Web 消费者与 Mobile 非消费者。
- 删除 `autodrive_console/current_map_task_points.py`、`autodrive_console/task_start_navigation.py`、`tests/test_current_map_task_points.py`、`tests/test_task_start_navigation.py`。

### Task 1: 建立纯后端手动地图标记存储

**Files:**
- Create: `autodrive_console/manual_map_markers.py`
- Create: `tests/test_manual_map_markers.py`

**Interfaces:**
- Produces: `ManualMapMarker`, `ManualMapMarkerError`, `ManualMapMarkerStore`。
- `ManualMapMarker.public() -> dict[str, object]` 仅返回 `id`、`alias`、`x`、`y`、`yaw`。
- `ManualMapMarkerStore.list_for_map(map_id: str) -> list[dict[str, object]]`；`create(map_id: str, *, alias: object, x: object, y: object, yaw: object) -> dict[str, object]`；`resolve(map_id: str, marker_id: object) -> ManualMapMarker`；`remove(map_id: str, marker_id: object) -> None`。
- Consumed later by: `MapMarkerNavigationController` 和 `web_console.py`。

- [ ] **Step 1: 写出存储的失败测试**

```python
def test_create_normalizes_yaw_and_isolates_map_records(tmp_path: Path) -> None:
    store = ManualMapMarkerStore(tmp_path / "live_map_markers.json")

    created = store.create("a" * 16, alias="  电梯厅待命点  ", x=12.4, y=-5.8, yaw=math.tau + 0.25)

    assert created == {
        "id": created["id"], "alias": "电梯厅待命点", "x": 12.4, "y": -5.8, "yaw": pytest.approx(0.25),
    }
    assert store.list_for_map("a" * 16) == [created]
    assert store.list_for_map("b" * 16) == []
    raw = json.loads((tmp_path / "live_map_markers.json").read_text(encoding="utf-8"))
    assert raw["schema"] == 1
    assert raw["markers"][0]["map_id"] == "a" * 16
    assert "map_path" not in json.dumps(raw, ensure_ascii=False)


@pytest.mark.parametrize("kwargs", [
    {"alias": "", "x": 0, "y": 0, "yaw": 0},
    {"alias": "x" * 49, "x": 0, "y": 0, "yaw": 0},
    {"alias": "点", "x": float("nan"), "y": 0, "yaw": 0},
    {"alias": "点", "x": 0, "y": 100001, "yaw": 0},
    {"alias": "点", "x": 0, "y": 0, "yaw": 10001},
])
def test_create_rejects_invalid_operator_input(tmp_path: Path, kwargs: dict[str, object]) -> None:
    with pytest.raises(ManualMapMarkerError):
        ManualMapMarkerStore(tmp_path / "markers.json").create("a" * 16, **kwargs)
```

另加三个独立测试：无文件首次读取返回空列表；`remove` 后配置不再包含该 ID；同图创建 501 个标记时第 501 个抛出 `ManualMapMarkerError("当前地图标记数量已达上限")`。使用一个预置坏 JSON 的测试，确认读取时跳过坏记录而保留同文档中有效记录。

- [ ] **Step 2: 运行测试，确认实现尚不存在**

Run: `pixi run pytest tests/test_manual_map_markers.py -q`\
Expected: FAIL，原因是 `autodrive_console.manual_map_markers` 尚不存在。

- [ ] **Step 3: 以最小实现满足模型与写入边界**

```python
@dataclass(frozen=True)
class ManualMapMarker:
    id: str
    map_id: str
    alias: str
    x: float
    y: float
    yaw: float

    def public(self) -> dict[str, object]:
        return {"id": self.id, "alias": self.alias, "x": self.x, "y": self.y, "yaw": self.yaw}


class ManualMapMarkerStore:
    SCHEMA = 1
    MAX_PER_MAP = 500

    def create(self, map_id: str, *, alias: object, x: object, y: object, yaw: object) -> dict[str, object]:
        marker = ManualMapMarker(secrets.token_urlsafe(12), self._map_id(map_id), self._alias(alias),
                                 self._coordinate(x, "x"), self._coordinate(y, "y"), self._yaw(yaw))
        with self._lock:
            markers = self._load_locked()
            if sum(item.map_id == marker.map_id for item in markers) >= self.MAX_PER_MAP:
                raise ManualMapMarkerError("当前地图标记数量已达上限")
            markers.append(marker)
            self._save_locked(markers)
        return marker.public()
```

用私有 `_load_locked()` 将 JSON 解析为有效 `ManualMapMarker` 元组；不得让单条坏记录阻塞其余有效记录。用私有 `_save_locked()` 以同目录临时文件、`json.dump(..., ensure_ascii=False, separators=(",", ":"))`、`flush()`、`os.fsync()` 和 `os.replace()` 写入；在删除路径中复用它。`resolve` 和 `remove` 都先验证 16 位十六进制 `map_id`，仅匹配该地图的 ID，否则抛出 `ManualMapMarkerError("地图标记不存在或不属于当前地图")`。不使用 `Path.rglob`、`os.walk`、`task_directory` 或任何任务模块导入。

- [ ] **Step 4: 运行存储测试，确认通过**

Run: `pixi run pytest tests/test_manual_map_markers.py -q`\
Expected: PASS。

- [ ] **Step 5: 检查不意外引入任务扫描依赖**

Run: `rg -n "task_directory|os\.walk|rglob|current_map_task_points" autodrive_console/manual_map_markers.py`\
Expected: 无匹配输出。

### Task 2: 暴露严格验证的内部地图 ID，并迁移受控 Nav2 控制器

**Files:**
- Modify: `autodrive_console/observation.py:277-326`
- Create: `autodrive_console/map_marker_navigation.py`
- Create: `tests/test_map_marker_navigation.py`
- Delete: `autodrive_console/task_start_navigation.py`
- Delete: `tests/test_task_start_navigation.py`

**Interfaces:**
- Consumes: `ManualMapMarkerStore.resolve(map_id, marker_id)` 和 `ManualMapMarker` 的有限 `x/y/yaw`。
- Produces: `ObservationManager.active_manual_map_id() -> str | None` 与 `ObservationManager.verify_active_manual_map_id(candidate_map_id: str) -> tuple[bool, str]`；`MapMarkerNavigationController.begin_marker(marker_id: str) -> dict[str, object]`、`status()`、`cancel()`、`blocks_runs()`。
- `verify_active_manual_map_id` 必须调用现有 map_server YAML + OccupancyGrid 严格验证链路，不能只比较缓存 ID。
- Consumed later by: `web_console.py` 的路由、运行/车辆控制互斥守卫。

- [ ] **Step 1: 写出活动地图 ID 与二次校验的失败测试**

在 `tests/test_live_observation_realtime.py` 的 `ObservationManager` 现有 map-server 测试附近新增：

```python
def test_active_manual_map_id_only_exists_after_strict_live_layer_match(manager: ObservationManager) -> None:
    manager._active_task_map = ("a" * 16, Path("/opt/ry/maps/a.yaml"))
    with patch.object(manager, "active_map_id", return_value="a" * 16):
        assert manager.active_manual_map_id() == "a" * 16
    with patch.object(manager, "active_map_id", return_value="b" * 16):
        assert manager.active_manual_map_id() is None
```

在新 `tests/test_map_marker_navigation.py` 使用假实现：

```python
class _Observation:
    def active_manual_map_id(self): return "a" * 16
    def verify_active_manual_map_id(self, map_id):
        self.checked.append(map_id)
        return (map_id == "a" * 16, "当前地图匹配")

def test_begin_rechecks_current_map_before_sending_goal() -> None:
    observation = _Observation()
    transport = _Transport()
    controller = MapMarkerNavigationController(_MarkerStore(), observation, _Vehicle(), _Localization(),
                                               active_run_guard=lambda: False, transport=transport)

    snapshot = controller.begin_marker("opaque")

    assert snapshot["phase"] == "navigating"
    assert observation.checked == ["a" * 16, "a" * 16]
    assert transport.goals == [("map", -6.0, 5.0, 1.2)]
```

另加测试覆盖：活动运行、非 `navigation` 控制源、急停、定位异常、手动会话、重定位占用均拒绝；地图 ID 在第二次确认时变化不发送 Goal；导航结果成功/失败；状态变化自动取消；300 秒超时自动取消；传输异常不泄露 ROS 原始异常；控制器源文件不包含 `task_directory`、`Path(` 或任务点索引导入。

- [ ] **Step 2: 运行定向测试，确认失败**

Run: `pixi run pytest tests/test_live_observation_realtime.py tests/test_map_marker_navigation.py -q`\
Expected: FAIL，原因是新增方法与 `map_marker_navigation` 尚不存在。

- [ ] **Step 3: 抽取 ObservationManager 的严格地图确认辅助方法**

```python
def active_manual_map_id(self) -> str | None:
    active_id = self.active_map_id()
    with self._lock:
        verified = self._active_task_map
    if active_id is None or verified is None or verified[0] != active_id:
        return None
    return verified[0]

def verify_active_manual_map_id(self, candidate_map_id: str) -> tuple[bool, str]:
    active_id = self.active_manual_map_id()
    if active_id is None or candidate_map_id != active_id:
        return False, "当前地图不匹配"
    # 复用现有 _map_server_yaml_path、_cached_asset、_map_server_asset 的几何核验；
    # 唯一接受条件还包括 map_server YAML 等于 _active_task_map 中保存的 YAML。
```

将 `verify_active_task_map` 的共同严格验证内容收为一个私有方法，例如 `_verify_live_map_locked(expected_id: str, expected_yaml: Path) -> tuple[bool, str]`，供新旧方法内部调用；本任务完成时旧任务点文件将删除，保留旧公开方法没有必要时一并移除。`live_layers()` 对不匹配和 metadata-only 回退继续清空 `_active_task_map`，保证新 API 在未确认图上 fail closed。

- [ ] **Step 4: 用手动标记重建控制器，不改变安全状态机**

```python
class MapMarkerNavigationController:
    ACTIVE_PHASES = frozenset({"checking", "navigating", "cancelling"})
    MAX_DURATION_S = 300.0

    def begin_marker(self, marker_id: str) -> dict[str, object]:
        with self._lock:
            if self._phase in self.ACTIVE_PHASES:
                raise MapMarkerNavigationConflict("前往地图标记正在进行")
            self._phase, self._detail = "checking", "正在核验地图标记与车辆状态"
        try:
            self._require_safe_to_begin()
            map_id = self._require_active_map_id()
            marker = self._marker_store.resolve(map_id, marker_id)
            self._require_current_map(map_id)
            self._require_safe_to_begin()
            self._require_current_map(map_id)
            handle = self._transport.send_goal("map", marker.x, marker.y, marker.yaw, self._on_result)
            if handle is None:
                raise MapMarkerNavigationUnavailable("导航服务未接受目标")
        except ManualMapMarkerError as exc:
            self._fail(str(exc))
            raise MapMarkerNavigationConflict(str(exc)) from exc
```

从旧控制器保留 `_RosNavigateToPoseTransport`，但重命名其 ROS Node 为 `ry_aletheia_map_marker_navigation`。所有用户文案改为“地图标记”：空闲说明“可右键同图地图标记后前往”；成功“已到达地图标记”；超时“前往地图标记超时”；日志只记录状态和标记 ID，不记录别名、坐标、路径或 ROS 详情。`_check_timeout_locked()` 在轮询状态时仍重新调用 `_require_safe_to_begin()` 与 `_require_current_map(self._map_id)`，任一失败即请求取消现有 Goal。删除旧控制器和旧测试，保证代码没有任务文件依赖。

- [ ] **Step 5: 运行 Observation 与导航测试，确认通过**

Run: `pixi run pytest tests/test_live_observation_realtime.py tests/test_map_marker_navigation.py -q`\
Expected: PASS。

### Task 3: 替换 HTTP 装配、路由与错误响应

**Files:**
- Modify: `web_console.py:20-45, 180-193, 632-640, 1260-1330`
- Modify: `tests/test_offline_modules.py:1942-1953`

**Interfaces:**
- Consumes: `ManualMapMarkerStore(CONFIG_DIR / "live_map_markers.json")`、`ObservationManager.active_manual_map_id()`、`MapMarkerNavigationController`。
- Produces: `GET/POST /api/observation/map-markers`、`POST /api/observation/map-markers/remove`、`GET/POST /api/observation/map-marker-navigation`。
- Removes: 所有 `/api/observation/task-points` 与 `/api/observation/task-point-navigation*` 路由、全局和异常类型。
- Consumed later by: PC Web 任务 4。

- [ ] **Step 1: 写出 HTTP 接口的失败测试**

在 `tests/test_offline_modules.py` 将旧静态检查替换为：

```python
def test_manual_map_marker_routes_use_backend_owned_map_identity(self):
    observation = Path("shared/contracts/realtime_observation.md").read_text(encoding="utf-8")
    console = Path("web_console.py").read_text(encoding="utf-8")

    assert "/api/observation/map-markers" in console
    assert "/api/observation/map-marker-navigation/begin" in console
    assert 'set(data) != {"alias", "x", "y", "yaw"}' in console
    assert 'set(data) != {"id"}' in console
    assert "/api/observation/task-points" not in console
    assert "task-point-navigation" not in console
    assert "map_id" not in observation.split("## PC 手动地图标记", 1)[1].split("##", 1)[0]
```

在现有 Handler 单元测试风格中补充 mock 测试：当前地图未确认时 `GET /map-markers` 返回 `{map_ready: false, points: []}`；创建请求只将 `alias/x/y/yaw` 传给存储器；请求含 `map_id` 返回 409；删除和 begin 只接收 `{id}`；`MapMarkerNavigationConflict` 返回 409 并附当前导航 status，`MapMarkerNavigationUnavailable` 返回 503。

- [ ] **Step 2: 运行定向后端接口测试，确认失败**

Run: `pixi run pytest tests/test_offline_modules.py -k "map_marker" -q`\
Expected: FAIL，因为新路由和新控制器尚未装配。

- [ ] **Step 3: 装配存储器、严格地图门与新路由**

```python
MAP_MARKERS = ManualMapMarkerStore(CONFIG_DIR / "live_map_markers.json")
MAP_MARKER_NAVIGATION = MapMarkerNavigationController(
    MAP_MARKERS, OBSERVATION, VEHICLE_CONTROL, LOCALIZATION_STATUS,
    active_run_guard=RUNS.has_active_run,
)
RUNS.set_task_start_navigation_guard(MAP_MARKER_NAVIGATION.blocks_runs)
VEHICLE_CONTROL.set_task_start_navigation_guard(MAP_MARKER_NAVIGATION.blocks_runs)

def _active_manual_map_id_or_none() -> str | None:
    return OBSERVATION.active_manual_map_id()
```

`GET /api/observation/map-markers` 在 ID 缺失时返回 `{"map_ready": False, "points": []}`，否则返回 `{"map_ready": True, "points": MAP_MARKERS.list_for_map(map_id)}`。创建/删除的 POST 都先取得 ID，缺失时抛 `ValueError("当前地图尚未确认")`；创建严格要求 `{"alias", "x", "y", "yaw"}`，删除严格要求 `{"id"}`，每个请求体按 2–16 KiB 限制读取。成功创建和删除调用 `LOGGER.info("地图标记已创建：id=%s", point["id"])` / `LOGGER.info("地图标记已删除：id=%s", marker_id)`，不记录别名/坐标。

把导航路由替换为 `/api/observation/map-marker-navigation`、`/begin`、`/cancel`，并将 `TaskStartNavigation*` except 子句替换成 `MapMarkerNavigation*`。保留 `RUNS`、`VEHICLE_CONTROL` 的守卫接入，不能因为更名失去互斥。

- [ ] **Step 4: 运行接口和受影响后端回归测试，确认通过**

Run: `pixi run pytest tests/test_offline_modules.py -k "map_marker or manual_map" -q`\
Expected: PASS。

Run: `pixi run pytest tests/test_manual_map_markers.py tests/test_map_marker_navigation.py tests/test_live_observation_realtime.py -q`\
Expected: PASS。

### Task 4: 将 PC 实时页改为按需手动地图标记界面

**Files:**
- Modify: `frontend/live-observation.html:136-170`
- Modify: `frontend/src/liveObservation.js:148-152, 528-625, 1700-1715, 2299-2400, 2870-2880, 3168-3275`
- Modify: `frontend/src/liveObservation.css:335-344`
- Modify: `frontend/test/live-observation-map.test.mjs:247-260`

**Interfaces:**
- Consumes: `GET/POST /api/observation/map-markers`、`POST /remove`、`GET/POST /api/observation/map-marker-navigation*`。
- Produces: “地图标记”图层、`添加标记`浮层、输入验证、右键前往/删除菜单和非轮询刷新流程。
- Removes: `taskPoints*`、`taskPointStatusTimer`、旧任务起终点的分类/分组渲染和 5 秒标记轮询。

- [ ] **Step 1: 写出 PC 静态行为失败测试**

将 `frontend/test/live-observation-map.test.mjs` 中旧测试替换为：

```js
test("desktop map uses an on-demand manual marker layer", () => {
  const page = readFileSync(pagePath, "utf8");
  const source = readFileSync(observationPath, "utf8");
  const stylesheet = readFileSync(stylesheetPath, "utf8");

  assert.match(page, /id="mapMarkersVisible" type="checkbox" checked/);
  assert.match(page, />地图标记</);
  assert.match(page, /id="mapMarkerCreateToggle"/);
  assert.match(page, /id="mapMarkerAlias"/);
  assert.match(source, /function renderMapMarkers\(/);
  assert.match(source, /function openMapMarkerMenu\(/);
  assert.match(source, /"\/api\/observation\/map-markers"/);
  assert.match(source, /map-marker-navigation\/begin/);
  assert.doesNotMatch(source, /setInterval\([\s\S]*?refreshMapMarkers/);
  assert.doesNotMatch(source, /task-points|task-point-navigation/);
  assert.match(stylesheet, /\.map-marker-menu/);
  assert.match(stylesheet, /\.map-marker-form/);
  assert.match(stylesheet, /prefers-reduced-motion/);
});
```

另加断言确认 `refreshMapMarkers()` 只从成功 `live_layers` 回调、图层重新开启以及保存/删除成功后调用，而不是从心跳计时器调用；确认页面未包含“任务起终点”“任务起点”“任务终点”。

- [ ] **Step 2: 运行前端测试，确认失败**

Run: `node --test frontend/test/live-observation-map.test.mjs`\
Expected: FAIL，因为页面仍使用任务起终点元素和旧端点。

- [ ] **Step 3: 改造 HTML 为小型表单与上下文菜单**

将图层 checkbox 换为 `id="mapMarkersVisible"` 和文本“地图标记”。在 `relocalization-control` 相邻位置新增独立、默认收起的控件，避免与手动重定位业务合并：

```html
<div class="map-marker-control" id="mapMarkerControl">
  <button id="mapMarkerCreateToggle" class="map-marker-toggle" type="button" aria-expanded="false" aria-controls="mapMarkerForm">
    <span aria-hidden="true">＋</span><span>添加标记</span>
  </button>
  <section id="mapMarkerForm" class="map-marker-form" aria-label="添加地图标记" hidden>
    <label>名称<input id="mapMarkerAlias" maxlength="48" autocomplete="off" /></label>
    <div class="map-marker-coordinate-grid">
      <label>X（米）<input id="mapMarkerX" inputmode="decimal" /></label>
      <label>Y（米）<input id="mapMarkerY" inputmode="decimal" /></label>
      <label>yaw（弧度）<input id="mapMarkerYaw" inputmode="decimal" /></label>
    </div>
    <small id="mapMarkerFormDetail">标记只保存到当前已确认地图。</small>
    <div><button id="mapMarkerSave" type="button">保存标记</button><button id="mapMarkerCancel" type="button">取消</button></div>
  </section>
</div>
<section id="mapMarkerMenu" class="map-marker-menu" aria-label="地图标记操作" hidden>
  <p id="mapMarkerMenuLabel">地图标记</p>
  <button id="mapMarkerNavigate" type="button">前往此标记</button>
  <button id="mapMarkerRemove" type="button">删除标记</button>
  <small id="mapMarkerMenuDetail">将由后端再次核验地图和车辆状态</small>
</section>
```

所有 id 名称与后续 JS 完全一致；取消按钮 `type="button"`，不使用 HTML form submit。

- [ ] **Step 4: 以按需请求替换旧任务点状态与轮询**

将 `taskPointsVisible/taskPoints/selectedTaskPoint/taskPointStatusTimer/taskPointNavigationStatus` 改为 `mapMarkersVisible/mapMarkers/selectedMapMarker/mapMarkerNavigationStatus`。实现：

```js
async function refreshMapMarkers() {
  if (mobileConsoleEnabled() || !mapMarkersVisible) return;
  const generation = mapGeneration;
  const activeMapId = requestedActiveMapId;
  const snapshot = await request("/api/observation/map-markers");
  if (generation !== mapGeneration || activeMapId !== requestedActiveMapId) return;
  mapMarkers = snapshot.map_ready === true && Array.isArray(snapshot.points)
    ? snapshot.points.filter(isValidMapMarker)
    : [];
  renderMapMarkers();
  scheduleMapDraw();
}
```

`isValidMapMarker` 只接收字符串 ID/别名和有限 `x/y/yaw`。网络失败时若地图代际仍相同，清空当前标记并重绘；不得启动重试定时器。`refreshMapMarkerNavigationStatus()` 初次加载和每次开始/取消操作后请求一次；仅在 `can_cancel === true` 时以 1 秒有限状态轮询更新，终态立即 `clearInterval`，它不得调用 `refreshMapMarkers()`。

实现保存与删除：保存将输入原样解析成 Number，客户端只检查非空和 `Number.isFinite`，把 `{alias, x, y, yaw}` POST 给后端；成功后关闭浮层、清空输入、调用 `refreshMapMarkers()`。删除必须先 `window.confirm(\`确认删除地图标记“${marker.alias}”？\`)`，再 POST `{id}`；成功后关闭菜单并刷新。错误写入 `mapMarkerFormDetail` 或 `mapMarkerMenuDetail`，保留操作上下文。

`setupMapMarkerLayer()` 监听按钮、Escape、视口 resize 和菜单按键，但不创建旧的 5 秒点位定时器。图层重新开启时调用 `refreshMapMarkers()`；`refreshActiveMap()` 开始新 map generation 时清空 `mapMarkers`、关闭表单和菜单。将 `scheduleLiveWallCompensation()` 在严格 `matched` 成功分支中的旧 `refreshTaskPoints()` 改为 `refreshMapMarkers()`；这是成功地图确认后的唯一自动读取点。

- [ ] **Step 5: 用单一、低干扰符号渲染与命中手动标记**

把 `renderTaskPoints()`/`taskPointAtViewportPoint()` 改为 `renderMapMarkers()`/`mapMarkerAtViewportPoint()`。每个记录独立渲染，不按起终点合并：

```js
const marker = new Graphics();
marker.circle(x, y, radius + 1.5).fill({ color: 0xffffff, alpha: 0.9 });
marker.circle(x, y, radius).fill({ color: 0x2486d7, alpha: 0.94 });
marker.poly([x, y - radius * 0.55, x + radius * 0.55, y, x, y + radius * 0.55, x - radius * 0.55, y])
  .fill({ color: 0xe7f3fb, alpha: 0.96 });
```

右键命中半径为 16 CSS 像素，仅在没有手动重定位预览时处理；空白右键关闭菜单，左键开始拖图时关闭菜单。上下文菜单显示 `marker.alias`，前往确认文字为 `确认让车辆自动前往“${marker.alias}”？`；导航中按钮改为“取消导航”。永久不绘制别名文本，避免覆盖密集地图。

- [ ] **Step 6: 用克制的半透明 CSS 加入表单和危险操作层级**

将旧 `.task-point-menu` 替换为 `.map-marker-menu`，并新增 `.map-marker-control`、`.map-marker-toggle`、`.map-marker-form`、`.map-marker-coordinate-grid`。复用现有实时页的 12px 圆角、`backdrop-filter: blur(16px) saturate(135%)`、细蓝灰边框与浅色主题覆盖；表单最大宽度 238px，输入高度不超过 30px，按钮最小高度 29px。`#mapMarkerRemove` 使用透明红色边框/文字，hover 才加强，不能与蓝色“前往”竞争视觉权重。补齐 `body.theme-light` 和 `html.mobile-console` 隐藏规则；在 `prefers-reduced-motion` 下不使用新增连续动画。

- [ ] **Step 7: 运行前端测试与构建检查，确认通过**

Run: `node --test frontend/test/live-observation-map.test.mjs`\
Expected: PASS。

Run: `pixi run frontend-check`\
Expected: PASS，Vite 产物只在临时构建目录产生，不纳入版本控制。

### Task 5: 同步跨端契约、清理遗留项并完成回归验证

**Files:**
- Modify: `shared/contracts/realtime_observation.md:46-61,77`
- Modify: `shared/contracts/robot_control.md` 的受控导航相关描述（如存在“任务点”术语）
- Modify: `shared/contracts/task_execution.md:16-22`
- Modify: `docs/backend/README.md`、`USER_GUIDE.md` 中所有实时页任务起终点说明（若 `rg` 找到）
- Delete: `autodrive_console/current_map_task_points.py`
- Delete: `tests/test_current_map_task_points.py`
- Verify: 所有任务 1–4 涉及文件

**Interfaces:**
- Consumes: 已实现的 `map-markers` 与 `map-marker-navigation` API。
- Produces: 与代码一致的 Backend/PC Web/Mobile 消费者记录和安全边界说明。

- [ ] **Step 1: 写出契约防回归失败断言**

在 `tests/test_offline_modules.py` 加入：

```python
def test_manual_marker_contract_has_no_task_directory_discovery(self):
    contract = Path("shared/contracts/realtime_observation.md").read_text(encoding="utf-8")

    section = contract.split("## PC 手动地图标记", 1)[1].split("##", 1)[0]
    assert "/api/observation/map-markers" in section
    assert "/api/observation/map-marker-navigation/begin" in section
    assert "任务目录" not in section
    assert "map_path" not in section
    assert "Mobile 不是" in section
    assert "300 秒" in section
```

- [ ] **Step 2: 运行契约断言，确认它在文档更新前失败**

Run: `pixi run pytest tests/test_offline_modules.py -k "manual_marker_contract" -q`\
Expected: FAIL，因为新章节尚不存在。

- [ ] **Step 3: 更新契约和用户可见文字**

把 `realtime_observation.md` 第 46 节替换为“PC 手动地图标记与受控前往”，逐项记录：三个标记端点、三个导航端点、16 KiB、隐私字段、严格地图绑定、500 条上限、输入范围、创建/删除、PC-only、无扫描、二次确认、300 秒、取消与工具日志。把第 77 节的“任务起终点”层改成“地图标记”层，并保留图层顺序。

把 `task_execution.md` 的标题和正文改为“受控地图标记前往与执行互斥”，将控制器名改为 `MapMarkerNavigationController`，明确它不属于任务执行、不会读取任务文件、不能与任一活动运行并行。`robot_control.md` 中如有同义术语，同样替换为“地图标记前往”，并明确它不切换控制源。`docs/backend/README.md` 和 `USER_GUIDE.md` 仅在确有旧术语时做最小同义更新；不引入与实现不符的流程。

- [ ] **Step 4: 删除旧扫描实现，并确认仓库无残留 API/文案**

Run: `rg -n "current_map_task_points|task_start_navigation|/api/observation/task-points|task-point-navigation|任务起终点|前往任务起点" autodrive_console frontend tests shared/contracts docs USER_GUIDE.md`\
Expected: 无实现、测试、契约或页面残留；历史设计/计划文档可保留，不作为运行代码消费者。

使用 `apply_patch` 删除本任务列出的旧模块和旧测试；不要删除历史设计/计划文档，也不要删除用户工作区中无关的未跟踪内容。

- [ ] **Step 5: 运行完整受影响验证并记录结果**

Run: `scripts/test-backend.sh`\
Expected: PASS。

Run: `scripts/test-web.sh`\
Expected: PASS。

Run: `git diff --check`\
Expected: 无输出、退出码 0。

Run: `git status --short`\
Expected: 仅人工审阅本任务改动；不暂存或修改不属于本计划的现有脏文件。

## Self-Review

1. **规格覆盖：** 任务 1 覆盖持久化、输入限制、原子写入、地图隔离和无扫描；任务 2 覆盖严格地图身份与全部 Nav2 安全状态机；任务 3 覆盖 API、大小限制、日志和运行/车辆守卫；任务 4 覆盖 PC 表单、图层、右键前往/删除、非轮询、视觉层级与地图切换；任务 5 覆盖契约、用户术语、遗留代码清理和完整验证。移动端不变与不部署要求在全局约束明确。
2. **占位检查：** 本计划没有未决占位、延后实现说明或笼统错误处理描述。每项实现步骤列出精确接口、字段、文件和命令。
3. **类型一致性：** 存储器统一使用 `map_id` 作为仅后端内部参数、公开记录统一为 `id/alias/x/y/yaw`；控制器入口统一为 `begin_marker(marker_id)`；HTTP 与前端统一为 `map-markers` 和 `map-marker-navigation`；前端状态统一为 `mapMarkers*`。
