from __future__ import annotations

from math import pi

import pytest

from autodrive_console.task_path import (
    TaskPathError,
    return_task_transition_points,
    task_segment_transitions,
)


def test_task_segment_keeps_manual_saved_order_and_return_is_its_exact_reverse():
    """The same ordered segment feeds both task and localization consumers."""
    project = {
        "waypoints": [
            {"id": "first", "map_asset_id": "floor", "kind": "transition", "x": 1, "y": 2, "yaw": 0.2, "speed_mode": "slow_point"},
            {"id": "ignored-generated", "map_asset_id": "floor", "kind": "transition", "x": 3, "y": 4, "yaw": 0.4, "generated_by": "migration"},
            {"id": "ignored-excluded", "map_asset_id": "floor", "kind": "transition", "x": 5, "y": 6, "yaw": 0.6, "exclude_task_export": True},
            {"id": "second", "map_asset_id": "floor", "kind": "transition", "x": 7, "y": 8, "yaw": -0.3, "speed_mode": "narrow_point"},
        ]
    }

    outbound = task_segment_transitions(project, "floor")
    returned = return_task_transition_points(outbound)

    assert [(point["x"], point["y"], point["speed_mode"]) for point in outbound] == [
        (1.0, 2.0, "slow_point"), (7.0, 8.0, "narrow_point"),
    ]
    assert [(point["x"], point["y"], point["speed_mode"]) for point in returned] == [
        (7.0, 8.0, "narrow_point"), (1.0, 2.0, "slow_point"),
    ]
    assert returned[0]["yaw"] == -0.3 + pi
    assert returned[1]["yaw"] == 0.2 - pi


@pytest.mark.parametrize(
    ("outbound_yaw", "expected_return_yaw"),
    [
        (0.0, -pi),
        (pi / 2, -pi / 2),
        (pi, 0.0),
        (-pi / 2, pi / 2),
    ],
)
def test_return_transition_heading_always_faces_the_reverse_segment(
    outbound_yaw: float, expected_return_yaw: float,
):
    returned = return_task_transition_points([
        {"x": 1.0, "y": 2.0, "yaw": outbound_yaw, "speed_mode": "single_point"},
    ])

    assert returned[0]["yaw"] == pytest.approx(expected_return_yaw)


def test_task_segment_rejects_behavior_tree_only_speed_modes():
    """Both artifact consumers reject a transition that cannot be navigated."""
    project = {
        "waypoints": [{
            "map_asset_id": "floor", "kind": "transition",
            "x": 1, "y": 2, "yaw": 0, "speed_mode": "elevator_in",
        }]
    }

    with pytest.raises(TaskPathError, match="过渡点速度模式"):
        task_segment_transitions(project, "floor")
