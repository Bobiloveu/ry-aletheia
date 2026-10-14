"""Read-only raster paths used to discover facilities on fixed task legs.

Pixel membership and predecessors stay compact even for the 35M-cell maps.
Only explored frontier cells have Python search records; no full-map tuple set
or tuple-keyed predecessor dictionary is constructed. Nav2 owns driving paths.
"""
from heapq import heappop, heappush
from math import ceil, floor, hypot, sqrt

import numpy as np

from .automatic_route import (
    AutomaticRouteError, _cell_center, _crosses_virtual_wall,
    _nearest_free_cell, _normalise_virtual_walls, _wall_segment,
)
from .execution_chain import (
    _component_local, _region_geometry, _segment_area_span,
    build_directed_map_execution_plan,
)

_DIRECTIONS = ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1))


def _clearance_costs(grid,resolution):
    """Bounded coarse clearance preferences, matching the Web corridor bias.

    This display/discovery preference does not alter exported navigation or the
    existing exact reachability boundary. Distances are capped at 2.5m; the
    field has at most 900k cells even when the source has tens of millions.
    """
    width,height,free = grid
    cached = getattr(free,'_fixed_route_costs',None)
    if cached is not None:
        return cached
    factor = max(1,ceil(sqrt(width*height/900000)))
    cw,ch = ceil(width/factor),ceil(height/factor)
    while cw*ch>900000:
        factor += 1
        cw,ch = ceil(width/factor),ceil(height/factor)
    blocked = np.zeros((ch,cw),dtype=np.bool_)
    mask = np.frombuffer(free.mask,dtype=np.uint8).reshape(height,width)
    for dy in range(factor):
        for dx in range(factor):
            part = mask[dy::factor,dx::factor]
            blocked[:part.shape[0],:part.shape[1]] |= part==0
    distance = np.where(blocked,0.,2.5).astype(np.float32)
    spacing = resolution*factor
    for _ in range(ceil(2.5/spacing)):
        padded = np.pad(distance,1,constant_values=0.)
        updated = distance.copy()
        for dx,dy in _DIRECTIONS:
            np.minimum(updated,padded[1+dy:1+dy+ch,1+dx:1+dx+cw]+spacing*hypot(dx,dy),out=updated)
        if np.array_equal(updated,distance):
            break
        distance = updated
    distance = np.maximum(0.,distance-spacing*sqrt(2)/2)
    costs = (1+5*np.exp(-np.maximum(0.,distance-.39)/.65)).astype(np.float32)
    free._fixed_route_costs = (factor,costs)
    return factor,costs


