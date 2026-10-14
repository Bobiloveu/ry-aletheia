"""Exact eight-neighbour reachability without building millions of tuples."""
import random

import pytest

from autodrive_console.automatic_route import AutomaticRouteError, _map_path
from autodrive_console.map_reachability import FreeCells, map_reachable


def asset(w, h):
    return {'id': 'qa', 'width': w, 'height': h, 'resolution_m': 1., 'origin': [0., 0., 0.]}


def point(x, y, h):
    return {'x': x + .5, 'y': h - y - .5}


def test_free_cells_are_byte_sized_and_keep_ros_threshold_semantics():
    pixels = bytes(range(256))
    for negate in (0, 1):
        cells = FreeCells(16, 16, pixels, negate=negate, free_thresh=.25)
        assert len(cells.mask) == 256
        for i, value in enumerate(pixels):
            assert ((i % 16, i // 16) in cells) == ((value if negate else 255-value)/255. < .25)
        assert (-1, 0) not in cells
        assert (16, 0) not in cells
        assert (0, 16) not in cells
        assert len(cells) == sum((v if negate else 255-v)/255. < .25 for v in pixels)


def test_reachability_matches_existing_validation_on_random_grids_and_virtual_walls():
    rng = random.Random(9081)
    w, h = 18, 23
    for trial in range(100):
        pixels = bytes(254 if rng.random() > .28 else 0 for _ in range(w*h))
        free = {(i%w, i//w) for i,v in enumerate(pixels) if v}
        grid = (w, h, FreeCells(w, h, pixels))
        start, end = point(1, 1, h), point(w-2, h-2, h)
        walls = ([{'start': {'x': 9., 'y': -.5}, 'end': {'x': 9., 'y': h+.5}}] if trial % 3 == 0 else
                 [{'start': {'x': 4.5, 'y': 2.5}, 'end': {'x': 12.5, 'y': 17.5}}] if trial % 3 == 1 else [])
        try:
            _map_path(asset(w, h), start, end, virtual_walls=walls, grid_override=(w,h,free))
            expected = True
        except AutomaticRouteError:
            expected = False
        try:
            map_reachable(asset(w, h), start, end, virtual_walls=walls, grid_override=grid)
            actual = True
        except AutomaticRouteError:
            actual = False
        assert actual == expected, trial


def test_diagonal_contact_and_virtual_wall_endpoints_preserve_existing_graph():
    a = asset(2, 2)
    grid = (2, 2, FreeCells(2,2,bytes([254,0,0,254])))
    start, end = point(0,0,2), point(1,1,2)
    map_reachable(a,start,end,grid_override=grid)
    walls = [{'start': {'x': 1.,'y': 0.},'end': {'x': 1.,'y': 2.}}]
    with pytest.raises(AutomaticRouteError):
        map_reachable(a,start,end,virtual_walls=walls,grid_override=grid)


def test_noninteger_pixel_centers_cannot_round_past_virtual_wall():
    from autodrive_console.automatic_route import _cell_center
    w,h=168,20
    a={'id':'rounding','resolution_m':.05,'origin':[-10.,-10.,0.]}
    pixels=bytearray(w*h)
    for x in (164,165,166):pixels[5*w+x]=254
    grid=(w,h,FreeCells(w,h,pixels))
    start=dict(zip(('x','y'),_cell_center((164,5),h,a['origin'],.05)))
    end=dict(zip(('x','y'),_cell_center((166,5),h,a['origin'],.05)))
    x=_cell_center((165,5),h,a['origin'],.05)[0]
    walls=[{'start':{'x':x,'y':-11},'end':{'x':x,'y':-8}}]
    with pytest.raises(AutomaticRouteError):
        map_reachable(a,start,end,virtual_walls=walls,grid_override=grid)
