"""Store previews and downloads must validate the exact deployment evidence."""
from copy import deepcopy
from pathlib import Path
from math import pi
import shutil

import pytest
import yaml

from autodrive_console.deployment import DeploymentStore
from autodrive_console.task_compiler import CompilationError
from test_task_compiler import two_map_project
from test_fixed_task_compiler import fixed_project, compile_fixed
from test_fixed_multi_export import ferry_source


def store_project(tmp_path, project):
    """Copy synthetic evidence into the same controlled layout as imported maps."""
    project = deepcopy(project)
    store = DeploymentStore(tmp_path / 'projects')
    document = store.create('编译一致性', project.get('task_mode', 'single'))
    root = store._project_dir(document['id']) / 'maps'
    original_root = Path(project['_test_map_root'])
    shutil.copytree(original_root, root)
    for asset in project['map_assets']:
        asset['source_yaml'] = str(root / Path(asset['source_yaml']).relative_to(original_root))
    document.update({k:v for k,v in project.items() if not k.startswith('_') and k != 'id'})
    store._write_json(store._document_path(document['id']), document)
    return store, document['id']


@pytest.mark.parametrize('field', ['building', 'unit'])
def test_store_rejects_source_lobby_instance_ownership_conflict(two_map_project, tmp_path, field):
    project = fixed_project(two_map_project)
    project['task_mode'] = 'multi'
    project['task_lines'][0]['steps'].pop()
    project['map_instances'][0][field] = '2'
    store, identifier = store_project(tmp_path, project)
    with pytest.raises(CompilationError, match='源.*楼栋.*单元'):
        store.task_compiler_preview(identifier)
    assert store.get(identifier)['map_instances'][0][field] == '2'


def test_store_keeps_global_ferry_instance_ownership_empty(two_map_project, tmp_path):
    project = ferry_source(fixed_project(two_map_project))
    project['task_mode'] = 'multi'
    project['task_lines'][0]['steps'].pop()
    store, identifier = store_project(tmp_path, project)
    preview = store.task_compiler_preview(identifier)
    assert preview['manifest']['multi_task_files'][0] == 'multi_tasks/高科一号/sub_outdoor_eguard.json'
    instance = store.get(identifier)['map_instances'][0]
    assert (instance['scope'], instance['building'], instance['unit']) == ('global', '', '')


def test_compiler_accepts_matching_historical_unit_owned_ferry(two_map_project):
    project = ferry_source(fixed_project(two_map_project))
    project['task_mode'] = 'multi'
    project['task_lines'][0]['steps'].pop()
    project['map_instances'][0].update(scope='unit', building='1', unit='1')
    project['localization_bindings'][0].update(building='1', unit='1')
    preview = compile_fixed(project)
    assert preview.manifest['multi_task_files'][0] == 'multi_tasks/高科一号/sub_outdoor_eguard.json'


@pytest.mark.parametrize('yaw', ['0', '-0.0'])
def test_store_accepts_numerically_equal_yaml_calibration_without_rewriting(two_map_project, tmp_path, yaw):
    store, identifier = store_project(tmp_path, fixed_project(two_map_project))
    source = Path(store.get(identifier)['map_assets'][0]['source_yaml'])
    source.write_text(f'image: map.pgm\nresolution: 1\norigin: [-10, -10, {yaw}]\n')
    evidence = source.read_bytes()
    assert store.task_compiler_preview(identifier)['manifest']['task_mode'] == 'single'
    assert source.read_bytes() == evidence


@pytest.mark.parametrize('yaw', [.2, -pi/2, 2*pi, -2*pi, 1e-12])
@pytest.mark.parametrize('mode', ['single', 'multi'])
def test_store_rejects_matching_but_rotated_yaml_and_asset_calibration(two_map_project, tmp_path, yaw, mode):
    project = fixed_project(two_map_project)
    project['task_mode'] = mode
    project['task_lines'][0]['steps'].pop()
    asset = project['map_assets'][0]
    asset['origin'][2] = yaw
    source = Path(asset['source_yaml'])
    metadata = yaml.safe_load(source.read_text())
    metadata['origin'] = list(asset['origin'])
    source.write_text(yaml.safe_dump(metadata))
    store, identifier = store_project(tmp_path, project)
    evidence = Path(store.get(identifier)['map_assets'][0]['source_yaml']).read_bytes()
    for request in (store.task_compiler_preview, store.task_compiler_bundle):
        with pytest.raises(CompilationError, match='不支持旋转栅格.*origin yaw=0.*坐标一致'):
            request(identifier)
    assert Path(store.get(identifier)['map_assets'][0]['source_yaml']).read_bytes() == evidence


