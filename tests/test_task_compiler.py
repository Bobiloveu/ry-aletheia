from __future__ import annotations

import json
import zipfile
from io import BytesIO
from math import isclose, pi
from pathlib import Path

import pytest

from autodrive_console.task_compiler import CompilationError, bundle_zip, compile_indoor_elevator


@pytest.fixture
def two_map_project(tmp_path: Path) -> dict:
    map_root = tmp_path / "maps"
    lobby_yaml = map_root / "gk1" / "P1" / "map.yaml"
    target_yaml = map_root / "gk1" / "P2" / "map.yaml"
    for source in (lobby_yaml, target_yaml):
        source.parent.mkdir(parents=True)
        source.write_text("image: map.pgm\nresolution: 1.0\norigin: [-10.0, -10.0, 0.0]\n", encoding="utf-8")

    assets = [
        {"id": "lobby-map", "source_yaml": str(lobby_yaml), "origin": [-10.0, -10.0, 0.0], "width": 40, "height": 40, "resolution_m": 1.0},
        {"id": "target-map", "source_yaml": str(target_yaml), "origin": [-10.0, -10.0, 0.0], "width": 40, "height": 40, "resolution_m": 1.0},
    ]
    return {
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
        "task_compiler": {"identity": {"community": "高科一号"}},
        "components": [
            {"id": "start", "map_asset_id": "lobby-map", "kind": "start", "x": 0.0, "y": -2.0, "yaw": 0.0, "attributes": {}},
            {"id": "lobby-elevator", "map_asset_id": "lobby-map", "kind": "elevator", "x": 0.0, "y": 0.0, "yaw": 0.0, "attributes": {"elevator_id": "A", "width_m": 2.0, "height_m": 2.0, "wait_distance_m": 1.5, "map_floor": 1, "physical_floor": 2}},
            {"id": "target-elevator", "map_asset_id": "target-map", "kind": "elevator", "x": 2.0, "y": 0.0, "yaw": pi, "attributes": {"elevator_id": "A", "width_m": 2.0, "height_m": 2.0, "wait_distance_m": 1.5, "map_floor": 15, "physical_floor": 16}},
            {"id": "target", "map_asset_id": "target-map", "kind": "target", "x": 5.0, "y": 3.0, "yaw": 0.25, "attributes": {"door": "1509"}},
        ],
        "_test_map_root": str(map_root),
    }


def _compile(project: dict):
    return compile_indoor_elevator(project, map_root=Path(project["_test_map_root"]))


def test_compiler_emits_four_subtasks_and_approved_speed_sequence(two_map_project):
    payload = _compile(two_map_project).task_json
    assert [item["subtask_name"] for item in payload["subtasks"]] == ["elevator_hall", "1509", "1509_r", "elevator_hall_r"]
    assert [[point["speed_mode"] for point in item["waypoints"]] for item in payload["subtasks"]] == [
        ["task_point", "single_point", "elevator_in"],
        ["backward", "single_point"],
        ["single_point", "task_point", "elevator_in"],
        ["backward", "single_point"],
    ]


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


def test_compiler_rejects_missing_elevator_pair(two_map_project):
    two_map_project["components"] = two_map_project["components"][:-2] + two_map_project["components"][-1:]
    with pytest.raises(CompilationError, match="同一电梯"):
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
    assert 'map_url="' + str(Path(two_map_project["map_assets"][1]["source_yaml"])) + '"' in outbound
    assert 'x="0" y="0"' in returned
    lobby_yaml = contents["localization/rycx_loc_livox_1_1_lobby.yaml"]
    assert "map_path: " + str(Path(two_map_project["map_assets"][0]["source_yaml"]).parent) in lobby_yaml
    assert "map_path:" in lobby_yaml
    assert "{{" not in inbound + outbound + returned


def test_bundle_contains_only_safe_versioned_artifacts(two_map_project):
    preview = _compile(two_map_project)
    with zipfile.ZipFile(BytesIO(bundle_zip(preview))) as archive:
        names = archive.namelist()
    assert "manifest.json" in names
    assert all(not name.startswith("/") and ".." not in Path(name).parts for name in names)
    assert all(name.startswith(("manifest.json", "tasks/", "waypoint_tasks/", "localization/")) for name in names)


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


def test_compiler_rejects_elevator_floor_that_disagrees_with_map_instance(two_map_project):
    two_map_project["components"][2]["attributes"]["map_floor"] = 14
    with pytest.raises(CompilationError, match="楼层"):
        _compile(two_map_project)


def test_manifest_is_experimental_and_fingerprints_artifacts(two_map_project):
    preview = _compile(two_map_project)
    assert preview.manifest["validation_status"] == "experimental_preview"
    assert preview.manifest["robot_runtime_changed"] is False
    assert preview.input_sha256 == preview.manifest["input_sha256"]
    assert len(preview.manifest["artifacts"]) == len(preview.artifacts)
    assert json.loads(next(item.content for item in preview.artifacts if item.relative_path.startswith("tasks/")).decode("utf-8"))["task_group_name"] == "高科一号_1_15_1509"
