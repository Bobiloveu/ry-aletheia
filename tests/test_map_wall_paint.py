from copy import deepcopy

import pytest

from autodrive_console.deployment import DeploymentError, DeploymentStore
from autodrive_console.location_manifest import LocationManifestError, _read_pgm_bytes, _rasterize_map_edits
from test_deployment import _map


def test_mixed_wall_erase_edges_accumulate_like_the_canvas_edit_layer():
    asset = {'resolution_m': 1, 'origin': [0, 0, 0]}
    source = b'P5\n3 3\n255\n' + b'\xfe' * 9
    stroke = {'kind': 'brush_erase', 'shape': 'square', 'radius_m': .5,
              'points': [{'x': 1.1, 'y': 1.5}]}
    edits = [{**stroke, 'mode': mode} for mode in ('wall', 'erase', 'wall')]
    _, _, pixels = _read_pgm_bytes(_rasterize_map_edits(source, asset, edits))
    # Each stroke covers 40% of this cell. The combined layer has alpha .784
    # and gray .306, so the same threshold as the preview must make it black.
    assert pixels[3] == 0
    assert pixels[5] == 254


@pytest.mark.parametrize('kind,shape', [('brush_erase','circle'),('brush_erase','square'),('polygon_erase',None)])
def test_wall_paint_exports_black_and_later_erase_restores_white(kind, shape):
    asset={'resolution_m':1,'origin':[0,0,0]}
    points=[{'x':2,'y':2},{'x':4,'y':2},{'x':4,'y':4},{'x':2,'y':4}]
    wall={'kind':kind,'mode':'wall','points':points if kind=='polygon_erase' else [{'x':3,'y':3}], 'radius_m':1,'shape':shape}
    source=b'P5\n8 8\n255\n'+b'\xfe'*64
    before=deepcopy(wall)
    _,_,painted=_read_pgm_bytes(_rasterize_map_edits(source,asset,[wall]))
    assert painted[4*8+3]==0
    assert painted[0]==254
    assert wall==before
    _,_,erased=_read_pgm_bytes(_rasterize_map_edits(source,asset,[wall,{**wall,'mode':'erase'}]))
    assert erased[4*8+3]==254
    _,_,repainted=_read_pgm_bytes(_rasterize_map_edits(source,asset,[wall,{**wall,'mode':'erase'},wall]))
    assert repainted[4*8+3]==0


@pytest.mark.parametrize('mode',[None,'invert','white',True,0])
def test_invalid_wall_modes_are_rejected_by_export(mode):
    edit={'kind':'brush_erase','mode':mode,'radius_m':1,'points':[{'x':3,'y':3}]}
    with pytest.raises(LocationManifestError,match='模式'):
        _rasterize_map_edits(b'P5\n8 8\n255\n'+b'\xfe'*64,{'resolution_m':1,'origin':[0,0,0]},[edit])


def test_saved_wall_mode_survives_reload_and_undo_preserves_original_map(tmp_path,monkeypatch):
    root=tmp_path/'maps';source=_map(root/'lobby')
    monkeypatch.setattr(DeploymentStore,'MAP_ROOT',root.resolve())
    store=DeploymentStore(tmp_path/'deployments');project=store.create('补墙')
    asset=store.import_map(project['id'],source,'大厅','lobby');original=source.with_name('map.pgm').read_bytes()
    payload={'action':'add','map_id':asset['id'],'kind':'brush_erase','mode':'wall','shape':'square','radius_m':.1,'points':[{'x':-.95,'y':-1.95}]}
    store.update_map_edits(project['id'],payload)
    assert store.get(project['id'])['map_edits'][0]['mode']=='wall'
    store.update_map_edits(project['id'],{**payload,'mode':'erase'})
    undone=store.update_map_edits(project['id'],{'action':'undo','map_id':asset['id']})
    assert [e['mode'] for e in undone['map_edits']]==['wall']
    with pytest.raises(DeploymentError,match='模式'):
        store.update_map_edits(project['id'],{**payload,'mode':'invert'})
    assert len(store.get(project['id'])['map_edits'])==1
    assert source.with_name('map.pgm').read_bytes()==original


def test_wall_edits_reach_navigation_export_without_modifying_sources(tmp_path):
    from test_location_manifest import _route_project
    from autodrive_console.location_manifest import compile_location_manifest
    project,root=_route_project(tmp_path,kinds=("floor",))
    asset=project['map_assets'][0]
    from pathlib import Path
    image=Path(asset['source_yaml']).with_name('map.pgm')
    image.write_bytes(b'P5\n100 100\n255\n'+b'\xfe'*10000)
    original=image.read_bytes()
    project['map_edits']=[{'map_asset_id':asset['id'],'kind':'brush_erase','mode':'wall','radius_m':.5,'shape':'square','points':[{'x':.5,'y':.5}]}]
    artifacts=compile_location_manifest(project,map_root=root).artifacts
    exported=next(a.content for a in artifacts if a.relative_path.endswith('/map.pgm'))
    _,_,pixels=_read_pgm_bytes(exported)
    assert pixels[89*100+10]==0
    assert image.read_bytes()==original
