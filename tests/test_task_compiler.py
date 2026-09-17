from __future__ import annotations

import json
import zipfile
from io import BytesIO
from math import isclose, pi
from pathlib import Path
from xml.etree import ElementTree

import pytest

from autodrive_console.deployment import DeploymentStore
from autodrive_console.task_compiler import CompilationError, bundle_zip, compile_indoor_elevator


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
                "elevator_protocol": "bluetooth",
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
        ],
        "localization_routes": [{
            "id": "route-1", "building": "1", "unit": "1",
            "binding_ids": ["lobby-binding", "floor-binding"],
            "task_start_waypoint_id": "route-start", "task_target_waypoint_id": "route-target",
            "links": [{
                "from_binding_id": "lobby-binding", "to_binding_id": "floor-binding",
                "anchor": {"kind": "component_center", "component_id": "lobby-elevator"},
            }],
        }],
        "_test_map_root": str(map_root),
    }


def _compile(project: dict):
    return compile_indoor_elevator(project, map_root=Path(project["_test_map_root"]))


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
    store.create_localization_route(project["id"], {
        "building": "1", "unit": "1",
        "binding_ids": [indoor["id"], floor["id"]],
        "task_start_waypoint_id": start["id"],
        "task_target_waypoint_id": task_target["id"],
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
        ["single_point", "task_point", "elevator_in"],
        ["backward", "single_point"],
    ]


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
    return_inbound = contents["waypoint_tasks/gk1/1_1_elevator_in_x_n.xml"]
    outbound = contents["waypoint_tasks/gk1/1_1_elevator_out_n_x.xml"]
    returned = contents["waypoint_tasks/gk1/1_1_elevator_out_x_n.xml"]
    assert 'output_key="origin_floor" value="2"' in inbound
    assert 'output_key="origin_floor" value="16"' in return_inbound
    assert 'map_url="/opt/ry/data/maps/高科一号/1_1/floor-2/map.yaml"' in outbound
    assert 'x="0" y="0"' in returned
    lobby_yaml = contents["runtime/localization/高科一号/1_1/indoor.yaml"]
    assert "map_path: /opt/ry/data/maps/高科一号/1_1/indoor" in lobby_yaml
    assert "map_path:" in lobby_yaml
    assert "{{" not in inbound + outbound + returned


def test_compiler_derives_origin_floor_from_the_landing_button_not_the_map_floor(two_map_project):
    """Catches the old map-floor-plus-one protocol mapping."""
    two_map_project["components"][1]["attributes"]["button_floor"] = -1

    preview = _compile(two_map_project)
    outgoing = next(item for item in preview.artifacts if item.relative_path.endswith("elevator_out_n_x.xml"))

    assert 'output_key="origin_floor" value="1"' in outgoing.content.decode("utf-8")


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
            "elevator_protocol": "bluetooth",
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
    elevator = store.add_physical_elevator(project["id"], {"elevator_id": "A", "elevator_protocol": "bluetooth", "min_floor": 1, "max_floor": 15})
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
        ["single_point", "task_point", "elevator_in"],
        ["backward", "single_point"],
    ]
    assert [[point["waypoint_task_id"] for point in item["waypoints"]] for item in subtasks] == [
        ["start_task", "1_1_elevator_in_n_x", "1_1_elevator_out_n_x"],
        ["1_1_close_elevdoor_x", "place_water"],
        ["", "1_1_elevator_in_x_n", "1_1_elevator_out_x_n"],
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
    shared = store.add_physical_elevator(project["id"], {"elevator_id": "10014", "elevator_protocol": "bluetooth", "min_floor": 1, "max_floor": 15})
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
