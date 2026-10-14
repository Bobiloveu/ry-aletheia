from __future__ import annotations

import http.client
import io
import json
import logging
import threading
import time
from http.server import ThreadingHTTPServer
from unittest.mock import Mock, patch
from types import SimpleNamespace

import pytest
import web_console
from autodrive_console.tool_audit import BrowserEventRecorder
from autodrive_console.tool_logging import ToolLogStore, _JsonFormatter


@pytest.fixture
def http_console(tmp_path):
    store = ToolLogStore(tmp_path / "logs")
    store.directory.mkdir()
    normal = logging.FileHandler(store.file())
    normal.setFormatter(_JsonFormatter())
    errors = logging.FileHandler(store.file(True))
    errors.setLevel(logging.ERROR)
    errors.setFormatter(_JsonFormatter())
    logger = logging.getLogger("ry_aletheia")
    server = ThreadingHTTPServer(("127.0.0.1", 0), web_console.ConsoleHandler)
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    with patch.object(logger, "handlers", [normal, errors]), patch.object(logger, "level", logging.INFO), patch.object(web_console, "LOGS", store), patch.object(web_console, "CLIENT_DIAGNOSTICS", BrowserEventRecorder(maximum=3)):
        worker.start()
        try:
            yield server.server_address, store
        finally:
            server.shutdown()
            worker.join(timeout=2)
            server.server_close()
            normal.close()
            errors.close()


def request(address, method, path, payload=None, headers=None):
    connection = http.client.HTTPConnection(*address, timeout=2)
    try:
        body = json.dumps(payload).encode() if payload is not None else None
        connection.request(method, path, body, headers or {"Content-Type": "application/json"})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def audited_entries(store, request_id):
    # Receiving the response body does not wait for the handler's audit
    # finalizer. Synchronize on the matching record, not TCP delivery timing.
    deadline = time.monotonic() + 2
    terminal_events = {'operation_completed', 'operation_failed',
                       'operation_recovered', 'operation_interrupted'}
    while True:
        entries = store.entries()
        if any(entry['request_id'] == request_id and entry.get('event') in terminal_events
               for entry in entries):
            return entries
        if time.monotonic() >= deadline:
            pytest.fail(f'HTTP audit record did not arrive: {request_id}')
        time.sleep(0.005)


def test_relocalization_browser_is_audited_without_recording_its_path_query(http_console):
    address, store = http_console
    listing = {'root': '/opt/ry/config/localization', 'path': '/opt/ry/config/localization',
               'parent': None, 'directories': [], 'files': []}
    browser = Mock(browse_configs=Mock(return_value=listing))
    with patch.object(web_console, 'MANUAL_RELOCALIZATION', browser):
        status, headers, body = request(address, 'GET', '/api/observation/relocalization/configs?path=private-query')
    assert status == 200
    assert json.loads(body) == listing
    browser.browse_configs.assert_called_once_with('private-query')
    entries = audited_entries(store, headers['X-Request-ID'])
    assert any(entry['request_id'] == headers['X-Request-ID'] for entry in entries)
    assert 'private-query' not in store.file().read_text()


def test_actual_http_project_write_error_and_log_view_preserve_correlation(http_console):
    address, store = http_console
    with patch.object(web_console, "DEPLOYMENTS", Mock(create=Mock(return_value={"id": "p"}))):
        status, headers, body = request(address, "POST", "/api/deployments?token=private", {"name": "test", "task_mode": "multi"})
    assert status == 201, body
    assert len(headers["X-Request-ID"]) == 12
    saved = audited_entries(store, headers['X-Request-ID'])
    assert saved[0]["request_id"] == headers["X-Request-ID"]
    assert saved[0]["status"] == 201
    assert "private" not in store.file().read_text()
    assert not store.entries(True)

    status, headers, body = request(address, "POST", "/api/deployments", {"password": "private"})
    assert status == 400
    saved = audited_entries(store, headers['X-Request-ID'])
    assert saved[0]["level"] == "WARNING"
    assert saved[0]["request_id"] == headers["X-Request-ID"]
    status, _, body = request(address, "GET", "/api/tool-logs?scope=all")
    assert status == 200
    assert json.loads(body)["entries"][0]["request_id"] == headers["X-Request-ID"]


