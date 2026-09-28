from __future__ import annotations

import builtins
from math import pi

import pytest

import autodrive_console.automatic_route as automatic_route
from autodrive_console.automatic_route import (
    AutomaticRouteError,
    _map_path,
    _nearest_free_cell,
    _read_grid,
    derive_localization_routes,
)


def _project() -> dict:
    return {
        "deployment_flow": [
            {"id": "lobby", "type": "lobby", "label": "电梯大厅"},
            {"id": "target_floor", "type": "target_floor", "label": "用户楼层"},
        ],
        "map_stage_assignments": [
            {"stage": "lobby", "map_asset_id": "lobby-map"},
            {"stage": "target_floor", "map_asset_id": "floor-map"},
        ],
        "map_assets": [
            {"id": "lobby-map", "label": "大厅", "origin": [-10, -10, 0], "width": 40, "height": 40, "resolution_m": 1.0},
            {"id": "floor-map", "label": "1509", "origin": [-10, -10, 0], "width": 40, "height": 40, "resolution_m": 1.0},
        ],
        "localization_bindings": [
            {"id": "lobby-binding", "map_asset_id": "lobby-map", "building": "1", "unit": "1", "type": "indoor"},
            {"id": "floor-binding", "map_asset_id": "floor-map", "building": "1", "unit": "1", "type": "floor", "floor_template": "1"},
        ],
        "components": [
            {"id": "start", "map_asset_id": "lobby-map", "kind": "start", "label": "起点", "x": -6.0, "y": 0.0, "yaw": 0.0, "generated_waypoint_ids": ["start-point"]},
            {"id": "lobby-lift", "map_asset_id": "lobby-map", "kind": "elevator", "label": "大厅电梯", "x": 6.0, "y": 0.0, "yaw": 0.0, "attributes": {"physical_elevator_id": "lift-a", "height_m": 2.0, "wait_distance_m": 1.5}},
            {"id": "floor-lift", "map_asset_id": "floor-map", "kind": "elevator", "label": "楼层电梯", "x": -6.0, "y": 0.0, "yaw": -pi / 2, "attributes": {"physical_elevator_id": "lift-a", "height_m": 2.0, "wait_distance_m": 1.5}},
            {"id": "target", "map_asset_id": "floor-map", "kind": "target", "label": "目标", "x": 6.0, "y": 0.0, "yaw": 0.0, "generated_waypoint_ids": ["target-point"]},
            {"id": "slow", "map_asset_id": "floor-map", "kind": "slow_zone", "label": "减速区", "x": -1.0, "y": 0.0, "yaw": 0.0, "attributes": {"width_m": 2.0, "height_m": 2.0}},
        ],
        "waypoints": [
            {"id": "start-point", "map_asset_id": "lobby-map", "kind": "start", "generated_by": "start", "x": -6.0, "y": 0.0, "yaw": 0.0},
            {"id": "target-point", "map_asset_id": "floor-map", "kind": "target", "generated_by": "target", "x": 6.0, "y": 0.0, "yaw": 0.0},
            {"id": "transition-late", "map_asset_id": "floor-map", "kind": "transition", "label": "后过渡点", "x": 3.0, "y": 0.0, "yaw": 0.0},
            {"id": "transition-early", "map_asset_id": "floor-map", "kind": "transition", "label": "先过渡点", "x": -3.0, "y": 0.0, "yaw": 0.0},
        ],
    }


def _install_open_grid(tmp_path, asset: dict) -> None:
    source = tmp_path / f"{asset['id']}.yaml"
    source.write_text("image: map.pgm\n", encoding="utf-8")
    source.with_name("map.pgm").write_bytes(
        b"P5\n40 40\n255\n" + bytes([255]) * (40 * 40)
    )
    asset["source_yaml"] = str(source)


def test_map_path_detours_through_the_only_gap_in_virtual_walls(tmp_path):
    project = _project()
    asset = project["map_assets"][1]
    _install_open_grid(tmp_path, asset)
    walls = [
        {"start": {"x": 0.0, "y": -10.0}, "end": {"x": 0.0, "y": 4.0}},
        {"start": {"x": 0.0, "y": 6.0}, "end": {"x": 0.0, "y": 30.0}},
    ]

    path = _map_path(
        asset,
        {"x": -4.0, "y": 0.0},
        {"x": 4.0, "y": 0.0},
        virtual_walls=walls,
    )

    assert max(y for _, y in path) >= 4.5


