"""Regressions for actual facility nodes and retraced return travel."""
from copy import deepcopy
import json
from math import cos, sin
from pathlib import Path

import pytest
from test_task_compiler import two_map_project
from test_fixed_task_compiler import fixed_project, compile_fixed, waypoints
from autodrive_console.task_compiler import CompilationError


def return_nodes(preview):
    return [w for sub in preview.task_json['subtasks'] if sub['subtask_name'].startswith('return_') for w in sub['waypoints']]


def region(identifier, x, y, *, width=4., height=1., kind='narrow_passage', yaw=0.):
    return {'id':identifier,'kind':kind,'map_asset_id':'lobby-map','x':x,'y':y,'yaw':yaw,
            'label':'通道 / A','attributes':{'width_m':width,'height_m':height,'speed_profile':'narrow_point',
            **({'controller_device_id':'123','pre_open_distance_m':.5,'post_open_distance_m':.5} if kind in {'gate','auto_door'} else {})}}


def straight_project(two_map_project):
    p = fixed_project(two_map_project)
    p['components'][0].update(x=0.,y=0.)
    next(c for c in p['components'] if c['id']=='market-a').update(x=10.,y=0.)
    p['task_lines'][0]['steps'] = [p['task_lines'][0]['steps'][1]]
    p['localization_routes'] = []
    return p


def test_waypoint_names_and_trace_describe_actual_exported_nodes(two_map_project):
    p = fixed_project(two_map_project)
    before = deepcopy(p)
    preview = compile_fixed(p)
    nodes = waypoints(preview)
    assert not any('fl_' in w['waypoint_id'] for w in nodes)
    trace = preview.manifest['waypoint_trace']
    assert [t['waypoint_id'] for t in trace] == [w['waypoint_id'] for w in nodes]
    assert len({w['waypoint_id'] for w in nodes}) == len(nodes)
    assert [int(t['waypoint_id'].split('_',1)[0]) for t in trace] == list(range(1,len(nodes)+1))
    assert all(set(t)=={'waypoint_id','map_asset_id','leg','label','role','source_id'} for t in trace)
    assert trace[0]['source_id']=='start' and trace[0]['leg']=='outbound'
    assert trace[-1]['source_id']=='start' and trace[-1]['leg']=='return'
    assert any('pickup' in t['waypoint_id'] for t in trace)
    assert p == before


def test_return_retraces_visits_without_repeating_pickup_actions(two_map_project):
    preview = compile_fixed(fixed_project(two_map_project))
    nodes = return_nodes(preview)
    coordinates = [(w['pose']['position']['x'],w['pose']['position']['y']) for w in nodes]
    assert coordinates[0] == (5.,3.)
    assert coordinates[-5:] == [(5.,4.),(2.,4.),(4.,4.),(2.,4.),(0.,-2.)]
    assert coordinates[-1]==(0.,-2.)
    assert len(nodes)==10
    assert all(not w['waypoint_task_id'] or 'return_elevator' in w['waypoint_task_id']
               or 'task_complete' in w['waypoint_task_id'] for w in nodes)


def test_same_map_return_revisits_prior_positions_without_target_actions(two_map_project):
    p = fixed_project(two_map_project)
    p['task_lines'][0]['steps'] = p['task_lines'][0]['steps'][:4]
    preview = compile_fixed(p)
    nodes = return_nodes(preview)
    assert len(nodes)==4
    assert nodes[-1]['pose']['position']['y']==-2.
    assert all(not node['waypoint_task_id'] for node in nodes[:-1])


@pytest.mark.parametrize('mode,cross_map', [('single',False),('single',True),('multi',True)])
@pytest.mark.parametrize('yaw', [0.,1.2,-2.4])
def test_return_arrival_preserves_saved_start_heading_in_exported_json(two_map_project,mode,cross_map,yaw):
    p = fixed_project(two_map_project)
    p['task_mode'] = mode
    p['components'][0]['yaw'] = yaw
    if cross_map:
        p['task_lines'][0]['steps'].pop()  # One terminal delivery, valid in both modes.
    else:
        p['task_lines'][0]['steps'] = p['task_lines'][0]['steps'][:2]
    before = deepcopy(p)
    preview = compile_fixed(p)
    if mode == 'multi':
        artifacts = {a.relative_path:a for a in preview.artifacts}
        exported = [w for name in preview.manifest['multi_task_files']
                    for w in json.loads(artifacts[name].content)['waypoints']]
    else:
        task = next(a for a in preview.artifacts if a.relative_path.startswith('tasks/'))
        exported = [w for s in json.loads(task.content)['subtasks'] for w in s['waypoints']]
    expected = {'x':0.,'y':0.,'z':sin(yaw/2),'w':cos(yaw/2)}
    assert exported[0]['pose']['orientation'] == pytest.approx(expected)
    assert exported[-1]['pose']['orientation'] == pytest.approx(expected)
    assert exported[-1]['pose'] == exported[0]['pose']
    assert waypoints(preview)[-1]['pose'] == exported[-1]['pose']
    assert 'task_complete' in exported[-1]['waypoint_task_id']
    assert p == before


def test_unselected_passage_emits_long_axis_nodes_both_ways_only_when_crossed(two_map_project):
    p = straight_project(two_map_project)
    p['components'] += [region('passage',5.,0.),region('unused',5.,8.)]
    preview = compile_fixed(p)
    trace = preview.manifest['waypoint_trace']
    passage = [(w,t) for w,t in zip(waypoints(preview),trace) if t['source_id']=='passage']
    assert [(w['pose']['position']['x'],t['leg'],t['role'],w['speed_mode']) for w,t in passage] == [
        (3.,'outbound','entry','single_point'),(7.,'outbound','exit','narrow_point'),
        (7.,'return','entry','single_point'),(3.,'return','exit','narrow_point')]
    assert not any(t['source_id']=='unused' for t in trace)


