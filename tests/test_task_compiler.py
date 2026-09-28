from __future__ import annotations

import json
import re
import shutil
import zipfile
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from math import atan2, cos, isclose, pi, sin
from pathlib import Path
from xml.etree import ElementTree

import pytest

import autodrive_console.task_compiler as task_compiler_module
import autodrive_console.task_status_codes as task_status_codes_module
from autodrive_console.deployment import DeploymentStore
from autodrive_console.task_compiler import (
    CompilationError,
    bundle_zip,
    compile_indoor_elevator,
    compile_multi_task_points,
    compile_single_task_points,
)


TEMPLATE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "autodrive_console"
    / "task_templates"
    / "indoor_elevator_v1"
)
APPROVED_STATUS_TEMPLATES = (
    "start_task.xml",
    "task_complete.xml",
    "place_water.xml",
    "auto_cargo.xml",
    "elevator_in_n_x.xml",
    "elevator_in_x_n.xml",
    "elevator_out_n_x.xml",
    "elevator_out_x_n.xml",
    "close_elevdoor_n.xml",
    "close_elevdoor_x.xml",
    "components/gate_open_go.xml",
    "components/gate_close_go.xml",
    "components/gate_open_back.xml",
    "components/gate_close_back.xml",
    "components/auto_door_open_go.xml",
    "components/auto_door_close_go.xml",
    "components/auto_door_open_back.xml",
    "components/auto_door_close_back.xml",
)


def _template(name: str) -> str:
    return (TEMPLATE_ROOT / name).read_text(encoding="utf-8")


def _status_tokens(text: str) -> list[str]:
    return [
        node.attrib["status_code"].removeprefix("{{").removesuffix("}}")
        for node in ElementTree.fromstring(text).iter("PublishTaskStatus")
    ]


def _artifact_text(preview, relative_path: str) -> str:
    return next(
        artifact.content.decode("utf-8")
        for artifact in preview.artifacts
        if artifact.relative_path == relative_path
    )


def _copy_registry(tmp_path: Path) -> Path:
    registry = tmp_path / "task-status-codes.json"
    registry.write_bytes(task_status_codes_module.STATUS_CODE_PATH.read_bytes())
    return registry


def _replace_registry_code(path: Path, name: str, value: int) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    document["codes"][name] = value
    path.write_text(json.dumps(document), encoding="utf-8")


def _registry_sha() -> str:
    return sha256(task_status_codes_module.STATUS_CODE_PATH.read_bytes()).hexdigest()


def test_compiler_renders_current_registry_values_and_records_its_sha(two_map_project) -> None:
    """Catches preview XML retaining tokens or omitting its status-code provenance."""
    preview = _compile(two_map_project)

    rendered = _artifact_text(preview, "waypoint_tasks/gk1/1_1_elevator_in_n_x.xml")
    assert 'status_code="200"' in rendered
    assert 'status_code="209"' in rendered
    assert "STATUS_" not in rendered
    assert preview.manifest["task_status_codes_sha256"] == _registry_sha()
    assert preview.manifest["template_sha256"]["task-status-codes.json"] == _registry_sha()


def test_compiler_reacts_to_a_registry_code_change(monkeypatch, two_map_project, tmp_path: Path) -> None:
    """Catches a new registry value being ignored by rendered XML or preview identity."""
    config = _copy_registry(tmp_path)
    monkeypatch.setattr(task_status_codes_module, "STATUS_CODE_PATH", config)
    before = _compile(two_map_project)

    _replace_registry_code(config, "elevator_waiting", 811)
    after = _compile(two_map_project)

    assert before.input_sha256 != after.input_sha256
    assert 'status_code="811"' in _artifact_text(after, "waypoint_tasks/gk1/1_1_elevator_in_n_x.xml")


def test_compiler_uses_one_status_registry_snapshot(monkeypatch, two_map_project, tmp_path: Path) -> None:
    """A changed file after its snapshot cannot split XML values from provenance."""
    config = _copy_registry(tmp_path)
    monkeypatch.setattr(task_status_codes_module, "STATUS_CODE_PATH", config)
    expected_sha = _registry_sha()
    original_snapshot = task_status_codes_module.task_status_code_snapshot

    def snapshot_then_change():
        snapshot = original_snapshot()
        _replace_registry_code(config, "elevator_waiting", 811)
        return snapshot

    monkeypatch.setattr(task_status_codes_module, "task_status_code_snapshot", snapshot_then_change)
    preview = _compile(two_map_project)

    rendered = _artifact_text(preview, "waypoint_tasks/gk1/1_1_elevator_in_n_x.xml")
    assert 'status_code="200"' in rendered
    assert 'status_code="811"' not in rendered
    assert preview.manifest["task_status_codes_sha256"] == expected_sha
    assert preview.manifest["template_sha256"]["task-status-codes.json"] == expected_sha
    assert task_status_codes_module.task_status_code("elevator_waiting") == "811"


def test_compiler_renders_changed_registry_value_in_component_action_xml(
    monkeypatch, two_map_project, tmp_path: Path,
) -> None:
    """Component actions must receive the same registry-backed token values as base XML."""
    config = _copy_registry(tmp_path)
    monkeypatch.setattr(task_status_codes_module, "STATUS_CODE_PATH", config)
    gate = {
        "id": "component-target-gate", "map_asset_id": "target-map", "kind": "gate",
        "label": "东侧闸机", "x": 3.0, "y": 0.0, "yaw": pi / 2,
        "attributes": {
            "width_m": 2.0, "height_m": 1.0, "speed_profile": "single_point",
            "controller_device_id": "10044",
        },
    }
    two_map_project["components"].append(gate)
    _set_execution_nodes(two_map_project, target=[{"kind": "component", "id": gate["id"]}])
    _replace_registry_code(config, "gate_in", 811)

    preview = _compile(two_map_project)

    rendered = _artifact_text(preview, "waypoint_tasks/gk1/e_guard_open_go.xml")
    assert 'status_code="811"' in rendered
    assert "STATUS_" not in rendered


def test_compiler_blocks_preview_when_invalid_registry(monkeypatch, two_map_project, tmp_path: Path) -> None:
    """Catches an invalid profile registry being silently compiled into a preview."""
    config = _copy_registry(tmp_path)
    monkeypatch.setattr(task_status_codes_module, "STATUS_CODE_PATH", config)
    document = json.loads(config.read_text(encoding="utf-8"))
    del document["codes"]["task_start"]
    config.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(CompilationError, match="任务状态码配置"):
        _compile(two_map_project)