def test_map_path_never_skips_a_virtual_wall_when_grid_metadata_is_invalid(tmp_path):
    project = _project()
    asset = project["map_assets"][1]
    _install_open_grid(tmp_path, asset)
    asset["resolution_m"] = 0.0

    with pytest.raises(AutomaticRouteError, match="虚拟墙"):
        _map_path(
            asset,
            {"x": -4.0, "y": 0.0},
            {"x": 4.0, "y": 0.0},
            virtual_walls=[{
                "start": {"x": 0.0, "y": -10.0},
                "end": {"x": 0.0, "y": 30.0},
            }],
        )


def test_automatic_route_rejects_a_virtual_wall_that_seals_a_map(tmp_path):
    project = _project()
    floor_asset = project["map_assets"][1]
    _install_open_grid(tmp_path, floor_asset)
    project["virtual_walls"] = [{
        "id": "floor-boundary",
        "map_asset_id": "floor-map",
        "points": [{"x": 0.0, "y": -10.0}, {"x": 0.0, "y": 30.0}],
    }]

    with pytest.raises(AutomaticRouteError, match="虚拟墙"):
        derive_localization_routes(project)


def test_virtual_walls_only_constrain_their_own_map():
    project = _project()
    target = next(component for component in project["components"] if component["id"] == "target")
    target["x"] = -1.0
    target_point = next(waypoint for waypoint in project["waypoints"] if waypoint["id"] == "target-point")
    target_point["x"] = -1.0
    next(component for component in project["components"] if component["id"] == "slow")["x"] = -2.0
    next(waypoint for waypoint in project["waypoints"] if waypoint["id"] == "transition-late")["x"] = -2.5
    project["virtual_walls"] = [{
        "id": "floor-boundary",
        "map_asset_id": "floor-map",
        "points": [{"x": 0.0, "y": -10.0}, {"x": 0.0, "y": 30.0}],
    }]

    routes = derive_localization_routes(project)

    assert routes[0]["binding_ids"] == ["lobby-binding", "floor-binding"]


def test_derives_route_membership_anchors_and_chain_from_scene_and_map_marks():
    routes = derive_localization_routes(_project())

    assert len(routes) == 1
    route = routes[0]
    assert route["binding_ids"] == ["lobby-binding", "floor-binding"]
    assert route["task_start_waypoint_id"] == "start-point"
    assert route["task_target_waypoint_id"] == "target-point"
    assert route["links"] == [{
        "from_binding_id": "lobby-binding", "to_binding_id": "floor-binding",
        "anchor": {"kind": "component_center", "component_id": "lobby-lift"},
    }]
    assert route["execution_nodes"] == [
        {"binding_id": "lobby-binding", "node_refs": []},
        {"binding_id": "floor-binding", "node_refs": [
            {"kind": "transition", "id": "transition-early"},
            {"kind": "component", "id": "slow"},
            {"kind": "transition", "id": "transition-late"},
        ]},
    ]


def test_unit_map_instances_derive_each_building_route_without_overwriting_stage_assignment():
    """The import-guide's first-map assignment cannot hide the second unit."""
    project = _project()
    project["map_assets"].extend([
        {"id": "lobby-map-2", "label": "二栋大厅", "origin": [-10, -10, 0], "width": 40, "height": 40, "resolution_m": 1.0},
        {"id": "floor-map-2", "label": "二栋 1501", "origin": [-10, -10, 0], "width": 40, "height": 40, "resolution_m": 1.0},
    ])
    project["map_instances"] = [
        {"map_asset_id": "lobby-map", "role": "lobby", "building": "1", "unit": "1", "floor": 1},
        {"map_asset_id": "floor-map", "role": "typical_floor", "building": "1", "unit": "1", "floor": 15},
        {"map_asset_id": "lobby-map-2", "role": "lobby", "building": "2", "unit": "1", "floor": 1},
        {"map_asset_id": "floor-map-2", "role": "typical_floor", "building": "2", "unit": "1", "floor": 15},
    ]
    project["localization_bindings"].extend([
        {"id": "lobby-binding-2", "map_asset_id": "lobby-map-2", "building": "2", "unit": "1", "type": "indoor"},
        {"id": "floor-binding-2", "map_asset_id": "floor-map-2", "building": "2", "unit": "1", "type": "floor", "floor_template": "1"},
    ])
    project["components"].extend([
        {"id": "start-2", "map_asset_id": "lobby-map-2", "kind": "start", "label": "二栋起点", "x": -6.0, "y": 0.0, "yaw": 0.0, "generated_waypoint_ids": ["start-point-2"]},
        {"id": "lobby-lift-2", "map_asset_id": "lobby-map-2", "kind": "elevator", "label": "二栋大厅电梯", "x": 6.0, "y": 0.0, "yaw": 0.0, "attributes": {"physical_elevator_id": "lift-b", "height_m": 2.0, "wait_distance_m": 1.5}},
        {"id": "floor-lift-2", "map_asset_id": "floor-map-2", "kind": "elevator", "label": "二栋楼层电梯", "x": -6.0, "y": 0.0, "yaw": -pi / 2, "attributes": {"physical_elevator_id": "lift-b", "height_m": 2.0, "wait_distance_m": 1.5}},
        {"id": "target-2", "map_asset_id": "floor-map-2", "kind": "target", "label": "二栋目标", "x": 6.0, "y": 0.0, "yaw": 0.0, "generated_waypoint_ids": ["target-point-2"]},
    ])
    project["waypoints"].extend([
        {"id": "start-point-2", "map_asset_id": "lobby-map-2", "kind": "start", "generated_by": "start-2", "x": -6.0, "y": 0.0, "yaw": 0.0},
        {"id": "target-point-2", "map_asset_id": "floor-map-2", "kind": "target", "generated_by": "target-2", "x": 6.0, "y": 0.0, "yaw": 0.0},
    ])

    routes = derive_localization_routes(project)

    assert [(route["building"], route["unit"]) for route in routes] == [("1", "1"), ("2", "1")]
    assert [route["binding_ids"] for route in routes] == [
        ["lobby-binding", "floor-binding"],
        ["lobby-binding-2", "floor-binding-2"],
    ]


