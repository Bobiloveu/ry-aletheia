"""Return travel must retrace the chosen route, including facility sides."""
from copy import deepcopy
import json
from math import atan2, pi
from xml.etree import ElementTree as ET

import pytest
from test_task_compiler import two_map_project
from test_fixed_task_compiler import fixed_project, compile_fixed, waypoints
from test_fixed_task_return import straight_project, region, return_nodes


def xy(node):
    position = node['pose']['position']
    return position['x'], position['y']


def test_same_map_return_retraces_repeated_visits_without_repeating_cargo(two_map_project):
    project = fixed_project(two_map_project)
    project['task_lines'][0]['steps'] = project['task_lines'][0]['steps'][:4]
    before = deepcopy(project)
    preview = compile_fixed(project)
    returned = return_nodes(preview)
    assert list(map(xy, returned)) == [(2., 4.), (4., 4.), (2., 4.), (0., -2.)]
    assert all(not node['waypoint_task_id'] for node in returned[:-1])
    assert 'task_complete' in returned[-1]['waypoint_task_id']
    assert project == before


@pytest.mark.parametrize('mode', ['single', 'multi'])
def test_floor_return_reverses_passage_axis_before_reentering_same_lift(two_map_project, mode):
    project = fixed_project(two_map_project)
    project['task_mode'] = mode
    project['task_lines'][0]['steps'].pop()
    project['components'].append({**region('floor-passage', 2., 3., width=1., height=2.),
                                  'map_asset_id':'target-map'})
    project['task_lines'][0]['steps'].insert(-1, {'kind':'component', 'id':'floor-passage'})
    preview = compile_fixed(project)
    actual = [(xy(node), trace['role'], node['speed_mode'])
              for node, trace in zip(waypoints(preview), preview.manifest['waypoint_trace'])
              if trace['source_id']=='floor-passage']
    assert actual == [((2., 2.), 'entry', 'single_point'), ((2., 4.), 'exit', 'narrow_point'),
                      ((2., 4.), 'entry', 'single_point'), ((2., 2.), 'exit', 'narrow_point')]
    floor_return = [node for node, trace in zip(waypoints(preview), preview.manifest['waypoint_trace'])
                    if trace['leg']=='return' and trace['map_asset_id']=='target-map']
    for node, expected in zip(floor_return, [(2., 4.), (2., 2.), (2., -2.5), (2., -2.5), (2., 0.)], strict=True):
        assert xy(node) == pytest.approx(expected)
    if mode == 'multi':
        exported = next(json.loads(a.content) for a in preview.artifacts
                        if '/floor/' in a.relative_path and a.relative_path.endswith('_r.json'))
        assert list(map(xy, exported['waypoints'])) == list(map(xy, floor_return))


def test_return_door_reuses_asymmetric_clearance_points_and_reverses_actions(two_map_project):
    project = straight_project(two_map_project)
    door = region('door-device', 5., 0., width=1., height=3., kind='auto_door')
    door['attributes'].update(pre_open_distance_m=1., post_open_distance_m=2.)
    project['components'].append(door)
    preview = compile_fixed(project)
    nodes = [(node, trace) for node, trace in zip(waypoints(preview), preview.manifest['waypoint_trace'])
             if trace['source_id']=='door-device']
    assert [(xy(node), trace['leg'], trace['role']) for node, trace in nodes] == [
        ((3.5, 0.), 'outbound', 'entry'), ((7.5, 0.), 'outbound', 'exit'),
        ((7.5, 0.), 'return', 'entry'), ((3.5, 0.), 'return', 'exit')]
    assert 'open_back' in nodes[2][0]['waypoint_task_id']
    assert 'close_back' in nodes[3][0]['waypoint_task_id']
    for node, _ in nodes[2:]:
        q = node['pose']['orientation']
        assert abs(2*atan2(q['z'], q['w'])) == pytest.approx(pi)
    trees = {a.relative_path.rsplit('/', 1)[-1][:-4]: ET.fromstring(a.content)
             for a in preview.artifacts if a.relative_path.endswith('.xml')}
    assert sum(len(list(trees[node['waypoint_task_id']].iter('CargoSingleCommand')))
               for node in return_nodes(preview) if node['waypoint_task_id']) == 0


def test_terminal_transition_keeps_continuous_speed_on_retraced_route(two_map_project):
    project = fixed_project(two_map_project)
    project['waypoints'].append({'id':'terminal', 'kind':'transition', 'map_asset_id':'lobby-map',
                                 'x':6., 'y':4., 'yaw':0., 'speed_mode':'normal'})
    project['task_lines'][0]['steps'] = [project['task_lines'][0]['steps'][0],
                                        {'kind':'transition', 'id':'terminal'}]
    preview = compile_fixed(project)
    returned = return_nodes(preview)
    assert list(map(xy, returned)) == [(2., 4.), (0., -2.)]
    assert returned[0]['speed_mode']=='normal'
    assert not returned[0]['is_single_point']


def test_return_passage_entry_stops_even_when_final_outbound_transition_is_normal(two_map_project):
    project = straight_project(two_map_project)
    project['components'].append(region('passage', 5., 0.))
    project['waypoints'].append({'id':'terminal', 'kind':'transition', 'map_asset_id':'lobby-map',
                                'x':10., 'y':0., 'yaw':0., 'speed_mode':'normal'})
    project['task_lines'][0]['steps'] = [{'kind':'component','id':'passage'},
                                       {'kind':'transition','id':'terminal'}]
    preview = compile_fixed(project)
    returned = [(node, trace) for node, trace in zip(waypoints(preview), preview.manifest['waypoint_trace'])
                if trace['leg']=='return' and trace['source_id']=='passage']
    assert [(xy(node), trace['role'], node['speed_mode']) for node, trace in returned] == [
        ((7.,0.), 'entry', 'single_point'), ((3.,0.), 'exit', 'narrow_point')]


@pytest.mark.parametrize('kind,speed', [('gate','narrow_point'), ('auto_door','task_point')])
def test_return_device_nodes_keep_their_locked_speed_profile(two_map_project, kind, speed):
    project = straight_project(two_map_project)
    project['components'].append(region('device',5.,0.,width=1.,height=3.,kind=kind))
    preview = compile_fixed(project)
    speeds = [node['speed_mode'] for node, trace in zip(waypoints(preview), preview.manifest['waypoint_trace'])
              if trace['source_id']=='device']
    assert speeds == [speed, speed, speed, speed]
