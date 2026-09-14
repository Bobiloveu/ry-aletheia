# 共享物理电梯 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 让一个部署项目中的同一部物理电梯可关联多个地图落点，并保持现有室内电梯实验任务编译产物正确、可追溯且不触碰机器人运行时目录。

**Architecture:** 项目文档新增 physical_elevators 保存唯一电梯编号、协议和服务楼层范围；地图上的 kind: "elevator" 组件成为只保存几何、候梯距离和门朝向的落点，并通过 physical_elevator_id 引用共享实体。Store 在读取旧项目时迁移遗留副本；编译器优先消费新关系，纯旧夹具保留原有兼容配对逻辑。

**Tech Stack:** Python 3、Pytest、http.server HTTP 边界、原生 HTML/CSS/JavaScript、Vite Web 检查。

**Spec:** docs/superpowers/specs/2026-09-05-shared-physical-elevator-design.md

## Global Constraints

- 浏览器只能调用部署 HTTP API，不能直接访问 ROS Topic。
- 只修改部署控制台及必要测试；不写入 /opt/ry 运行时任务、行为树或定位目录。
- 速度模式、既有行为树名称和已批准的四子任务顺序保持不变。
- elevator_id 在同一个部署项目内唯一且稳定。
- 同一物理电梯的每个地图落点必须独立保存 yaw，该值就是本层电梯门方向。
- 不提交地图、日志、缓存、构建产物或用户已有的无关修改。

---

### Task 1: 项目级物理电梯模型与旧项目迁移

**Files:**
- Modify: autodrive_console/deployment.py:45-285, 717-985
- Test: tests/test_deployment.py:124-221

**Interfaces:**
- Produces: project["physical_elevators"]: list[dict[str, Any]]；每项为 {"id", "elevator_id", "elevator_protocol", "min_floor", "max_floor"}。
- Produces: 每个电梯地图组件的 attributes["physical_elevator_id"]。
- Consumes: component_templates["elevator_protocols"] 和既有电梯组件属性。

- [ ] **Step 1: 写迁移与唯一性失败测试**

在 tests/test_deployment.py 添加两个测试：第一个构造两个 elevator_id == "10014" 的旧组件，调用 store.get() 后断言项目只有一个物理电梯、两个组件引用同一 physical_elevator_id，且本地 yaw 和 wait_distance_m 未变化；第二个先创建编号 10014 的物理电梯，再创建同编号，断言抛出 DeploymentError("电梯编号已存在")。

~~~
loaded = store.get(project["id"])
assert len(loaded["physical_elevators"]) == 1
assert {item["attributes"]["physical_elevator_id"] for item in loaded["components"] if item["kind"] == "elevator"} == {loaded["physical_elevators"][0]["id"]}
with pytest.raises(DeploymentError, match="电梯编号已存在"):
    store.add_physical_elevator(project["id"], {
        "elevator_id": "10014", "elevator_protocol": "bluetooth",
        "min_floor": 1, "max_floor": 15,
    })
~~~

- [ ] **Step 2: 运行测试，确认按预期失败**

Run: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. pixi run pytest tests/test_deployment.py -q

Expected: FAIL，原因是 physical_elevators 尚不存在且 add_physical_elevator 未定义。

- [ ] **Step 3: 实现规范化、迁移和共享实体校验**

在 DeploymentStore.create() 的初始文档加入 "physical_elevators": []；在 get() 确保该字段为 list，并提取 _normalise_physical_elevators()：

~~~
def _normalise_physical_elevators(self, document: dict[str, Any]) -> bool:
    # 返回是否迁移；按 legacy attributes.elevator_id 创建实体，
    # 为 component.attributes 写 physical_elevator_id。
    # 对相同编号的 protocol/min/max 不一致记录 deterministic conflict，
    # 不覆盖任一来源值。
~~~

新增 _normalise_physical_elevator(data, templates)，校验非空、至多 64 字符的编号，项目内唯一编号，存在于项目协议模板的协议，以及 -20 <= min <= max <= 120。

新增 add_physical_elevator(project_id, data)、update_physical_elevator(project_id, id, data) 和 delete_physical_elevator(project_id, id)。删除时若任一组件仍引用该 ID，抛出 DeploymentError("物理电梯仍有地图落点")。迁移冲突在实体中以 migration_conflict 保存可读原因，供 Task 3 编译校验使用。