def test_external_stages_are_derived_from_core_handoff_marks_without_manual_ordering():
    """A public ferry is shared, while each unit owns its outdoor segment."""
    project = _project()
    project["deployment_flow"] = [
        {"id": "ferry", "type": "ferry"},
        {"id": "outdoor", "type": "outdoor"},
        {"id": "lobby", "type": "lobby"},
        {"id": "target_floor", "type": "target_floor"},
    ]
    project["map_assets"] = [
        {"id": "ferry-map", "label": "摆渡层", "origin": [-10, -10, 0], "width": 40, "height": 40, "resolution_m": 1.0},
        {"id": "outdoor-map", "label": "一栋户外", "origin": [-10, -10, 0], "width": 40, "height": 40, "resolution_m": 1.0},
        *project["map_assets"],
    ]
    project["map_instances"] = [
        {"map_asset_id": "ferry-map", "role": "ferry", "scope": "global", "building": "", "unit": "", "floor": None},
        {"map_asset_id": "outdoor-map", "role": "outdoor", "scope": "unit", "building": "1", "unit": "1", "floor": 1},
        {"map_asset_id": "lobby-map", "role": "lobby", "scope": "unit", "building": "1", "unit": "1", "floor": 1},
        {"map_asset_id": "floor-map", "role": "typical_floor", "scope": "unit", "building": "1", "unit": "1", "floor": 15},
    ]
    project["localization_bindings"] = [
        {"id": "ferry-binding", "map_asset_id": "ferry-map", "building": "", "unit": "", "type": "ferry"},
        {"id": "outdoor-binding", "map_asset_id": "outdoor-map", "building": "1", "unit": "1", "type": "outdoor"},
        *project["localization_bindings"],
    ]
    project["components"].extend([
        {"id": "ferry-start", "map_asset_id": "ferry-map", "kind": "start", "x": -6.0, "y": 0.0, "yaw": 0.0, "generated_waypoint_ids": ["ferry-start-point"]},
        {"id": "outdoor-start", "map_asset_id": "outdoor-map", "kind": "start", "x": -6.0, "y": 0.0, "yaw": 0.0, "generated_waypoint_ids": ["outdoor-start-point"]},
        {"id": "lobby-entry", "map_asset_id": "lobby-map", "kind": "building_entrance", "x": -5.0, "y": 0.0, "yaw": 0.0},
    ])
    project["waypoints"].extend([
        {"id": "ferry-start-point", "map_asset_id": "ferry-map", "kind": "start", "generated_by": "ferry-start", "x": -6.0, "y": 0.0, "yaw": 0.0},
        {"id": "ferry-handoff", "map_asset_id": "ferry-map", "kind": "transition", "x": 6.0, "y": 0.0, "yaw": 0.0, "speed_mode": "single_point"},
        {"id": "outdoor-start-point", "map_asset_id": "outdoor-map", "kind": "start", "generated_by": "outdoor-start", "x": -6.0, "y": 0.0, "yaw": 0.0},
        {"id": "outdoor-handoff", "map_asset_id": "outdoor-map", "kind": "transition", "x": 6.0, "y": 0.0, "yaw": 0.0, "speed_mode": "single_point"},
    ])

    routes = derive_localization_routes(project)

    assert routes[0]["binding_ids"] == [
        "ferry-binding", "outdoor-binding", "lobby-binding", "floor-binding",
    ]
    assert routes[0]["links"] == [
        {"from_binding_id": "ferry-binding", "to_binding_id": "outdoor-binding", "anchor": {"kind": "waypoint", "waypoint_id": "ferry-handoff"}},
        {"from_binding_id": "outdoor-binding", "to_binding_id": "lobby-binding", "anchor": {"kind": "waypoint", "waypoint_id": "outdoor-handoff"}},
        {"from_binding_id": "lobby-binding", "to_binding_id": "floor-binding", "anchor": {"kind": "component_center", "component_id": "lobby-lift"}},
    ]
    assert routes[0]["entry_anchors"] == [
        {"binding_id": "outdoor-binding", "anchor": {"kind": "waypoint", "waypoint_id": "outdoor-start-point"}},
        {"binding_id": "lobby-binding", "anchor": {"kind": "component_center", "component_id": "lobby-entry"}},
        {"binding_id": "floor-binding", "anchor": {"kind": "component_center", "component_id": "floor-lift"}},
    ]
    assert routes[0]["execution_nodes"][:2] == [
        {"binding_id": "ferry-binding", "node_refs": []},
        {"binding_id": "outdoor-binding", "node_refs": []},
    ]


