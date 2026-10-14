from copy import deepcopy
from http import HTTPStatus
from unittest.mock import patch

import pytest
import web_console
from autodrive_console.deployment import DeploymentError, DeploymentStore
from test_deployment import _map, _deployment_handler, _compiler_ready_store


def test_project_settings_save_keeps_identity_and_all_existing_map_facts(tmp_path, monkeypatch):
    source_root = tmp_path / 'robot-maps'
    source = _map(source_root / 'lobby')
    monkeypatch.setattr(DeploymentStore, 'MAP_ROOT', source_root.resolve())
    store = DeploymentStore(tmp_path / 'deployments')
    project = store.create('原项目', 'single')
    asset = store.import_map(project['id'], source, '大厅', 'lobby')
    store.add_component(project['id'], {'map_id': asset['id'], 'kind': 'start', 'x': -.95, 'y': -1.95})
    before = store.get(project['id'])
    before['task_compiler']['identity']['last_preview_input_sha256'] = 'a' * 64
    store._write_json(store._document_path(project['id']), before)
    export = store._project_dir(project['id']) / 'exports' / 'old.zip'
    export.parent.mkdir(); export.write_bytes(b'previous-export')
    saved = store.update_project_settings(project['id'], {'name': '  修改后   项目  ', 'task_mode': 'multi'})
    expected = deepcopy(before)
    expected.update(name='修改后 项目', task_mode='multi', updated_at=saved['updated_at'])
    expected['task_compiler']['identity']['last_preview_input_sha256'] = None
    assert saved == expected
    assert store.get(project['id']) == saved
    assert store.list_projects()[0]['name'] == '修改后 项目'
    assert export.read_bytes() == b'previous-export'
    assert source.exists()


@pytest.mark.parametrize('payload', [
    {}, {'name': '项目'}, {'name': '', 'task_mode': 'single'},
    {'name': 'x' * 81, 'task_mode': 'single'}, {'name': 123, 'task_mode': 'single'},
    {'name': '项目', 'task_mode': 'unknown'}, {'name': '项目', 'task_mode': True},
    {'name': '项目', 'task_mode': 'multi', 'id': 'other'},
])
def test_project_settings_reject_invalid_payload_without_changing_snapshot(tmp_path, payload):
    store = DeploymentStore(tmp_path / 'deployments')
    project = store.create('项目')
    original = store._document_path(project['id']).read_bytes()
    with pytest.raises(DeploymentError):
        store.update_project_settings(project['id'], payload)
    assert store._document_path(project['id']).read_bytes() == original


def test_unchanged_project_settings_keep_the_verified_preview(tmp_path):
    store = DeploymentStore(tmp_path / 'deployments')
    project = store.create('原项目')
    project['task_compiler']['identity']['last_preview_input_sha256'] = 'a' * 64
    store._write_json(store._document_path(project['id']), project)
    assert store.update_project_settings(project['id'], {'name': ' 原项目 ', 'task_mode': 'single'}) == project


def test_settings_http_persists_the_requested_project_and_rejects_nested_paths(tmp_path):
    store = DeploymentStore(tmp_path / 'deployments')
    project = store.create('原项目')
    handler = _deployment_handler(f"/api/deployments/{project['id']}/settings", {'name': '现场项目', 'task_mode': 'multi'})
    with patch.object(web_console, 'DEPLOYMENTS', store):
        handler.do_POST()
    assert handler._json.call_args.args == ({'project': store.get(project['id'])},)
    assert store.get(project['id'])['task_mode'] == 'multi'
    handler = _deployment_handler(f"/api/deployments/{project['id']}/nested/settings", {'name': '错误项目', 'task_mode': 'single'})
    with patch.object(web_console, 'DEPLOYMENTS', store):
        handler.do_POST()
    assert handler._json.call_args.args[1] == HTTPStatus.BAD_REQUEST
    assert store.get(project['id'])['name'] == '现场项目'


def test_mode_change_recompiles_the_preview_with_the_new_mode(tmp_path, monkeypatch):
    store, project, target = _compiler_ready_store(tmp_path, monkeypatch)
    store.update_component(project['id'], target['id'], {'attributes': {'door': '1509'}})
    store.update_task_compiler_config(project['id'], {'community': '高科一号'})
    before = store.task_compiler_preview(project['id'])
    assert before['task_mode'] == 'single'
    store.update_project_settings(project['id'], {'name': project['name'], 'task_mode': 'multi'})
    after = store.task_compiler_preview(project['id'])
    assert after['task_mode'] == 'multi'
    assert after['input_sha256'] != before['input_sha256']