def raster_path(asset, start, end, *, grid, virtual_walls=(), _prefer_clearance=True):
    """Find a deterministic eight-neighbour A* path through the exported map."""
    width, height, free = grid
    origin, resolution = asset['origin'], float(asset['resolution_m'])
    walls = [_wall_segment((w['start']['x'],w['start']['y']), (w['end']['x'],w['end']['y']))
             for w in _normalise_virtual_walls(virtual_walls)]
    # Exact anchors avoid cell-centre artifacts when a straight navigable leg
    # runs on the boundary between raster rows; this also keeps open stress-map
    # routes proportional to their length rather than the map's pixel count.
    factor,costs = _clearance_costs(grid,resolution)
    a,b = (start['x'],start['y']),(end['x'],end['y'])
    steps = max(1,ceil(hypot(b[0]-a[0],b[1]-a[1])/resolution*2))
    direct = not _crosses_virtual_wall(a,b,walls)
    for step in range(steps+1) if direct else ():
        ratio = step/steps
        x = floor((a[0]+(b[0]-a[0])*ratio-float(origin[0]))/resolution)
        y = height-1-floor((a[1]+(b[1]-a[1])*ratio-float(origin[1]))/resolution)
        if (x,y) not in free or costs[y//factor,x//factor] > 2.:
            direct = False
            break
    if direct:
        return [a,b]
    first = _nearest_free_cell(start,width,height,free,origin,resolution,virtual_walls=walls)
    last = _nearest_free_cell(end,width,height,free,origin,resolution,virtual_walls=walls)
    initial, goal = first[1]*width+first[0], last[1]*width+last[0]
    use_clearance = (_prefer_clearance and resolution<=.2
        and costs[first[1]//factor,first[0]//factor]<6
        and costs[last[1]//factor,last[0]//factor]<6)
    parents = bytearray(width*height)
    parents[initial] = 9
    scores = {initial:0.}
    frontier = [(hypot(last[0]-first[0],last[1]-first[1]),0,initial,0.)]
    serial = 0
    expanded = 0
    while frontier:
        _,_,index,cost = heappop(frontier)
        if cost != scores.get(index):
            continue
        if index == goal:
            path = []
            while index != initial:
                x,y = index%width,index//width
                path.append(_cell_center((x,y),height,origin,resolution))
                dx,dy = _DIRECTIONS[parents[index]-1]
                index -= dy*width+dx
            path.append(_cell_center(first,height,origin,resolution))
            path.reverse()
            # Preserve exact waypoint anchors, not just raster cell centres.
            return [(start['x'],start['y']),*path,(end['x'],end['y'])]
        expanded += 1
        if expanded>250000:
            raise AutomaticRouteError('通行组件路径计算达到安全预览上限；请检查地图范围、障碍与组件位置')
        x,y = index%width,index//width
        current = _cell_center((x,y),height,origin,resolution) if walls else None
        for direction,(dx,dy) in enumerate(_DIRECTIONS,1):
            nx,ny = x+dx,y+dy
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            nxt = ny*width+nx
            if not free.mask[nxt] or (use_clearance and costs[ny//factor,nx//factor]>=6):
                continue
            if use_clearance and dx and dy:
                if (not free.mask[y*width+nx] or not free.mask[ny*width+x]
                    or costs[y//factor,nx//factor]>=6 or costs[ny//factor,x//factor]>=6):
                    continue
            if walls and _crosses_virtual_wall(current,_cell_center((nx,ny),height,origin,resolution),walls):
                continue
            local_cost = float(costs[y//factor,x//factor]+costs[ny//factor,nx//factor])/2
            candidate = cost+hypot(dx,dy)*local_cost
            if candidate >= scores.get(nxt,float('inf')):
                continue
            scores[nxt] = candidate
            parents[nxt] = direction
            serial += 1
            heappush(frontier,(candidate+hypot(last[0]-nx,last[1]-ny),serial,nxt,candidate))
    if use_clearance:
        return raster_path(asset,start,end,grid=grid,virtual_walls=virtual_walls,_prefer_clearance=False)
    raise AutomaticRouteError(f"地图“{asset.get('label') or asset['id']}”的路径被可通行区域或虚拟墙阻断")


def crossing_components(components, path):
    """Order open-footprint intersections along the actual navigable path."""
    hits = []
    for component in components:
        center,width,height,_ = _region_geometry(component)
        for index,(a,b) in enumerate(zip(path,path[1:])):
            local_a = _component_local({'x':a[0],'y':a[1]},center)
            local_b = _component_local({'x':b[0],'y':b[1]},center)
            lo,hi = _segment_area_span(local_a,local_b,width/2-1e-6,height/2-1e-6)
            if lo is not None and hi-lo > 1e-9:
                hits.append((index+lo,component['id'],component))
                break
    return [component for _,_,component in sorted(hits,key=lambda item:(item[0],item[1]))]


def discover_execution_nodes(project,binding,asset,start,end,*,excluded,grid,virtual_walls):
    candidates = [c for c in project.get('components',[]) if c.get('map_asset_id')==asset['id']
                  and c.get('kind') in {'narrow_passage','slow_zone','ramp','gate','auto_door'}
                  and c['id'] not in excluded]
    if not candidates:
        return ()
    path = raster_path(asset,start,end,grid=grid,virtual_walls=virtual_walls)
    crossed = crossing_components(candidates,path)
    if not crossed:
        return ()
    return build_directed_map_execution_plan(project,binding['id'],
        node_refs=[{'kind':'component','id':c['id']} for c in crossed],
        start_anchor=start,end_anchor=end,end_speed_mode='single_point').outbound_nodes


def validate_passage_axis(asset,component,entry,exit_point,*,grid,virtual_walls):
    """A forced passage interior must be straight and free, never an outside detour."""
    width,height,free = grid
    resolution = float(asset['resolution_m'])
    origin = asset['origin']
    a,b = (entry.x,entry.y),(exit_point.x,exit_point.y)
    walls = [_wall_segment((w['start']['x'],w['start']['y']),(w['end']['x'],w['end']['y']))
             for w in _normalise_virtual_walls(virtual_walls)]
    blocked = _crosses_virtual_wall(a,b,walls)
    # Split at every raster boundary. Testing each interval midpoint checks all
    # cells met by the axis without missing a thin/shallow obstacle between
    # fixed-distance samples. Endpoints are tested separately as actual nodes.
    ratios = [0.,1.]
    for first,last,offset in ((a[0],b[0],origin[0]),(a[1],b[1],origin[1])):
        if abs(last-first)<1e-12:
            continue
        low,high = sorted(((first-offset)/resolution,(last-offset)/resolution))
        ratios.extend((offset+line*resolution-first)/(last-first)
                      for line in range(floor(low)+1,ceil(high)))
    ratios.sort()
    checks = [0.,1.,*((lo+hi)/2 for lo,hi in zip(ratios,ratios[1:]))]
    for ratio in checks if not blocked else ():
        x = floor((a[0]+(b[0]-a[0])*ratio-origin[0])/resolution)
        y = height-1-floor((a[1]+(b[1]-a[1])*ratio-origin[1])/resolution)
        if (x,y) not in free:
            blocked = True
            break
    if blocked:
        raise AutomaticRouteError(f"窄通道“{component.get('label') or component['id']}”首尾轴线被地图或虚拟墙阻断；请调整组件位置或通行区域")
