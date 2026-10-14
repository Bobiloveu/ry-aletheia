from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree as ET
import json

import pytest
from test_task_compiler import two_map_project
from autodrive_console.task_compiler import CompilationError, bundle_zip


def fixed_project(two_map_project):
    p = two_map_project
    # Real traversable rasters, matching the asset metadata.
    for asset in p['map_assets']:
        Path(asset['source_yaml']).with_name('map.pgm').write_bytes(b'P5\n40 40\n255\n' + b'\xfe' * 1600)
    p['components'].extend([
        {'id':'market-a','kind':'target','map_asset_id':'lobby-map','x':4.,'y':4.,'yaw':0.,'attributes':{}},
        {'id':'market-b','kind':'target','map_asset_id':'lobby-map','x':5.,'y':4.,'yaw':0.,'attributes':{}},
        {'id':'customer-b','kind':'target','map_asset_id':'target-map','x':6.,'y':3.,'yaw':0.,'attributes':{}},
    ])
    p['waypoints'].append({'id':'door','kind':'transition','map_asset_id':'lobby-map','x':2.,'y':4.,'yaw':0.,'speed_mode':'normal'})
    p['task_lines'] = [{'id':'line-a','name':'双仓配送','start_component_id':'start','steps':[
        {'kind':'transition','id':'door'},
        {'kind':'component','id':'market-a','action':{'purpose':'pickup','cargo_id':1,'operation':'open'}},
        {'kind':'transition','id':'door'},
        {'kind':'component','id':'market-b','action':{'purpose':'pickup','cargo_id':2,'operation':'open'}},
        {'kind':'component','id':'target','action':{'purpose':'delivery','cargo_id':1,'operation':'unload'}},
        {'kind':'component','id':'customer-b','action':{'purpose':'delivery','cargo_id':2,'operation':'open'}},
    ]}]
    p['active_task_line_id'] = 'line-a'
    return p


def compile_fixed(p):
    from autodrive_console.fixed_task_compiler import compile_fixed_task_line
    return compile_fixed_task_line(p, map_root=Path(p['_test_map_root']))


def waypoints(preview):
    return [w for sub in preview.task_json['subtasks'] for w in sub['waypoints']]


def test_multiple_pickups_deliveries_and_automatic_return(two_map_project):
    p = fixed_project(two_map_project)
    preview = compile_fixed(p)
    nodes = waypoints(preview)
    actions = {Path(a.relative_path).stem: ET.fromstring(a.content) for a in preview.artifacts if a.relative_path.endswith('.xml')}
    cargo = [(w, actions[w['waypoint_task_id']].find('.//CargoSingleCommand')) for w in nodes if w['waypoint_task_id'] in actions and actions[w['waypoint_task_id']].find('.//CargoSingleCommand') is not None]
    assert [(n.attrib['caogo_id'], n.attrib['operation_code']) for _,n in cargo] == [('1','0'),('2','0'),('1','2'),('2','0')]
    assert len({w['waypoint_id'] for w in nodes}) == len(nodes)
    assert sum(t['source_id']=='door' for t in preview.manifest['waypoint_trace']) == 4
    assert nodes[-1]['pose']['position']['x'] == 0
    assert nodes[-1]['pose']['position']['y'] == -2
    executed = [actions[w['waypoint_task_id']] for w in nodes if w['waypoint_task_id']]
    assert sum(n.attrib.get('status_code') == '109' for root in executed for n in root.iter('PublishTaskStatus')) == 1
    for w, _ in cargo[:2]:
        assert all(n.attrib.get('status_code') != '701' for n in actions[w['waypoint_task_id']].iter('PublishTaskStatus'))
    assert all('GetTaskTargetInfo' not in ET.tostring(root).decode() for root in executed)
    assert len(bundle_zip(preview)) > 0
    manifest = json.loads(next(a.content for a in preview.artifacts if a.relative_path == 'runtime/loc_yaml_path.json'))
    floor = next(e for e in manifest['loc_yaml'][0]['yaml_index'] if e['type'] == 'floor')
    return_sub = next(s for s in preview.task_json['subtasks'] if s['subtask_name'].startswith('return_') and s['map_url'] == floor['2D_yaml'])
    first_return = return_sub['waypoints'][0]
    assert floor['init_return']['x'] == first_return['pose']['position']['x']
    assert floor['init_return']['y'] == first_return['pose']['position']['y']