def test_compiler_rejects_a_literal_status_code_in_an_approved_template(
    monkeypatch, two_map_project, tmp_path: Path,
) -> None:
    """Catches a future approved template bypassing the registry token boundary."""
    template_root = tmp_path / "templates"
    shutil.copytree(TEMPLATE_ROOT, template_root)
    template = template_root / "task_complete.xml"
    template.write_text(
        template.read_text(encoding="utf-8").replace(
            "{{STATUS_TASK_COMPLETE}}", "109",
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(task_compiler_module, "TEMPLATE_ROOT", template_root)

    with pytest.raises(CompilationError, match="任务状态码"):
        _compile(two_map_project)


@pytest.mark.parametrize(("name", "expected"), [
    ("start_task.xml", ["STATUS_TASK_START", "STATUS_INDOOR_TASKING"]),
    ("task_complete.xml", ["STATUS_TASK_COMPLETE"]),
    ("place_water.xml", ["STATUS_CLAMP_WATER_WAITING", "STATUS_CLAMP_WATER", "STATUS_PLACE_WATER_WAITING", "STATUS_PLACE_WATER", "STATUS_PHOTO_UPLOAD", "STATUS_TASK_RETURN_WAITING"]),
    ("auto_cargo.xml", ["STATUS_MULTI_TASK_START", "STATUS_MULTI_TASK_ARRIVED"]),
    ("elevator_in_n_x.xml", ["STATUS_ELEVATOR_WAITING", "STATUS_ELEVATOR_ARRIVED", "STATUS_ELEVATOR_IN"]),
    ("elevator_in_x_n.xml", ["STATUS_ELEVATOR_WAITING", "STATUS_ELEVATOR_ARRIVED", "STATUS_ELEVATOR_IN"]),
    ("elevator_out_n_x.xml", ["STATUS_ELEVATOR_TAKING", "STATUS_ELEVATOR_WAITING", "STATUS_ELEVATOR_ARRIVED"]),
    ("elevator_out_x_n.xml", ["STATUS_ELEVATOR_TAKING", "STATUS_ELEVATOR_WAITING", "STATUS_ELEVATOR_ARRIVED"]),
    ("close_elevdoor_n.xml", ["STATUS_ELEVATOR_OUTING", "STATUS_ELEVATOR_OUTED"]),
    ("close_elevdoor_x.xml", ["STATUS_ELEVATOR_OUTING", "STATUS_ELEVATOR_OUTED"]),
    ("components/gate_open_go.xml", ["STATUS_DOOR_WAITING", "STATUS_GATE_IN"]),
    ("components/gate_open_back.xml", ["STATUS_DOOR_WAITING", "STATUS_GATE_IN"]),
    ("components/gate_close_go.xml", ["STATUS_DOOR_WAITING", "STATUS_GATE_OUT"]),
    ("components/gate_close_back.xml", ["STATUS_DOOR_WAITING", "STATUS_GATE_OUT"]),
    ("components/auto_door_open_go.xml", ["STATUS_DOOR_WAITING", "STATUS_AUTO_DOOR_IN"]),
    ("components/auto_door_open_back.xml", ["STATUS_DOOR_WAITING", "STATUS_AUTO_DOOR_IN"]),
    ("components/auto_door_close_go.xml", ["STATUS_DOOR_WAITING", "STATUS_AUTO_DOOR_OUT"]),
    ("components/auto_door_close_back.xml", ["STATUS_DOOR_WAITING", "STATUS_AUTO_DOOR_OUT"]),
])
def test_approved_templates_have_only_registry_status_tokens(name: str, expected: list[str]) -> None:
    """Catches a profile template retaining a literal or semantically wrong status code."""
    text = _template(name)
    assert _status_tokens(text) == expected
    assert not re.search(r'status_code="[0-9]+"', text)


@pytest.mark.parametrize("name", [
    "elevator_in_n_x.xml",
    "elevator_in_x_n.xml",
    "elevator_out_n_x.xml",
    "elevator_out_x_n.xml",
])
def test_elevator_caller_statuses_are_adjacent_to_the_caller(name: str) -> None:
    """Catches waiting or arrival publication moving away from its caller action."""
    root = ElementTree.fromstring(_template(name))
    sequence = root.find(".//Sequence[@name='CallAndCheckDoor']")
    assert sequence is not None
    children = list(sequence)
    caller_index = next(index for index, child in enumerate(children) if child.tag == "ElevatorCaller")
    assert children[caller_index - 1].attrib["status_code"] == "{{STATUS_ELEVATOR_WAITING}}"
    assert children[caller_index + 1].attrib["status_code"] == "{{STATUS_ELEVATOR_ARRIVED}}"


@pytest.mark.parametrize(("name", "before_retry", "after_retry"), [
    ("elevator_in_n_x.xml", None, "STATUS_ELEVATOR_IN"),
    ("elevator_in_x_n.xml", None, "STATUS_ELEVATOR_IN"),
    ("elevator_out_n_x.xml", "STATUS_ELEVATOR_TAKING", None),
    ("elevator_out_x_n.xml", "STATUS_ELEVATOR_TAKING", None),
])
def test_elevator_travel_statuses_are_adjacent_to_the_retry(name: str, before_retry: str | None, after_retry: str | None) -> None:
    """Catches travel status publication occurring before a retry succeeds or after unrelated work."""
    root = ElementTree.fromstring(_template(name))
    main_sequence = root.find(".//BehaviorTree/Sequence")
    assert main_sequence is not None
    children = list(main_sequence)
    retry_index = next(index for index, child in enumerate(children) if child.tag == "RetryUntilSuccessful")
    if before_retry:
        assert children[retry_index - 1].attrib["status_code"] == f"{{{{{before_retry}}}}}"
    if after_retry:
        assert children[retry_index + 1].attrib["status_code"] == f"{{{{{after_retry}}}}}"


@pytest.mark.parametrize(("name", "expected_after_retry"), [
    ("components/gate_open_go.xml", "STATUS_GATE_IN"),
    ("components/gate_open_back.xml", "STATUS_GATE_IN"),
    ("components/gate_close_go.xml", "STATUS_GATE_OUT"),
    ("components/gate_close_back.xml", "STATUS_GATE_OUT"),
    ("components/auto_door_open_go.xml", "STATUS_AUTO_DOOR_IN"),
    ("components/auto_door_open_back.xml", "STATUS_AUTO_DOOR_IN"),
    ("components/auto_door_close_go.xml", "STATUS_AUTO_DOOR_OUT"),
    ("components/auto_door_close_back.xml", "STATUS_AUTO_DOOR_OUT"),
])
def test_access_statuses_wrap_only_the_door_control(name: str, expected_after_retry: str) -> None:
    """Catches access status publication detached from the controlled door action."""
    root = ElementTree.fromstring(_template(name))
    action_sequence = root.find(".//Sequence[@name='CallAndCheckDoor']")
    assert action_sequence is not None
    action_children = list(action_sequence)
    door_index = next(index for index, child in enumerate(action_children) if child.tag == "DoorControl")
    assert action_children[door_index - 1].attrib["status_code"] == "{{STATUS_DOOR_WAITING}}"
    main_sequence = root.find(".//BehaviorTree/Sequence")
    assert main_sequence is not None
    main_children = list(main_sequence)
    retry_index = next(index for index, child in enumerate(main_children) if child.tag == "RetryUntilSuccessful")
    assert main_children[retry_index + 1].attrib["status_code"] == f"{{{{{expected_after_retry}}}}}"


@pytest.mark.parametrize("name", APPROVED_STATUS_TEMPLATES)
def test_approved_templates_do_not_publish_unimplemented_door_waiting_codes(name: str) -> None:
    """Catches adding an unused 305 status publication without a real behavior."""
    text = _template(name)
    assert "STATUS_DOOR_WAITING_OPEN" not in text
    assert "STATUS_DOOR_WAITING_CLOSE" not in text


@pytest.fixture
def two_map_project(tmp_path: Path) -> dict:
    map_root = tmp_path / "maps"
    lobby_yaml = map_root / "gk1" / "P1" / "map.yaml"
    target_yaml = map_root / "gk1" / "P2" / "map.yaml"
    for source in (lobby_yaml, target_yaml):
        source.parent.mkdir(parents=True)
        source.with_name("map.pgm").write_bytes(b"P5\n2 2\n255\n\x00\x00\x00\x00")
        source.write_text("image: map.pgm\nresolution: 1.0\norigin: [-10.0, -10.0, 0.0]\n", encoding="utf-8")
        source.with_name("index.txt").write_text("0 0 0\n0 0 0 0.pcd\n", encoding="utf-8")
        source.with_name("0.pcd").write_bytes(b"# controlled cloud fixture\n")

    assets = [
        {"id": "lobby-map", "source_yaml": str(lobby_yaml), "origin": [-10.0, -10.0, 0.0], "width": 40, "height": 40, "resolution_m": 1.0},
        {"id": "target-map", "source_yaml": str(target_yaml), "origin": [-10.0, -10.0, 0.0], "width": 40, "height": 40, "resolution_m": 1.0},
    ]
    return {
        "id": "test-site",
        "scene_model": "indoor",
        "map_assets": assets,
        "map_stage_assignments": [
            {"stage": "lobby", "map_asset_id": "lobby-map"},
            {"stage": "target_floor", "map_asset_id": "target-map"},
        ],
        "map_instances": [
            {"map_asset_id": "lobby-map", "role": "lobby", "building": "1", "unit": "1", "floor": 1},
            {"map_asset_id": "target-map", "role": "typical_floor", "building": "1", "unit": "1", "floor": 15},
        ],
        "physical_elevators": [
            {
                "id": "physical-elevator-a",
                "elevator_id": "10014",
                "elevator_protocol": "mqtt",
                "min_floor": -2,
                "max_floor": 25,
            }
        ],
        "task_compiler": {"identity": {"community": "高科一号"}},
        "components": [
            {"id": "start", "map_asset_id": "lobby-map", "kind": "start", "x": 0.0, "y": -2.0, "yaw": 0.0, "attributes": {}},
            {"id": "lobby-elevator", "map_asset_id": "lobby-map", "kind": "elevator", "x": 0.0, "y": 0.0, "yaw": 0.0, "attributes": {"physical_elevator_id": "physical-elevator-a", "button_floor": 1, "width_m": 2.0, "height_m": 2.0, "wait_distance_m": 1.5}},
            {"id": "target-elevator", "map_asset_id": "target-map", "kind": "elevator", "x": 2.0, "y": 0.0, "yaw": pi, "attributes": {"physical_elevator_id": "physical-elevator-a", "button_floor": 15, "width_m": 2.0, "height_m": 2.0, "wait_distance_m": 1.5}},
            {"id": "target", "map_asset_id": "target-map", "kind": "target", "x": 5.0, "y": 3.0, "yaw": 0.25, "attributes": {"door": "1509"}},
        ],
        "localization_bindings": [
            {"id": "lobby-binding", "map_asset_id": "lobby-map", "building": "1", "unit": "1", "type": "indoor"},
            {"id": "floor-binding", "map_asset_id": "target-map", "building": "1", "unit": "1", "type": "floor", "floor_template": "2"},
        ],
        "waypoints": [
            {"id": "route-start", "map_asset_id": "lobby-map", "x": 0.0, "y": -2.0, "yaw": 0.0},
            {"id": "route-target", "map_asset_id": "target-map", "x": 5.0, "y": 3.0, "yaw": 0.25},
            {"id": "route-return", "map_asset_id": "target-map", "x": 4.0, "y": 2.0, "yaw": -0.25},
        ],
        "localization_routes": [{
            "id": "route-1", "building": "1", "unit": "1",
            "binding_ids": ["lobby-binding", "floor-binding"],
            "task_start_waypoint_id": "route-start", "task_target_waypoint_id": "route-target", "task_return_waypoint_id": "route-return",
            "execution_nodes": [
                {"binding_id": "lobby-binding", "node_refs": []},
                {"binding_id": "floor-binding", "node_refs": []},
            ],
            "links": [{
                "from_binding_id": "lobby-binding", "to_binding_id": "floor-binding",
                "anchor": {"kind": "component_center", "component_id": "lobby-elevator"},
            }],
        }],
        "_test_map_root": str(map_root),
    }


def _compile(project: dict):
    return compile_indoor_elevator(project, map_root=Path(project["_test_map_root"]))


def test_target_arrival_action_selects_and_exports_the_matching_behavior_tree(two_map_project):
    """The stored target action must control the runtime task ID and exported XML."""
    target = next(item for item in two_map_project["components"] if item["id"] == "target")
    target["attributes"]["arrival_action"] = "auto_cargo"

    preview = _compile(two_map_project)

    target_subtask = next(item for item in preview.task_json["subtasks"] if item["subtask_name"] == "1509")
    assert target_subtask["waypoints"][-1]["waypoint_task_id"] == "auto_cargo"
    cargo_tree = _artifact_text(preview, "waypoint_tasks/gk1/auto_cargo.xml")
    assert 'status_code="700"' in cargo_tree
    assert 'status_code="701"' in cargo_tree
    assert 'status_code="109"' not in cargo_tree


@pytest.mark.parametrize("invalid", [False, 0, [], {}])
def test_compiler_rejects_falsy_non_string_target_arrival_actions(two_map_project, invalid):
    target = next(item for item in two_map_project["components"] if item["id"] == "target")
    target["attributes"]["arrival_action"] = invalid

    with pytest.raises(CompilationError, match="目标点到达动作不受支持"):
        _compile(two_map_project)


def test_auto_cargo_template_preserves_the_reference_runtime_blackboard_inputs():
    text = _template("auto_cargo.xml")
    tokens = re.findall(r"(?<!\{)\{([a-z_]+)\}(?!\})", text)

    assert tokens == [
        "delivery_code", "task_target_success", "delivery_code",
        "cargo_id", "cargo_operation_code", "delivery_code",
    ]


def test_single_task_mode_generates_a_complete_task_for_each_target(two_map_project):
    second = {
        "id": "target-1508", "map_asset_id": "target-map", "kind": "target",
        "x": 6.0, "y": 3.0, "yaw": 0.25, "attributes": {"door": "1508"},
        "generated_waypoint_ids": ["route-target-1508"],
    }
    two_map_project["components"].append(second)
    two_map_project["waypoints"].append({
        "id": "route-target-1508", "map_asset_id": "target-map", "x": 6.0, "y": 3.0, "yaw": 0.25,
    })
    route = dict(two_map_project["localization_routes"][0])
    route.update({"id": "route-1508", "task_target_waypoint_id": "route-target-1508"})
    two_map_project["localization_routes"].append(route)

    preview = compile_single_task_points(two_map_project, map_root=Path(two_map_project["_test_map_root"]))

    paths = [item.relative_path for item in preview.artifacts if item.relative_path.startswith("tasks/")]
    assert paths == ["tasks/高科一号_1_1_15_1508.json", "tasks/高科一号_1_1_15_1509.json"]
    assert all(len(json.loads(next(item.content for item in preview.artifacts if item.relative_path == path))["subtasks"]) == 4 for path in paths)


def test_single_task_filename_uses_target_elevator_button_when_map_floor_is_derived(two_map_project):
    """Map instances carry identity only; filenames keep the real panel floor."""
    for instance in two_map_project["map_instances"]:
        instance["floor"] = None

    preview = compile_single_task_points(two_map_project, map_root=Path(two_map_project["_test_map_root"]))

    assert "tasks/高科一号_1_1_15_1509.json" in {
        artifact.relative_path for artifact in preview.artifacts
    }


def test_single_task_mode_marks_legacy_single_target_preview(two_map_project):
    preview = compile_single_task_points(two_map_project, map_root=Path(two_map_project["_test_map_root"]))

    assert preview.manifest["task_mode"] == "single"
    assert len(preview.task_json["subtasks"]) == 4


def test_single_task_mode_keeps_indoor_flow_on_the_existing_compiler(two_map_project, monkeypatch):
    """Indoor-only flow metadata must not invoke public-route family validation."""
    two_map_project["deployment_flow"] = [
        {"id": "lobby", "type": "lobby"},
        {"id": "target_floor", "type": "target_floor"},
    ]
    monkeypatch.setattr(
        task_compiler_module,
        "derive_task_route_families",
        lambda _project: (_ for _ in ()).throw(AssertionError("不应推导公共路线族")),
    )

    preview = compile_single_task_points(two_map_project, map_root=Path(two_map_project["_test_map_root"]))

    assert preview.manifest["task_mode"] == "single"
    assert len(preview.task_json["subtasks"]) == 4


def test_multi_task_mode_splits_shared_indoor_and_each_target_floor_pair(two_map_project):
    """Lobby-to-floor topology must not create ferry/outdoor directories."""
    two_map_project["deployment_flow"] = [
        {"id": "lobby", "type": "lobby"},
        {"id": "target_floor", "type": "target_floor"},
    ]
    second = {
        "id": "target-1508", "map_asset_id": "target-map", "kind": "target",
        "x": 6.0, "y": 3.0, "yaw": 0.25, "attributes": {"door": "1508"},
        "generated_waypoint_ids": ["route-target-1508"],
    }
    two_map_project["components"].append(second)
    two_map_project["waypoints"].append({
        "id": "route-target-1508", "map_asset_id": "target-map", "x": 6.0, "y": 3.0, "yaw": 0.25,
    })
    route = dict(two_map_project["localization_routes"][0])
    route.update({"id": "route-1508", "task_target_waypoint_id": "route-target-1508"})
    two_map_project["localization_routes"].append(route)

    preview = compile_multi_task_points(two_map_project, map_root=Path(two_map_project["_test_map_root"]))

    paths = [item.relative_path for item in preview.artifacts if item.relative_path.startswith("multi_tasks/")]
    assert paths == [
        "multi_tasks/高科一号/floor/1_1_n_n08.json",
        "multi_tasks/高科一号/floor/1_1_n_n08_r.json",
        "multi_tasks/高科一号/floor/1_1_n_n09.json",
        "multi_tasks/高科一号/floor/1_1_n_n09_r.json",
        "multi_tasks/高科一号/indoor/1_1.json",
        "multi_tasks/高科一号/indoor/1_1_r.json",
    ]
    assert all("/ferry/" not in path and "/outdoor/" not in path for path in paths)
    assert [json.loads(next(item.content for item in preview.artifacts if item.relative_path == path))["subtask_name"] for path in paths] == [
        "1508", "1508_r", "1509", "1509_r", "elevator_hall", "elevator_hall_r",
    ]
    assert all(
        set(json.loads(next(item.content for item in preview.artifacts if item.relative_path == path)))
        == {"change_loc", "map_url", "pcd_url", "subtask_name", "waypoints"}
        for path in paths
    )
    assert all(
        "component_id" not in target
        for family in preview.manifest["route_families"]
        for target in family["targets"]
    )
    family_manifest = preview.manifest["route_families"][0]
    assert family_manifest["targets"] == [
        {
            "full_room_number": "1508",
                "physical_floor": 16,
            "button_floor": 15,
            "door": "08",
            "floor_stem": "1_1_n_n08",
        },
        {
            "full_room_number": "1509",
                "physical_floor": 16,
            "button_floor": 15,
            "door": "09",
            "floor_stem": "1_1_n_n09",
        },
    ]
    assert family_manifest["stages"] == [
        {"type": "lobby", "label": "电梯大厅"},
        {"type": "target_floor", "label": "用户楼层"},
    ]
    assert all("map_asset_id" not in stage for stage in family_manifest["stages"])
    assert set(preview.manifest["input_fingerprints"]) == {
        "deployment_flow", "map_assets", "map_instances", "components",
        "virtual_walls", "map_edits", "localization_bindings",
        "localization_routes", "physical_elevators", "localization_template",
        "component_templates", "behavior_templates", "task_status_codes",
    }
    assert preview.manifest["task_status_codes_sha256"] == _registry_sha()
    assert preview.manifest["input_sha256"] == preview.input_sha256


def test_multi_task_mode_uses_explicit_override_floor_stem(two_map_project):
    """A non-standard map must never be packaged under the reusable n_n name."""
    two_map_project["deployment_flow"] = [
        {"id": "lobby", "type": "lobby"},
        {"id": "target_floor", "type": "target_floor"},
    ]
    target_instance = next(item for item in two_map_project["map_instances"] if item["role"] == "typical_floor")
    target_instance.update({"role": "floor_override", "floor": None})
    target_elevator = next(item for item in two_map_project["components"] if item["id"] == "target-elevator")
    target_elevator["attributes"]["button_floor"] = 5
    target = next(item for item in two_map_project["components"] if item["kind"] == "target")
    target["attributes"] = {"door": "501"}

    preview = compile_multi_task_points(two_map_project, map_root=Path(two_map_project["_test_map_root"]))

    paths = {item.relative_path for item in preview.artifacts}
    assert "multi_tasks/高科一号/floor/1_1_5_501.json" in paths
    assert "multi_tasks/高科一号/floor/1_1_5_501_r.json" in paths
    assert not any("n_n" in path for path in paths if path.startswith("multi_tasks/高科一号/floor/"))


def test_multi_task_mode_compiles_every_unit_from_its_own_automatic_route(two_map_project):
    """A second unit must not reuse the first import-guide stage assignment."""
    two_map_project["deployment_flow"] = [
        {"id": "lobby", "type": "lobby"},
        {"id": "target_floor", "type": "target_floor"},
    ]
    lobby_asset = deepcopy(next(item for item in two_map_project["map_assets"] if item["id"] == "lobby-map"))
    target_asset = deepcopy(next(item for item in two_map_project["map_assets"] if item["id"] == "target-map"))
    lobby_asset["id"], target_asset["id"] = "lobby-map-2", "target-map-2"
    two_map_project["map_assets"].extend([lobby_asset, target_asset])
    two_map_project["map_instances"].extend([
        {"map_asset_id": "lobby-map-2", "role": "lobby", "building": "2", "unit": "1", "floor": 1},
        {"map_asset_id": "target-map-2", "role": "typical_floor", "building": "2", "unit": "1", "floor": 15},
    ])
    two_map_project["physical_elevators"].append({
        "id": "physical-elevator-b", "elevator_id": "10015", "elevator_protocol": "mqtt", "min_floor": -2, "max_floor": 25,
    })
    two_map_project["components"].extend([
        {"id": "start-2", "map_asset_id": "lobby-map-2", "kind": "start", "x": 0.0, "y": -2.0, "yaw": 0.0, "attributes": {}},
        {"id": "lobby-elevator-2", "map_asset_id": "lobby-map-2", "kind": "elevator", "x": 0.0, "y": 0.0, "yaw": 0.0, "attributes": {"physical_elevator_id": "physical-elevator-b", "button_floor": 1, "width_m": 2.0, "height_m": 2.0, "wait_distance_m": 1.5}},
        {"id": "target-elevator-2", "map_asset_id": "target-map-2", "kind": "elevator", "x": 2.0, "y": 0.0, "yaw": pi, "attributes": {"physical_elevator_id": "physical-elevator-b", "button_floor": 15, "width_m": 2.0, "height_m": 2.0, "wait_distance_m": 1.5}},
        {"id": "target-2", "map_asset_id": "target-map-2", "kind": "target", "x": 5.0, "y": 3.0, "yaw": 0.25, "attributes": {"door": "1501"}},
    ])
    two_map_project["localization_bindings"].extend([
        {"id": "lobby-binding-2", "map_asset_id": "lobby-map-2", "building": "2", "unit": "1", "type": "indoor"},
        {"id": "floor-binding-2", "map_asset_id": "target-map-2", "building": "2", "unit": "1", "type": "floor", "floor_template": "2"},
    ])
    two_map_project["waypoints"].extend([
        {"id": "route-start-2", "map_asset_id": "lobby-map-2", "x": 0.0, "y": -2.0, "yaw": 0.0},
        {"id": "route-target-2", "map_asset_id": "target-map-2", "x": 5.0, "y": 3.0, "yaw": 0.25},
    ])
    two_map_project["localization_routes"].append({
        "id": "route-2", "building": "2", "unit": "1",
        "binding_ids": ["lobby-binding-2", "floor-binding-2"],
        "task_start_waypoint_id": "route-start-2", "task_target_waypoint_id": "route-target-2",
        "execution_nodes": [
            {"binding_id": "lobby-binding-2", "node_refs": []},
            {"binding_id": "floor-binding-2", "node_refs": []},
        ],
        "links": [{
            "from_binding_id": "lobby-binding-2", "to_binding_id": "floor-binding-2",
            "anchor": {"kind": "component_center", "component_id": "lobby-elevator-2"},
        }],
    })

    preview = compile_multi_task_points(two_map_project, map_root=Path(two_map_project["_test_map_root"]))

    task_paths = {item.relative_path for item in preview.artifacts if item.relative_path.startswith("multi_tasks/")}
    assert task_paths == {
        "multi_tasks/高科一号/indoor/1_1.json",
        "multi_tasks/高科一号/indoor/1_1_r.json",
        "multi_tasks/高科一号/floor/1_1_n_n09.json",
        "multi_tasks/高科一号/floor/1_1_n_n09_r.json",
        "multi_tasks/高科一号/indoor/2_1.json",
        "multi_tasks/高科一号/indoor/2_1_r.json",
        "multi_tasks/高科一号/floor/2_1_n_n01.json",
        "multi_tasks/高科一号/floor/2_1_n_n01_r.json",
    }

    single = compile_single_task_points(two_map_project, map_root=Path(two_map_project["_test_map_root"]))
    assert {item.relative_path for item in single.artifacts if item.relative_path.startswith("tasks/")} == {
        "tasks/高科一号_1_1_15_1509.json",
        "tasks/高科一号_2_1_15_1501.json",
    }


def test_multi_task_mode_rejects_optional_stages_without_a_derived_public_route(two_map_project):
    two_map_project["deployment_flow"] = [
        {"id": "ferry", "type": "ferry"},
        {"id": "lobby", "type": "lobby"},
        {"id": "target_floor", "type": "target_floor"},
    ]
    two_map_project["map_instances"].append({"map_asset_id": "ferry-map", "role": "ferry"})

    with pytest.raises(CompilationError, match="摆渡"):
        compile_multi_task_points(two_map_project, map_root=Path(two_map_project["_test_map_root"]))


def test_multi_task_mode_emits_only_required_public_route_files(two_map_project):
    """Ferry is emitted once; outdoor is emitted for its owning building/unit."""
    ferry = deepcopy(next(item for item in two_map_project["map_assets"] if item["id"] == "lobby-map"))
    outdoor = deepcopy(ferry)
    ferry["id"], ferry["label"] = "ferry-map", "摆渡层"
    outdoor["id"], outdoor["label"] = "outdoor-map", "一栋户外"
    two_map_project["map_assets"].extend([ferry, outdoor])
    two_map_project["deployment_flow"] = [
        {"id": "ferry", "type": "ferry"},
        {"id": "outdoor", "type": "outdoor"},
        {"id": "lobby", "type": "lobby"},
        {"id": "target_floor", "type": "target_floor"},
    ]
    two_map_project["map_instances"].extend([
        {"map_asset_id": "ferry-map", "role": "ferry", "scope": "global", "building": "", "unit": "", "floor": None},
        {"map_asset_id": "outdoor-map", "role": "outdoor", "scope": "unit", "building": "1", "unit": "1", "floor": 1},
    ])
    two_map_project["localization_bindings"] = [
        {"id": "ferry-binding", "map_asset_id": "ferry-map", "building": "", "unit": "", "type": "ferry"},
        {"id": "outdoor-binding", "map_asset_id": "outdoor-map", "building": "1", "unit": "1", "type": "outdoor"},
        *two_map_project["localization_bindings"],
    ]
    two_map_project["components"].extend([
        {"id": "ferry-start", "map_asset_id": "ferry-map", "kind": "start", "x": 0.0, "y": -2.0, "yaw": 0.0, "generated_waypoint_ids": ["ferry-start-point"]},
        {"id": "outdoor-start", "map_asset_id": "outdoor-map", "kind": "start", "x": 0.0, "y": -2.0, "yaw": 0.0, "generated_waypoint_ids": ["outdoor-start-point"]},
        {"id": "outdoor-gate", "map_asset_id": "outdoor-map", "kind": "gate", "x": 0.0, "y": -1.0, "yaw": 0.0, "attributes": {"width_m": 2.0, "height_m": 1.0, "controller_device_id": "10044", "pre_open_distance_m": 1.0, "post_open_distance_m": 1.0}},
        {"id": "lobby-entry", "map_asset_id": "lobby-map", "kind": "building_entrance", "x": 0.0, "y": -2.0, "yaw": 0.0, "generated_waypoint_ids": ["lobby-entry-point"]},
    ])
    two_map_project["waypoints"].extend([
        {"id": "ferry-start-point", "map_asset_id": "ferry-map", "kind": "start", "generated_by": "ferry-start", "x": 0.0, "y": -2.0, "yaw": 0.0},
        {"id": "ferry-handoff", "map_asset_id": "ferry-map", "kind": "map_transition", "x": 0.0, "y": 0.0, "yaw": 0.0},
        {"id": "outdoor-start-point", "map_asset_id": "outdoor-map", "kind": "start", "generated_by": "outdoor-start", "x": 0.0, "y": -2.0, "yaw": 0.0},
        {"id": "outdoor-handoff", "map_asset_id": "outdoor-map", "kind": "map_transition", "x": 0.0, "y": 0.0, "yaw": 0.0},
        {"id": "lobby-entry-point", "map_asset_id": "lobby-map", "kind": "building_entrance", "generated_by": "lobby-entry", "x": 0.0, "y": -2.0, "yaw": 0.0},
    ])
    route = two_map_project["localization_routes"][0]
    route.update({
        "binding_ids": ["ferry-binding", "outdoor-binding", "lobby-binding", "floor-binding"],
        "links": [
            {"from_binding_id": "ferry-binding", "to_binding_id": "outdoor-binding", "anchor": {"kind": "waypoint", "waypoint_id": "ferry-handoff"}},
            {"from_binding_id": "outdoor-binding", "to_binding_id": "lobby-binding", "anchor": {"kind": "waypoint", "waypoint_id": "outdoor-handoff"}},
            {"from_binding_id": "lobby-binding", "to_binding_id": "floor-binding", "anchor": {"kind": "component_center", "component_id": "lobby-elevator"}},
        ],
        "entry_anchors": [
            {"binding_id": "outdoor-binding", "anchor": {"kind": "waypoint", "waypoint_id": "outdoor-start-point"}},
            {"binding_id": "lobby-binding", "anchor": {"kind": "component_center", "component_id": "lobby-entry"}},
            {"binding_id": "floor-binding", "anchor": {"kind": "component_center", "component_id": "target-elevator"}},
        ],
        "task_start_waypoint_id": "ferry-start-point",
        "execution_nodes": [
            {"binding_id": "ferry-binding", "node_refs": []},
            {"binding_id": "outdoor-binding", "node_refs": [{"kind": "component", "id": "outdoor-gate"}]},
            {"binding_id": "lobby-binding", "node_refs": []},
            {"binding_id": "floor-binding", "node_refs": []},
        ],
    })

    preview = compile_multi_task_points(two_map_project, map_root=Path(two_map_project["_test_map_root"]))

    paths = {item.relative_path for item in preview.artifacts if item.relative_path.startswith("multi_tasks/")}
    assert paths == {
        "multi_tasks/高科一号/sub_outdoor_eguard.json",
        "multi_tasks/高科一号/sub_outdoor_eguard_r.json",
        "multi_tasks/高科一号/outdoor/1_1.json",
        "multi_tasks/高科一号/outdoor/1_1_r.json",
        "multi_tasks/高科一号/indoor/1_1.json",
        "multi_tasks/高科一号/indoor/1_1_r.json",
        "multi_tasks/高科一号/floor/1_1_n_n09.json",
        "multi_tasks/高科一号/floor/1_1_n_n09_r.json",
    }
    assert json.loads(_artifact_text(preview, "multi_tasks/高科一号/sub_outdoor_eguard.json"))["subtask_name"] == "outdoor"
    assert json.loads(_artifact_text(preview, "multi_tasks/高科一号/outdoor/1_1.json"))["subtask_name"] == "outdoor_1_1"
    assert "waypoint_tasks/gk1/e_guard_open_go.xml" in {item.relative_path for item in preview.artifacts}

    single = compile_single_task_points(two_map_project, map_root=Path(two_map_project["_test_map_root"]))
    single_task = single.task_json["tasks"][0]
    assert [item["subtask_name"] for item in single_task["subtasks"]] == [
        "outdoor", "outdoor_1_1", "elevator_hall", "1509", "1509_r", "elevator_hall_r", "outdoor_1_1_r", "outdoor_r",
    ]


def _set_execution_nodes(project: dict, *, lobby: list[dict] | None = None, target: list[dict] | None = None) -> None:
    """Declare operator intent explicitly; never let a compiler test use save order."""
    project["localization_routes"][0]["execution_nodes"] = [
        {"binding_id": "lobby-binding", "node_refs": lobby or []},
        {"binding_id": "floor-binding", "node_refs": target or []},
    ]


def _add_store_localization_route(
    store: DeploymentStore, project: dict, lobby: dict, target: dict, lobby_elevator: dict
) -> None:
    """Create the route facts required by the route-derived export boundary."""
    indoor = store.create_localization_binding(project["id"], {
        "map_asset_id": lobby["id"], "building": "1", "unit": "1", "type": "indoor",
    })
    floor = store.create_localization_binding(project["id"], {
        "map_asset_id": target["id"], "building": "1", "unit": "1", "type": "floor", "floor_template": "2",
    })
    start = store.add_waypoint(project["id"], {
        "map_id": lobby["id"], "kind": "start", "x": -1.0, "y": -1.0,
    })
    task_target = store.add_waypoint(project["id"], {
        "map_id": target["id"], "kind": "target", "x": 1.0, "y": 1.0,
    })
    task_return = store.add_waypoint(project["id"], {
        "map_id": target["id"], "kind": "return", "x": 1.5, "y": 1.0,
    })
    store.create_localization_route(project["id"], {
        "building": "1", "unit": "1",
        "binding_ids": [indoor["id"], floor["id"]],
        "task_start_waypoint_id": start["id"],
        "task_target_waypoint_id": task_target["id"],
        "task_return_waypoint_id": task_return["id"],
        "links": [{
            "from_binding_id": indoor["id"], "to_binding_id": floor["id"],
            "anchor": {"kind": "component_center", "component_id": lobby_elevator["id"]},
        }],
    })


def test_compiler_emits_four_subtasks_and_approved_speed_sequence(two_map_project):
    payload = _compile(two_map_project).task_json
    assert [item["subtask_name"] for item in payload["subtasks"]] == ["elevator_hall", "1509", "1509_r", "elevator_hall_r"]
    assert [[point["speed_mode"] for point in item["waypoints"]] for item in payload["subtasks"]] == [
        ["task_point", "single_point", "elevator_in"],
        ["backward", "single_point"],
        ["task_point", "elevator_in"],
        ["backward", "single_point"],
    ]


def test_compiler_keeps_outbound_target_and_return_handoff_distinct(two_map_project):
    subtasks = _compile(two_map_project).task_json["subtasks"]
    outbound = subtasks[1]["waypoints"][-1]["pose"]["position"]
    return_origin = subtasks[2]["waypoints"][0]["pose"]["position"]
    assert (outbound["x"], outbound["y"]) == (5.0, 3.0)
    assert isclose(return_origin["x"], 2.0, abs_tol=1e-9)
    assert isclose(return_origin["y"], -2.5, abs_tol=1e-9)
    assert (return_origin["x"], return_origin["y"]) != (outbound["x"], outbound["y"])


def test_compiler_rejects_a_route_target_that_does_not_match_the_delivery_target(two_map_project):
    """A route endpoint and the generated task cannot silently describe different destinations."""
    route_target = next(item for item in two_map_project["waypoints"] if item["id"] == "route-target")
    route_target["x"] = 4.5

    with pytest.raises(CompilationError, match="定位路线的去程终点必须与目标点一致"):
        _compile(two_map_project)


def test_compiler_generates_controlled_gate_actions_for_both_travel_directions(two_map_project):
    """Catches a configured gate being visible on the map yet absent from JSON/XML output."""
    gate = {
        "id": "component-target-gate", "map_asset_id": "target-map", "kind": "gate",
        "label": "东侧闸机", "x": 3.0, "y": 0.0, "yaw": pi / 2,
        "attributes": {
            "width_m": 2.0, "height_m": 1.0, "speed_profile": "single_point",
            "controller_device_id": "10044",
        },
    }
    two_map_project["components"].append(gate)
    _set_execution_nodes(two_map_project, target=[{"kind": "component", "id": gate["id"]}])

    preview = _compile(two_map_project)
    subtasks = {item["subtask_name"]: item["waypoints"] for item in preview.task_json["subtasks"]}
    artifact_text = {
        item.relative_path: item.content.decode("utf-8")
        for item in preview.artifacts if item.relative_path.endswith(".xml")
    }

    assert [point["waypoint_id"] for point in subtasks["1509"]] == [
        "target_wait", "1509_component-target-gate_open_go", "1509_component-target-gate_close_go", "target",
    ]
    assert [point["waypoint_id"] for point in subtasks["1509_r"]] == [
        "1509_r_component-target-gate_open_back", "1509_r_component-target-gate_close_back",
        "target_return_wait", "target_return_elevator_center",
    ]
    action_trees = {
        path: text for path, text in artifact_text.items() if "/e_guard_" in path
    }
    assert len(action_trees) == 4
    assert all('doorid="10044"' in text for text in action_trees.values())
    assert all("/home/bob/" not in text and "SetUseWheelOdom" not in text for text in action_trees.values())
    task_action_ids = {
        point["waypoint_task_id"]
        for points in subtasks.values() for point in points
        if point["waypoint_task_id"].startswith("e_guard_")
    }
    action_tree_stems = {Path(path).stem for path in action_trees}
    assert task_action_ids == action_tree_stems
    location_manifest = json.loads(next(
        item.content for item in preview.artifacts if item.relative_path == "runtime/loc_yaml_path.json"
    ))
    floor_return = location_manifest["loc_yaml"][0]["yaml_index"][1]["init_return"]
    first_return = subtasks["1509_r"][0]["pose"]
    assert floor_return == {
        "x": first_return["position"]["x"], "y": first_return["position"]["y"],
        "z": 0.0, "yaw": pytest.approx(2 * atan2(
            first_return["orientation"]["z"], first_return["orientation"]["w"],
        )),
    }
    chain = preview.manifest["execution_chain"]["target"]
    assert [node["action"] for node in chain["outbound"]] == ["open_go", "close_go"]
    assert [node["action"] for node in chain["return"]] == ["open_back", "close_back"]
    assert {node["controller_device_id"] for node in chain["outbound"]} == {"10044"}
    assert {node["generated_by"] for node in chain["outbound"]} == {"component-target-gate"}
    assert {node["behavior_tree"] for node in chain["outbound"]} == {
        "e_guard_open_go.xml",
        "e_guard_close_go.xml",
    }


@pytest.mark.parametrize("kind", ["gate", "auto_door"])
def test_controlled_access_actions_stop_before_and_after_the_barrier(two_map_project, kind):
    """Open before the barrier and close only after a configured clear distance."""
    barrier = {
        "id": f"component-{kind}-clearance", "map_asset_id": "target-map", "kind": kind,
        "label": kind, "x": 3.0, "y": 0.0, "yaw": pi / 2,
        "attributes": {
            "width_m": 2.0, "height_m": 0.5, "controller_device_id": "10044",
            "pre_open_distance_m": 1.25, "post_open_distance_m": 0.75,
        },
    }
    two_map_project["components"].append(barrier)
    _set_execution_nodes(two_map_project, target=[{"kind": "component", "id": barrier["id"]}])

    subtasks = {item["subtask_name"]: item["waypoints"] for item in _compile(two_map_project).task_json["subtasks"]}
    outbound_actions = subtasks["1509"][1:3]
    return_actions = subtasks["1509_r"][:2]

    assert [point["waypoint_id"].rsplit("_", 2)[-2:] for point in outbound_actions] == [["open", "go"], ["close", "go"]]
    assert [point["pose"]["position"]["x"] for point in outbound_actions] == pytest.approx([1.5, 4.0])
    assert [point["waypoint_id"].rsplit("_", 2)[-2:] for point in return_actions] == [["open", "back"], ["close", "back"]]
    assert [point["pose"]["position"]["x"] for point in return_actions] == pytest.approx([4.0, 1.5])


def test_compiler_uses_the_existing_auto_door_behavior_tree_filename_contract(two_map_project):
    """Component UUIDs must never leak into the deployment behavior-tree contract."""
    auto_door = {
        "id": "component-target-auto-door", "map_asset_id": "target-map", "kind": "auto_door",
        "label": "东侧自动门", "x": 3.0, "y": 0.0, "yaw": pi / 2,
        "attributes": {
            "width_m": 2.0, "height_m": 0.3, "speed_profile": "task_point",
            "controller_device_id": "10045",
        },
    }
    two_map_project["components"].append(auto_door)
    _set_execution_nodes(two_map_project, target=[{"kind": "component", "id": auto_door["id"]}])

    preview = _compile(two_map_project)
    task_ids = {
        point["waypoint_task_id"]
        for subtask in preview.task_json["subtasks"] for point in subtask["waypoints"]
        if point["waypoint_task_id"]
    }
    expected_tree_names = {
        "1_1_open_door_go.xml", "1_1_close_door_go.xml",
        "1_1_open_door_back.xml", "1_1_close_door_back.xml",
    }
    tree_names = {
        Path(item.relative_path).name
        for item in preview.artifacts
        if Path(item.relative_path).name in expected_tree_names
    }

    assert {
        "1_1_open_door_go", "1_1_close_door_go",
        "1_1_open_door_back", "1_1_close_door_back",
    } <= task_ids
    assert tree_names == expected_tree_names


@pytest.mark.parametrize(
    ("kind", "stale_profile", "expected_profile"),
    [("auto_door", "slow_point", "task_point"), ("gate", "single_point", "narrow_point")],
)
def test_compiler_enforces_the_template_speed_for_controlled_access_components(
    two_map_project, kind: str, stale_profile: str, expected_profile: str,
):
    """Task JSON must obey the template even when a legacy project saved another mode."""
    barrier = {
        "id": f"component-{kind}-speed", "map_asset_id": "target-map", "kind": kind,
        "label": kind, "x": 3.0, "y": 0.0, "yaw": pi / 2,
        "attributes": {
            "width_m": 2.0, "height_m": 1.0, "speed_profile": stale_profile,
            "controller_device_id": "10044",
        },
    }
    two_map_project["components"].append(barrier)
    _set_execution_nodes(two_map_project, target=[{"kind": "component", "id": barrier["id"]}])

    target_waypoints = next(
        subtask["waypoints"]
        for subtask in _compile(two_map_project).task_json["subtasks"]
        if subtask["subtask_name"] == "1509"
    )

    assert [point["speed_mode"] for point in target_waypoints[1:3]] == [expected_profile, expected_profile]


@pytest.mark.parametrize("kind", ["gate", "auto_door"])
def test_compiler_crosses_a_horizontal_barrier_perpendicular_to_its_long_edge(two_map_project, kind: str):
    """A horizontal door face must be crossed vertically, never along its leaves."""
    barrier = {
        "id": f"component-horizontal-{kind}", "map_asset_id": "target-map", "kind": kind,
        "label": f"水平{kind}", "x": 3.0, "y": 0.0, "yaw": 0.0,
        "attributes": {
            "width_m": 2.0, "height_m": 1.0, "speed_profile": "single_point",
            "controller_device_id": "10044",
        },
    }
    two_map_project["components"].append(barrier)
    _set_execution_nodes(two_map_project, target=[{"kind": "component", "id": barrier["id"]}])

    outbound = _compile(two_map_project).task_json["subtasks"][1]["waypoints"]

    assert [point["waypoint_id"] for point in outbound[1:3]] == [
        f"1509_{barrier['id']}_open_go", f"1509_{barrier['id']}_close_go",
    ]
    assert [
        (point["pose"]["position"]["x"], point["pose"]["position"]["y"])
        for point in outbound[1:3]
    ] == [(3.0, -2.0), (3.0, 2.0)]


@pytest.mark.parametrize("kind", ["gate", "auto_door"])
def test_compiler_crosses_a_rotated_barrier_perpendicular_to_its_long_edge(two_map_project, kind: str):
    """Rotating a vertical door face rotates its normal, not an internal arrow."""
    barrier = {
        "id": f"component-rotated-{kind}", "map_asset_id": "target-map", "kind": kind,
        "label": f"旋转{kind}", "x": 3.0, "y": 0.0, "yaw": pi / 2,
        "attributes": {
            "width_m": 2.0, "height_m": 1.0, "speed_profile": "single_point",
            "controller_device_id": "10044",
        },
    }
    two_map_project["components"].append(barrier)
    _set_execution_nodes(two_map_project, target=[{"kind": "component", "id": barrier["id"]}])

    outbound = _compile(two_map_project).task_json["subtasks"][1]["waypoints"]

    coordinates = [
        coordinate
        for point in outbound[1:3]
        for coordinate in (point["pose"]["position"]["x"], point["pose"]["position"]["y"])
    ]
    assert coordinates == pytest.approx([1.0, 0.0, 5.0, 0.0])
    return_waypoints = next(
        subtask["waypoints"]
        for subtask in _compile(two_map_project).task_json["subtasks"]
        if subtask["subtask_name"] == "1509_r"
    )
    assert [point["waypoint_id"] for point in return_waypoints[:2]] == [
        f"1509_r_{barrier['id']}_open_back", f"1509_r_{barrier['id']}_close_back",
    ]


def test_compiler_rejects_a_route_that_does_not_cross_both_barrier_faces(two_map_project):
    """A door must not fabricate a crossing when both route neighbours share one side."""
    door = {
        "id": "component-same-side-door", "map_asset_id": "target-map", "kind": "auto_door",
        "label": "同侧自动门", "x": 3.0, "y": 0.0, "yaw": 0.0,
        "attributes": {
            "width_m": 2.0, "height_m": 1.0, "speed_profile": "single_point",
            "controller_device_id": "10044",
        },
    }
    target = next(item for item in two_map_project["components"] if item["id"] == "target")
    route_target = next(item for item in two_map_project["waypoints"] if item["id"] == "route-target")
    target["y"] = route_target["y"] = -3.0
    two_map_project["components"].append(door)
    _set_execution_nodes(two_map_project, target=[{"kind": "component", "id": door["id"]}])

    with pytest.raises(CompilationError, match="门体没有被任务路径从两侧穿过"):
        _compile(two_map_project)


@pytest.mark.parametrize("kind", ["gate", "auto_door"])
def test_compiler_blocks_an_unconfigured_access_component_until_its_device_number_is_filled(
    two_map_project, kind: str,
):
    """A draft map marker must never turn into a behavior tree with a guessed device id."""
    component = {
        "id": f"component-draft-{kind}", "map_asset_id": "target-map", "kind": kind,
        "label": "待配置设备", "x": 3.0, "y": 0.0, "yaw": pi / 2,
        "attributes": {
            "width_m": 2.0, "height_m": 1.0, "speed_profile": "single_point",
            "controller_device_id": "",
        },
    }
    two_map_project["components"].append(component)
    _set_execution_nodes(two_map_project, target=[{"kind": "component", "id": component["id"]}])

    with pytest.raises(CompilationError, match="必须填写纯数字控制设备号"):
        _compile(two_map_project)


def test_compiler_blocks_a_route_with_an_unapproved_intermediate_map(two_map_project):
    """Catches silently dropping ferry/outdoor segments from the indoor task."""
    two_map_project["localization_bindings"].insert(1, {
        "id": "ferry-binding", "map_asset_id": "lobby-map", "building": "1",
        "unit": "1", "type": "ferry",
    })
    two_map_project["localization_routes"][0]["binding_ids"] = [
        "lobby-binding", "ferry-binding", "floor-binding",
    ]

    with pytest.raises(CompilationError, match="不支持户外或摆渡"):
        _compile(two_map_project)


def test_compiler_blocks_an_unapproved_custom_flow_stage(two_map_project):
    """Catches presenting a profile as ready while its stage has no BT semantics."""
    two_map_project["scene_model"] = "custom"
    two_map_project["deployment_flow"] = [
        {"id": "ferry", "type": "ferry"},
        {"id": "lobby", "type": "lobby"},
        {"id": "target", "type": "target_floor"},
    ]

    with pytest.raises(CompilationError, match="不支持户外或摆渡"):
        _compile(two_map_project)


def test_compiler_turns_a_slow_zone_into_physical_entry_and_exit_edges(two_map_project):
    """A visible region changes speed only while traversing its physical span."""
    slow_zone = {
        "id": "component-slow-zone", "map_asset_id": "target-map", "kind": "slow_zone",
        "label": "电梯口减速区", "x": 3.0, "y": 0.0, "yaw": pi,
        "attributes": {"width_m": 2.0, "height_m": 2.0, "speed_profile": "slow_point"},
    }
    two_map_project["components"].append(slow_zone)
    _set_execution_nodes(two_map_project, target=[{"kind": "component", "id": slow_zone["id"]}])

    preview = _compile(two_map_project)
    subtasks = {item["subtask_name"]: item["waypoints"] for item in preview.task_json["subtasks"]}

    assert [point["waypoint_id"] for point in subtasks["1509"]] == [
        "target_wait", "1509_component-slow-zone_entry", "1509_component-slow-zone_exit", "target",
    ]
    assert [point["speed_mode"] for point in subtasks["1509"]] == [
        "backward", "single_point", "slow_point", "single_point",
    ]
    assert [point["waypoint_id"] for point in subtasks["1509_r"]] == [
        "1509_r_component-slow-zone_exit", "1509_r_component-slow-zone_entry",
        "target_return_wait", "target_return_elevator_center",
    ]
    assert [point["speed_mode"] for point in subtasks["1509_r"]] == [
        "single_point", "slow_point", "task_point", "elevator_in",
    ]
    floor_return = json.loads(next(
        item.content for item in preview.artifacts if item.relative_path == "runtime/loc_yaml_path.json"
    ))["loc_yaml"][0]["yaml_index"][1]["init_return"]
    assert floor_return["x"] == subtasks["1509_r"][0]["pose"]["position"]["x"]
    assert floor_return["y"] == subtasks["1509_r"][0]["pose"]["position"]["y"]


@pytest.mark.parametrize(
    ("kind", "speed_profile"),
    [("narrow_passage", "narrow_point"), ("ramp", "slow_point")],
)
def test_compiler_treats_passive_regions_as_rotated_areas_not_directional_arrows(
    two_map_project, kind: str, speed_profile: str,
):
    """A narrow passage or ramp must work in either travel direction across its footprint."""
    region = {
        "id": f"component-{kind}", "map_asset_id": "target-map", "kind": kind,
        "label": kind, "x": 3.5, "y": 0.25, "yaw": pi,
        "attributes": {"width_m": 2.0, "height_m": 2.0, "speed_profile": speed_profile},
    }
    two_map_project["components"].append(region)
    _set_execution_nodes(two_map_project, target=[{"kind": "component", "id": region["id"]}])

    preview = _compile(two_map_project)
    outbound = preview.task_json["subtasks"][1]["waypoints"]
    returned = preview.task_json["subtasks"][2]["waypoints"]

    assert [point["waypoint_id"] for point in outbound] == [
        "target_wait", f"1509_{region['id']}_entry", f"1509_{region['id']}_exit", "target",
    ]
    assert [point["speed_mode"] for point in outbound] == [
        "backward", "single_point", speed_profile, "single_point",
    ]
    assert [point["waypoint_id"] for point in returned[:2]] == [
        f"1509_r_{region['id']}_exit", f"1509_r_{region['id']}_entry",
    ]


def test_compiler_routes_through_an_off_line_passive_region(two_map_project):
    """A required region creates a deliberate detour instead of rejecting its map mark."""
    region = {
        "id": "component-off-line-narrow", "map_asset_id": "target-map", "kind": "narrow_passage",
        "label": "离线窄通道", "x": 3.0, "y": 5.0, "yaw": 0.0,
        "attributes": {"width_m": 1.0, "height_m": 2.0, "speed_profile": "narrow_point"},
    }
    two_map_project["components"].append(region)
    _set_execution_nodes(two_map_project, target=[{"kind": "component", "id": region["id"]}])

    outbound = _compile(two_map_project).task_json["subtasks"][1]["waypoints"]

    assert [point["waypoint_id"] for point in outbound] == [
        "target_wait", "1509_component-off-line-narrow_entry",
        "1509_component-off-line-narrow_exit", "target",
    ]
    assert [
        (point["pose"]["position"]["x"], point["pose"]["position"]["y"])
        for point in outbound[1:3]
    ] == [(3.0, 4.0), (3.0, 6.0)]


def test_compiler_emits_saved_target_transition_points_without_behavior_trees(two_map_project):
    """A marked task transition must survive preview generation in route order."""
    two_map_project["waypoints"].extend([
        {
            "id": "transition-first", "map_asset_id": "target-map", "kind": "transition",
            "label": "过渡点", "x": 3.0, "y": 1.0, "yaw": 0.5,
            "speed_mode": "slow_point",
        },
        {
            "id": "transition-second", "map_asset_id": "target-map", "kind": "transition",
            "label": "过渡点", "x": 4.0, "y": 2.0, "yaw": 0.75,
            "speed_mode": "narrow_point",
        },
    ])
    _set_execution_nodes(two_map_project, target=[
        {"kind": "transition", "id": "transition-first"},
        {"kind": "transition", "id": "transition-second"},
    ])

    outbound = _compile(two_map_project).task_json["subtasks"][1]["waypoints"]

    assert [point["waypoint_id"] for point in outbound] == [
        "target_wait", "1509_1", "1509_2", "target",
    ]
    assert [point["speed_mode"] for point in outbound] == [
        "backward", "slow_point", "narrow_point", "single_point",
    ]
    assert [(point["waypoint_task_id"], point["is_task_point"]) for point in outbound[1:3]] == [
        ("", False), ("", False),
    ]
    assert [point["pose"]["position"] for point in outbound[1:3]] == [
        {"x": 3.0, "y": 1.0, "z": 0.0},
        {"x": 4.0, "y": 2.0, "z": 0.0},
    ]


def test_compiler_mirrors_lobby_and_target_transitions_through_all_four_task_segments(two_map_project):
    """Catches dropping a map's transitions or traversing them forward on return."""
    two_map_project["waypoints"].extend([
        {"id": "lobby-first", "map_asset_id": "lobby-map", "kind": "transition", "label": "大厅过渡 1", "x": 0.0, "y": -1.5, "yaw": 0.2, "speed_mode": "slow_point"},
        {"id": "lobby-second", "map_asset_id": "lobby-map", "kind": "transition", "label": "大厅过渡 2", "x": 0.0, "y": -1.0, "yaw": 0.4, "speed_mode": "narrow_point"},
        {"id": "target-first", "map_asset_id": "target-map", "kind": "transition", "label": "楼层过渡 1", "x": 3.0, "y": 1.0, "yaw": 0.5, "speed_mode": "slow_point"},
        {"id": "target-second", "map_asset_id": "target-map", "kind": "transition", "label": "楼层过渡 2", "x": 4.0, "y": 2.0, "yaw": 0.75, "speed_mode": "narrow_point"},
    ])
    _set_execution_nodes(two_map_project, lobby=[
        {"kind": "transition", "id": "lobby-first"},
        {"kind": "transition", "id": "lobby-second"},
    ], target=[
        {"kind": "transition", "id": "target-first"},
        {"kind": "transition", "id": "target-second"},
    ])

    subtasks = _compile(two_map_project).task_json["subtasks"]
    by_name = {item["subtask_name"]: item["waypoints"] for item in subtasks}

    assert [point["waypoint_id"] for point in by_name["elevator_hall"]] == [
        "lobby_start", "lobby_1", "lobby_2", "lobby_wait", "lobby_elevator_center",
    ]
    assert [point["waypoint_id"] for point in by_name["1509"]] == [
        "target_wait", "1509_1", "1509_2", "target",
    ]
    assert [point["waypoint_id"] for point in by_name["1509_r"]] == [
        "1509_r_1", "1509_r_2", "target_return_wait", "target_return_elevator_center",
    ]
    assert [point["waypoint_id"] for point in by_name["elevator_hall_r"]] == [
        "lobby_return_wait", "lobby_r_1", "lobby_r_2", "lobby_return_start",
    ]
    # Speed belongs to the physical edge ending at a point.  On return, the
    # first edge is target→last transition (the target's normal arrival edge),
    # and only the next edge retraces the original narrow segment.
    assert [point["speed_mode"] for point in by_name["1509_r"][:2]] == ["single_point", "narrow_point"]
    assert [point["pose"]["orientation"] for point in by_name["1509_r"][:2]] == [
        {"x": 0.0, "y": 0.0, "z": sin(-2.391592653589793 / 2), "w": cos(-2.391592653589793 / 2)},
        {"x": 0.0, "y": 0.0, "z": sin(-2.641592653589793 / 2), "w": cos(-2.641592653589793 / 2)},
    ]
    transition_ids = {"lobby_1", "lobby_2", "1509_1", "1509_2", "1509_r_1", "1509_r_2", "lobby_r_1", "lobby_r_2"}
    for waypoints in by_name.values():
        for point in waypoints:
            if point["waypoint_id"] in transition_ids:
                assert point["waypoint_task_id"] == ""
                assert point["is_task_point"] is False


def test_target_return_transition_is_shared_by_task_json_and_location_manifest(two_map_project):
    """The target floor must relocalize at its first return transition, not the elevator wait."""
    two_map_project["waypoints"].extend([
        {"id": "target-first", "map_asset_id": "target-map", "kind": "transition", "label": "楼层过渡 1", "x": 3.0, "y": 1.0, "yaw": 0.5, "speed_mode": "slow_point"},
        {"id": "target-last", "map_asset_id": "target-map", "kind": "transition", "label": "楼层过渡 2", "x": 4.0, "y": 2.0, "yaw": 0.75, "speed_mode": "narrow_point"},
    ])
    _set_execution_nodes(two_map_project, target=[
        {"kind": "transition", "id": "target-first"},
        {"kind": "transition", "id": "target-last"},
    ])

    preview = _compile(two_map_project)
    task_return = next(item for item in preview.task_json["subtasks"] if item["subtask_name"] == "1509_r")["waypoints"][0]
    manifest = json.loads(next(
        item.content for item in preview.artifacts if item.relative_path == "runtime/loc_yaml_path.json"
    ))
    floor_return = manifest["loc_yaml"][0]["yaml_index"][1]["init_return"]

    assert task_return["waypoint_id"] == "1509_r_1"
    assert floor_return == {"x": 4.0, "y": 2.0, "z": 0.0, "yaw": pytest.approx(0.75 - pi)}
    assert floor_return["x"] != pytest.approx(2.0)
    assert floor_return["y"] != pytest.approx(-2.5)


def test_target_return_without_transitions_falls_back_to_the_elevator_wait_pose(two_map_project):
    """The door wait remains the only fallback when no task transition was marked."""
    preview = _compile(two_map_project)
    task_return = next(item for item in preview.task_json["subtasks"] if item["subtask_name"] == "1509_r")["waypoints"][0]
    manifest = json.loads(next(
        item.content for item in preview.artifacts if item.relative_path == "runtime/loc_yaml_path.json"
    ))
    floor_return = manifest["loc_yaml"][0]["yaml_index"][1]["init_return"]

    assert task_return["waypoint_id"] == "target_return_wait"
    assert task_return["pose"]["position"] == {"x": floor_return["x"], "y": floor_return["y"], "z": 0.0}


def test_compiler_rejects_transition_speed_modes_reserved_for_behavior_trees(two_map_project):
    two_map_project["waypoints"].append({
        "id": "unsafe-transition", "map_asset_id": "target-map", "kind": "transition",
        "label": "过渡点", "x": 3.0, "y": 1.0, "yaw": 0.0,
        "speed_mode": "elevator_in",
    })
    _set_execution_nodes(two_map_project, target=[
        {"kind": "transition", "id": "unsafe-transition"},
    ])

    with pytest.raises(CompilationError, match="过渡点速度模式"):
        _compile(two_map_project)


def test_exported_task_json_keeps_the_approved_readable_field_order(two_map_project):
    preview = _compile(two_map_project)
    task = next(item for item in preview.artifacts if item.relative_path.startswith("tasks/"))
    text = task.content.decode("utf-8")

    assert text.startswith('{\n  "subtasks": [\n')
    assert text.endswith("}\n")
    assert text.index('"waypoint_task_id"') < text.index('"is_task_point"')
    assert text.index('"is_task_point"') < text.index('"speed_mode"')
    assert json.loads(text) == preview.task_json


def test_exported_behavior_trees_keep_the_approved_readable_xml_hierarchy(two_map_project):
    preview = _compile(two_map_project)
    artifact = next(
        item for item in preview.artifacts if item.relative_path.endswith("elevator_out_n_x.xml")
    )
    text = artifact.content.decode("utf-8")

    assert text.startswith('<root main_tree_to_execute="MainTree">\n')
    assert '\n  <BehaviorTree ID="MainTree">\n' in text
    assert '\n    <Sequence name="WaitForElevator">\n' in text
    assert '\n      <GetTaskTargetInfo ' in text
    assert "</Sequence></BehaviorTree>" not in text
    assert text.endswith("\n")
    assert ElementTree.fromstring(text).tag == "root"


def test_waiting_point_is_one_point_five_metres_beyond_the_door_face(two_map_project):
    waiting = _compile(two_map_project).derived_points["lobby_wait"]
    assert isclose(waiting["x"], 0.0, abs_tol=1e-9)
    assert isclose(waiting["y"], 2.5, abs_tol=1e-9)


@pytest.mark.parametrize("yaw, expected", [(0.0, (0.0, 2.5)), (pi / 2, (-2.5, 0.0)), (pi, (0.0, -2.5)), (-pi / 2, (2.5, 0.0))])
def test_door_normals_cover_all_yaw_quadrants(two_map_project, yaw, expected):
    two_map_project["components"][1]["yaw"] = yaw
    waiting = _compile(two_map_project).derived_points["lobby_wait"]
    assert isclose(waiting["x"], expected[0], abs_tol=1e-9)
    assert isclose(waiting["y"], expected[1], abs_tol=1e-9)


@pytest.mark.parametrize("yaw, expected", [
    (0.0, -pi / 2), (pi / 2, 0.0), (pi, pi / 2), (-pi / 2, -pi),
])
def test_manifest_task_center_and_return_xml_share_the_inward_heading(two_map_project, yaw, expected):
    """Catches the manifest and actual return relocalization disagreeing by 90°."""
    two_map_project["components"][1]["yaw"] = yaw
    preview = _compile(two_map_project)
    manifest = json.loads(next(
        item.content for item in preview.artifacts if item.relative_path == "runtime/loc_yaml_path.json"
    ))
    assert manifest["loc_yaml"][0]["yaml_index"][0]["init_return"]["yaw"] == pytest.approx(expected)
    assert preview.derived_points["lobby_elevator_center"]["yaw"] == pytest.approx(expected)
    returned = next(item.content for item in preview.artifacts if item.relative_path.endswith("elevator_out_x_n.xml"))
    node = next(node for node in ElementTree.fromstring(returned).iter() if node.tag == "SetUseWheelOdom" and "yaw" in node.attrib)
    assert float(node.attrib["yaw"]) == pytest.approx(expected, abs=1e-8)


def test_compiler_rejects_the_lobby_asset_hidden_under_an_outdoor_binding(two_map_project):
    """Catches approved map paths silently pointing to a different indoor asset."""
    project = two_map_project
    project["localization_bindings"][0]["type"] = "outdoor"
    extra_asset = dict(project["map_assets"][0], id="unrelated-map")
    project["map_assets"].append(extra_asset)
    project["localization_bindings"].append({
        "id": "unrelated-indoor", "map_asset_id": "unrelated-map", "building": "1", "unit": "1", "type": "indoor",
    })
    project["waypoints"].append({
        "id": "unrelated-anchor", "map_asset_id": "unrelated-map", "x": 1.0, "y": 0.0, "yaw": 0.0,
    })
    project["localization_routes"][0].update({
        "binding_ids": ["lobby-binding", "unrelated-indoor", "floor-binding"],
        "links": [
            {"from_binding_id": "lobby-binding", "to_binding_id": "unrelated-indoor", "anchor": {"kind": "waypoint", "waypoint_id": "route-start"}},
            {"from_binding_id": "unrelated-indoor", "to_binding_id": "floor-binding", "anchor": {"kind": "waypoint", "waypoint_id": "unrelated-anchor"}},
        ],
    })

    with pytest.raises(CompilationError, match="所选大厅|室内编译"):
        _compile(project)


def test_compiler_rejects_a_waypoint_for_the_indoor_elevator_transfer(two_map_project):
    """Catches compiling elevator tasks with an empty runtime lift list."""
    two_map_project["localization_routes"][0]["links"][0]["anchor"] = {
        "kind": "waypoint", "waypoint_id": "route-start",
    }

    with pytest.raises(CompilationError, match="电梯组件"):
        _compile(two_map_project)


def test_compiler_rejects_missing_elevator_pair(two_map_project):
    two_map_project["components"] = two_map_project["components"][:-2] + two_map_project["components"][-1:]
    with pytest.raises(CompilationError, match="同一物理电梯"):
        _compile(two_map_project)


def test_compiler_rejects_out_of_bounds_waiting_point(two_map_project):
    two_map_project["map_assets"][0].update({"origin": [-1.0, -1.0, 0.0], "width": 2, "height": 2})
    with pytest.raises(CompilationError, match="地图边界"):
        _compile(two_map_project)


def test_xml_and_localization_substitutions_are_controlled(two_map_project):
    preview = _compile(two_map_project)
    contents = {item.relative_path: item.content.decode("utf-8") for item in preview.artifacts}
    inbound = contents["waypoint_tasks/gk1/1_1_elevator_in_n_x.xml"]
    outbound = contents["waypoint_tasks/gk1/1_1_elevator_out_n_x.xml"]
    returned = contents["waypoint_tasks/gk1/1_1_elevator_out_x_n.xml"]
    assert 'output_key="origin_floor" value="2"' in inbound
    assert 'map_url="/opt/ry/data/maps/高科一号/1_1/floor-2/map.yaml"' in outbound
    assert 'x="0" y="0"' in returned
    lobby_yaml = contents["runtime/localization/高科一号/1_1/indoor.yaml"]
    assert "map_path: /opt/ry/data/maps/高科一号/1_1/indoor" in lobby_yaml
    assert "map_path:" in lobby_yaml
    assert "{{" not in inbound + outbound + returned


def test_all_behavior_trees_use_the_task_origin_physical_floor(two_map_project):
    """Catches return trees overwriting origin_floor with the target landing."""
    preview = _compile(two_map_project)
    values_by_tree = {}
    for artifact in preview.artifacts:
        if not artifact.relative_path.startswith("waypoint_tasks/"):
            continue
        values = [
            node.attrib["value"]
            for node in ElementTree.fromstring(artifact.content).iter("SetBlackboard")
            if node.attrib.get("output_key") == "origin_floor"
        ]
        if values:
            values_by_tree[artifact.relative_path] = values

    assert values_by_tree == {
        "waypoint_tasks/gk1/1_1_elevator_in_n_x.xml": ["2"],
        "waypoint_tasks/gk1/1_1_elevator_in_x_n.xml": ["2"],
        "waypoint_tasks/gk1/1_1_elevator_out_n_x.xml": ["2"],
        "waypoint_tasks/gk1/1_1_elevator_out_x_n.xml": ["2"],
        "waypoint_tasks/gk1/1_1_close_elevdoor_n.xml": ["2"],
    }


def test_compiler_derives_origin_floor_from_the_landing_button_not_the_map_floor(two_map_project):
    """Catches the old map-floor-plus-one protocol mapping."""
    two_map_project["components"][1]["attributes"]["button_floor"] = -1

    preview = _compile(two_map_project)
    outgoing = next(item for item in preview.artifacts if item.relative_path.endswith("elevator_out_n_x.xml"))

    assert 'output_key="origin_floor" value="1"' in outgoing.content.decode("utf-8")


def test_compiler_skips_unavailable_elevator_buttons_when_deriving_physical_floors(two_map_project):
    """Catches every button above a missing panel key being offset by one."""
    two_map_project["physical_elevators"][0]["max_floor"] = 20
    two_map_project["physical_elevators"][0]["unavailable_button_floors"] = [11]

    preview = _compile(two_map_project)

    # XML keeps ``floor`` as a runtime blackboard placeholder. The compiled
    # task group is the consumer of the derived physical target floor.
    assert preview.task_json["task_group_name"] == "高科一号_1_14_1509"


def test_compiler_rejects_a_landing_without_an_explicit_button_floor(two_map_project):
    """Catches silently recreating the retired map-floor-plus-one fallback."""
    two_map_project["components"][1]["attributes"].pop("button_floor")

    with pytest.raises(CompilationError, match="按钮层"):
        _compile(two_map_project)


def test_bundle_contains_only_safe_versioned_artifacts(two_map_project):
    preview = _compile(two_map_project)
    with zipfile.ZipFile(BytesIO(bundle_zip(preview))) as archive:
        names = archive.namelist()
    assert "manifest.json" in names
    assert all(not name.startswith("/") and ".." not in Path(name).parts for name in names)
    assert all(name.startswith(("manifest.json", "tasks/", "waypoint_tasks/", "runtime/")) for name in names)


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda project: project["task_compiler"]["identity"].update({"community": ""}), "小区"),
        (lambda project: project["components"][-1]["attributes"].update({"door": ""}), "门牌"),
        (lambda project: project["components"].pop(0), "起点"),
        (lambda project: project["components"].pop(), "目标"),
        (lambda project: project.update({"scene_model": "indoor_outdoor"}), "室内"),
    ],
)
def test_compiler_rejects_missing_required_facts(two_map_project, mutate, expected):
    mutate(two_map_project)
    with pytest.raises(CompilationError, match=expected):
        _compile(two_map_project)


