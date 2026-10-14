"""Preview reuse survives reopening while auditing source and published bytes."""
from pathlib import Path
import json
import shutil
from unittest.mock import Mock

import pytest

from autodrive_console.deployment import DeploymentStore
from test_fixed_task_compiler import fixed_project
from test_task_compiler import two_map_project


@pytest.fixture
def ready(tmp_path, two_map_project):
    p = fixed_project(two_map_project)
    store = DeploymentStore(tmp_path/'projects')
    document = store.create('缓存测试')
    root = store._project_dir(document['id'])/'maps'
    shutil.copytree(Path(p['_test_map_root']), root)
    for a in p['map_assets']:
        a['source_yaml'] = str(root/Path(a['source_yaml']).relative_to(Path(p['_test_map_root'])))
    document.update({k:v for k,v in p.items() if not k.startswith('_') and k != 'id'})
    store._write_json(store._document_path(document['id']), document)
    return store, document['id']


def test_preview_and_download_reuse_verified_publication_after_store_recreation(ready, monkeypatch):
    store, id = ready
    first = store.task_compiler_preview(id)
    compile = Mock(side_effect=AssertionError('unchanged preview recompiled'))
    monkeypatch.setattr(store, '_compile_task_preview', compile)
    assert store.task_compiler_preview(id) == first
    filename, contents = store.task_compiler_bundle(id)
    assert filename == '高科一号_双仓配送_experimental.zip'
    assert contents
    restarted = DeploymentStore(store.root)
    monkeypatch.setattr(restarted, '_compile_task_preview', compile)
    assert restarted.task_compiler_preview(id) == first
    compile.assert_not_called()


@pytest.mark.parametrize('change', ['map','yaml','wall','cloud','component','edit','line','template','corrupt','missing'])
def test_changed_inputs_or_damaged_publication_recompile(ready, monkeypatch, change):
    from autodrive_console import task_compiler as tc
    store, id = ready
    first = store.task_compiler_preview(id)
    p = store.get(id)
    source = Path(p['map_assets'][0]['source_yaml'])
    export = store._compiler_export_directory(id,first['input_sha256'])
    if change == 'map':
        data = bytearray(source.with_name('map.pgm').read_bytes());data[-1]=0
        source.with_name('map.pgm').write_bytes(data)
    elif change == 'yaml':
        source.write_text(source.read_text()+'\n# changed metadata\n')
    elif change == 'wall':
        source.with_name('map_walls.yaml').write_text('virtual_walls: {segments: []}\n')
    elif change == 'cloud':
        source.with_name('0.pcd').write_bytes(source.with_name('0.pcd').read_bytes()+b'\n')
    elif change == 'component':
        p['components'][0]['yaw'] += .1
    elif change == 'edit':
        p['map_edits'] = [{'map_asset_id':p['map_assets'][0]['id'],'kind':'qa-only'}]
    elif change == 'line':
        p['task_lines'][0]['name'] += '改'
    elif change == 'template':
        templates = store.root/'qa-templates'
        shutil.copytree(tc.TEMPLATE_ROOT,templates)
        monkeypatch.setattr(tc,'TEMPLATE_ROOT',templates)
        (templates/'start_task.xml').write_text((templates/'start_task.xml').read_text()+'\n')
    else:
        target = export/first['artifacts'][0]['path']
        target.write_bytes(b'corrupted') if change == 'corrupt' else target.unlink()
    store._write_json(store._document_path(id),p)
    compile = Mock(side_effect=RuntimeError('expected cache miss'))
    monkeypatch.setattr(store,'_compile_task_preview',compile)
    with pytest.raises(RuntimeError,match='expected cache miss'):
        store.task_compiler_preview(id)
    compile.assert_called_once()


def test_identical_templates_at_new_extraction_path_keep_the_cache(ready, monkeypatch):
    from autodrive_console import task_compiler as tc
    store, id = ready
    first = store.task_compiler_preview(id)
    relocated = store.root/'new-extraction'/'templates'
    shutil.copytree(tc.TEMPLATE_ROOT,relocated)
    monkeypatch.setattr(tc,'TEMPLATE_ROOT',relocated)
    compile = Mock(side_effect=AssertionError('identical extracted template recompiled'))
    monkeypatch.setattr(store,'_compile_task_preview',compile)
    assert store.task_compiler_preview(id) == first


def test_bytecode_fingerprint_ignores_extraction_filename_but_detects_changed_logic():
    from autodrive_console.task_preview_cache import stable_code_bytes
    one = compile('def f():\n return 1\n','/tmp/_MEIone/module.py','exec')
    same = compile('def f():\n return 1\n','/tmp/_MEItwo/module.py','exec')
    changed = compile('def f():\n return 2\n','/tmp/_MEItwo/module.py','exec')
    assert stable_code_bytes(one) == stable_code_bytes(same)
    assert stable_code_bytes(one) != stable_code_bytes(changed)


def test_compiler_fingerprint_survives_python_hash_randomization():
    import os,subprocess,sys
    code='from autodrive_console.task_preview_cache import _compiler_code_digest; print(_compiler_code_digest().hex())'
    hashes=[subprocess.check_output([sys.executable,'-c',code],env={**os.environ,'PYTHONHASHSEED':str(seed)},text=True).strip() for seed in (1,2)]
    assert hashes[0] == hashes[1]


def test_simultaneous_preview_requests_compile_only_once(ready, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import time
    store,id=ready
    original=store._compile_task_preview
    def slow(*args):
        time.sleep(.03)
        return original(*args)
    compile=Mock(side_effect=slow)
    monkeypatch.setattr(store,'_compile_task_preview',compile)
    with ThreadPoolExecutor(max_workers=4) as workers:
        previews=list(workers.map(lambda _:store.task_compiler_preview(id),range(4)))
    assert all(p==previews[0] for p in previews)
    compile.assert_called_once()
