from __future__ import annotations

import pytest

from autodrive_console.virtual_walls import (
    VirtualWallError,
    parse_virtual_wall_segments,
    render_virtual_wall_file,
    validate_polyline,
    validate_segment,
)


def test_rendered_wall_file_uses_image_relative_segments() -> None:
    contents = render_virtual_wall_file(
        [-38.0, -17.0, 0.0],
        [
            {
                "start": {"x": -37.5, "y": -16.25},
                "end": {"x": -36.0, "y": -15.0},
            }
        ],
    )

    assert b"coordinate_mode: image_relative" in contents
    assert b"frame_id: map" in contents
    assert parse_virtual_wall_segments(contents, [-38.0, -17.0, 0.0]) == [
        {
            "start": {"x": -37.5, "y": -16.25},
            "end": {"x": -36.0, "y": -15.0},
        }
    ]


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ({"x": 0, "y": 0}, {"x": 0, "y": 0}),
        ({"x": float("nan"), "y": 0}, {"x": 1, "y": 0}),
    ],
)
def test_validate_segment_rejects_invalid_geometry(start: dict[str, float], end: dict[str, float]) -> None:
    with pytest.raises(VirtualWallError):
        validate_segment(start, end)


def test_parser_rejects_unknown_coordinate_mode() -> None:
    contents = b"""virtual_walls:
  coordinate_mode: pixels
  segments: []
"""

    with pytest.raises(VirtualWallError, match="坐标模式"):
        parse_virtual_wall_segments(contents, [0.0, 0.0, 0.0])


def test_polyline_validation_keeps_every_vertex_and_rejects_duplicate_neighbors() -> None:
    points = validate_polyline([
        {"x": 0, "y": 0},
        {"x": 1, "y": 0},
        {"x": 1, "y": 2},
    ])

    assert points == [
        {"x": 0.0, "y": 0.0},
        {"x": 1.0, "y": 0.0},
        {"x": 1.0, "y": 2.0},
    ]
    with pytest.raises(VirtualWallError, match="相邻"):
        validate_polyline([{"x": 0, "y": 0}, {"x": 0, "y": 0}])