把电梯组件属性规范化改为本地字段：width_m、height_m、wait_distance_m、physical_elevator_id。只有迁移路径保留 elevator_id、elevator_protocol、min_floor、max_floor、map_floor 和 physical_floor；新的落点不得把这些字段作为可编辑来源。

- [ ] **Step 4: 运行测试，确认通过**

Run: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. pixi run pytest tests/test_deployment.py -q

Expected: PASS，包括新迁移和唯一性测试。

- [ ] **Step 5: 提交该独立后端模型改动**

~~~
git add autodrive_console/deployment.py tests/test_deployment.py
git commit -m "feat: model shared physical elevators"
~~~

### Task 2: 落点创建、编辑和协议引用保护

**Files:**
- Modify: autodrive_console/deployment.py:717-835
- Test: tests/test_deployment.py:198-221

**Interfaces:**
- Consumes: add_component(project_id, {"kind": "elevator", "attributes": {"physical_elevator_id": id, "wait_distance_m": 1.5}})。
- Produces: 带有效 physical_elevator_id 的电梯落点；非电梯组件 API 行为不变。
- Produces: remove_component_protocol() 能识别 physical_elevators[*].elevator_protocol。

- [ ] **Step 1: 写电梯落点关联失败测试**

添加测试：创建 10014 共享实体；用其 ID 在两张地图各放一个电梯落点，断言可以保存且两条 yaw 不同；传入未知 ID 时断言错误为“物理电梯不存在”；尝试删除其使用中的协议时断言错误；用含落点的共享电梯调用删除时断言错误。

~~~
landing = store.add_component(project_id, {
    "map_id": second_map["id"], "kind": "elevator", "x": 1.0, "y": 1.0,
    "yaw": pi, "attributes": {"physical_elevator_id": elevator["id"]},
})
assert landing["attributes"]["physical_elevator_id"] == elevator["id"]
assert landing["yaw"] == pi
~~~

- [ ] **Step 2: 运行测试，确认按预期失败**

Run: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. pixi run pytest tests/test_deployment.py -q

Expected: FAIL，新的组件关联会被旧属性规则忽略或未知 ID 未被拒绝。

- [ ] **Step 3: 让组件 API 只管理落点本地信息**

修改 add_component() 和 update_component()：当 kind == "elevator" 时，必须解析并验证 physical_elevator_id，不得用组件请求覆盖共享协议/服务楼层；只保存尺寸、候梯距离和 yaw。保留生成 Waypoint 的稳定 ID 更新机制。

修改 remove_component_protocol()，除了组件的旧属性之外，还必须检查 document["physical_elevators"] 的 elevator_protocol。修改 delete_component()：删除电梯落点仅删除组件及其生成点，不删除共享实体。

- [ ] **Step 4: 运行测试，确认通过**

Run: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. pixi run pytest tests/test_deployment.py -q

Expected: PASS，落点能关联、未知关联与危险删除被拒绝。

- [ ] **Step 5: 提交该独立 Store 行为改动**

~~~
git add autodrive_console/deployment.py tests/test_deployment.py
git commit -m "feat: validate physical elevator landings"
~~~

### Task 3: HTTP 边界与室内电梯编译器的共享实体解析

**Files:**
- Modify: web_console.py:590-670, 1270-1325
- Modify: autodrive_console/task_compiler.py:50-390
- Test: tests/test_deployment.py:458-555
- Test: tests/test_task_compiler.py:39-145, 182-240

**Interfaces:**
- Produces: POST /api/deployments/<project>/physical-elevators、POST /api/deployments/<project>/physical-elevators/<id> 和 DELETE /api/deployments/<project>/physical-elevators/<id>。
- Consumes: 带 physical_elevators 和电梯落点 physical_elevator_id 的项目文档。
- Produces: compile_indoor_elevator() 对 Store 项目使用共享 ID 配对，对纯 legacy 输入仍按 elevator_id 兼容配对。

- [ ] **Step 1: 写 HTTP 与编译器失败测试**

