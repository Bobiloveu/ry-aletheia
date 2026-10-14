"""Every saved multi-mode route must survive preview and runtime fragment export."""
from copy import deepcopy
from itertools import permutations
from io import BytesIO
from pathlib import Path
import json
from zipfile import ZipFile

import pytest
from test_task_compiler import two_map_project
from test_fixed_multi_export import project, ferry_source
from autodrive_console.deployment import DeploymentStore
from autodrive_console.task_compiler import CompilationError, bundle_zip


def multiple(two_map_project):
    p=project(two_map_project)
    customer=next(c for c in p['components'] if c['id']=='customer-b')
    customer['attributes']['door']='1508'
    second=deepcopy(p['task_lines'][0]);second.update(id='line-b',name='1508配送')
    second['steps'][-1]['id']='customer-b'
    p['task_lines'].append(second)
    return p


@pytest.mark.parametrize('ferry',[False,True])
def test_multi_compiles_all_saved_lines_with_independent_floor_files(two_map_project,tmp_path,ferry):
    p=multiple(two_map_project)
    if ferry:ferry_source(p)
    before=deepcopy(p)
    from autodrive_console.fixed_task_compiler import compile_fixed_task_lines
    preview=compile_fixed_task_lines(p,map_root=Path(p['_test_map_root']))
    assert p==before
    assert [line['id'] for line in preview.manifest['compiled_task_lines']]==['line-a','line-b']
    files={a.relative_path:json.loads(a.content) for a in preview.artifacts if a.relative_path.startswith('multi_tasks/')}
    assert len(files)==6  # One common pair and one pair per room.
    for room in ['08','09']:
        for suffix in ['','_r']:
            assert f'multi_tasks/高科一号/floor/1_1_n_n{room}{suffix}.json' in files
    common='sub_outdoor_eguard' if ferry else 'indoor/1_1'
    assert f'multi_tasks/高科一号/{common}.json' in files
    assert not any('/indoor/' in name for name in files) if ferry else True
    assert len(preview.manifest['route_families'][0]['targets'])==2
    assert len(preview.manifest['location_manifest']['bindings'])==preview.manifest['location_manifest']['binding_count']==2
    assert len(preview.task_json['subtasks'])==8
    assert len(preview.manifest['subtask_task_line_ids'])==8
    trace=preview.manifest['waypoint_trace']
    assert {t['task_line_id'] for t in trace}=={'line-a','line-b'}
    assert [t['waypoint_id'] for t in trace]==[w['waypoint_id'] for s in preview.task_json['subtasks'] for w in s['waypoints']]
    for subtask in preview.task_json['subtasks']:
        assert subtask in files.values(),'preview must use actual exported fragment nodes'
    trees={Path(a.relative_path).stem for a in preview.artifacts if a.relative_path.endswith('.xml')}
    assert {w['waypoint_task_id'] for sub in files.values() for w in sub['waypoints'] if w['waypoint_task_id']}<=trees
    with ZipFile(BytesIO(bundle_zip(preview))) as archive:
        for path in files:assert path in archive.namelist()
    from autodrive_console.multi_task_catalog import MultiTaskCatalog
    for name,document in files.items():
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(document))
    catalog=MultiTaskCatalog(tmp_path/'multi_tasks').scan()
    for room in [1508,1509]:assert catalog.validate_destination('高科一号',1,1,15,room).available


def test_multiple_conflicting_public_routes_are_not_silently_overwritten(two_map_project):
    from autodrive_console.fixed_task_compiler import compile_fixed_task_lines
    p=multiple(two_map_project)
    p['task_lines'][1]['steps'][1]['action']['cargo_id']=2
    with pytest.raises(CompilationError,match='公共.*不一致|公共.*冲突'):
        compile_fixed_task_lines(p,map_root=Path(p['_test_map_root']))


