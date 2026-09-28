import json
from pathlib import Path

import autodrive_console.task_status_codes as task_status_codes_module
from autodrive_console.return_signal import ReturnSignalGate


def _copy_registry(tmp_path: Path) -> Path:
    config = tmp_path / "task-status-codes.json"
    config.write_bytes(task_status_codes_module.STATUS_CODE_PATH.read_bytes())
    return config


def _replace_code(config: Path, name: str, value: int) -> None:
    document = json.loads(config.read_text(encoding="utf-8"))
    document["codes"][name] = value
    config.write_text(json.dumps(document), encoding="utf-8")


def _invalidate_registry(config: Path) -> None:
    document = json.loads(config.read_text(encoding="utf-8"))
    del document["codes"]["task_start"]
    config.write_text(json.dumps(document), encoding="utf-8")


def test_return_signal_gate_accepts_only_the_first_waiting_return_event_for_each_armed_task():
    """A duplicate or unrelated TaskStatus event must not create a second return command."""
    gate = ReturnSignalGate()

    assert gate.accept("103") is False
    gate.arm(1)
    assert gate.accept("403") is False
    assert gate.accept("103") is True
    assert gate.accept("103") is False
    gate.disarm(1)
    assert gate.accept("103") is False

    gate.arm(2)
    assert gate.accept("103") is True


def test_return_signal_gate_uses_the_reloaded_waiting_return_code(monkeypatch, tmp_path: Path):
    """A changed approved return status must be accepted exactly once when armed."""
    config = _copy_registry(tmp_path)
    monkeypatch.setattr(task_status_codes_module, "STATUS_CODE_PATH", config)
    _replace_code(config, "task_return_waiting", 813)
    gate = ReturnSignalGate()
    gate.arm(1)

    assert gate.accept("813") is True


def test_return_signal_gate_refuses_automatic_return_when_registry_is_invalid(
    monkeypatch, tmp_path: Path,
):
    """A malformed registry cannot authorize a physical automatic-return command."""
    config = _copy_registry(tmp_path)
    monkeypatch.setattr(task_status_codes_module, "STATUS_CODE_PATH", config)
    _invalidate_registry(config)
    gate = ReturnSignalGate()
    gate.arm(1)

    assert gate.accept("103") is False
