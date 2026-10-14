"""Navigation erasures follow the raw editor's geometry at native map scale."""
import pytest

from autodrive_console.location_manifest import _read_pgm_bytes, _rasterize_map_edits


@pytest.mark.parametrize("kind,shape,points,radius,expected", [
    ("brush_erase", "square", [(3, 3)], 1, {(2, 2), (3, 2), (2, 3), (3, 3)}),
    ("brush_erase", "circle", [(3, 3)], 1, {(2, 2), (3, 2), (2, 3), (3, 3)}),
    ("brush_erase", "square", [(2, 3), (6, 3)], .75,
     {(x, y) for x in (1, 2, 5, 6) for y in (2, 3)}),
    ("brush_erase", "circle", [(2, 3), (6, 3)], 1,
     {(x, y) for x in range(1, 7) for y in (2, 3)}),
    ("polygon_erase", None, [(2, 2), (4, 2), (4, 4), (2, 4)], None,
     {(x, y) for x in (2, 3) for y in (2, 3)}),
    ("polygon_erase", None, [(2, 2), (4, 2), (4, 4), (2, 4)] * 2, None,
     {(x, y) for x in (2, 3) for y in (2, 3)}),
    ("polygon_erase", None, [(1, 3.3), (7, 3.3), (7, 3.7), (1, 3.7)], None, set()),
    ("polygon_erase", None, [(1, 3.2), (7, 3.2), (7, 3.8), (1, 3.8)], None,
     {(x, 3) for x in range(1, 7)}),
    # Canvas partial corner coverage is below half a cell; keep that wall pixel.
    ("brush_erase", "square", [(2.8, 2.8)], .8, {(2, 2), (3, 2), (2, 3)}),
    ("brush_erase", "square", [(3, 3)], .5, set()),
    ("brush_erase", "circle", [(3, 3), (3, 3)], 1,
     {(x, y) for x in (2, 3) for y in (2, 3)}),
    ("brush_erase", "circle", [(6, 3), (2, 3)], 1,
     {(x, y) for x in range(1, 7) for y in (2, 3)}),
])
def test_erase_export_matches_raw_canvas_geometry(kind, shape, points, radius, expected):
    asset = {"resolution_m": 1, "origin": [0, 0, 0]}
    edit = {"kind": kind, "points": [{"x": x, "y": 8-y} for x, y in points]}
    if radius is not None:
        edit.update(radius_m=radius, shape=shape)
    source = b"P5\n8 8\n255\n" + bytes(64)

    _, _, pixels = _read_pgm_bytes(_rasterize_map_edits(source, asset, [edit]))

    assert {(i % 8, i // 8) for i, pixel in enumerate(pixels) if pixel == 254} == expected
