from copy import deepcopy
import json
from pathlib import Path
from math import pi
from xml.etree import ElementTree as ET

import pytest
from test_task_compiler import two_map_project
from test_fixed_task_compiler import fixed_project, compile_fixed, waypoints
from autodrive_console.task_compiler import CompilationError


def project(two_map_project):
    p = fixed_project(two_map_project)
    p['task_mode'] = 'multi'
    p['task_lines'][0]['steps'].pop()  # One address; two common-source pickups remain.
    return p


def ferry_source(p):
    p['deployment_flow'] = [{'id':'ferry','type':'ferry'},{'id':'target_floor','type':'target_floor'}]
    p['map_stage_assignments'][0]['stage'] = 'ferry'
    p['map_instances'][0].update(role='ferry',scope='global',building='',unit='')
    p['localization_bindings'][0].update(type='ferry',building='',unit='')
    return p


def test_fixed_multi_uses_real_runtime_fragments_and_preserves_every_navigation_node(two_map_project, tmp_path):
    p = project(two_map_project)
    before = deepcopy(p)
    multi = compile_fixed(p)
    assert multi.manifest['task_mode'] == 'multi'
    names = [
        'multi_tasks/高科一号/indoor/1_1.json',
        'multi_tasks/高科一号/floor/1_1_n_n09.json',
        'multi_tasks/高科一号/floor/1_1_n_n09_r.json',
        'multi_tasks/高科一号/indoor/1_1_r.json',
    ]
    assert multi.manifest['multi_task_files'] == names
    artifacts = {a.relative_path:a for a in multi.artifacts}
    assert not any(name.startswith('tasks/') for name in artifacts)
    nodes = []
    for name in names:
        document = json.loads(artifacts[name].content)
        assert set(document) == {'change_loc','map_url','pcd_url','subtask_name','waypoints'}
        nodes.extend(document['waypoints'])
        path = tmp_path/name; path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(artifacts[name].content)
    assert nodes == waypoints(multi)
    single_project = deepcopy(p);single_project['task_mode'] = 'single'
    single = compile_fixed(single_project)
    assert single.manifest['task_mode'] == 'single'
    assert waypoints(single) == nodes  # Geometry, speeds, flags and references are unchanged.
    assert p == before
    from autodrive_console.multi_task_catalog import MultiTaskCatalog
    catalog = MultiTaskCatalog(tmp_path/'multi_tasks').scan()
    assert catalog.validate_destination('高科一号',1,1,15,1509).available
    assert not catalog.issues


def test_multi_elevator_is_dynamic_and_delivery_reports_the_runtime_delivery_code(two_map_project):
    preview = compile_fixed(project(two_map_project))
    trees = {Path(a.relative_path).stem:ET.fromstring(a.content) for a in preview.artifacts if a.relative_path.endswith('.xml')}
    for label in ['outbound_elevator_call','outbound_elevator_ride','return_elevator_call','return_elevator_ride']:
        tree = next(tree for name,tree in trees.items() if label in name)
        assert tree.find('.//GetTaskTargetInfo') is not None
        assert not any(n.get('output_key')=='floor' for n in tree.iter('SetBlackboard'))
        caller = tree.find('.//ElevatorCaller')
        expected = '{origin_floor}' if label in {'outbound_elevator_call','return_elevator_ride'} else '{floor}'
        assert caller.get('target_floor') == expected
    delivery = next(tree for name,tree in trees.items() if 'delivery_upper_unload' in name)
    assert delivery.find('.//GetTaskTargetInfo').get('delivery_code') == '{delivery_code}'
    assert all(n.get('message') == '{delivery_code}' for n in delivery.iter('PublishTaskStatus'))
    commands = [n.attrib for tree in trees.values() for n in tree.iter('CargoSingleCommand')]
    assert commands == [{'caogo_id':'1','operation_code':'0'},{'caogo_id':'2','operation_code':'0'},{'caogo_id':'1','operation_code':'2'}]


def test_ferry_uses_its_saved_stage_files_without_inventing_an_indoor_stage(two_map_project,tmp_path):
    p = ferry_source(project(two_map_project))
    before = deepcopy(p)
    preview = compile_fixed(p)
    files = {a.relative_path:json.loads(a.content) for a in preview.artifacts if a.relative_path.startswith('multi_tasks/')}
    assert not any('/indoor/' in name for name in files)
    assert preview.manifest['multi_task_files'] == [
        'multi_tasks/高科一号/sub_outdoor_eguard.json',
        'multi_tasks/高科一号/floor/1_1_n_n09.json',
        'multi_tasks/高科一号/floor/1_1_n_n09_r.json',
        'multi_tasks/高科一号/sub_outdoor_eguard_r.json',
    ]
    assert preview.manifest['route_families'][0]['required_outputs'] == ['ferry','floor']
    assert [s['type'] for s in preview.manifest['route_families'][0]['stages']] == ['ferry','target_floor']
    outgoing = files['multi_tasks/高科一号/sub_outdoor_eguard.json']['waypoints']
    assert sum('pickup_' in w['waypoint_task_id'] for w in outgoing) == 2
    returning = files['multi_tasks/高科一号/sub_outdoor_eguard_r.json']['waypoints']
    assert not any('pickup_' in w['waypoint_task_id'] or 'delivery_' in w['waypoint_task_id'] for w in returning)
    assert 'task_complete' in returning[-1]['waypoint_task_id']
    assert [w for name in preview.manifest['multi_task_files'] for w in files[name]['waypoints']] == waypoints(preview)
    for name,document in files.items():
        assert set(document) == {'change_loc','map_url','pcd_url','subtask_name','waypoints'}
        path = tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(document))
    from autodrive_console.multi_task_catalog import MultiTaskCatalog
    catalog = MultiTaskCatalog(tmp_path/'multi_tasks').scan()
    assert catalog.gate_status('高科一号').available
    assert catalog.validate_destination('高科一号',1,1,15,1509).available
    assert p == before