def test_export_names_explain_actions_in_execution_order_and_match_json_references(two_map_project):
    p = fixed_project(two_map_project)
    preview = compile_fixed(p)
    line = p['task_lines'][0]['name']
    task = next(a for a in preview.artifacts if a.relative_path.startswith('tasks/'))
    assert Path(task.relative_path).name == f"{p['task_compiler']['identity']['community']}_{line}.json"
    assert preview.task_json['task_group_name'] == Path(task.relative_path).stem
    refs = [w['waypoint_task_id'] for w in waypoints(preview) if w['waypoint_task_id']]
    expected = [
        'start_task', 'pickup_upper_open', 'pickup_lower_open',
        'outbound_elevator_call', 'outbound_elevator_ride', 'outbound_elevator_close_door',
        'delivery_upper_unload', 'delivery_lower_open',
        'return_elevator_call', 'return_elevator_ride', 'return_elevator_close_door', 'task_complete',
    ]
    assert refs == [f'{index:02d}_{action}_{line}' for index, action in enumerate(expected, 1)]
    trees = {Path(a.relative_path).stem for a in preview.artifacts if a.relative_path.startswith('waypoint_tasks/')}
    assert trees == set(refs)
    assert sorted(trees) == refs
    assert all('fl_' not in s['subtask_name'] for s in preview.task_json['subtasks'])
    from io import BytesIO
    from zipfile import ZipFile
    from hashlib import sha256
    with ZipFile(BytesIO(bundle_zip(preview))) as bundle:
        assert task.relative_path in bundle.namelist()
        for artifact in preview.manifest['artifacts']:
            assert sha256(bundle.read(artifact['path'])).hexdigest() == artifact['sha256']


def test_same_or_sanitized_line_names_export_without_collisions_or_unsafe_paths(two_map_project):
    p = fixed_project(two_map_project)
    names = ['route/one', 'route\\one', 'route_one_2', '门' * 80, '门' * 79 + '口', '../../']
    base = deepcopy(p['task_lines'][0])
    p['task_lines'] = [{**deepcopy(base), 'id':f'line-{i}', 'name':name} for i,name in enumerate(names)]
    task_paths, tree_paths = [], []
    for line in p['task_lines']:
        p['active_task_line_id'] = line['id']
        preview = compile_fixed(p)
        task = next(a.relative_path for a in preview.artifacts if a.relative_path.startswith('tasks/'))
        task_paths.append(task)
        tree_paths.extend(a.relative_path for a in preview.artifacts if a.relative_path.startswith('waypoint_tasks/'))
        for path in [task, *tree_paths]:
            assert '..' not in Path(path).parts
            assert '\\' not in path
            assert len(Path(path).name.encode('utf-8')) <= 240
    assert len(set(task_paths)) == len(task_paths)
    assert len(set(tree_paths)) == len(tree_paths)


def test_action_filenames_stay_sorted_when_there_are_more_than_99_actions(two_map_project):
    p = fixed_project(two_map_project)
    p['task_lines'][0]['steps'] = [deepcopy(p['task_lines'][0]['steps'][1]) for _ in range(100)]
    preview = compile_fixed(p)
    refs = [w['waypoint_task_id'] for w in waypoints(preview) if w['waypoint_task_id']]
    assert len(refs) == 102
    assert refs[0].startswith('001_start_task_')
    assert refs[-1].startswith('102_task_complete_')
    assert sorted(refs) == refs


def test_selected_normal_transition_is_continuous_in_both_directions(two_map_project):
    p = fixed_project(two_map_project)
    p['task_lines'][0]['steps'] = p['task_lines'][0]['steps'][:2]
    preview = compile_fixed(p)
    visits = [w for w,t in zip(waypoints(preview),preview.manifest['waypoint_trace']) if t['source_id']=='door']
    assert len(visits) == 2
    assert all(w['speed_mode'] == 'normal' for w in visits)
    assert all(not w['is_single_point'] and not w['is_task_point'] for w in visits)
    assert all(not w['waypoint_task_id'] for w in visits)


