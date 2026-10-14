"""Persisted-read defaults remain usable and failures stay bounded and private."""
from concurrent.futures import ThreadPoolExecutor
import json
import logging

import pytest

from autodrive_console.case_workspace import CaseWorkspace
from autodrive_console.scenario_setup import DEFAULT_DOCUMENT, ScenarioSetupStore
from autodrive_console.settings import DEFAULT_ROBOT_LOG_SOURCES, DEFAULT_VEHICLE_CONTROL_PARAMETERS, RobotSettings, SettingsStore


@pytest.fixture(autouse=True)
def capture_tool_namespace(caplog):
    caplog.set_level(logging.INFO, logger="ry_aletheia")
    logger = logging.getLogger("ry_aletheia")
    added = not logger.propagate
    if added:
        logger.addHandler(caplog.handler)
    yield
    if added:
        logger.removeHandler(caplog.handler)


def _store(kind, root):
    if kind == "settings":
        return SettingsStore(root / "console.json"), {}, RobotSettings(), "ry_aletheia.settings"
    if kind == "scenario":
        return ScenarioSetupStore(root), {}, DEFAULT_DOCUMENT, "ry_aletheia.scenario_setup"
    return CaseWorkspace(root, root / "tasks"), {"schema": 1, "cases": {}}, {"schema": 1, "cases": {}}, "ry_aletheia.case_workspace"


def _records(caplog, source):
    return [record for record in caplog.records if record.name == source]


@pytest.mark.parametrize("kind", ["settings", "scenario", "cases"])
def test_missing_configuration_is_quiet_and_corruption_logs_failure_recovery_only(tmp_path, caplog, kind):
    store, valid, expected, source = _store(kind, tmp_path)
    assert store.load() == expected
    assert not _records(caplog, source)
    store.path.write_text('{"token":"private-config-secret"')
    for _ in range(20):
        assert store.load() == expected
    store.path.write_text(json.dumps(valid))
    for _ in range(20):
        assert store.load() == expected

    records = _records(caplog, source)
    assert [record.levelno for record in records] == [logging.WARNING, logging.INFO]
    assert "private-config-secret" not in caplog.text
    assert all(record.exc_info is None for record in records)


@pytest.mark.parametrize("kind", ["settings", "scenario", "cases"])
def test_concurrent_corrupt_configuration_reads_emit_one_warning(tmp_path, caplog, kind):
    store, _valid, expected, source = _store(kind, tmp_path)
    store.path.write_text("invalid json")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: store.load(), range(40)))
    assert all(result == expected for result in results)
    assert len(_records(caplog, source)) == 1


@pytest.mark.parametrize("section", ["robot_logs", "vehicle_control"])
def test_invalid_persisted_section_retains_safe_defaults_and_logs_recovery(tmp_path, caplog, section):
    store = SettingsStore(tmp_path / "console.json")
    invalid = {"sources": [{"id": "source", "name": "private source", "path": "/etc/private-secret"}]} if section == "robot_logs" else {"press": "private-config-secret"}
    store.path.write_text(json.dumps({"supervisor_command": "supervisorctl -p private-config-secret status", section: invalid}))
    for _ in range(20):
        value = store.load()
        assert value.robot_logs["sources"] == DEFAULT_ROBOT_LOG_SOURCES if section == "robot_logs" else value.vehicle_control == DEFAULT_VEHICLE_CONTROL_PARAMETERS
    store.path.write_text("{}")
    store.load()
    store.load()

    records = _records(caplog, "ry_aletheia.settings")
    assert [record.levelno for record in records] == [logging.WARNING, logging.INFO]
    assert all(section in record.message for record in records)
    assert "private-config-secret" not in caplog.text and "private source" not in caplog.text


def test_scenario_invalid_field_shape_logs_default_fallback_without_content(tmp_path, caplog):
    store = ScenarioSetupStore(tmp_path)
    store.path.write_text('{"profiles":"private-config-secret"}')
    assert store.load()["profiles"] == []
    assert store.load()["profiles"] == []
    store.path.write_text("{}")
    store.load()
    assert [record.levelno for record in _records(caplog, "ry_aletheia.scenario_setup")] == [logging.WARNING, logging.INFO]
    assert "private-config-secret" not in caplog.text
