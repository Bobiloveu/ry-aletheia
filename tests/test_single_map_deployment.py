from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import shutil
import zipfile
from xml.etree import ElementTree as ET

import pytest

from autodrive_console.automatic_route import derive_localization_routes
from autodrive_console.deployment import DeploymentStore
from autodrive_console.fixed_task_compiler import compile_fixed_task_lines
from test_task_compiler import two_map_project
from test_fixed_task_compiler import fixed_project, compile_fixed, waypoints


STAGES = ("ferry", "outdoor", "lobby", "target_floor")


def standalone_project(two_map_project, stage, mode="multi"):
    p = fixed_project(two_map_project)
    asset = p["map_assets"][0]
    asset['label'] = '单图场景'
    map_id = asset["id"]
    binding_type = {"lobby": "indoor", "target_floor": "floor"}.get(stage, stage)
    p.update(task_mode=mode, deployment_flow=[{"id": stage, "type": stage}],
             map_assets=[asset], map_stage_assignments=[{"stage": stage, "map_asset_id": map_id}],
             physical_elevators=[], localization_routes=[])
    instance = {"map_asset_id": map_id, "role": "typical_floor" if stage == "target_floor" else stage,
                "scope": "global" if stage == "ferry" else "unit",
                "building": "" if stage == "ferry" else "1", "unit": "" if stage == "ferry" else "1",
                "floor": None}
    p["map_instances"] = [instance]
    p["localization_bindings"] = [{"id": "binding", "map_asset_id": map_id, "type": binding_type,
        "building": instance["building"], "unit": instance["unit"],
        **({"floor_template": "2"} if stage == "target_floor" else {})}]
    p["components"] = [
        {"id": "start", "kind": "start", "map_asset_id": map_id, "x": 0., "y": -2., "yaw": .4,
         "attributes": {}, "generated_waypoint_ids": ["route-start"]},
        {"id": "pickup", "kind": "target", "map_asset_id": map_id, "x": 4., "y": 4., "yaw": 0.,
         "attributes": {}, "generated_waypoint_ids": ["route-pickup"]},
        {"id": "target", "kind": "target", "map_asset_id": map_id, "x": 5., "y": 3., "yaw": .25,
         "attributes": {"door": "1509"}, "generated_waypoint_ids": ["route-target"]},
    ]
    p["waypoints"] = [{"id": c["generated_waypoint_ids"][0], "map_asset_id": map_id,
                       "generated_by": c["id"], "kind": c["kind"],
                       **{k: c[k] for k in ("x", "y", "yaw")}} for c in p["components"]]
    p["task_lines"] = [{"id": "line-a", "name": "同图配送", "start_component_id": "start", "steps": [
        {"kind": "component", "id": "pickup", "action": {"purpose": "pickup", "cargo_id": 1, "operation": "open"}},
        {"kind": "component", "id": "target", "action": {"purpose": "delivery", "cargo_id": 1, "operation": "unload"}},
    ]}]
    return p


@pytest.mark.parametrize("stage", STAGES)
def test_every_stage_can_be_saved_and_reopened_alone(tmp_path, stage):
    store = DeploymentStore(tmp_path / "projects")
    p = store.create("单图场景", "multi")
    store.set_deployment_flow(p["id"], [{"id": stage, "type": stage}])
    assert [s["type"] for s in store.get(p["id"])["deployment_flow"]] == [stage]
    assert [s["stage"] for s in store.stage_plan(p["id"])["stages"]] == [stage]


@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.parametrize("mode", ("single", "multi"))
def test_standalone_export_preserves_actions_and_return_without_other_stages(two_map_project, stage, mode):
    p = standalone_project(two_map_project, stage, mode)
    before = deepcopy(p)
    preview = compile_fixed(p)
    assert p == before
    assert preview.manifest["task_mode"] == mode
    nodes = waypoints(preview)
    assert len(set(preview.manifest["subtask_map_asset_ids"])) == 1
    assert nodes[-1]["pose"]["position"] == nodes[0]["pose"]["position"]
    assert nodes[-1]["pose"]["orientation"] == nodes[0]["pose"]["orientation"]
    assert not any("elevator" in w["waypoint_task_id"] for w in nodes)
    trees = {Path(a.relative_path).stem: ET.fromstring(a.content) for a in preview.artifacts if a.relative_path.endswith('.xml')}
    executed = [trees[w['waypoint_task_id']] for w in nodes if w['waypoint_task_id']]
    assert [c.attrib for tree in executed for c in tree.iter('CargoSingleCommand')] == [
        {'caogo_id': '1', 'operation_code': '0'}, {'caogo_id': '1', 'operation_code': '2'}]
    assert sum(n.attrib.get('status_code') == '109' for tree in executed for n in tree.iter('PublishTaskStatus')) == 1
    if mode == "multi":
        stem = {"ferry": "sub_outdoor_eguard", "outdoor": "outdoor/1_1",
                "lobby": "indoor/1_1", "target_floor": "floor/1_1_n_n09"}[stage]
        assert preview.manifest["multi_task_files"] == [f"multi_tasks/高科一号/{stem}.json", f"multi_tasks/高科一号/{stem}_r.json"]
        members = {a.relative_path: a for a in preview.artifacts}
        fragments = [json.loads(members[path].content) for path in preview.manifest["multi_task_files"]]
        assert all(set(d) == {"change_loc", "map_url", "pcd_url", "subtask_name", "waypoints"} for d in fragments)
        assert [w for d in fragments for w in d["waypoints"]] == nodes
        if stage == "target_floor":
            assert preview.manifest["route_families"][0]["targets"][0]["physical_floor"] is None
    else:
        assert any(a.relative_path.startswith("tasks/") for a in preview.artifacts)
    if stage == "ferry":
        loc = json.loads(next(a.content for a in preview.artifacts if a.relative_path == "runtime/loc_yaml_path.json"))
        assert loc["loc_yaml"][0]["building"] == loc["loc_yaml"][0]["unit"] == ""