在 tests/test_deployment.py 模仿已有 component handler 测试，断言新建物理电梯路由把精确 project ID 和 JSON 传给 DEPLOYMENTS.add_physical_elevator()，并将 DeploymentError 映射为 400。

在 tests/test_task_compiler.py 修改两地图夹具，使两落点各有不同 yaw、同一个 physical_elevator_id，共享实体编号为 10014。断言：

~~~
assert preview.derived_points["lobby_wait"] != preview.derived_points["target_wait"]
assert 'output_key="origin_floor" value="2"' in inbound
assert 'output_key="origin_floor" value="16"' in returned_inbound
~~~

另加一个测试令两个落点关联不同实体，断言 CompilationError 包含“同一物理电梯”；再加一个 migration_conflict 实体测试，断言预览明确拒绝。

- [ ] **Step 2: 运行测试，确认按预期失败**

Run: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. pixi run pytest tests/test_deployment.py tests/test_task_compiler.py -q

Expected: FAIL，HTTP 路由和以 physical_elevator_id 配对的编译逻辑尚不存在。

- [ ] **Step 3: 实现 HTTP 路由和编译器解析**

在 web_console.py 的现有部署 POST/DELETE 分支相邻位置加入三条物理电梯路由，复用 JSON 读取、unquote() 和 DeploymentError -> 400 模式。所有响应返回更新后的 project，不引入 ROS 调用。

在 task_compiler.py 添加 _physical_elevators(project) 和 _shared_elevator_pair(project, components, lobby_id, target_id)。对含共享数组的项目：

1. 要求两张阶段地图各只有一个电梯落点；
2. 要求两个 physical_elevator_id 相等、存在且没有 migration_conflict；
3. 从共享实体读取编号、协议、楼层服务范围；
4. 用对应 map_instances[*].floor 校验服务范围，并以 floor + 1 计算物理楼层；
5. 继续用各落点的 x/y/yaw/height_m/wait_distance_m 调用 _wait_point()。

无共享数组的纯旧输入继续调用当前 _elevator_pair() 和 _physical_floor()，使已有独立编译器调用不破坏。更新 _input_hash() 的输入，让共享实体变化必然使预览失效。

- [ ] **Step 4: 运行测试，确认通过**

Run: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. pixi run pytest tests/test_deployment.py tests/test_task_compiler.py -q

Expected: PASS，四子任务、速度模式、行为树文件名与物理楼层断言全部保持通过。

- [ ] **Step 5: 提交 API 与编译器改动**

~~~
git add web_console.py autodrive_console/task_compiler.py tests/test_deployment.py tests/test_task_compiler.py
git commit -m "feat: compile shared physical elevator landings"
~~~

### Task 4: 部署编辑器的关联已有电梯流程

**Files:**
- Modify: autodrive_console/web/deployment.html:343-400
- Modify: autodrive_console/web/deployment.js:90-185, 1503-1715, 1880-1918
- Modify: autodrive_console/web/deployment.css:component-popover rules
- Test: tests/test_deployment.py:562-618

**Interfaces:**
- Consumes: selectedProject.physical_elevators 和 Task 3 的 HTTP 路由。
- Produces: openElevatorLandingDialog(point)，在创建或关联实体后调用既有 /components 接口。
- Produces: 电梯快捷编辑只允许修改本地尺寸、候梯距离、朝向；共享字段只读显示并提供“编辑共享电梯”动作。

- [ ] **Step 1: 写页面结构与本地门方向的失败测试**

新增静态测试读取 HTML/JS/CSS，并断言存在 elevatorLandingDialog、中文“关联已有电梯”、中文“新建物理电梯”、physical_elevator_id 以及保留 drawElevatorDoorMarker(width, height) 与 context.rotate(-item.yaw || 0)。

~~~
assert 'id="elevatorLandingDialog"' in html
assert "关联已有电梯" in html
assert "physical_elevator_id" in source
assert "context.rotate(-item.yaw || 0);" in source
~~~

- [ ] **Step 2: 运行测试，确认按预期失败**

Run: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. pixi run pytest tests/test_deployment.py -q

Expected: FAIL，关联对话框和共享引用尚未出现在页面源码。

- [ ] **Step 3: 实现紧凑的落点关联对话框与快捷编辑**

