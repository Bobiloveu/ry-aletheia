from __future__ import annotations

import json
import logging
import subprocess
from unittest.mock import patch

import pytest

from autodrive_console.tool_logging import ToolLogStore, _JsonFormatter
from autodrive_console.tool_audit import (
    BrowserEventRecorder, HttpAudit, audit_request, inject_client_diagnostics, safe_message,
)


@pytest.fixture(autouse=True)
def capture_tool_logs(caplog):
    logger = logging.getLogger("ry_aletheia")
    with patch.object(logger, "handlers", [caplog.handler]), patch.object(logger, "propagate", False):
        yield


def test_operation_context_survives_json_log_and_old_mobile_fields(tmp_path):
    audit = HttpAudit("POST", "/api/deployments/p/task-lines?token=secret")
    with audit.context():
        record = logging.LogRecord("ry_aletheia.deployment", logging.INFO, __file__, 1, "已保存", (), None)
        payload = json.loads(_JsonFormatter().format(record))
    assert payload["request_id"] == audit.request_id
    assert payload["path"] == "/api/deployments/p/task-lines"
    assert set(("time", "level", "source", "message")) <= payload.keys()
    (tmp_path / ToolLogStore.NORMAL_NAME).write_text(json.dumps(payload) + "\n")
    assert ToolLogStore(tmp_path).entries()[0]["request_id"] == audit.request_id
    # Existing Flutter parser ignores added keys and continues consuming these strings.
    assert all(isinstance(payload[key], str) for key in ("time", "level", "source", "message"))


def test_safe_message_removes_credentials_queries_and_bounds_text():
    message = safe_message("failed https://admin:password@host/a?token=secret#fragment password=hunter2 Authorization: Bearer abcdef")
    assert "https://host/a" in message
    assert not any(secret in message for secret in ("hunter2", "abcdef", "secret", "admin:", "fragment"))
    assert len(safe_message("a" * 2000, limit=1200)) <= 1200
    assert "sensitive" not in safe_message('{"token":"sensitive-token","password":"sensitive password"} {\'secret\': \'sensitive-secret\'}')
    assert "sensitive" not in safe_message("Command ['supervisorctl', '-p', 'sensitive-password', 'status'] timed out after 5s")
    assert "sensitive" not in safe_message(subprocess.TimeoutExpired(['supervisorctl', '-p', 'sensitive-password', 'status'], 5))
    assert "sensitive" not in safe_message("rtsps://user:sensitive@host/live?token=sensitive")


class FakeHandler:
    def __init__(self, path, method="POST"):
        self.path, self.command = path, method
        self.status = 200
        self.body = {}

    @audit_request
    def action(self):
        self._tool_audit.response(self.status, self.body)


def events(caplog):
    return [record for record in caplog.records if record.name == "ry_aletheia.http"]


def test_http_save_denial_and_failure_capture_operation_result(caplog):
    with caplog.at_level(logging.INFO, logger="ry_aletheia.http"):
        item = FakeHandler("/api/deployments/p/components?password=hidden")
        item.action()
        item.status, item.body = 422, {"error": "invalid token=hidden"}
        item.action()
        item.status, item.body = 503, {"error": "service offline"}
        item.action()
    records = events(caplog)
    assert [r.levelno for r in records] == [20, 20, 20, 30, 20, 40]
    assert "部署" in records[1].message
    assert "422" in records[3].message and "invalid" in records[3].message
    assert "hidden" not in " ".join(r.message for r in records)
    assert records[0].request_id == records[1].request_id
    assert records[2].request_id != records[0].request_id


def test_polling_failures_throttle_and_log_recovery_without_success_spam(caplog):
    with caplog.at_level(logging.INFO, logger="ry_aletheia.http"):
        item = FakeHandler("/api/vehicle-execution-status", "GET")
        for _ in range(5):
            item.action()
        assert not events(caplog)
        item.status, item.body = 503, {"error": "unavailable"}
        for _ in range(100):
            item.action()
        assert len(events(caplog)) == 1
        item.status, item.body = 200, {}
        item.action()
        item.action()
    assert len(events(caplog)) == 2
    assert "恢复" in events(caplog)[-1].message


@pytest.mark.parametrize("path", ["/api/vehicle-control/vector", "/api/vehicle-control/heartbeat", "/api/vehicle-control/command", "/api/observation/heartbeat"])
def test_real_high_frequency_success_routes_never_log_each_pulse(caplog, path):
    with caplog.at_level(logging.INFO, logger="ry_aletheia.http"):
        item = FakeHandler(path)
        for _ in range(100):
            item.action()
    assert not events(caplog)