def test_occupancy_detour_discovers_passage_missing_from_endpoint_chord(two_map_project):
    p = straight_project(two_map_project)
    p['components'].append(region('detour',5.,5.,width=1.8,height=2.))
    # A wall at x=5 has its only opening near y=5; direct y=0 chord is blocked.
    pixels = bytearray(b'\xfe'*1600)
    for row in range(40):
        if row not in {23,24,25}: pixels[row*40+15]=0
    Path(p['map_assets'][0]['source_yaml']).with_name('map.pgm').write_bytes(b'P5\n40 40\n255\n'+pixels)
    preview = compile_fixed(p)
    assert sum(t['source_id']=='detour' for t in preview.manifest['waypoint_trace'])==4


def test_passage_on_chord_is_not_emitted_when_virtual_wall_forces_detour(two_map_project):
    p = straight_project(two_map_project)
    p['components'].append(region('blocked-shortcut',5.,0.,width=1.,height=1.))
    p['virtual_walls'] = [{'map_asset_id':'lobby-map','points':[{'x':5.,'y':-3.},{'x':5.,'y':3.}]}]
    preview = compile_fixed(p)
    assert not any(t['source_id']=='blocked-shortcut' for t in preview.manifest['waypoint_trace'])


def test_return_crossing_unselected_controlled_door_executes_approved_back_actions(two_map_project):
    p = straight_project(two_map_project)
    p['components'].append(region('door-device',5.,0.,width=1.,height=3.,kind='auto_door'))
    preview = compile_fixed(p)
    actions = [w['waypoint_task_id'] for w in return_nodes(preview)]
    assert any('return_auto_door_open_back' in a for a in actions)
    assert any('return_auto_door_close_back' in a for a in actions)


def test_return_reverses_outbound_floor_loopback_without_skipping_maps(two_map_project):
    p = fixed_project(two_map_project)
    extra = deepcopy(p['map_assets'][1]);extra['id']='other-map';p['map_assets'].append(extra)
    p['localization_bindings'].append({'id':'other-binding','map_asset_id':'other-map','building':'1','unit':'1','type':'floor','floor_template':'3'})
    lift = deepcopy(p['components'][2]);lift.update(id='other-lift',map_asset_id='other-map');lift['attributes']['button_floor']=5
    target = deepcopy(p['components'][3]);target.update(id='other-target',map_asset_id='other-map')
    p['components'] += [lift,target]
    p['task_lines'][0]['steps'] += [
        {'kind':'component','id':'other-target','action':{'purpose':'visit'}},
        {'kind':'component','id':'market-a','action':{'purpose':'visit'}}]
    preview = compile_fixed(p)
    maps = [t['map_asset_id'] for t in preview.manifest['waypoint_trace'] if t['leg']=='return']
    assert [map_id for index,map_id in enumerate(maps) if index==0 or map_id!=maps[index-1]] == [
        'lobby-map','other-map','target-map','lobby-map']
    assert any('return_elevator' in a.relative_path for a in preview.artifacts)
    assert return_nodes(preview)[-1]['pose']['position']['y']==-2.


def test_induced_passage_approach_rechecks_controlled_facilities(two_map_project):
    p = straight_project(two_map_project)
    p['components'][0].update(y=1.9)
    next(c for c in p['components'] if c['id']=='market-a').update(y=1.9)
    p['components'] += [region('induced-passage',5.,0.,width=4.,height=3.9),
                         region('approach-door',1.5,.95,width=.2,height=1.,kind='auto_door')]
    preview = compile_fixed(p)
    actions = [w['waypoint_task_id'] for w in waypoints(preview)]
    assert any('auto_door_open_go' in a for a in actions)
    assert any('auto_door_close_go' in a for a in actions)


def test_discovery_prefers_clear_corridor_over_point_robot_gap(two_map_project):
    p = straight_project(two_map_project)
    asset = p['map_assets'][0]
    asset.update(width=200,height=200,resolution_m=.1,origin=[0.,0.,0.])
    source = Path(asset['source_yaml'])
    source.write_text('image: map.pgm\nresolution: 0.1\norigin: [0.,0.,0.]\n')
    p['components'][0].update(x=1.,y=5.)
    next(c for c in p['components'] if c['id']=='market-a').update(x=9.,y=5.)
    p['components'].append(region('clear-corridor',5.,7.,width=2.,height=1.5))
    pixels = bytearray(b'\xfe'*40000)
    for row in range(200):
        y=20.-(row+.5)*.1
        if not (6.2 < y < 7.8 or 4.95 < y < 5.05): pixels[row*200+50]=0
    source.with_name('map.pgm').write_bytes(b'P5\n200 200\n255\n'+pixels)
    preview = compile_fixed(p)
    assert sum(t['source_id']=='clear-corridor' for t in preview.manifest['waypoint_trace'])==4


def test_narrow_axis_blocked_by_virtual_wall_cannot_be_validated_by_outside_detour(two_map_project):
    p = straight_project(two_map_project)
    p['components'].append(region('blocked-axis',5.,0.,width=8.,height=1.))
    p['task_lines'][0]['steps'].insert(0,{'kind':'component','id':'blocked-axis'})
    p['virtual_walls'] = [{'map_asset_id':'lobby-map','points':[{'x':5.,'y':-2.},{'x':5.,'y':2.}]}]
    with pytest.raises(CompilationError,match='窄通道|轴线'):
        compile_fixed(p)