@pytest.mark.parametrize('field,value', [
    ('origin', [1000, 1000, 0]),
    ('origin', [-10, -10, .2]),
    ('resolution', .1),
    ('resolution', 0),
    ('resolution', -1),
    ('resolution', float('nan')),
    ('resolution', float('inf')),
    ('resolution', True),
    ('resolution', '1.0'),
    ('resolution', None),
    ('origin', [-10, -10]),
    ('origin', [-10, -10, 0, 0]),
    ('origin', {'x': -10, 'y': -10, 'yaw': 0}),
    ('origin', [-10, -10, float('nan')]),
    ('origin', [-10, float('inf'), 0]),
    ('origin', [-10, -10, True]),
    ('origin', [-10, '-10', 0]),
    ('origin', None),
])
def test_store_rejects_yaml_calibration_drift_and_invalid_schema_after_cached_preview(
    two_map_project, tmp_path, field, value,
):
    store, identifier = store_project(tmp_path, fixed_project(two_map_project))
    store.task_compiler_preview(identifier)
    source = Path(store.get(identifier)['map_assets'][0]['source_yaml'])
    metadata = yaml.safe_load(source.read_text())
    metadata[field] = value
    source.write_text(yaml.safe_dump(metadata))
    evidence = source.read_bytes()
    for request in (store.task_compiler_preview, store.task_compiler_bundle):
        with pytest.raises(CompilationError, match='标定|origin|resolution'):
            request(identifier)
        assert source.read_bytes() == evidence


@pytest.mark.parametrize('map_id,x,y', [('lobby-map', 0., 1.6), ('target-map', 2., -1.6)])
@pytest.mark.parametrize('kind', ['gate', 'auto_door', 'narrow_passage', 'ramp', 'slow_zone'])
@pytest.mark.parametrize('mode', ['single', 'multi'])
def test_store_rejects_facilities_intersecting_reserved_elevator_transfer(
    two_map_project, tmp_path, map_id, x, y, kind, mode,
):
    project = fixed_project(two_map_project)
    project['task_mode'] = mode
    project['task_lines'][0]['steps'] = [project['task_lines'][0]['steps'][-2]]
    next(c for c in project['components'] if c['id'] == 'start').update(y=4.)
    project['components'].append({
        'id': 'lift-access-facility', 'map_asset_id': map_id, 'kind': kind,
        'label': '梯门外设施', 'x': x, 'y': y, 'yaw': .1,
        'attributes': {'width_m': 2., 'height_m': .2, 'speed_profile': 'narrow_point',
                       'controller_device_id': '123', 'pre_open_distance_m': .5, 'post_open_distance_m': .5},
    })
    store, identifier = store_project(tmp_path, project)
    for request in (store.task_compiler_preview, store.task_compiler_bundle):
        with pytest.raises(CompilationError, match='电梯.*梯门外设施'):
            request(identifier)


@pytest.mark.parametrize('kind', ['gate', 'auto_door', 'narrow_passage', 'ramp', 'slow_zone'])
def test_facility_beside_elevator_corridor_does_not_block_transfer(two_map_project, tmp_path, kind):
    project = fixed_project(two_map_project)
    project['task_lines'][0]['steps'] = [project['task_lines'][0]['steps'][-2]]
    next(c for c in project['components'] if c['id'] == 'start').update(y=4.)
    project['components'].append({
        'id': 'beside-lift', 'map_asset_id': 'lobby-map', 'kind': kind,
        'x': 1.1, 'y': 1.6, 'yaw': 0.,
        'attributes': {'width_m': 2., 'height_m': .2, 'speed_profile': 'narrow_point',
                       'controller_device_id': '123', 'pre_open_distance_m': .5, 'post_open_distance_m': .5},
    })
    store, identifier = store_project(tmp_path, project)
    preview = store.task_compiler_preview(identifier)
    assert not any(t['source_id'] == 'beside-lift' for t in preview['manifest']['waypoint_trace'])
    assert any(t['role'] == 'elevator_center' for t in preview['manifest']['waypoint_trace'])
