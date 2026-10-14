from __future__ import annotations

from copy import deepcopy
from math import pi

import pytest

import autodrive_console.execution_chain as execution_chain
from autodrive_console.execution_chain import ExecutionChainError, build_map_execution_plan


@pytest.fixture
def project():
    return {
        "map_assets": [{"id": "floor", "origin": [-10, -10, 0],
                        "width": 20, "height": 20, "resolution_m": 1}],
        "localization_bindings": [{"id": "binding", "map_asset_id": "floor"}],
        "waypoints": [
            {"id": "door-pass", "kind": "transition", "map_asset_id": "floor",
             "x": 0, "y": -3, "yaw": 0.2, "speed_mode": "normal"},
            {"id": "other", "kind": "transition", "map_asset_id": "floor",
             "x": 3, "y": 3, "yaw": 0.5, "speed_mode": "slow_point"},
        ],
        "components": [],
        "localization_routes": [{"binding_ids": ["binding"], "execution_nodes": [{
            "binding_id": "binding", "node_refs": [
                {"kind": "transition", "id": "door-pass"},
                {"kind": "transition", "id": "other"},
            ],
        }]}],
    }


def _directed(project, refs, *, start=None, end=None, end_speed="single_point"):
    return execution_chain.build_directed_map_execution_plan(
        project, "binding", node_refs=refs,
        start_anchor=start or {"x": 0, "y": -8, "yaw": 0},
        end_anchor=end or {"x": 0, "y": 8, "yaw": 0}, end_speed_mode=end_speed,
    )


def _legacy(project):
    return build_map_execution_plan(
        project, "binding", start_anchor={"x": 0, "y": -8},
        end_anchor={"x": 0, "y": 8}, end_speed_mode="single_point",
    )


def test_directed_segment_keeps_repeated_normal_visits_in_explicit_order(project):
    del project["localization_routes"]
    refs = [{"kind": "transition", "id": "door-pass"}] * 2
    before = deepcopy(project)

    plan = _directed(project, refs, end_speed="normal")

    assert [(node.source_id, node.incoming_speed_mode) for node in plan.outbound_nodes] == [
        ("door-pass", "normal"), ("door-pass", "normal"),
    ]
    assert [(node.source_id, node.incoming_speed_mode) for node in plan.return_nodes] == [
        ("door-pass", "normal"), ("door-pass", "normal"),
    ]
    assert all(node.yaw == pytest.approx(0.2 - pi) for node in plan.return_nodes)
    assert all(node.action is None and node.return_action is None for node in plan.outbound_nodes)
    assert project == before


def test_normal_transition_return_does_not_inherit_target_single_point_speed(project):
    plan = _directed(project, [{"kind": "transition", "id": "door-pass"}])

    assert plan.outbound_nodes[0].incoming_speed_mode == "normal"
    assert plan.return_nodes[0].incoming_speed_mode == "normal"
    assert plan.return_nodes[0].action is None


def test_directed_segment_accepts_empty_subset_without_persisted_execution_route(project):
    del project["localization_routes"]

    plan = _directed(project, [])

    assert plan.outbound_nodes == ()
    assert plan.return_nodes == ()


@pytest.mark.parametrize("kind", ["gate", "auto_door"])
def test_directed_device_return_pairs_actions_at_the_same_physical_points(project, kind):
    project["components"] = [{
        "id": "device", "kind": kind, "map_asset_id": "floor", "x": 0, "y": 0, "yaw": 0,
        "attributes": {"width_m": 2, "height_m": 1, "controller_device_id": "101",
                       "pre_open_distance_m": 1, "post_open_distance_m": 2},
    }]

    plan = _directed(project, [{"kind": "component", "id": "device"}])

    assert [node.action for node in plan.outbound_nodes] == ["open_go", "close_go"]
    assert [node.action for node in plan.return_nodes] == ["open_back", "close_back"]
    for outbound, returned in zip(plan.outbound_nodes, reversed(plan.return_nodes)):
        assert (returned.x, returned.y) == (outbound.x, outbound.y)
        assert returned.yaw == pytest.approx(outbound.yaw - pi)
        assert returned.action == outbound.return_action
        assert returned.return_action == outbound.action
        assert returned.controller_device_id == "101"
        assert returned.component_kind == kind


