from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import autodrive_console.task_status_codes as task_status_codes_module
from autodrive_console.models import MultiDestination, MultiTaskRequest
from autodrive_console.multi_task_status import MultiTaskStatusCollector


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


def request() -> MultiTaskRequest:
    return MultiTaskRequest(
        community="数创大厦",
        out_eguard=False,
        return_origin=True,
        destinations=(
            MultiDestination("5", "1", "5", "501", 1, "code-501"),
            MultiDestination("5", "1", "3", "301", 2, "code-301"),
        ),
        task_uuid="task-001",
    )


def test_collector_accepts_only_matching_uuid_delivery_events():
    collector = MultiTaskStatusCollector(request())

    assert collector.observe(SimpleNamespace(status_code="701", task_uuid="", message="code-501")) is False
    assert collector.observe(SimpleNamespace(status_code="701", task_uuid="old", message="code-501")) is False
    assert collector.observe(SimpleNamespace(status_code="109", task_uuid="task-001", message="code-501")) is False
    assert collector.observe(SimpleNamespace(status_code="701", task_uuid="task-001", message="unknown")) is False
    assert collector.observe(SimpleNamespace(status_code="701", task_uuid="task-001", message="code-501")) is True

    evidence = collector.evidence()
    assert evidence[0]["delivery_code"] == "code-501"
    assert evidence[0]["status"] == "passed"
    assert evidence[1]["delivery_code"] == "code-301"
    assert evidence[1]["status"] == "skipped"


def test_collector_does_not_accept_delivery_code_from_another_chain():
    collector = MultiTaskStatusCollector(request())

    assert collector.observe_fields("701", "task-001", "code-501") is True
    assert collector.observe_fields("701", "task-001", "code-501") is False
    assert collector.observe_fields("701", "task-001", "code-301") is True
    assert all(item["status"] == "passed" for item in collector.evidence())


def test_multi_collector_uses_the_reloaded_arrival_code(monkeypatch, tmp_path: Path):
    """A changed approved delivery event marks only the matching frozen destination."""
    config = _copy_registry(tmp_path)
    monkeypatch.setattr(task_status_codes_module, "STATUS_CODE_PATH", config)
    _replace_code(config, "multi_task_arrived", 814)
    collector = MultiTaskStatusCollector(request())

    assert collector.observe_fields("814", "task-001", "code-501") is True


def test_multi_collector_refuses_delivery_when_registry_is_invalid(monkeypatch, tmp_path: Path):
    """A malformed registry cannot mark a frozen delivery point as passed."""
    config = _copy_registry(tmp_path)
    monkeypatch.setattr(task_status_codes_module, "STATUS_CODE_PATH", config)
    _invalidate_registry(config)
    collector = MultiTaskStatusCollector(request())

    assert collector.observe_fields("701", "task-001", "code-501") is False


def test_multi_collector_evidence_uses_the_reloaded_arrival_code(monkeypatch, tmp_path: Path):
    """Skipped evidence must name the currently configured arrival code, not a stale literal."""
    config = _copy_registry(tmp_path)
    monkeypatch.setattr(task_status_codes_module, "STATUS_CODE_PATH", config)
    _replace_code(config, "multi_task_arrived", 814)

    evidence = MultiTaskStatusCollector(request()).evidence()

    assert evidence[0]["message"] == "未收到匹配的 814 配送码事件"


def test_multi_collector_evidence_uses_safe_text_when_registry_is_invalid(monkeypatch, tmp_path: Path):
    """A malformed registry cannot expose an obsolete numeric arrival code in skipped evidence."""
    config = _copy_registry(tmp_path)
    monkeypatch.setattr(task_status_codes_module, "STATUS_CODE_PATH", config)
    _invalidate_registry(config)

    evidence = MultiTaskStatusCollector(request()).evidence()

    assert evidence[0]["message"] == "未收到匹配的配送码事件（状态码配置不可用）"
