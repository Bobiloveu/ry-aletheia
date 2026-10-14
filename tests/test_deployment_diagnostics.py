"""Only committed compatibility repairs should report successful changes."""
import logging

import pytest

from autodrive_console.deployment import DeploymentError, DeploymentStore
from test_task_lines import _fixture


@pytest.fixture(autouse=True)
def capture_tool_namespace(caplog):
    caplog.set_level(logging.INFO, logger="ry_aletheia")
    logger = logging.getLogger("ry_aletheia")
    handler_added = not logger.propagate
    if handler_added:
        logger.addHandler(caplog.handler)
    yield
    if handler_added:
        logger.removeHandler(caplog.handler)


def _records(caplog):
    return [record for record in caplog.records if record.name == "ry_aletheia.deployment"]


def test_legacy_project_migration_logs_once_after_persistence(tmp_path, caplog):
    store = DeploymentStore(tmp_path / "projects")
    project = store.create("legacy")
    project.pop("task_mode")
    store._write_json(store._document_path(project["id"]), project)
    caplog.clear()

    store.get(project["id"])
    store.get(project["id"])
    store.list_projects()

    records = _records(caplog)
    assert len(records) == 1 and records[0].levelno == logging.INFO
    assert project["id"] in records[0].message and "auto_lines_added=0" in records[0].message
    assert '"task_mode": "single"' in store._document_path(project["id"]).read_text()


def test_failed_migration_does_not_log_success(tmp_path, monkeypatch, caplog):
    store = DeploymentStore(tmp_path / "projects")
    project = store.create("legacy")
    project.pop("task_mode")
    path = store._document_path(project["id"])
    store._write_json(path, project)
    before = path.read_bytes()

    def fail_write(*_args):
        raise OSError("disk full")

    monkeypatch.setattr(store, "_write_json", fail_write)
    caplog.clear()
    with pytest.raises(OSError, match="disk full"):
        store.get(project["id"])

    records = _records(caplog)
    assert len(records) == 1 and records[0].levelno == logging.ERROR
    assert records[0].exc_info is not None and project["id"] in records[0].message
    assert path.read_bytes() == before


def _floor_project(tmp_path):
    store, project_id, payload = _fixture(tmp_path)
    store.save_task_line(project_id, payload)
    document = store.get(project_id)
    document.update(task_mode="multi", target_line_policy_version=1)
    document["map_assets"] = [{"id": "floor", "label": "floor", "origin": [0, 0, 0], "resolution_m": 1, "width": 20, "height": 20}]
    document["map_instances"] = [{"id": "floor-instance", "map_asset_id": "floor", "role": "typical_floor", "building": "1", "unit": "1"}]
    store._write_json(store._document_path(project_id), document)
    store.get(project_id)
    return store, project_id, payload


def test_one_time_target_line_repair_logs_actual_added_count(tmp_path, caplog):
    store, project_id, _ = _floor_project(tmp_path)
    document = store.get(project_id)
    document.pop("target_line_policy_version")
    document["components"].append({"id": "old-customer", "kind": "target", "map_asset_id": "floor", "attributes": {"door": "1508"}})
    store._write_json(store._document_path(project_id), document)
    caplog.clear()

    repaired = store.get(project_id)
    store.get(project_id)

    assert len(repaired["task_lines"]) == 2
    records = _records(caplog)
    assert len(records) == 1 and "auto_lines_added=1" in records[0].message
    assert project_id in records[0].message


@pytest.mark.parametrize("failed", [False, True])
def test_automatic_lines_report_success_only_after_component_write(tmp_path, monkeypatch, caplog, failed):
    store, project_id, _ = _floor_project(tmp_path)
    path = store._document_path(project_id)
    before = path.read_bytes()
    original_write = store._write_json

    def write(target, document):
        assert not _records(caplog), "success cannot precede durable project write"
        if failed:
            raise OSError("disk full")
        original_write(target, document)

    monkeypatch.setattr(store, "_write_json", write)
    caplog.clear()
    if failed:
        with pytest.raises(OSError):
            store.add_component(project_id, {"map_id": "floor", "kind": "target", "x": 3, "y": 3})
        assert path.read_bytes() == before
        assert not _records(caplog)
    else:
        component = store.add_component(project_id, {"map_id": "floor", "kind": "target", "x": 3, "y": 3})
        records = _records(caplog)
        assert len(records) == 1 and "count=1" in records[0].message
        assert project_id in records[0].message
        assert len(store.get(project_id)["task_lines"]) == 2 and component["id"] in path.read_text()


def test_corrupt_project_skip_logs_once_with_bounded_tracking_then_recovery(tmp_path, caplog):
    store = DeploymentStore(tmp_path / "projects")
    healthy = store.create("healthy")
    for index in range(150):
        path = store._document_path(f"broken-{index:03d}")
        path.parent.mkdir()
        path.write_text("invalid json")
    caplog.clear()

    assert len(store.list_projects()) == 1
    initial = _records(caplog)
    assert initial and len(initial) <= 129
    assert all(record.levelno == logging.WARNING for record in initial)
    caplog.clear()
    store.list_projects()
    assert not _records(caplog)
    repaired = {**healthy, "id": "broken-000", "name": "repaired"}
    store._write_json(store._document_path("broken-000"), repaired)
    assert len(store.list_projects()) == 2
    records = _records(caplog)
    assert any(record.levelno == logging.INFO and "broken-000" in record.message for record in records)
    # Recovery frees one bounded tracking slot for a previously untracked
    # corrupt project, followed by at most one new overflow notice.
    assert sum(record.levelno >= logging.WARNING for record in records) <= 2
    caplog.clear()
    store.list_projects()
    assert not _records(caplog)


def test_recovered_projects_do_not_starve_later_corruption_diagnostics(tmp_path, caplog):
    store = DeploymentStore(tmp_path / "projects")
    for index in range(129):
        identifier = f"project-{index}"
        try:
            raise DeploymentError("invalid stored document")
        except DeploymentError as exc:
            store._record_project_read_result(identifier, exc)
        store._record_project_read_result(identifier, None)

    assert not store._project_read_states
    caplog.clear()
    try:
        raise DeploymentError("invalid stored document")
    except DeploymentError as exc:
        store._record_project_read_result("later-project", exc)
    records = _records(caplog)
    assert len(records) == 1 and records[0].levelno == logging.WARNING
    assert "later-project" in records[0].message


def test_first_delivery_recipe_logs_only_automatically_added_lines(tmp_path, caplog):
    store, project_id, payload = _floor_project(tmp_path)
    document = store.get(project_id)
    document.update(task_lines=[], active_task_line_id=None)
    document["components"].append({"id": "second-customer", "kind": "target", "map_asset_id": "floor", "attributes": {"door": "1508"}})
    store._write_json(store._document_path(project_id), document)
    store.get(project_id)
    caplog.clear()

    manual = store.save_task_line(project_id, payload)

    assert len(store.get(project_id)["task_lines"]) == 2
    assert manual["steps"][-1]["id"] == "customer"
    records = _records(caplog)
    assert len(records) == 1
    assert "operation=save_task_line" in records[0].message and "count=1" in records[0].message