def test_compiler_rejects_duplicate_elevators(two_map_project):
    two_map_project["components"].append(dict(two_map_project["components"][1], id="another"))
    with pytest.raises(CompilationError, match="两个"):
        _compile(two_map_project)


def test_compiler_rejects_elevator_outside_the_shared_service_range(two_map_project):
    two_map_project["physical_elevators"][0]["max_floor"] = 14
    with pytest.raises(CompilationError, match="按钮层"):
        _compile(two_map_project)


def test_compiler_rejects_two_landings_that_reference_different_physical_elevators(two_map_project):
    two_map_project["physical_elevators"].append(
        {
            "id": "physical-elevator-b",
            "elevator_id": "10015",
            "elevator_protocol": "mqtt",
            "min_floor": 1,
            "max_floor": 15,
        }
    )
    two_map_project["components"][2]["attributes"]["physical_elevator_id"] = "physical-elevator-b"
    with pytest.raises(CompilationError, match="同一物理电梯"):
        _compile(two_map_project)


def test_compiler_rejects_a_shared_elevator_with_legacy_migration_conflict(two_map_project):
    two_map_project["physical_elevators"][0]["migration_conflict"] = "梯控协议不一致"

    with pytest.raises(CompilationError, match="旧数据冲突"):
        _compile(two_map_project)