在地图工作区添加符合现有 component-popover 样式的 elevatorLandingDialog：默认选择“关联已有电梯”；若项目没有实体，自动选“新建物理电梯”。关联模式提供下拉列表，以 elevator_id 为主标签，并以协议和服务楼层为次级说明；新建模式显示编号、协议、最小和最大服务楼层字段。

将 canvas 放置流程在 placementKind === "elevator" 时改为先打开该对话框而不立即创建组件。确认时：关联模式直接带 physical_elevator_id 调用 /components；新建模式先调用 /physical-elevators，成功后再创建落点。失败时保留对话框输入和待放置坐标，显示后端中文错误；成功后更新项目、选中落点并显示快捷编辑。

修改 COMPONENT_SPECS.elevator 和 renderComponentAttributes()：从可编辑字段移除编号、协议、最低/最高层和地图楼层；增加共享实体摘要（编号、协议、服务范围、当前地图逻辑/物理楼层）和一个显式“编辑共享电梯”入口。保持 yaw 输入、尺寸控制点、候梯距离和 drawElevatorDoorMarker() 不变。CSS 使用单列紧凑表单、清晰的模式切换和小屏回退，不新增分散的侧边卡片。

- [ ] **Step 4: 运行测试与 Web 检查，确认通过**

Run: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. pixi run pytest tests/test_deployment.py -q && ./scripts/test-web.sh

Expected: PASS；Vite check/build 成功，静态断言证明门方向仍依赖地图本地 yaw。

- [ ] **Step 5: 提交编辑器改动**

~~~
git add autodrive_console/web/deployment.html autodrive_console/web/deployment.js autodrive_console/web/deployment.css tests/test_deployment.py
git commit -m "feat: link elevator landings across maps"
~~~

### Task 5: 端到端回归、视觉核验与文档对齐

**Files:**
- Modify: docs/development/PROFILES.md:51-55
- Verify: tests/test_deployment.py
- Verify: tests/test_task_compiler.py

**Interfaces:**
- Consumes: Tasks 1-4 的 Store、HTTP、编辑器与编译器接口。
- Produces: 同一实体在两张地图有独立门方向、但生成同一部电梯任务的回归证据。

- [ ] **Step 1: 写端到端 Store 回归测试**

在 _compiler_ready_store() 的独立场景中：建立 10014、在大厅和目标层关联它，分别设定 yaw = 0 和 yaw = pi；保存小区和门牌后调用预览。断言四子任务顺序、批准的速度模式、两个派生候梯点方向相反、XML 的 origin_floor 分别是 2 与 16，以及导出仍只在项目拥有的实验目录。

- [ ] **Step 2: 运行端到端回归测试，确认完整路径通过**

Run: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. pixi run pytest tests/test_deployment.py tests/test_task_compiler.py -q

Expected: PASS；证明共享字段由物理实体读取、两个候梯点由本地 yaw 推导。

- [ ] **Step 3: 补充最小使用说明**

仅在既有组件任务编译器说明中补充三步：第一张地图新建物理电梯、后续楼层关联相同编号、每张地图分别确认门方向和候梯距离。明确说明该功能仍是实验预览，不会部署到机器人。

- [ ] **Step 4: 运行完整相关验证和 UI 规则检查**

Run:

~~~
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. pixi run pytest tests/test_deployment.py tests/test_task_compiler.py -q
./scripts/test-web.sh
node /home/bob/.codex/skills/impeccable/scripts/detect.mjs --json autodrive_console/web/deployment.html autodrive_console/web/deployment.js autodrive_console/web/deployment.css
git diff --check
~~~

Expected: 所有相关 Pytest 通过；Web 检查与构建通过；检测器无确定性违规；git diff --check 无输出。

- [ ] **Step 5: 手动核验两张地图的关联流程**

运行本地预览，创建临时部署项目：第一张图新建 10014 并旋转门方向；第二张图选择“关联已有电梯”并设置另一个门方向。确认第二层不重复输入协议和楼层范围，两个图标都有正确门标识，任务预览可生成，且项目目录以外没有新增运行时任务文件。

- [ ] **Step 6: 提交测试与文档收尾**

~~~
git add docs/development tests/test_deployment.py tests/test_task_compiler.py
git commit -m "docs: explain shared elevator deployment workflow"
~~~