def test_stale_references_and_no_active_line_are_blocked(two_map_project):
    p = fixed_project(two_map_project)
    p['active_task_line_id'] = None
    with pytest.raises(CompilationError, match='选择'):
        compile_fixed(p)
    p['active_task_line_id'] = 'line-a'
    p['components'] = [c for c in p['components'] if c['id'] != 'market-a']
    with pytest.raises(CompilationError, match='第 2 步'):
        compile_fixed(p)


def test_same_map_line_does_not_require_floor_targets_or_routes(two_map_project):
    p = fixed_project(two_map_project)
    p['task_lines'][0]['steps'] = p['task_lines'][0]['steps'][:4]
    p['localization_routes'] = []
    preview = compile_fixed(p)
    assert all('elevator' not in w['waypoint_task_id'] for w in waypoints(preview))
    assert preview.manifest['active_task_line']['id'] == 'line-a'


def test_ferry_map_with_lift_compiles_without_independent_lobby(two_map_project):
    p = fixed_project(two_map_project)
    p['deployment_flow'] = [{'id':'ferry','type':'ferry'}, {'id':'target_floor','type':'target_floor'}]
    p['localization_routes'] = []
    ferry = p['localization_bindings'][0]
    ferry.update(type='ferry',building='',unit='')
    before = deepcopy(p)
    preview = compile_fixed(p)
    assert p == before  # Global map ownership remains global in the project.
    assert any('/ferry/map.yaml' in sub['map_url'] for sub in preview.task_json['subtasks'])
    locations = json.loads(next(a.content for a in preview.artifacts if a.relative_path=='runtime/loc_yaml_path.json'))
    assert len(locations['loc_yaml']) == 1
    group = locations['loc_yaml'][0]
    assert (group['building'],group['unit']) == ('1','1')
    assert {entry['type'] for entry in group['yaml_index']} == {'ferry','floor'}
    assert len([a for a in preview.artifacts if '_elevator_ride_' in a.relative_path]) == 2
    assert waypoints(preview)[-1]['pose']['position']['y'] == p['components'][0]['y']


def test_ferry_unit_is_not_guessed_from_unconnected_floor(two_map_project):
    p = fixed_project(two_map_project)
    p['localization_bindings'][0].update(type='ferry',building='',unit='')
    p['components'] = [c for c in p['components'] if c['id'] != 'target-elevator']
    with pytest.raises(CompilationError,match='电梯|连接'):
        compile_fixed(p)


def test_shared_ferry_rejects_ambiguous_units_in_selected_line(two_map_project):
    p = fixed_project(two_map_project)
    p['localization_bindings'][0].update(type='ferry',building='',unit='')
    p['map_assets'].append({**p['map_assets'][1],'id':'other-floor'})
    p['localization_bindings'].append({**p['localization_bindings'][1],
        'id':'other-binding','map_asset_id':'other-floor','unit':'2'})
    lift = deepcopy(next(c for c in p['components'] if c['id']=='target-elevator'))
    lift.update(id='other-lift',map_asset_id='other-floor')
    target = deepcopy(next(c for c in p['components'] if c['id']=='target'))
    target.update(id='other-target',map_asset_id='other-floor')
    p['components'] += [lift,target]
    p['task_lines'][0]['steps'].append({'kind':'component','id':'other-target','action':{'purpose':'visit'}})
    before = deepcopy(p)
    with pytest.raises(CompilationError,match='唯一楼栋单元'):
        compile_fixed(p)
    assert p == before


def test_disconnected_map_or_ambiguous_lift_is_not_guessed(two_map_project):
    p = fixed_project(two_map_project)
    p['components'] = [c for c in p['components'] if c['id'] != 'target-elevator']
    with pytest.raises(CompilationError, match='电梯|连接'):
        compile_fixed(p)


def test_terminal_normal_transition_keeps_continuous_speed_and_validates_reserved_speed(two_map_project):
    p = fixed_project(two_map_project)
    p['task_lines'][0]['steps'] = [{'kind':'transition','id':'door'}]
    preview = compile_fixed(p)
    outbound = preview.task_json['subtasks'][1]['waypoints'][-1]
    assert outbound['speed_mode'] == 'normal'
    assert outbound['is_single_point'] is False
    p['waypoints'][-1]['speed_mode'] = 'elevator_in'
    with pytest.raises(CompilationError, match='速度'):
        compile_fixed(p)


