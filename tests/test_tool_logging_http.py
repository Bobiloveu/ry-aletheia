from __future__ import annotations

import http.client
import io
import json
import logging
import threading
import time
import zipfile
from pathlib import Path
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


def file_info(address, name):
    status, _, body = request(address, 'GET', '/api/tool-logs/files')
    assert status == 200
    return next(f for f in json.loads(body)['files'] if f['name'] == name)


def test_log_management_policy_is_persisted_and_legacy_entries_still_work(http_console):
    address, store = http_console
    policy = {'retention_days': 14, 'max_total_mib': 512, 'max_file_mib': 8}
    status, _, body = request(address, 'PUT', '/api/tool-logs/retention', {'policy': policy})
    assert status == 200, body
    assert json.loads(body)['storage']['policy'] == policy
    status, _, body = request(address, 'GET', '/api/tool-logs/files')
    assert json.loads(body)['storage']['limit_bytes'] == 512 * 1024 * 1024
    assert request(address, 'GET', '/api/tool-logs?scope=all')[0] == 200
    assert request(address, 'PUT', '/api/tool-logs/retention', {'policy': {**policy, 'retention_days': False}})[0] == 400
    assert store.storage_status()['policy'] == policy


def test_http_clear_keeps_open_writer_and_requires_confirmation(http_console):
    address, store = http_console
    path = store.directory / 'video-runtime.log'
    with path.open('ab', buffering=0) as producer:
        producer.write(b'before\n')
        file = file_info(address, path.name)
        url = f'/api/tool-logs/files/{path.name}/clear'
        assert request(address, 'POST', url, {'file_id': file['file_id']})[0] == 400
        assert path.read_bytes() == b'before\n'
        status, _, body = request(address, 'POST', url, {'file_id': file['file_id'], 'confirm': True})
        assert status == 200, body
        producer.write(b'after\n')
        assert path.read_bytes() == b'after\n'


def test_http_delete_is_only_for_confirmed_current_identity_of_history(http_console):
    address, store = http_console
    path = store.directory / 'video-runtime.log.1'
    path.write_text('old history')
    file = file_info(address, path.name)
    url = f'/api/tool-logs/files/{path.name}'
    replacement = store.directory / 'replacement'
    replacement.write_text('new history')
    replacement.replace(path)
    assert request(address, 'DELETE', url, {'file_id': file['file_id'], 'confirm': True})[0] == 409
    assert path.read_text() == 'new history'
    file = file_info(address, path.name)
    assert request(address, 'DELETE', url, {'file_id': file['file_id'], 'confirm': True})[0] == 200
    assert not path.exists()
    current = store.directory / 'video-runtime.log'
    current.write_text('current')
    file = file_info(address, current.name)
    assert request(address, 'DELETE', '/api/tool-logs/files/video-runtime.log', {'file_id': file['file_id'], 'confirm': True})[0] == 400


def test_http_cleanup_history_does_not_clear_current_logs(http_console):
    address, store = http_console
    (store.directory / 'video-runtime.log').write_text('keep current')
    (store.directory / 'video-runtime.log.1').write_text('remove history')
    assert request(address, 'POST', '/api/tool-logs/cleanup', {'mode': 'history'})[0] == 400
    status, _, body = request(address, 'POST', '/api/tool-logs/cleanup', {'mode': 'history', 'confirm': True})
    assert status == 200, body
    assert (store.directory / 'video-runtime.log').read_text() == 'keep current'
    assert not (store.directory / 'video-runtime.log.1').exists()


def test_http_download_lease_blocks_clear_and_releases_on_context_exit(http_console):
    address, store = http_console
    path = store.directory / 'video-runtime.log'
    path.write_text('download snapshot')
    file = file_info(address, path.name)
    with store.open_diagnostic(path.name):
        assert request(address, 'POST', f'/api/tool-logs/files/{path.name}/clear', {'file_id': file['file_id'], 'confirm': True})[0] == 409
    assert request(address, 'POST', f'/api/tool-logs/files/{path.name}/clear', {'file_id': file['file_id'], 'confirm': True})[0] == 200


def test_downloads_stream_owned_files_without_whole_file_reads(http_console, monkeypatch):
    address, store = http_console
    target = store.directory / 'video-runtime.log'
    target.write_bytes(b'diagnostic\n' * 20000)
    (store.directory / 'video-runtime.log.1').write_text('archived detail')
    original = Path.read_bytes
    def refuse_log_read(path):
        if path.parent == store.directory:
            pytest.fail('download allocated complete log')
        return original(path)
    monkeypatch.setattr(Path, 'read_bytes', refuse_log_read)
    status, _, body = request(address, 'GET', '/api/tool-logs/files/video-runtime.log/download')
    assert status == 200
    assert body == b'diagnostic\n' * 20000
    status, _, body = request(address, 'GET', '/api/tool-logs/download?scope=all')
    assert status == 200
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        assert archive.read('video-runtime.log.1') == b'archived detail'
        assert archive.read('video-runtime.log') == b'diagnostic\n' * 20000
    assert not store._leases


def test_slow_network_download_does_not_pin_or_truncate_the_live_log(http_console, monkeypatch):
    address, store = http_console
    path = store.directory / 'video-runtime.log'
    path.write_text('stable download snapshot')
    selected = file_info(address, path.name)['file_id']
    original = web_console.ConsoleHandler._stream_tool_log
    def clear_before_network_write(handler, source, size, filename, content_type='text/plain; charset=utf-8'):
        assert not store._leases
        store.clear_file(path.name, selected)
        original(handler, source, size, filename, content_type)
    monkeypatch.setattr(web_console.ConsoleHandler, '_stream_tool_log', clear_before_network_write)
    status, _, body = request(address, 'GET', '/api/tool-logs/files/video-runtime.log/download')
    assert status == 200
    assert body == b'stable download snapshot'
    assert path.read_text() == ''


@pytest.mark.parametrize('path', [
    '/api/tool-logs/files/..%2Fprivate.log/clear',
    '/api/tool-logs/files/video-runtime.log.99/clear',
])
def test_http_management_rejects_paths_outside_owned_log_whitelist(http_console, path):
    address, _ = http_console
    assert request(address, 'POST', path, {'file_id': 'invalid', 'confirm': True})[0] == 400


def test_clear_permission_failure_is_a_controlled_server_error(http_console):
    address, store = http_console
    path = store.directory / 'video-runtime.log'
    path.write_text('keep when permissions fail')
    file = file_info(address, path.name)
    import os
    open_file = os.open
    def deny_target(target, *args, **kwargs):
        if Path(target) == path:
            raise PermissionError('not writable')
        return open_file(target, *args, **kwargs)
    with patch('autodrive_console.tool_logging.os.open', deny_target):
        status, _, body = request(address, 'POST', f'/api/tool-logs/files/{path.name}/clear', {'file_id':file['file_id'],'confirm':True})
    assert status == 500, body
    assert path.read_text() == 'keep when permissions fail'