def test_disconnect_is_not_recorded_as_service_error(caplog):
    class Handler(FakeHandler):
        @audit_request
        def action(self):
            raise BrokenPipeError()
    with caplog.at_level(logging.INFO, logger="ry_aletheia.http"), pytest.raises(BrokenPipeError):
        Handler("/api/deployments/p/task-compiler/download", "GET").action()
    assert all(record.levelno < logging.ERROR for record in events(caplog))


def test_preview_errors_are_visible_even_with_http_200(caplog):
    with caplog.at_level(logging.INFO, logger="ry_aletheia.http"):
        item = FakeHandler("/api/deployments/p/task-compiler/preview", "GET")
        item.body = {"preview": {"errors": ["电梯未关联"]}}
        item.action()
    assert events(caplog)[-1].levelno == logging.WARNING
    assert "电梯未关联" in events(caplog)[-1].message


def test_successful_creation_records_result_identity_without_request_body(caplog):
    with caplog.at_level(logging.INFO, logger="ry_aletheia.http"):
        item = FakeHandler("/api/deployments")
        item.body = {"project": {"id": "project-new", "name": "private project name"}}
        item.action()
    assert "project=project-new" in events(caplog)[-1].message
    assert "private project name" not in events(caplog)[-1].message


def test_case_validation_issues_and_compiler_warnings_remain_visible(caplog):
    with caplog.at_level(logging.INFO, logger="ry_aletheia.http"):
        item = FakeHandler("/api/cases", "GET")
        item.body = {"validationIssues": [{"filename": "broken.json", "message": "JSON格式错误"}]}
        item.action()
        item = FakeHandler("/api/deployments/with-warning/task-compiler/preview", "GET")
        item.body = {"preview": {"errors": [], "warnings": ["实验预览尚未安装"]}}
        item.action()
    assert len(events(caplog)) == 2
    assert all(record.levelno == logging.WARNING for record in events(caplog))
    assert "JSON格式错误" in events(caplog)[0].message
    assert "实验预览尚未安装" in events(caplog)[1].message


def test_unexpected_exception_has_traceback_and_request_id(caplog):
    class Handler(FakeHandler):
        @audit_request
        def action(self):
            raise RuntimeError("worker failed")
    with caplog.at_level(logging.INFO, logger="ry_aletheia.http"), pytest.raises(RuntimeError):
        Handler("/api/settings").action()
    assert events(caplog)[-1].exc_info
    assert events(caplog)[-1].request_id


def test_browser_diagnostics_validate_deduplicate_and_separate_error_level(caplog):
    recorder = BrowserEventRecorder(clock=lambda: 1)
    payload = {"level": "ERROR", "event": "browser_error", "page": "/deployment.html", "message": "failed https://host/a?token=secret"}
    with caplog.at_level(logging.INFO, logger="ry_aletheia.browser"):
        assert recorder.record(payload, "local") is True
        assert recorder.record(payload, "local") is False
    assert caplog.records[-1].levelno == logging.ERROR
    assert "secret" not in caplog.records[-1].message
    for invalid in ({**payload, "page": "https://external.test/"}, {**payload, "page": "/\nforged"}, {**payload, "page": "/\\forged"}, {**payload, "message": "a" * 1201}, {**payload, "event": "anything"}, {**payload, "level": "CRITICAL"}, {**payload, "token": "secret"}):
        with pytest.raises(ValueError):
            recorder.record(invalid, "local")


def test_browser_diagnostics_rate_limit_bounds_clients():
    recorder = BrowserEventRecorder(clock=lambda: 1, maximum=3)
    for index in range(3):
        recorder.record({"level": "INFO", "event": "operation_completed", "page": "/", "message": str(index)}, "a")
    with pytest.raises(OverflowError):
        recorder.record({"level": "ERROR", "event": "browser_error", "page": "/", "message": "new"}, "a")


def test_early_diagnostics_injection_is_idempotent_and_shell_independent():
    body = b"<html><head><script>throw new Error()</script></head><body></body></html>"
    injected = inject_client_diagnostics(body)
    assert injected.index(b"client-diagnostics.js") < injected.index(b"throw new Error")
    assert inject_client_diagnostics(injected) == injected