def test_browser_events_enter_real_error_file_and_bad_inputs_never_recurse(http_console):
    address, store = http_console
    payload = {"level": "ERROR", "event": "browser_error", "page": "/deployment.html", "message": "failed https://user:pass@host/path?token=private"}
    status, _, body = request(address, "POST", "/api/tool-logs/client-events", payload)
    assert status == 202 and json.loads(body)["recorded"]
    assert store.entries(True)[0]["source"] == "browser"
    assert "private" not in store.file(True).read_text()
    status, _, body = request(address, "POST", "/api/tool-logs/client-events", payload)
    assert status == 202 and not json.loads(body)["recorded"]
    assert len(store.entries()) == 1
    assert request(address, "POST", "/api/tool-logs/client-events", {**payload, "event": "unknown"})[0] == 400
    assert request(address, "POST", "/api/tool-logs/client-events", {**payload, "message": "unique1"})[0] == 202
    assert request(address, "POST", "/api/tool-logs/client-events", {**payload, "message": "unique2"})[0] == 429
    assert all(item["source"] == "browser" for item in store.entries())
    assert request(address, "POST", "/api/tool-logs/client-events", {**payload, "message": "a" * 9000})[0] == 400


def test_high_frequency_vector_requests_have_no_success_audit_records(http_console):
    address, store = http_console
    with patch.object(web_console, "VEHICLE_CONTROL", Mock(set_vector=Mock(return_value={}))):
        for _ in range(20):
            assert request(address, "POST", "/api/vehicle-control/vector", {"session_id": "s", "linear_ratio": 0.2, "angular_ratio": 0})[0] == 200
    assert not store.entries()


def test_observation_client_error_enters_independent_error_stream(http_console):
    _, store = http_console
    from autodrive_console.observation import ObservationManager
    manager = object.__new__(ObservationManager)
    manager.record_client_event("ERROR", "websocket decode failed")
    assert store.entries(True)[0]["level"] == "ERROR"
    assert store.entries(True)[0]["source"] == "observation"


def test_stdout_follower_failure_after_200_is_not_reported_as_success(http_console):
    _, store = http_console
    from autodrive_console.tool_audit import HttpAudit
    handler = object.__new__(web_console.ConsoleHandler)
    handler.send_response = Mock()
    handler.send_header = Mock()
    handler.end_headers = Mock()
    handler.wfile = io.BytesIO()
    handler._tool_audit = HttpAudit("GET", "/api/robot-logs/sources/s/files/f/tail")
    process = Mock(stdout=io.BytesIO(b""), poll=Mock(return_value=7))
    supervisor = Mock(discover=Mock(return_value=[SimpleNamespace(name="node")]), tail_stdout=Mock(return_value=process))
    selected = SimpleNamespace(name="node.out.log", stream=io.BytesIO())
    with patch.object(web_console, "ROBOT_LOGS", Mock(open_file=Mock(return_value=selected))), patch.object(web_console, "SupervisorClient", Mock(return_value=supervisor)), patch.object(web_console, "ROBOT_LOG_TAILS", Mock()):
        handler._tail_robot_log_stdout("s", "f")
    handler.send_response.assert_called_once_with(200)
    assert store.entries(True)[0]["level"] == "ERROR"
    assert "returncode=7" in store.entries(True)[0]["message"]
    assert "异常退出" in handler._tool_audit.reason


@pytest.mark.parametrize("path", ["/api/report-files/report.html", "/api/robot-logs/downloads/a/file", "/api/deployments/p/task-compiler/download", "/api/reports/report.html/native", "/api/scenario-setup/file"])
def test_meaningful_read_actions_are_logged(path):
    from autodrive_console.tool_audit import HttpAudit
    assert HttpAudit("GET", path).read_action