@pytest.mark.parametrize('source_role',['indoor','ferry'])
def test_stage_kind_controls_paths_even_when_map_display_label_is_misleading(two_map_project,source_role):
    p = project(two_map_project)
    if source_role=='ferry':
        ferry_source(p)
    p['map_assets'][0]['label'] = '电梯大厅' if source_role=='ferry' else '摆渡层'
    preview = compile_fixed(p)
    expected = 'sub_outdoor_eguard.json' if source_role=='ferry' else 'indoor/1_1.json'
    assert preview.manifest['multi_task_files'][0] == f'multi_tasks/高科一号/{expected}'


def test_multi_export_rejects_conflicting_saved_stage_and_localization_role(two_map_project):
    p = ferry_source(project(two_map_project))
    p['localization_bindings'][0].update(type='indoor',building='1',unit='1')
    with pytest.raises(CompilationError,match='阶段|角色'):
        compile_fixed(p)


def test_multi_export_does_not_silently_reorder_or_skip_configured_stages(two_map_project):
    p = ferry_source(project(two_map_project))
    p['deployment_flow'].reverse()
    with pytest.raises(CompilationError,match='顺序|阶段'):
        compile_fixed(p)
    p['deployment_flow'].reverse()
    p['deployment_flow'].insert(1,{'id':'lobby','type':'lobby'})
    with pytest.raises(CompilationError,match='顺序|阶段'):
        compile_fixed(p)


def test_special_floor_names_use_button_labels_and_runtime_metadata_uses_physical_index(two_map_project):
    p = project(two_map_project)
    p['map_instances'][1]['role'] = 'floor_override'
    p['physical_elevators'][0]['min_floor'] = 1
    p['physical_elevators'][0]['unavailable_button_floors'] = [11]
    preview = compile_fixed(p)
    assert 'multi_tasks/高科一号/floor/1_1_15_1509.json' in preview.manifest['multi_task_files']
    target = preview.manifest['route_families'][0]['targets'][0]
    assert target['button_floor'] == 15
    assert target['physical_floor'] == 13  # Zero-based: buttons 1..10,12..15.


@pytest.mark.parametrize('source_type',['indoor','ferry'])
def test_multi_elevator_switches_and_recovers_the_correct_map_on_both_legs(two_map_project,source_type):
    p = project(two_map_project)
    if source_type=='ferry':
        ferry_source(p)
    preview = compile_fixed(p)
    artifacts = {a.relative_path:a.content for a in preview.artifacts}
    entries = json.loads(artifacts['runtime/loc_yaml_path.json'])['loc_yaml'][0]['yaml_index']
    common = next(e for e in entries if e['type']==source_type)
    floor = next(e for e in entries if e['type']=='floor')
    trees = {Path(path).stem:ET.fromstring(body) for path,body in artifacts.items() if path.endswith('.xml')}
    for direction,odometry,destination,x,y,yaw in [
        ('outbound',floor,floor,2.,0.,pi/2),('return',floor,common,0.,0.,-pi/2),
    ]:
        ride = next(tree for name,tree in trees.items() if f'{direction}_elevator_ride' in name)
        assert ride.find('.//SwitchMap').get('map_url') == destination['2D_yaml']
        enabled = next(n for n in ride.iter('SetUseWheelOdom') if n.get('use_wheel_odom')=='true')
        recovered = next(n for n in ride.iter('SetUseWheelOdom') if n.get('use_wheel_odom')=='false')
        assert enabled.get('map_path') == odometry['yaml']
        assert recovered.get('map_path') == destination['yaml']
        assert float(recovered.get('x')) == pytest.approx(x)
        assert float(recovered.get('y')) == pytest.approx(y)
        assert float(recovered.get('yaw')) == pytest.approx(yaw)
        assert float(recovered.get('z')) == .4


def test_store_rejects_a_compiler_that_ignores_the_selected_project_mode(tmp_path,monkeypatch):
    from autodrive_console.deployment import DeploymentStore
    from autodrive_console.task_compiler import CompilationPreview, Artifact
    store = DeploymentStore(tmp_path/'projects')
    p = store.create('模式审计','multi')
    wrong = CompilationPreview('a'*64,{},(Artifact('tasks/wrong.json',b'{}','b'*64),),{'task_mode':'single'},{})
    monkeypatch.setattr('autodrive_console.deployment.compile_fixed_task_lines',lambda *args,**kwargs:wrong)
    with pytest.raises(CompilationError,match='模式不一致'):
        store._compile_task_preview(p['id'],p)


@pytest.mark.parametrize('problem', ['multiple_destinations','floor_reentry','missing_room','no_floor'])
def test_multi_rejects_unrepresentable_itineraries_instead_of_exporting_single(two_map_project,problem):
    p = project(two_map_project)
    if problem == 'multiple_destinations':
        p['task_lines'][0]['steps'].append({'kind':'component','id':'customer-b','action':{'purpose':'delivery','cargo_id':2,'operation':'open'}})
    elif problem == 'floor_reentry':
        p['task_lines'][0]['steps'].append({'kind':'component','id':'market-a','action':{'purpose':'pickup','cargo_id':1,'operation':'open'}})
    elif problem == 'missing_room':
        next(c for c in p['components'] if c['id']=='target')['attributes']['door'] = ''
    else:
        p['task_lines'][0]['steps'] = p['task_lines'][0]['steps'][:4]
    with pytest.raises(CompilationError,match='多任务|房号|门牌'):
        compile_fixed(p)
