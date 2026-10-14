"""Fixed task execution poses share the controlled localization export pipeline."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
import yaml

from autodrive_console.location_manifest import LocationManifestError, compile_location_manifest


def _project(tmp_path: Path):
    root = tmp_path / "maps"
    assets, bindings, components, entries = [], [], [], []
    for index, kind in enumerate(("indoor", "floor", "floor")):
        source = root / str(index) / "map.yaml"
        source.parent.mkdir(parents=True)
        source.write_text("image: map.pgm\nresolution: 1.0\norigin: [-5, -5, 0]\n", encoding="utf-8")
        source.with_name("map.pgm").write_bytes(b"P5\n10 10\n255\n" + bytes([205, 0]) * 50)
        source.with_name("index.txt").write_text("0 0 0\n0 0 0 0.pcd\n", encoding="utf-8")
        source.with_name("0.pcd").write_bytes(b"# fixture cloud\n")
        assets.append({"id": f"map-{index}", "source_yaml": str(source), "origin": [-5, -5, 0], "resolution_m": 1, "width": 10, "height": 10})
        bindings.append({"id": f"binding-{index}", "map_asset_id": f"map-{index}", "type": kind, "building": "1", "unit": "2", **({"floor_template": str(index)} if kind == "floor" else {})})
        components.append({"id": f"lift-{index}", "map_asset_id": f"map-{index}", "kind": "elevator", "x": 0, "y": 0, "yaw": 0, "attributes": {"physical_elevator_id": "physical"}})
        entries.append({"binding_id": f"binding-{index}", "init_go": {"x": index, "y": 1, "z": 0, "yaw": .2}, "init_return": {"x": -index, "y": 2, "z": 0, "yaw": -.3}, "elevator_anchors": [f"lift-{index}"]})
    return {"id": "project", "task_compiler": {"identity": {"community": "site"}}, "map_assets": assets, "localization_bindings": bindings, "components": components, "physical_elevators": [{"id": "physical", "elevator_id": "10044"}], "localization_routes": [], "map_edits": []}, root, entries


def test_fixed_entries_export_multiple_floors_without_persisted_route(tmp_path):
    project, root, entries = _project(tmp_path)
    before = deepcopy(project)
    originals = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    result = compile_location_manifest(project, map_root=root, execution_entries=entries)
    document = json.loads(result.json_bytes)
    assert len(document["loc_yaml"]) == 1
    assert document["loc_yaml"][0]["building"] == "1"
    assert document["loc_yaml"][0]["unit"] == "2"
    actual = document["loc_yaml"][0]["yaml_index"]
    assert [value.get("floor", value["type"]) for value in actual] == ["indoor", "1", "2"]
    assert actual[2]["init_go"] == {"x": 2, "y": 1, "z": 0, "yaw": .2}
    assert actual[2]["init_return"] == {"x": -2, "y": 2, "z": 0, "yaw": -.3}
    artifacts = {item.relative_path: item.content for item in result.artifacts}
    localization = yaml.safe_load(artifacts["runtime/localization/site/1_2/floor-2.yaml"])
    pose = localization["system"]["init_pose"]
    assert (pose["x"], pose["y"], pose["yaw"]) == (2, 1, .2)
    assert pose["z"] == .4  # Preserve the approved localization template height.
    assert json.loads(artifacts["runtime/lift_id_list.json"])["lifts"] == [{"lift_id": "10044", "building": "1", "unit": "2"}]
    assert artifacts["runtime/maps/site/1_2/floor-2/map.pgm"] == b"P5\n10 10\n255\n" + bytes([254, 0]) * 50
    assert project == before
    assert all(path.read_bytes() == value for path, value in originals.items())


def test_fixed_entries_export_only_used_bindings_and_allow_no_lifts(tmp_path):
    project, root, entries = _project(tmp_path)
    entries[1]["elevator_anchors"] = []
    result = compile_location_manifest(project, map_root=root, execution_entries=[entries[1]])
    actual = json.loads(result.json_bytes)["loc_yaml"][0]["yaml_index"]
    assert len(actual) == 1 and actual[0]["floor"] == "1"
    assert "runtime/maps/site/1_2/indoor/map.pgm" not in {item.relative_path for item in result.artifacts}


@pytest.mark.parametrize("change", ["empty", "duplicate", "unknown_binding", "unknown_field", "missing_pose", "extra_pose", "nonfinite", "huge_number", "bool_pose", "text_pose", "outside_go", "outside_return", "wrong_anchor_map", "missing_anchor", "non_elevator", "repeated_anchor", "unknown_physical", "duplicate_binding_id", "bad_source", "missing_field", "anchors_not_list", "anchor_not_string", "entries_not_list"])
def test_fixed_entries_reject_invalid_controlled_execution(tmp_path, change):
    project, root, entries = _project(tmp_path)
    if change == "empty": entries = []
    elif change == "duplicate": entries.append(deepcopy(entries[0]))
    elif change == "unknown_binding": entries[0]["binding_id"] = "foreign"
    elif change == "unknown_field": entries[0]["unapproved"] = True
    elif change == "missing_pose": entries[0]["init_go"].pop("z")
    elif change == "extra_pose": entries[0]["init_go"]["source"] = "foreign"
    elif change == "nonfinite": entries[0]["init_go"]["yaw"] = float("nan")
    elif change == "huge_number": entries[0]["init_go"]["x"] = 10 ** 1000
    elif change == "bool_pose": entries[0]["init_go"]["x"] = True
    elif change == "text_pose": entries[0]["init_go"]["x"] = "0"
    elif change == "outside_go": entries[0]["init_go"]["x"] = 6
    elif change == "outside_return": entries[0]["init_return"]["y"] = -6
    elif change == "wrong_anchor_map": entries[0]["elevator_anchors"] = ["lift-1"]
    elif change == "missing_anchor": entries[0]["elevator_anchors"] = ["foreign"]
    elif change == "non_elevator": project["components"][0]["kind"] = "target"
    elif change == "repeated_anchor": entries[0]["elevator_anchors"] *= 2
    elif change == "unknown_physical": project["components"][0]["attributes"]["physical_elevator_id"] = "foreign"
    elif change == "duplicate_binding_id": project["localization_bindings"][1]["id"] = "binding-0"
    elif change == "bad_source": project["map_assets"][0]["source_yaml"] = str(tmp_path / "foreign.yaml")
    elif change == "missing_field": entries[0].pop("elevator_anchors")
    elif change == "anchors_not_list": entries[0]["elevator_anchors"] = "lift-0"
    elif change == "anchor_not_string": entries[0]["elevator_anchors"] = [{}]
    elif change == "entries_not_list": entries = tuple(entries)
    with pytest.raises(LocationManifestError):
        compile_location_manifest(project, map_root=root, execution_entries=entries)


def test_fixed_entries_reject_one_physical_lift_shared_between_buildings(tmp_path):
    project, root, entries = _project(tmp_path)
    project["localization_bindings"][2]["building"] = "2"
    with pytest.raises(LocationManifestError, match="多个楼栋"):
        compile_location_manifest(project, map_root=root, execution_entries=entries)


def test_fixed_entries_group_distinct_buildings_with_independent_lifts(tmp_path):
    project, root, entries = _project(tmp_path)
    project["localization_bindings"][2]["building"] = "2"
    project["components"][2]["attributes"]["physical_elevator_id"] = "physical-2"
    project["physical_elevators"].append({"id": "physical-2", "elevator_id": "10045"})
    result = compile_location_manifest(project, map_root=root, execution_entries=entries)
    document = json.loads(result.json_bytes)
    assert [(group["building"], len(group["yaml_index"])) for group in document["loc_yaml"]] == [("1", 2), ("2", 1)]


def test_omitting_fixed_entries_preserves_required_legacy_route(tmp_path):
    project, root, _ = _project(tmp_path)
    with pytest.raises(LocationManifestError, match="缺少定位路线"):
        compile_location_manifest(project, map_root=root)