def test_invalid_unselected_line_blocks_multi_export_with_its_name(two_map_project):
    from autodrive_console.fixed_task_compiler import compile_fixed_task_lines
    p=multiple(two_map_project);p['task_lines'][1]['steps'][-1]['id']='deleted'
    with pytest.raises(CompilationError,match='1508配送'):
        compile_fixed_task_lines(p,map_root=Path(p['_test_map_root']))


def test_new_floor_target_gets_one_independent_route_with_the_same_common_steps(two_map_project):
    from autodrive_console.task_lines import ensure_floor_target_line
    p=project(two_map_project)
    original=deepcopy(p['task_lines'][0])
    customer=next(c for c in p['components'] if c['id']=='customer-b')
    assert not customer['attributes'].get('door')
    ensure_floor_target_line(p,customer)
    assert len(p['task_lines'])==2
    assert p['task_lines'][0]==original
    added=p['task_lines'][1]
    assert added['id']!=original['id'] and added['steps'][:-1]==original['steps'][:-1]
    assert added['steps'][-1]=={**original['steps'][-1],'id':'customer-b'}
    ensure_floor_target_line(p,customer);assert len(p['task_lines'])==2
    old=deepcopy(customer);customer['attributes']['door']='1508'
    ensure_floor_target_line(p,customer,previous=old)
    assert '1508' in added['name']
    assert p['active_task_line_id']==original['id']
    added['name']='自定义线路';old=deepcopy(customer);customer['attributes']['door']='1507'
    ensure_floor_target_line(p,customer,previous=old)
    assert added['name']=='自定义线路'


def test_automatic_independent_routes_do_not_apply_to_pickup_maps_or_single_mode(two_map_project):
    from autodrive_console.task_lines import ensure_floor_target_line
    p=project(two_map_project)
    market=next(c for c in p['components'] if c['id']=='market-a')
    ensure_floor_target_line(p,market);assert len(p['task_lines'])==1
    p['task_mode']='single'
    ensure_floor_target_line(p,next(c for c in p['components'] if c['id']=='customer-b'))
    assert len(p['task_lines'])==1


def test_different_apartment_return_paths_share_terminal_map_metadata_without_losing_nodes(two_map_project):
    from autodrive_console.fixed_task_compiler import compile_fixed_task_lines,compile_fixed_task_line
    p=multiple(two_map_project)
    p['components'].append({'id':'passage','kind':'narrow_passage','map_asset_id':'target-map',
        'x':4.2,'y':1.5,'yaw':0.,'attributes':{'width_m':.4,'height_m':.2}})
    branches=[compile_fixed_task_line({**p,'active_task_line_id':line['id']},map_root=Path(p['_test_map_root'])) for line in p['task_lines']]
    def floor_pose(preview):
        runtime=json.loads(next(a.content for a in preview.artifacts if a.relative_path=='runtime/loc_yaml_path.json'))
        return next(e for e in runtime['loc_yaml'][0]['yaml_index'] if e['type']=='floor')['init_return']
    assert floor_pose(branches[0])!=floor_pose(branches[1])
    merged=compile_fixed_task_lines(p,map_root=Path(p['_test_map_root']))
    assert floor_pose(merged)==floor_pose(branches[0])
    for line,branch in zip(p['task_lines'],branches):
        expected=[n for n in branch.manifest['waypoint_trace'] if n['source_id']=='passage']
        actual=[n for n in merged.manifest['waypoint_trace'] if n['source_id']=='passage' and n['task_line_id']==line['id']]
        assert len(actual)==len(expected)


