import pytest

from autodrive_console.task_route_families import TaskRouteFamilyError, derive_task_route_families


def _project(*, stages=("lobby", "target_floor"), targets=("1501", "1502")):
    instances = [
        {"map_asset_id": "lobby", "role": "lobby", "building": "1", "unit": "1", "floor": 1},
        {"map_asset_id": "floor", "role": "typical_floor", "building": "1", "unit": "1", "floor": 15},
    ]
    if "outdoor" in stages:
        instances.append({"map_asset_id": "outdoor", "role": "outdoor", "building": "1", "unit": "1", "floor": 1})
    if "ferry" in stages:
        instances.append({"map_asset_id": "ferry", "role": "ferry"})
    return {
        "deployment_flow": [{"id": item, "type": item} for item in stages],
        "map_instances": instances,
        "components": [
            {"id": f"target-{index}", "map_asset_id": "floor", "kind": "target", "attributes": {"door": door}}
            for index, door in enumerate(targets)
        ],
    }


def test_lobby_to_target_requires_only_indoor_and_floor_outputs():
    family = derive_task_route_families(_project())[0]
    assert family.required_outputs == frozenset({"indoor", "floor"})
    assert [item.floor_stem for item in family.targets] == ["1_1_n_n01", "1_1_n_n02"]
    assert (family.targets[0].physical_floor, family.targets[0].door) == (15, "01")


def test_floorless_target_map_derives_runtime_floor_and_room_prefix_from_its_elevator_landing():
    """Catches restoring manual map-instance floors after the map stage."""
    project = _project(targets=("1501",))
    project["map_instances"][1]["floor"] = None
    project["physical_elevators"] = [{
        "id": "lift-1", "elevator_id": "10044", "min_floor": 1, "max_floor": 15,
    }]
    project["components"].append({
        "id": "floor-lift", "map_asset_id": "floor", "kind": "elevator",
        "attributes": {"physical_elevator_id": "lift-1", "button_floor": 15},
    })

    target = derive_task_route_families(project)[0].targets[0]

    assert (target.physical_floor, target.button_floor, target.door) == (14, 15, "01")


def test_optional_stages_are_derived_only_when_present_in_flow():
    family = derive_task_route_families(_project(stages=("ferry", "outdoor", "lobby", "target_floor")))[0]
    assert family.required_outputs == frozenset({"ferry", "outdoor", "indoor", "floor"})
    assert family.shared_bindings["ferry"].map_asset_id == "ferry"
    assert family.shared_bindings["outdoor"].map_asset_id == "outdoor"


def test_ferry_is_global_but_outdoor_maps_remain_per_building_unit():
    project = _project(stages=("ferry", "outdoor", "lobby", "target_floor"), targets=("1501",))
    project["map_instances"].extend([
        {"map_asset_id": "outdoor-2", "role": "outdoor", "scope": "unit", "building": "2", "unit": "1", "floor": 1},
        {"map_asset_id": "lobby-2", "role": "lobby", "scope": "unit", "building": "2", "unit": "1", "floor": 1},
        {"map_asset_id": "floor-2", "role": "typical_floor", "scope": "unit", "building": "2", "unit": "1", "floor": 15},
    ])
    project["components"].append({
        "id": "target-2", "map_asset_id": "floor-2", "kind": "target", "attributes": {"door": "1501"},
    })

    families = derive_task_route_families(project)

    assert [(item.building, item.unit) for item in families] == [("1", "1"), ("2", "1")]
    assert {item.shared_bindings["ferry"].map_asset_id for item in families} == {"ferry"}
    assert [item.shared_bindings["outdoor"].map_asset_id for item in families] == ["outdoor", "outdoor-2"]


def test_explicit_wrong_map_instance_scope_is_rejected():
    project = _project(stages=("ferry", "lobby", "target_floor"), targets=("1501",))
    next(item for item in project["map_instances"] if item["role"] == "ferry")["scope"] = "unit"

    with pytest.raises(TaskRouteFamilyError, match="地图实例归属"):
        derive_task_route_families(project)


def test_floor_override_uses_explicit_room_file_stem():
    project = _project(targets=("501",))
    project["map_instances"][1].update({"role": "floor_override", "floor": 5})
    assert derive_task_route_families(project)[0].targets[0].floor_stem == "1_1_5_501"


@pytest.mark.parametrize("room", ("501", "150", "A1501"))
def test_invalid_target_room_is_rejected(room):
    with pytest.raises(TaskRouteFamilyError):
        derive_task_route_families(_project(targets=(room,)))


def test_duplicate_derived_file_stem_is_rejected():
    with pytest.raises(TaskRouteFamilyError, match="输出文件名冲突"):
        derive_task_route_families(_project(targets=("1501", "1501")))
