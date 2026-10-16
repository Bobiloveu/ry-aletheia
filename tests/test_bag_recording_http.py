from __future__ import annotations

from unittest.mock import Mock, patch
import io
import json
from http import HTTPStatus

import web_console


class _RecorderApi:
    def available_topics(self):
        return [{"name": "/odom", "type": "nav_msgs/msg/Odometry", "publisher_count": 1}]

    def list_archives(self):
        return [{"archive_id": "a" * 32, "display_name": "bag_example", "audit_status": "passed"}]

    def archive_detail(self, archive_id):
        assert archive_id == "a" * 32
        return {"archive": {"archive_id": archive_id}, "manifest": {"archive_id": archive_id}}

    def delete_archive(self, archive_id):
        assert archive_id == "a" * 32


class _ManualRecordingApi:
    def __init__(self):
        self.started = []
        self.stopped = 0

    def status(self):
        return {"state": "idle"}

    def start(self, payload):
        self.started.append(payload)
        return {"state": "recording", "topic_count": 1}

    def stop(self):
        self.stopped += 1
        return {"state": "finalizing"}


def _handler(path):
    handler = object.__new__(web_console.ConsoleHandler)
    handler.path = path
    handler.headers = {"User-Agent": "test"}
    handler._json = Mock()
    handler._static_from = Mock()
    return handler


def _post_handler(path, payload):
    handler = _handler(path)
    encoded = json.dumps(payload).encode("utf-8")
    handler.headers = {"Content-Length": str(len(encoded))}
    handler.rfile = io.BytesIO(encoded)
    return handler


def test_bag_recording_api_exposes_only_manager_backed_topic_and_archive_data():
    handler = _handler("/api/bag-recordings/topics")
    with patch.object(web_console, "BAG_RECORDINGS", _RecorderApi(), create=True):
        handler.do_GET()
    assert handler._json.call_args.args[0] == {"topics": [{"name": "/odom", "type": "nav_msgs/msg/Odometry", "publisher_count": 1}]}

    handler = _handler("/api/bag-recordings")
    with patch.object(web_console, "BAG_RECORDINGS", _RecorderApi(), create=True):
        handler.do_GET()
    assert handler._json.call_args.args[0]["archives"][0]["archive_id"] == "a" * 32


def test_manual_bag_recording_http_exposes_state_and_only_safe_start_stop_actions():
    manual = _ManualRecordingApi()
    handler = _handler("/api/bag-recordings/manual")
    with patch.object(web_console, "MANUAL_BAG_RECORDINGS", manual, create=True):
        handler.do_GET()
    assert handler._json.call_args.args[0] == {"manual": {"state": "idle"}}

    handler = _post_handler("/api/bag-recordings/manual", {"topics": ["/odom"], "durationMinutes": 15, "label": "遥控复现"})
    with patch.object(web_console, "MANUAL_BAG_RECORDINGS", manual, create=True):
        handler.do_POST()
    assert manual.started == [{"topics": ["/odom"], "durationMinutes": 15, "label": "遥控复现"}]
    assert handler._json.call_args.args[0] == {"manual": {"state": "recording", "topic_count": 1}}

    handler = _post_handler("/api/bag-recordings/manual/stop", {})
    with patch.object(web_console, "MANUAL_BAG_RECORDINGS", manual, create=True):
        handler.do_POST()
    assert manual.stopped == 1
    assert handler._json.call_args.args[0] == {"manual": {"state": "finalizing"}}


def test_bag_recording_api_rejects_invalid_archive_identifier_before_manager_access():
    handler = _handler("/api/bag-recordings/../../etc")
    with patch.object(web_console, "BAG_RECORDINGS", _RecorderApi(), create=True):
        handler.do_GET()
    assert handler._static_from.called

def test_bag_download_stream_contains_only_the_verified_archive(tmp_path):
    import io
    import tarfile

    archive = tmp_path / "bag_demo"
    archive.mkdir()
    (archive / "manifest.json").write_text("{}", encoding="utf-8")
    (archive / "bag.db3.zstd").write_bytes(b"bag")
    handler = object.__new__(web_console.ConsoleHandler)
    handler.send_response = Mock(); handler.send_header = Mock(); handler.end_headers = Mock(); handler.wfile = io.BytesIO()

    class Recorder(_RecorderApi):
        def archive_download_name(self, archive_id):
            assert archive_id == "a" * 32
            return "bag_20261015_092825_aaaaaaaa.tar"

        def archive_path(self, archive_id):
            assert archive_id == "a" * 32
            return archive

    with patch.object(web_console, "BAG_RECORDINGS", Recorder(), create=True):
        handler._download_bag_archive("a" * 32)

    handler.wfile.seek(0)
    handler.send_header.assert_any_call("Content-Disposition", "attachment; filename=bag_20261015_092825_aaaaaaaa.tar")
    with tarfile.open(fileobj=handler.wfile, mode="r:") as bundle:
        assert sorted(bundle.getnames()) == ["bag_20261015_092825_aaaaaaaa/bag.db3.zstd", "bag_20261015_092825_aaaaaaaa/manifest.json"]


def test_scenario_apply_returns_immediately_with_a_trackable_activation():
    tracker = Mock()
    tracker.start.return_value = {"state": "running", "phase": "writing", "profile_id": "hall"}
    handler = _post_handler("/api/scenario-setup", {"action": "apply", "profile_id": "hall", "document": {"profiles": []}})
    with patch.object(web_console, "SCENARIO_ACTIVATIONS", tracker, create=True), \
         patch.object(web_console.RUNS, "has_active_run", return_value=False), \
         patch("web_console.apply_scenario_runtime") as apply:
        handler._scenario_setup_action()

    tracker.start.assert_called_once_with("hall", {"profiles": []})
    apply.assert_not_called()
    assert handler._json.call_args.args == ({"operation": tracker.start.return_value}, HTTPStatus.ACCEPTED)