def test_compiler_rejects_legacy_manual_binding_input_without_a_route(two_map_project):
    two_map_project["localization_routes"] = []
    two_map_project["localization_bindings"][0]["init_go"] = {"x": 0.0, "y": -2.0, "z": 0.0, "yaw": 0.0}

    with pytest.raises(CompilationError, match="迁移"):
        _compile(two_map_project)


def test_compiler_fingerprint_includes_route_referenced_waypoint_geometry(two_map_project):
    first = _compile(two_map_project).input_sha256
    two_map_project["waypoints"][0]["x"] = 1.0

    second = _compile(two_map_project).input_sha256

    assert second != first


def test_compiler_fingerprint_includes_saved_map_edits(two_map_project):
    """Catches reusing a preview generated before the map was erased."""
    two_map_project["map_edits"] = [{
        "id": "edit-1",
        "map_asset_id": two_map_project["map_assets"][0]["id"],
        "kind": "brush_erase",
        "radius_m": 0.2,
        "shape": "circle",
        "points": [{"x": -9.0, "y": -9.0}],
    }]
    first = _compile(two_map_project).input_sha256
    two_map_project["map_edits"][0]["points"][0]["x"] = -8.0

    second = _compile(two_map_project).input_sha256

    assert second != first


def test_compiler_fingerprint_includes_virtual_wall_segments(two_map_project):
    two_map_project["virtual_walls"] = [{
        "id": "virtual-wall-a",
        "map_asset_id": two_map_project["map_assets"][0]["id"],
        "start": {"x": -9.0, "y": -9.0},
        "end": {"x": -8.0, "y": -9.0},
    }]
    first = _compile(two_map_project).input_sha256
    two_map_project["virtual_walls"][0]["end"]["x"] = -7.0

    second = _compile(two_map_project).input_sha256

    assert second != first