def test_single_floor_multiple_lines_export_independent_pairs(two_map_project):
    p = standalone_project(two_map_project, "target_floor")
    target = deepcopy(p["components"][-1]); target.update(id="target-b", x=6.)
    target["attributes"]["door"] = "1508"; p["components"].append(target)
    line = deepcopy(p["task_lines"][0]); line.update(id="line-b", name="1508")
    line["steps"][-1]["id"] = "target-b"; p["task_lines"].append(line)
    result = compile_fixed_task_lines(p, map_root=Path(p["_test_map_root"]))
    assert len(result.manifest["multi_task_files"]) == 4
    assert {item["subtask_count"] for item in result.manifest["compiled_task_lines"]} == {2}
    assert set(result.manifest["subtask_map_asset_ids"]) == {"lobby-map"}


@pytest.mark.parametrize("stage", STAGES)
def test_standalone_route_derivation_does_not_require_an_elevator(two_map_project, stage):
    p = standalone_project(two_map_project, stage)
    # Pickup targets are valid business locations as well, not phantom maps.
    routes = derive_localization_routes(p)
    assert routes
    assert all(r["binding_ids"] == ["binding"] and r["links"] == [] for r in routes)


@pytest.mark.parametrize("stage", STAGES)
def test_store_preview_and_zip_finish_for_single_map_multi(tmp_path, two_map_project, stage):
    p = standalone_project(two_map_project, stage)
    store = DeploymentStore(tmp_path / "projects")
    document = store.create("单图导出", "multi")
    root = store._project_dir(document["id"]) / "maps"
    shutil.copytree(p["_test_map_root"], root)
    for asset in p["map_assets"]:
        asset["source_yaml"] = str(root / Path(asset["source_yaml"]).relative_to(p["_test_map_root"]))
    document.update({k: v for k, v in p.items() if k not in {"id", "_test_map_root"}})
    store._write_json(store._document_path(document["id"]), document)
    assert store.validate_topology(document['id'])['valid']
    preview = store.task_compiler_preview(document["id"])
    assert preview["status"] == "ready" and preview["errors"] == []
    _, body = store.task_compiler_bundle(document["id"])
    with zipfile.ZipFile(BytesIO(body)) as archive:
        assert len([path for path in archive.namelist() if path.startswith("multi_tasks/")]) == 2


@pytest.mark.parametrize('stage', STAGES)
def test_legacy_single_map_retains_facts_and_can_save_a_line_then_export(tmp_path, two_map_project, stage):
    from test_fixed_compiler_consistency import store_project
    p = standalone_project(two_map_project, stage)
    recipe = p.pop('task_lines')[0]
    p.pop('active_task_line_id')
    store, identifier = store_project(tmp_path, p)
    reopened = store.get(identifier)
    assert reopened['task_lines'] == []
    assert reopened['active_task_line_id'] is None
    for old, current in zip(p['components'], reopened['components']):
        assert {k: current[k] for k in ('id', 'kind', 'map_asset_id', 'x', 'y', 'yaw')} == {
            k: old[k] for k in ('id', 'kind', 'map_asset_id', 'x', 'y', 'yaw')}
        assert all(current['attributes'][k] == value for k, value in old['attributes'].items())
    assert reopened['map_instances'] == p['map_instances']
    store.save_task_line(identifier, {k: v for k, v in recipe.items() if k != 'id'})
    assert store.task_compiler_preview(identifier)['status'] == 'ready'
    assert store.task_compiler_bundle(identifier)[1]