def test_access_barrier_joins_the_automatic_route_without_manual_ordering():
    """Doors and gates are map facts just like passive regions and transitions."""
    project = _project()
    project["components"].append({
        "id": "target-door", "map_asset_id": "floor-map", "kind": "auto_door", "label": "自动门",
        "x": 1.0, "y": 0.0, "yaw": 0.0,
        "attributes": {"width_m": 2.0, "height_m": 0.5, "controller_device_id": "10044"},
    })

    routes = derive_localization_routes(project)

    assert routes[0]["execution_nodes"][1]["node_refs"] == [
        {"kind": "transition", "id": "transition-early"},
        {"kind": "component", "id": "slow"},
        {"kind": "component", "id": "target-door"},
        {"kind": "transition", "id": "transition-late"},
    ]


def test_multiple_targets_produce_deterministic_branches_without_manual_ordering():
    project = _project()
    project["components"].append({
        "id": "target-1502", "map_asset_id": "floor-map", "kind": "target", "label": "1502",
        "x": 7.0, "y": 0.0, "yaw": 0.0, "generated_waypoint_ids": ["target-1502-point"],
    })
    project["waypoints"].append({
        "id": "target-1502-point", "map_asset_id": "floor-map", "kind": "target",
        "generated_by": "target-1502", "x": 7.0, "y": 0.0, "yaw": 0.0,
    })

    routes = derive_localization_routes(project)

    assert [route["id"] for route in routes] == ["auto-1-1-target", "auto-1-1-target-1502"]
    assert [route["task_target_waypoint_id"] for route in routes] == ["target-point", "target-1502-point"]


def test_off_route_component_becomes_a_required_automatic_route_anchor():
    """A marked component must redirect the derived route instead of being rejected."""
    project = _project()
    slow_zone = next(component for component in project["components"] if component["id"] == "slow")
    slow_zone["y"] = 8.0

    routes = derive_localization_routes(project)

    assert routes[0]["execution_nodes"][1]["node_refs"] == [
        {"kind": "transition", "id": "transition-early"},
        {"kind": "transition", "id": "transition-late"},
        {"kind": "component", "id": "slow"},
    ]


def test_transition_waypoint_becomes_an_automatic_route_anchor_without_manual_sorting():
    project = _project()
    project["waypoints"] = [
        waypoint for waypoint in project["waypoints"]
        if waypoint.get("id") != "transition-late"
    ]
    transition = next(waypoint for waypoint in project["waypoints"] if waypoint["id"] == "transition-early")
    transition.update({"x": 0.0, "y": 5.0})
    slow_zone = next(component for component in project["components"] if component["id"] == "slow")
    slow_zone.update({"x": 3.0, "y": 2.5})

    routes = derive_localization_routes(project)

    assert routes[0]["execution_nodes"][1]["node_refs"] == [
        {"kind": "transition", "id": "transition-early"},
        {"kind": "component", "id": "slow"},
    ]