def test_directed_region_return_preserves_the_interior_edge_speed(project):
    project["components"] = [{
        "id": "slow", "kind": "slow_zone", "map_asset_id": "floor", "x": 0, "y": 0,
        "attributes": {"width_m": 2, "height_m": 2, "speed_profile": "slow_point"},
    }]

    plan = _directed(project, [{"kind": "component", "id": "slow"}], end_speed="normal")

    assert [(node.y, node.incoming_speed_mode) for node in plan.outbound_nodes] == [
        (-1, "single_point"), (1, "slow_point"),
    ]
    assert [(node.y, node.incoming_speed_mode) for node in plan.return_nodes] == [
        (1, "normal"), (-1, "slow_point"),
    ]


@pytest.mark.parametrize("refs", [
    None, {}, (), "door-pass", [None],
    [{"kind": "transition", "id": "door-pass", "action": "open"}],
    [{"kind": "transition"}], [{"kind": "unknown", "id": "door-pass"}],
    [{"kind": "transition", "id": 1}], [{"kind": "transition", "id": True}],
    [{"kind": "transition", "id": ""}], [{"kind": "transition", "id": " "}],
])
def test_directed_segment_rejects_malformed_explicit_refs(project, refs):
    with pytest.raises(ExecutionChainError, match="执行链节点"):
        _directed(project, refs)


@pytest.mark.parametrize("change", [
    {"map_asset_id": "foreign-map"}, {"generated_by": "component"},
    {"exclude_task_export": True}, {"kind": "start"}, {"speed_mode": "elevator_in"},
])
def test_directed_segment_rejects_invalid_manual_transition(project, change):
    project["waypoints"][0].update(change)

    with pytest.raises(ExecutionChainError):
        _directed(project, [{"kind": "transition", "id": "door-pass"}])


@pytest.mark.parametrize("kind", ["start", "target", "elevator", "building_entrance", "unknown"])
def test_directed_segment_rejects_anchor_and_unsupported_component_refs(project, kind):
    project["components"] = [{"id": "anchor", "kind": kind, "map_asset_id": "floor",
                              "x": 0, "y": 0}]

    with pytest.raises(ExecutionChainError, match="不能加入"):
        _directed(project, [{"kind": "component", "id": "anchor"}])


def test_directed_segment_rejects_missing_project_reference(project):
    with pytest.raises(ExecutionChainError, match="不存在"):
        _directed(project, [{"kind": "transition", "id": "foreign-project-point"}])


def test_directed_segment_keeps_device_side_constraint(project):
    project["components"] = [{
        "id": "gate", "kind": "gate", "map_asset_id": "floor", "x": 0, "y": 0,
        "attributes": {"width_m": 2, "height_m": 1, "controller_device_id": "101"},
    }]

    with pytest.raises(ExecutionChainError, match="两侧"):
        _directed(project, [{"kind": "component", "id": "gate"}], end={"x": 2, "y": -5})


def test_directed_segment_keeps_map_bounds_constraint(project):
    project["waypoints"][0]["x"] = 12

    with pytest.raises(ExecutionChainError, match="超出地图边界"):
        _directed(project, [{"kind": "transition", "id": "door-pass"}])


def test_legacy_execution_plan_still_rejects_repeated_refs(project):
    refs = project["localization_routes"][0]["execution_nodes"][0]["node_refs"]
    refs.append(dict(refs[0]))

    with pytest.raises(ExecutionChainError, match="不能重复"):
        _legacy(project)


def test_legacy_execution_plan_still_requires_all_map_nodes(project):
    project["localization_routes"][0]["execution_nodes"][0]["node_refs"].pop()

    with pytest.raises(ExecutionChainError, match="未编排任务节点"):
        _legacy(project)


def test_legacy_execution_plan_retains_the_same_expansion(project):
    refs = project["localization_routes"][0]["execution_nodes"][0]["node_refs"]

    assert _legacy(project) == _directed(project, refs)
