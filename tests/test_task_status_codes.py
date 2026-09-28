from __future__ import annotations

import json
from pathlib import Path

import pytest

import autodrive_console.task_status_codes as task_status_codes_module
from autodrive_console.task_status_codes import (
    TaskStatusCodeError,
    task_status_code,
    task_status_codes,
    task_status_phase_by_code,
    task_status_xml_values,
)


def _copy_registry(tmp_path: Path) -> Path:
    target = tmp_path / "task-status-codes.json"
    target.write_bytes(task_status_codes_module.STATUS_CODE_PATH.read_bytes())
    return target


def _read_registry(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_registry(path: Path, document: dict[str, object]) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")


def _replace_code(path: Path, name: str, value: object) -> None:
    document = _read_registry(path)
    document["codes"][name] = value
    _write_registry(path, document)


def _mutate_registry(path: Path, mutation: str) -> None:
    document = _read_registry(path)
    codes = document["codes"]
    if mutation == "missing_key":
        del codes["task_start"]
    elif mutation == "non_integer":
        codes["gate_in"] = "301"
    elif mutation == "out_of_range":
        codes["gate_in"] = 99
    elif mutation == "unknown_schema":
        document["schema"] = 2
    elif mutation == "illegal_duplicate":
        codes["gate_in"] = codes["gate_out"]
    else:  # pragma: no cover - test construction guard
        raise AssertionError(f"unknown mutation: {mutation}")
    _write_registry(path, document)


def test_registry_exposes_confirmed_codes_xml_tokens_and_phases() -> None:
    """Catches a registry that drifts from the confirmed task-status contract."""
    assert task_status_codes()["elevator_waiting"] == 200
    assert task_status_code("task_complete") == "109"
    assert task_status_xml_values()["STATUS_GATE_OUT"] == "302"
    assert task_status_phase_by_code()["304"] == "closing_access_door"


def test_onefile_release_builder_embeds_the_runtime_status_registry() -> None:
    """Catches a release that starts from /tmp/_MEI but cannot read its required registry."""
    builder = (Path(__file__).resolve().parents[1] / "build_binary.sh").read_text(
        encoding="utf-8"
    )

    assert '--add-data "autodrive_console/task_templates/indoor_elevator_v1/task-status-codes.json:autodrive_console/task_templates/indoor_elevator_v1"' in builder


def test_registry_reloads_a_controlled_file_change(monkeypatch, tmp_path: Path) -> None:
    """Catches stale in-process caching after a controlled registry update."""
    config = _copy_registry(tmp_path)
    monkeypatch.setattr(task_status_codes_module, "STATUS_CODE_PATH", config)

    _replace_code(config, "gate_in", 811)

    assert task_status_code("gate_in") == "811"
    assert task_status_phase_by_code()["811"] == "opening_gate"


def test_registry_normalizes_invalid_utf8_to_configuration_error(monkeypatch, tmp_path: Path) -> None:
    """Catches unreadable registry bytes leaking a decoder-specific exception."""
    config = _copy_registry(tmp_path)
    monkeypatch.setattr(task_status_codes_module, "STATUS_CODE_PATH", config)
    config.write_bytes(b"\xff")

    with pytest.raises(TaskStatusCodeError):
        task_status_codes()


@pytest.mark.parametrize(
    "mutation",
    ["missing_key", "non_integer", "out_of_range", "unknown_schema", "illegal_duplicate"],
)
def test_registry_rejects_invalid_configuration(monkeypatch, tmp_path: Path, mutation: str) -> None:
    """Catches malformed registry input before a consumer can act on it."""
    config = _copy_registry(tmp_path)
    monkeypatch.setattr(task_status_codes_module, "STATUS_CODE_PATH", config)
    _mutate_registry(config, mutation)

    with pytest.raises(TaskStatusCodeError):
        task_status_codes()