def test_start_action_is_executable_and_every_action_has_unique_xml(two_map_project):
    preview = compile_fixed(fixed_project(two_map_project))
    nodes = waypoints(preview)
    assert nodes[0]['is_task_point'] is True
    artifacts = {Path(a.relative_path).stem:a for a in preview.artifacts if a.relative_path.endswith('.xml')}
    assert all(w['waypoint_task_id'] in artifacts for w in nodes if w['waypoint_task_id'])
    assert all(w['is_task_point'] for w in nodes if w['waypoint_task_id'])


@pytest.mark.parametrize('source_type', ('indoor','ferry'))
def test_store_exports_selected_fixed_line_in_the_selected_structure(tmp_path, two_map_project, source_type):
    import shutil
    from autodrive_console.deployment import DeploymentStore, DeploymentError
    p = fixed_project(two_map_project)
    p['task_lines'][0]['steps'].pop()  # One destination, with both pickup stops retained.
    if source_type == 'ferry':
        p['localization_bindings'][0].update(type='ferry',building='',unit='')
        p['map_instances'][0].update(role='ferry',scope='global',building='',unit='')
        p['map_stage_assignments'][0]['stage'] = 'ferry'
        p['deployment_flow'] = [{'id':'ferry','type':'ferry'},{'id':'target_floor','type':'target_floor'}]
    store = DeploymentStore(tmp_path/'projects')
    document = store.create('固定线路导出')
    root = store._project_dir(document['id'])/'maps'
    shutil.copytree(Path(p['_test_map_root']),root)
    for asset in p['map_assets']:
        asset['source_yaml'] = str(root/Path(asset['source_yaml']).relative_to(Path(p['_test_map_root'])))
    p['id'] = document['id']
    for mode in ('single','multi'):
        document.update({k:v for k,v in p.items() if not k.startswith('_')})
        document['task_mode'] = mode
        store._write_json(store._document_path(document['id']),document)
        preview = store.task_compiler_preview(document['id'])
        assert preview['task_mode'] == mode
        assert preview['manifest']['active_task_line']['id'] == 'line-a'
        assert store.get(document['id'])['localization_bindings'][0]['type'] == source_type
        if source_type == 'ferry':
            assert store.get(document['id'])['localization_bindings'][0]['building'] == ''
        filename, content = store.task_compiler_bundle(document['id'])
        assert filename.endswith('_experimental.zip') and len(content)>0
        from io import BytesIO
        from zipfile import ZipFile
        with ZipFile(BytesIO(content)) as archive:
            prefix, forbidden = ('multi_tasks/','tasks/') if mode=='multi' else ('tasks/','multi_tasks/')
            assert any(name.startswith(prefix) for name in archive.namelist())
            assert not any(name.startswith(forbidden) for name in archive.namelist())
            if mode=='multi':
                assert filename == '高科一号_双仓配送_multi_experimental.zip'
    store.delete_task_line(document['id'],'line-a')
    with pytest.raises((CompilationError,DeploymentError),match='选择|线路'):
        store.task_compiler_preview(document['id'])


def test_cross_floor_chain_uses_unique_trip_parameters_and_first_map_init(two_map_project):
    p = fixed_project(two_map_project)
    extra = deepcopy(p['map_assets'][1]);extra['id'] = 'floor-other'
    p['map_assets'].append(extra)
    p['localization_bindings'].append({'id':'other-binding','map_asset_id':'floor-other','building':'1','unit':'1','type':'floor','floor_template':'3'})
    lift = deepcopy(p['components'][2]);lift['id']='other-lift';lift['map_asset_id']='floor-other';lift['attributes']['button_floor']=5
    target = deepcopy(p['components'][3]);target.update(id='other-customer',map_asset_id='floor-other')
    p['components'] += [lift,target]
    p['task_lines'][0]['steps'] += [
        {'kind':'component','id':'other-customer','action':{'purpose':'delivery','cargo_id':1,'operation':'open'}},
        {'kind':'component','id':'market-a','action':{'purpose':'pickup','cargo_id':1,'operation':'close'}},
    ]
    preview = compile_fixed(p)
    locations = json.loads(next(a.content for a in preview.artifacts if a.relative_path=='runtime/loc_yaml_path.json'))
    indoor = next(e for e in locations['loc_yaml'][0]['yaml_index'] if e['type']=='indoor')
    assert indoor['init_go']['x'] == 0
    assert indoor['init_go']['y'] == -2
    ride_trees = [ET.fromstring(a.content) for a in preview.artifacts if '_elevator_ride_' in a.relative_path]
    assert len(ride_trees)==6  # Return reverses all three outbound transfers.
    assert len({ET.tostring(tree) for tree in ride_trees})>=3
    assert len(preview.manifest['subtask_map_asset_ids'])==len(preview.task_json['subtasks'])