def test_terminal_floor_representative_is_stable_when_equal_entries_precede_a_different_one(two_map_project):
    from autodrive_console.fixed_task_compiler import compile_fixed_task_line
    from autodrive_console.fixed_multi_export import merge_multi_line_previews
    p=multiple(two_map_project)
    p['components'].append({'id':'passage','kind':'narrow_passage','map_asset_id':'target-map',
        'x':4.2,'y':1.5,'yaw':0.,'attributes':{'width_m':.4,'height_m':.2}})
    first,second=deepcopy(p['task_lines'])
    first['id']='z';second['id']='b'
    third=deepcopy(first);third['id']='a';third['name']='1507配送'
    customer=deepcopy(next(c for c in p['components'] if c['id']=='target'))
    customer.update(id='customer-c');customer['attributes']['door']='1507';p['components'].append(customer)
    third['steps'][-1]['id']='customer-c'
    p['task_lines']=[first,third,second];p['active_task_line_id']='z'
    branches=[(line,compile_fixed_task_line({**p,'active_task_line_id':line['id']},map_root=Path(p['_test_map_root']))) for line in p['task_lines']]
    def floor_entry(preview):
        document=json.loads(next(a.content for a in preview.artifacts if a.relative_path=='runtime/loc_yaml_path.json'))
        return next(e for e in document['loc_yaml'][0]['yaml_index'] if e['type']=='floor')
    expected=floor_entry(branches[1][1])
    assert floor_entry(branches[0][1])==expected and floor_entry(branches[2][1])!=expected
    for ordered in permutations(branches):assert floor_entry(merge_multi_line_previews(p,ordered))==expected


def test_merge_records_templates_used_only_by_a_later_route(two_map_project):
    from autodrive_console.fixed_task_compiler import compile_fixed_task_lines,compile_fixed_task_line
    p=multiple(two_map_project)
    p['components'].append({'id':'door-control','kind':'auto_door','map_asset_id':'target-map',
        'x':4.9,'y':1.5,'yaw':0.,'attributes':{'width_m':.2,'height_m':1.,'controller_device_id':'12','pre_open_distance_m':.5,'post_open_distance_m':.5}})
    branches=[compile_fixed_task_line({**p,'active_task_line_id':line['id']},map_root=Path(p['_test_map_root'])) for line in p['task_lines']]
    expected={name:digest for branch in branches for name,digest in branch.manifest['template_sha256'].items()}
    assert any('auto_door' in name for name in expected)
    merged=compile_fixed_task_lines(p,map_root=Path(p['_test_map_root']))
    assert merged.manifest['template_sha256']==expected


def test_store_repairs_existing_targets_once_and_placement_creates_exactly_one_more_route(tmp_path):
    from test_task_lines import _fixture
    store,pid,payload=_fixture(tmp_path)
    original=store.save_task_line(pid,payload)
    document=store.get(pid)
    document['map_assets']=[{'id':'floor','label':'15楼','origin':[0,0,0],'resolution_m':1,'width':20,'height':20}]
    document['map_instances']=[{'id':'floor-instance','map_asset_id':'floor','role':'typical_floor','building':'1','unit':'1'}]
    document['components'].append({'id':'old-customer','kind':'target','map_asset_id':'floor','attributes':{'door':'1508'}})
    store._write_json(store._document_path(pid),document)
    switched=store.update_project_settings(pid,{'name':document['name'],'task_mode':'multi'})
    repaired=store.get(pid)
    assert switched==repaired,'mode-switch response includes automatically repaired lines'
    assert repaired['target_line_policy_version']==1 and len(repaired['task_lines'])==2
    assert repaired['task_lines'][0]==original
    generated=repaired['task_lines'][1]
    store.delete_task_line(pid,generated['id'])
    assert len(store.get(pid)['task_lines'])==1,'repeated reads must respect explicit deletion'
    store.save_task_line(pid,{**payload,'name':'原线路更名'},original['id'])
    assert len(store.get(pid)['task_lines'])==1,'ordinary saves must not recreate an explicitly deleted line'
    target=store.add_component(pid,{'map_id':'floor','kind':'target','x':3,'y':3})
    after=store.get(pid);assert len(after['task_lines'])==2
    added=next(l for l in after['task_lines'] if l['steps'][-1]['id']==target['id'])
    store.update_component(pid,target['id'],{'attributes':{'door':'1507'}})
    final=store.get(pid)
    assert len(final['task_lines'])==2
    assert '1507' in next(l for l in final['task_lines'] if l['id']==added['id'])['name']
