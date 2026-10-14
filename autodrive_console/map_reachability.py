"""Compact, exact connectivity checks for explicitly ordered task lines.

The compiler needs to validate connectivity, not compute a shortest path that
it then discards. Robot navigation still owns the actual driving trajectory.
"""
from heapq import heappop, heappush
from math import floor

from .automatic_route import (
    AutomaticRouteError, _cell_center, _crosses_virtual_wall,
    _nearest_free_cell, _normalise_virtual_walls, _wall_segment,
)


class FreeCells:
    """Set-compatible membership backed by one byte per pixel, not tuples."""

    def __init__(self, width, height, pixels, *, negate=0, free_thresh=.196):
        self.width, self.height = width, height
        table = bytes(int((v if negate else 255-v)/255. < free_thresh) for v in range(256))
        self.mask = bytes(pixels).translate(table)

    def __contains__(self, cell):
        x, y = cell
        return 0 <= x < self.width and 0 <= y < self.height and bool(self.mask[y*self.width+x])

    def __len__(self):
        return self.mask.count(b'\1')


def map_reachable(asset, start, end, *, virtual_walls=(), grid_override):
    """Check the same eight-neighbour graph as the existing route validator.

    Bidirectional greedy search visits each cell at most once. Ordering by
    distance guides the two fronts together without paying for optimal path
    costs or predecessor dictionaries. Every explored edge still obeys the
    original exact virtual-wall intersection test, including endpoints.
    """
    width, height, free = grid_override
    origin, resolution = asset['origin'], float(asset['resolution_m'])
    walls = [_wall_segment((w['start']['x'], w['start']['y']),
                           (w['end']['x'], w['end']['y']))
             for w in _normalise_virtual_walls(virtual_walls)]
    first = _nearest_free_cell(start, width, height, free, origin, resolution, virtual_walls=walls)
    last = _nearest_free_cell(end, width, height, free, origin, resolution, virtual_walls=walls)
    if first == last:
        return

    # The one-cell margin includes walls intersecting an edge whose start is
    # just outside the wall's bucket. Only nearby walls reach exact geometry.
    buckets = {}
    bucket_size = 64
    for wall in walls:
        _, _, min_x, max_x, min_y, max_y = wall
        left = max(0, floor((min_x-float(origin[0]))/resolution)-2)//bucket_size
        right = min(width-1, floor((max_x-float(origin[0]))/resolution)+2)//bucket_size
        top = max(0, height-1-floor((max_y-float(origin[1]))/resolution)-2)//bucket_size
        bottom = min(height-1, height-1-floor((min_y-float(origin[1]))/resolution)+2)//bucket_size
        for by in range(top, bottom+1):
            for bx in range(left, right+1):
                buckets.setdefault((bx, by), []).append(wall)

    seen = bytearray(width*height)
    seen[first[1]*width+first[0]] = 1
    seen[last[1]*width+last[0]] = 2
    fronts = [[(0, 0, first)], [(0, 0, last)]]
    goals = (last, first)
    mask = free.mask
    serial = 0
    side = 0
    while fronts[0] and fronts[1]:
        front = fronts[side]
        color = side+1
        _, _, current = heappop(front)
        x, y = current
        nearby = buckets.get((x//bucket_size, y//bucket_size), ())
        center = _cell_center(current, height, origin, resolution) if nearby else None
        gx, gy = goals[side]
        for dx, dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
            nx, ny = x+dx, y+dy
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            index = ny*width+nx
            if not mask[index] or seen[index] == color:
                continue
            if nearby and _crosses_virtual_wall(center, _cell_center((nx,ny), height, origin, resolution), nearby):
                continue
            if seen[index]:
                return
            seen[index] = color
            serial += 1
            heappush(front, ((gx-nx)**2+(gy-ny)**2, serial, (nx,ny)))
        side = 1-side
    raise AutomaticRouteError(
        f"地图“{asset.get('label') or asset.get('id')}”的起止标记被可通行区域或虚拟墙阻断；请回到地图检查"
    )