def test_reachability_uses_exported_erasure_and_actual_yaml_image(two_map_project):
    p = fixed_project(two_map_project)
    p['task_lines'][0]['steps'] = [p['task_lines'][0]['steps'][1]]
    asset = p['map_assets'][0]
    source = Path(asset['source_yaml'])
    source.write_text(source.read_text().replace('image: map.pgm','image: custom.pgm'))
    source.with_name('map.pgm').unlink()
    pixels = bytearray(b'\xfe'*1600)
    for y in range(40):pixels[y*40+12]=0
    source.with_name('custom.pgm').write_bytes(b'P5\n40 40\n255\n'+pixels)
    with pytest.raises(CompilationError,match='阻断|可达'):
        compile_fixed(p)
    p['map_edits'] = [{'map_asset_id':'lobby-map','kind':'polygon_erase','points':[
        {'x':1.,'y':-10.},{'x':4.,'y':-10.},{'x':4.,'y':30.},{'x':1.,'y':30.}]}]
    preview = compile_fixed(p)
    image = next(a for a in preview.artifacts if a.relative_path.endswith('/custom.pgm'))
    assert image.content.endswith(b'\xfe'*1600)


def test_nested_yaml_image_reference_resolves_inside_export(two_map_project):
    import posixpath
    import yaml
    p = fixed_project(two_map_project)
    p['task_lines'][0]['steps'] = [p['task_lines'][0]['steps'][1]]
    source = Path(p['map_assets'][0]['source_yaml'])
    nested = source.parent / 'images' / 'custom.pgm'
    nested.parent.mkdir()
    source.with_name('map.pgm').rename(nested)
    source.write_text(source.read_text().replace('image: map.pgm', 'image: images/custom.pgm'))
    preview = compile_fixed(p)
    artifacts = {a.relative_path:a.content for a in preview.artifacts}
    for name, content in artifacts.items():
        if name.endswith('/map.yaml'):
            relative = yaml.safe_load(content)['image']
            assert not Path(relative).is_absolute()
            assert posixpath.normpath(posixpath.join(posixpath.dirname(name),relative)) in artifacts
    assert 'images/custom.pgm' in source.read_text()  # Source evidence is unchanged.


def test_inverted_map_uses_yaml_occupancy_not_pixel_majority(two_map_project):
    p = fixed_project(two_map_project)
    p['task_lines'][0]['steps'] = [p['task_lines'][0]['steps'][1]]
    source = Path(p['map_assets'][0]['source_yaml'])
    source.write_text(source.read_text()+'negate: 1\nfree_thresh: 0.196\n')
    source.with_name('map.pgm').write_bytes(b'P5\n40 40\n255\n'+b'\x00'*1600)
    assert compile_fixed(p).task_json['subtasks']


def test_wall_paint_blocks_fixed_line_until_the_wall_is_erased(two_map_project):
    p = fixed_project(two_map_project)
    p['task_lines'][0]['steps'] = [p['task_lines'][0]['steps'][1]]
    wall = {'map_asset_id':'lobby-map','kind':'polygon_erase','mode':'wall','points':[
        {'x':1.,'y':-10.},{'x':3.,'y':-10.},{'x':3.,'y':30.},{'x':1.,'y':30.}]}
    p['map_edits'] = [wall]
    with pytest.raises(CompilationError,match='阻断|可达'):
        compile_fixed(p)
    p['map_edits'].append({**wall,'mode':'erase'})
    assert compile_fixed(p).task_json['subtasks']