def test_compiler_rejects_when_route_export_omits_the_selected_lobby_map(two_map_project):
    alternate = dict(two_map_project["map_assets"][0], id="alternate-lobby-map")
    two_map_project["map_assets"].append(alternate)
    two_map_project["localization_bindings"][0]["map_asset_id"] = alternate["id"]
    two_map_project["waypoints"][0]["map_asset_id"] = alternate["id"]
    two_map_project["waypoints"].append(
        {"id": "alternate-anchor", "map_asset_id": alternate["id"], "x": 0.0, "y": 0.0, "yaw": 0.0}
    )
    two_map_project["localization_routes"][0]["links"][0]["anchor"] = {
        "kind": "waypoint", "waypoint_id": "alternate-anchor",
    }

    with pytest.raises(CompilationError, match="定位路线"):
        _compile(two_map_project)


def test_manifest_is_experimental_and_fingerprints_artifacts(two_map_project):
    preview = _compile(two_map_project)
    assert preview.manifest["validation_status"] == "experimental_preview"
    assert preview.manifest["robot_runtime_changed"] is False
    assert preview.input_sha256 == preview.manifest["input_sha256"]
    assert len(preview.manifest["artifacts"]) == len(preview.artifacts)
    assert json.loads(next(item.content for item in preview.artifacts if item.relative_path.startswith("tasks/")).decode("utf-8"))["task_group_name"] == "高科一号_1_15_1509"


