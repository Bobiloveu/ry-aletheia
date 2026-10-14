from copy import deepcopy

import pytest

from autodrive_console.deployment import DeploymentError, DeploymentStore


def _fixture(tmp_path):
    store = DeploymentStore(tmp_path / "projects")
    project = store.create("固定线路")
    project["components"] = [
        {"id": "start", "kind": "start", "map_asset_id": "map", "attributes": {}},
        {"id": "market-a", "kind": "target", "map_asset_id": "map", "attributes": {}},
        {"id": "market-b", "kind": "target", "map_asset_id": "map", "attributes": {}},
        {"id": "customer", "kind": "target", "map_asset_id": "floor", "attributes": {}},
    ]
    project["waypoints"] = [{"id": "door", "kind": "transition", "map_asset_id": "map"}]
    store._write_json(store._document_path(project["id"]), project)
    payload = {"name": "超市配送", "start_component_id": "start", "steps": [
        {"kind": "transition", "id": "door"},
        {"kind": "component", "id": "market-a", "action": {"purpose": "pickup", "cargo_id": 1, "operation": "open"}},
        {"kind": "transition", "id": "door"},
        {"kind": "component", "id": "market-b", "action": {"purpose": "pickup", "cargo_id": 2, "operation": "open"}},
        {"kind": "component", "id": "customer", "action": {"purpose": "delivery", "cargo_id": 1, "operation": "unload"}},
    ]}
    return store, project["id"], payload


def test_multiple_pickups_and_repeated_door_preserve_saved_business_order(tmp_path):
    store, project_id, payload = _fixture(tmp_path)
    first = store.save_task_line(project_id, payload)
    second = store.save_task_line(project_id, {**payload, "name": "另一条线路", "steps": [payload["steps"][-1]]})
    document = store.select_task_line(project_id, first["id"])
    assert document["active_task_line_id"] == first["id"]
    assert first["steps"] == payload["steps"]
    assert [line["id"] for line in store.get(project_id)["task_lines"]] == [first["id"], second["id"]]
    store.delete_task_line(project_id, second["id"])
    assert store.get(project_id)["active_task_line_id"] == first["id"]
    assert len(store.get(project_id)["components"]) == 4


@pytest.mark.parametrize("mutation", ["foreign", "empty", "cargo_bool", "cargo_negative", "extra", "transition_action"])
def test_invalid_lines_are_rejected_without_changing_project(tmp_path, mutation):
    store, project_id, payload = _fixture(tmp_path)
    invalid = deepcopy(payload)
    if mutation == "foreign": invalid["steps"][1]["id"] = "other-project-target"
    if mutation == "empty": invalid["steps"] = []
    if mutation == "cargo_bool": invalid["steps"][1]["action"]["cargo_id"] = True
    if mutation == "cargo_negative": invalid["steps"][1]["action"]["cargo_id"] = -1
    if mutation == "extra": invalid["return_steps"] = []
    if mutation == "transition_action": invalid["steps"][0]["action"] = {"purpose": "visit"}
    # Finish any ordinary legacy migration before checking atomic rejection.
    store.get(project_id)
    before = store._document_path(project_id).read_bytes()
    with pytest.raises(DeploymentError):
        store.save_task_line(project_id, invalid)
    assert store._document_path(project_id).read_bytes() == before


def test_selecting_saving_or_deleting_active_line_invalidates_preview(tmp_path):
    store, project_id, payload = _fixture(tmp_path)
    line = store.save_task_line(project_id, payload)
    document = store.get(project_id)
    document["task_compiler"]["identity"]["last_preview_input_sha256"] = "old-preview"
    store._write_json(store._document_path(project_id), document)
    store.select_task_line(project_id, line["id"])
    assert store.get(project_id)["task_compiler"]["identity"]["last_preview_input_sha256"] is None
    store.delete_task_line(project_id, line["id"])
    assert store.get(project_id)["active_task_line_id"] is None


def test_task_line_http_create_update_select_delete_uses_real_store(tmp_path, monkeypatch):
    import io
    import json
    from unittest.mock import Mock
    import web_console
    store, project_id, payload = _fixture(tmp_path)
    monkeypatch.setattr(web_console, 'DEPLOYMENTS', store)
    def call(method, path, body=None):
        item = object.__new__(web_console.ConsoleHandler)
        item.path = path
        item._json = Mock()
        data = json.dumps(body or {}).encode()
        item.headers = {'Content-Length':str(len(data))}
        item.rfile = io.BytesIO(data)
        getattr(item, 'do_' + method)()
        args = item._json.call_args.args
        assert len(args) == 1, args
        return args[0]
    base = f'/api/deployments/{project_id}/task-lines'
    created = call('POST', base, payload)
    identifier = created['task_line']['id']
    updated = call('POST', f'{base}/{identifier}', {**payload,'name':'更名'})
    assert updated['task_line']['id'] == identifier
    assert updated['task_line']['name'] == '更名'
    assert call('POST', f'{base}/{identifier}/select')['project']['active_task_line_id'] == identifier
    assert call('DELETE', f'{base}/{identifier}')['project']['task_lines'] == []


@pytest.mark.parametrize('value', [[], {}, 1, None])
def test_malformed_enum_values_are_controlled_errors(tmp_path, value):
    store, project_id, payload = _fixture(tmp_path)
    for field in ('kind','purpose','operation'):
        invalid = deepcopy(payload)
        if field == 'kind': invalid['steps'][0][field] = value
        else: invalid['steps'][1]['action'][field] = value
        with pytest.raises(DeploymentError):
            store.save_task_line(project_id, invalid)


def test_terminal_facility_requires_explicit_exit_or_target(tmp_path):
    store, project_id, payload = _fixture(tmp_path)
    document = store.get(project_id)
    document['components'].append({'id':'gate','kind':'gate','map_asset_id':'map','attributes':{}})
    store._write_json(store._document_path(project_id),document)
    payload['steps'] = [{'kind':'component','id':'gate'}]
    with pytest.raises(DeploymentError,match='末步|出口'):
        store.save_task_line(project_id,payload)


def test_new_projects_require_explicit_task_line_and_legacy_reads_keep_their_mode(tmp_path):
    from autodrive_console.task_compiler import CompilationError
    store = DeploymentStore(tmp_path/'projects')
    project = store.create('新建项目')
    assert project['task_lines'] == []
    assert project['active_task_line_id'] is None
    with pytest.raises(CompilationError,match='选择'):
        store.task_compiler_preview(project['id'])
    project.pop('task_lines');project.pop('active_task_line_id')
    store._write_json(store._document_path(project['id']),project)
    assert 'task_lines' not in store.get(project['id'])