def test_slow_zone_uses_its_rotated_area_instead_of_requiring_its_center_on_route():
    project = _project()
    project["map_assets"][1]["resolution_m"] = 0.05
    slow_zone = next(component for component in project["components"] if component["id"] == "slow")
    slow_zone.update({"x": 0.0, "y": 2.0, "yaw": 0.0})
    slow_zone["attributes"] = {"width_m": 0.5, "height_m": 4.0}

    routes = derive_localization_routes(project)

    floor_nodes = routes[0]["execution_nodes"][1]["node_refs"]
    assert floor_nodes == [
        {"kind": "transition", "id": "transition-early"},
        {"kind": "component", "id": "slow"},
        {"kind": "transition", "id": "transition-late"},
    ]


def test_passive_regions_use_their_rotated_area_instead_of_a_directional_center_point():
    """Narrow passages and ramps affect the path footprint, not travel direction."""
    for kind in ("narrow_passage", "ramp"):
        project = _project()
        project["map_assets"][1]["resolution_m"] = 0.05
        region = next(component for component in project["components"] if component["id"] == "slow")
        region.update({"id": kind, "kind": kind, "label": kind, "x": 0.0, "y": 2.0, "yaw": 0.0})
        region["attributes"] = {"width_m": 0.5, "height_m": 4.0}

        routes = derive_localization_routes(project)

        floor_nodes = routes[0]["execution_nodes"][1]["node_refs"]
        assert floor_nodes == [
            {"kind": "transition", "id": "transition-early"},
            {"kind": "component", "id": kind},
            {"kind": "transition", "id": "transition-late"},
        ]


def test_reads_standard_pgm_comment_lines_for_automatic_paths(tmp_path):
    (tmp_path / "map.pgm").write_bytes(
        b"P5\n# Created by a standard map exporter\n4 2\n255\n" + bytes([255, 255, 0, 255, 255, 255, 255, 0])
    )

    grid = _read_grid({"source_yaml": str(tmp_path / "map.yaml")})

    assert grid is not None
    width, height, free = grid
    assert (width, height) == (4, 2)
    assert free == {(0, 0), (1, 0), (3, 0), (0, 1), (1, 1), (2, 1)}


def test_grid_cache_reuses_an_unchanged_pgm_and_invalidates_after_a_write(tmp_path):
    pgm = tmp_path / "map.pgm"
    pgm.write_bytes(b"P5\n2 1\n255\n" + bytes([255, 0]))
    asset = {"source_yaml": str(tmp_path / "map.yaml")}

    first = _read_grid(asset)
    second = _read_grid(asset)

    assert first is second
    assert first is not None
    assert first[2] == {(0, 0)}

    pgm.write_bytes(b"P5\n2 1\n255\n" + bytes([0, 255]))
    refreshed = _read_grid(asset)

    assert refreshed is not first
    assert refreshed is not None
    assert refreshed[2] == {(1, 0)}


def test_nearest_free_cell_uses_the_exact_free_marker_without_sorting_the_full_map(monkeypatch):
    free = {(x, y) for x in range(500) for y in range(500)}
    original_sorted = builtins.sorted

    def reject_full_grid_sort(values, *args, **kwargs):
        if values is free:
            raise AssertionError("the full occupancy map must not be sorted for an exact marker")
        return original_sorted(values, *args, **kwargs)

    monkeypatch.setattr(builtins, "sorted", reject_full_grid_sort)

    assert _nearest_free_cell(
        {"x": 10.1, "y": 10.1}, 500, 500, free, [0.0, 0.0, 0.0], 1.0,
    ) == (10, 489)


def test_path_skips_exact_intersection_math_for_virtual_walls_far_from_the_edge(tmp_path, monkeypatch):
    project = _project()
    asset = project["map_assets"][1]
    _install_open_grid(tmp_path, asset)
    walls = [
        {"start": {"x": 100.0 + index, "y": 100.0}, "end": {"x": 100.0 + index, "y": 120.0}}
        for index in range(10)
    ]
    original_intersects = automatic_route._segments_intersect
    calls = 0

    def count_intersections(*args):
        nonlocal calls
        calls += 1
        return original_intersects(*args)

    monkeypatch.setattr(automatic_route, "_segments_intersect", count_intersections)

    path = _map_path(
        asset, {"x": -4.0, "y": 0.0}, {"x": 4.0, "y": 0.0}, virtual_walls=walls,
    )

    assert path
    assert calls == 0
