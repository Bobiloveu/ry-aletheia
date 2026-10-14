"""Integration checks for topology-owned localization without extra confirmation."""
from pathlib import Path

from autodrive_console.deployment import DeploymentStore


def _saved_project(tmp_path):
    store = DeploymentStore(tmp_path / "projects")
    project = store.create("自动定位")
    project["map_assets"] = [
        {"id": "lobby", "label": "大厅"},
        {"id": "floor", "label": "标准层"},
        {"id": "override", "label": "覆盖层"},
    ]
    project["map_instances"] = [
        {"id": "lobby-instance", "map_asset_id": "lobby", "role": "lobby", "building": "5", "unit": "2"},
        {"id": "floor-instance", "map_asset_id": "floor", "role": "typical_floor", "building": "5", "unit": "2"},
        {"id": "override-instance", "map_asset_id": "override", "role": "floor_override", "building": "5", "unit": "2"},
    ]
    store._write_json(store._document_path(project["id"]), project)
    return store, project["id"]


def test_reading_topology_creates_bindings_without_operator_confirmation(tmp_path):
    store, project_id = _saved_project(tmp_path)
    document = store.get(project_id)
    bindings = {item["map_asset_id"]: item for item in document["localization_bindings"]}
    assert set(bindings) == {"lobby", "floor", "override"}
    assert (bindings["lobby"]["type"], bindings["lobby"]["building"], bindings["lobby"]["unit"]) == ("indoor", "5", "2")
    assert bindings["floor"]["floor_template"] == "1"
    assert bindings["override"]["floor_template"] == "2"
    stored = store._document_path(project_id).read_bytes()
    assert store.get(project_id)["localization_bindings"] == document["localization_bindings"]
    assert store._document_path(project_id).read_bytes() == stored


def test_automatic_binding_preserves_legacy_template_and_binding_id(tmp_path):
    store, project_id = _saved_project(tmp_path)
    path = store._document_path(project_id)
    import json
    document = json.loads(path.read_text())
    legacy = {"id": "saved-floor", "map_asset_id": "floor", "type": "floor", "building": "5", "unit": "2", "floor_template": "7"}
    document["localization_bindings"] = [legacy]
    store._write_json(path, document)
    bindings = store.get(project_id)["localization_bindings"]
    assert next(item for item in bindings if item["map_asset_id"] == "floor") == legacy
    assert next(item for item in bindings if item["map_asset_id"] == "override")["floor_template"] != "7"


def test_ambiguous_map_instance_does_not_guess_localization_identity(tmp_path):
    store, project_id = _saved_project(tmp_path)
    path = store._document_path(project_id)
    import json
    document = json.loads(path.read_text())
    document["map_instances"].append({"id": "other", "map_asset_id": "lobby", "role": "lobby", "building": "6", "unit": "2"})
    store._write_json(path, document)
    assert all(item["map_asset_id"] != "lobby" for item in store.get(project_id)["localization_bindings"])