def test_gk1_store_preview_and_download_have_the_approved_indoor_structure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Exercise the store boundary with a controlled Gk1-shaped source tree.

    The assertions intentionally use the approved Gk1 sample's structural
    facts (four map-ordered subtasks, approved speed-mode sequence and the
    eight site behavior-tree names), rather than reading mutable `/opt/ry`
    task, map or behavior-tree files during a test run.
    """
    map_root = tmp_path / "robot-maps"
    monkeypatch.setattr(DeploymentStore, "MAP_ROOT", map_root.resolve())
    store = DeploymentStore(tmp_path / "deployments")
    project = store.create("Gk1 编译回归")
    store.set_scene_model(project["id"], "indoor")

    sources: list[Path] = []
    for floor in ("P1", "P2"):
        source = map_root / "gk1" / floor / "map.yaml"
        source.parent.mkdir(parents=True)
        source.with_name("map.pgm").write_bytes(b"P5\n40 40\n255\n" + bytes(40 * 40))
        source.write_text(f"image: map.pgm\nresolution: 0.2\norigin: [-2.0, -2.0, 0.0]\n# controlled {floor} fixture\n", encoding="utf-8")
        source.with_name("index.txt").write_text("0 0 0\n0 0 0 0.pcd\n", encoding="utf-8")
        source.with_name("0.pcd").write_bytes(b"# controlled cloud fixture\n")
        sources.append(source)

    lobby = store.import_map(project["id"], sources[0], "大厅", "lobby")
    target = store.import_map(project["id"], sources[1], "目标层", "typical_floor")
    store.add_map_instance(project["id"], {"map_id": lobby["id"], "role": "lobby", "building": "1", "unit": "1", "floor": 1})
    store.add_map_instance(project["id"], {"map_id": target["id"], "role": "typical_floor", "building": "1", "unit": "1", "floor": 15})
    store.add_component(project["id"], {"map_id": lobby["id"], "kind": "start", "x": -1.0, "y": -1.0})
    elevator = store.add_physical_elevator(project["id"], {"elevator_id": "A", "elevator_protocol": "mqtt", "min_floor": 1, "max_floor": 15})
    lobby_elevator = store.add_component(project["id"], {"map_id": lobby["id"], "kind": "elevator", "x": 0.0, "y": 0.0, "attributes": {"physical_elevator_id": elevator["id"], "button_floor": 1}})
    store.add_component(project["id"], {"map_id": target["id"], "kind": "elevator", "x": 0.0, "y": 1.0, "yaw": pi, "attributes": {"physical_elevator_id": elevator["id"], "button_floor": 15}})
    target_component = store.add_component(project["id"], {"map_id": target["id"], "kind": "target", "x": 1.0, "y": 1.0})
    store.update_component(project["id"], target_component["id"], {"attributes": {"door": "1509"}})
    store.update_task_compiler_config(project["id"], {"community": "高科一号"})
    _add_store_localization_route(store, project, lobby, target, lobby_elevator)

    preview = store.task_compiler_preview(project["id"])
    filename, payload = store.task_compiler_bundle(project["id"])

    assert filename == "高科一号_1_1_15_1509_experimental.zip"
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        assert set(archive.namelist()) == {
            "manifest.json",
            "tasks/高科一号_1_1_15_1509.json",
            "waypoint_tasks/gk1/1_1_elevator_in_n_x.xml",
            "waypoint_tasks/gk1/1_1_elevator_out_n_x.xml",
            "waypoint_tasks/gk1/1_1_close_elevdoor_x.xml",
            "waypoint_tasks/gk1/1_1_elevator_in_x_n.xml",
            "waypoint_tasks/gk1/1_1_elevator_out_x_n.xml",
                "waypoint_tasks/gk1/1_1_close_elevdoor_n.xml",
                "waypoint_tasks/gk1/start_task.xml",
                "waypoint_tasks/gk1/place_water.xml",
                "waypoint_tasks/gk1/task_complete.xml",
                "runtime/loc_yaml_path.json",
                "runtime/lift_id_list.json",
                "runtime/localization/高科一号/1_1/indoor.yaml",
                "runtime/localization/高科一号/1_1/floor-2.yaml",
                "runtime/maps/高科一号/1_1/indoor/map.yaml",
                "runtime/maps/高科一号/1_1/indoor/map.pgm",
                "runtime/maps/高科一号/1_1/floor-2/map.yaml",
                "runtime/maps/高科一号/1_1/floor-2/map.pgm",
                "runtime/maps/高科一号/1_1/indoor/index.txt",
                "runtime/maps/高科一号/1_1/indoor/0.pcd",
                "runtime/maps/高科一号/1_1/floor-2/index.txt",
                "runtime/maps/高科一号/1_1/floor-2/0.pcd",
        }

    subtasks = preview["task_json"]["subtasks"]
    assert [item["subtask_name"] for item in subtasks] == ["elevator_hall", "1509", "1509_r", "elevator_hall_r"]
    snapshot_sources = [Path(item["source_yaml"]) for item in store.get(project["id"])["map_assets"]]
    assert all(source.is_relative_to(store._project_dir(project["id"]) / "maps") for source in snapshot_sources)
    assert [item["map_url"] for item in subtasks] == [
        "/opt/ry/data/maps/高科一号/1_1/indoor/map.yaml",
        "/opt/ry/data/maps/高科一号/1_1/floor-2/map.yaml",
        "/opt/ry/data/maps/高科一号/1_1/floor-2/map.yaml",
        "/opt/ry/data/maps/高科一号/1_1/indoor/map.yaml",
    ]
    assert [[point["speed_mode"] for point in item["waypoints"]] for item in subtasks] == [
        ["task_point", "single_point", "elevator_in"],
        ["backward", "single_point"],
        ["task_point", "elevator_in"],
        ["backward", "single_point"],
    ]
    assert [[point["waypoint_task_id"] for point in item["waypoints"]] for item in subtasks] == [
        ["start_task", "1_1_elevator_in_n_x", "1_1_elevator_out_n_x"],
        ["1_1_close_elevdoor_x", "place_water"],
        ["1_1_elevator_in_x_n", "1_1_elevator_out_x_n"],
        ["1_1_close_elevdoor_n", "task_complete"],
    ]


def test_store_compiles_browser_uploaded_map_snapshots_after_upload_staging_is_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Experimental exports must use the durable project snapshot, never upload staging."""
    map_root = tmp_path / "robot-maps"
    upload_root = tmp_path / "browser-upload"
    map_root.mkdir()
    monkeypatch.setattr(DeploymentStore, "MAP_ROOT", map_root.resolve())
    store = DeploymentStore(tmp_path / "deployments")
    project = store.create("Gk1")
    store.set_scene_model(project["id"], "indoor")

    uploaded: list[Path] = []
    for floor in ("lobby", "target"):
        source = upload_root / floor / "map.yaml"
        source.parent.mkdir(parents=True)
        source.with_name("map.pgm").write_bytes(b"P5\n40 40\n255\n" + bytes(40 * 40))
        source.write_text(
            f"image: map.pgm\nresolution: 0.2\norigin: [-2.0, -2.0, 0.0]\n# {floor}\n",
            encoding="utf-8",
        )
        source.with_name("index.txt").write_text("0 0 0\n0 0 0 0.pcd\n", encoding="utf-8")
        source.with_name("0.pcd").write_bytes(b"# controlled cloud fixture\n")
        uploaded.append(source)

    lobby = store.import_uploaded_map(project["id"], uploaded[0], "大厅", "lobby", upload_root)
    target = store.import_uploaded_map(project["id"], uploaded[1], "目标层", "typical_floor", upload_root)
    for source in uploaded:
        source.unlink()
        source.with_name("map.pgm").unlink()
        source.with_name("index.txt").unlink()
        source.with_name("0.pcd").unlink()
    store.add_map_instance(project["id"], {"map_id": lobby["id"], "role": "lobby", "building": "1", "unit": "1", "floor": 1})
    store.add_map_instance(project["id"], {"map_id": target["id"], "role": "typical_floor", "building": "1", "unit": "1", "floor": 15})
    shared = store.add_physical_elevator(project["id"], {"elevator_id": "10014", "elevator_protocol": "mqtt", "min_floor": 1, "max_floor": 15})
    store.add_component(project["id"], {"map_id": lobby["id"], "kind": "start", "x": -1.0, "y": -1.0})
    lobby_elevator = store.add_component(project["id"], {"map_id": lobby["id"], "kind": "elevator", "x": 0.0, "y": 0.0, "attributes": {"physical_elevator_id": shared["id"], "button_floor": 1}})
    store.add_component(project["id"], {"map_id": target["id"], "kind": "elevator", "x": 0.0, "y": 1.0, "yaw": pi, "attributes": {"physical_elevator_id": shared["id"], "button_floor": 15}})
    target_component = store.add_component(project["id"], {"map_id": target["id"], "kind": "target", "x": 1.0, "y": 1.0})
    store.update_component(project["id"], target_component["id"], {"attributes": {"door": "1509"}})
    store.update_task_compiler_config(project["id"], {"community": "高科一号"})
    _add_store_localization_route(store, project, lobby, target, lobby_elevator)

    preview = store.task_compiler_preview(project["id"])

    sources = [Path(item["source_yaml"]) for item in store.get(project["id"])["map_assets"]]
    assert all(source.is_file() and source.is_relative_to(store._project_dir(project["id"]) / "maps") for source in sources)
    assert [item["map_url"] for item in preview["task_json"]["subtasks"]] == [
        "/opt/ry/data/maps/高科一号/1_1/indoor/map.yaml",
        "/opt/ry/data/maps/高科一号/1_1/floor-2/map.yaml",
        "/opt/ry/data/maps/高科一号/1_1/floor-2/map.yaml",
        "/opt/ry/data/maps/高科一号/1_1/indoor/map.yaml",
    ]
    assert any(item["path"].startswith("waypoint_tasks/gk1/") for item in preview["artifacts"])
