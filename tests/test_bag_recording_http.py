from __future__ import annotations

from unittest.mock import Mock, patch

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


def _handler(path):
    handler = object.__new__(web_console.ConsoleHandler)
    handler.path = path
    handler.headers = {"User-Agent": "test"}
    handler._json = Mock()
    handler._static_from = Mock()
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
        def archive_path(self, archive_id):
            assert archive_id == "a" * 32
            return archive

    with patch.object(web_console, "BAG_RECORDINGS", Recorder(), create=True):
        handler._download_bag_archive("a" * 32)

    handler.wfile.seek(0)
    with tarfile.open(fileobj=handler.wfile, mode="r:") as bundle:
        assert sorted(bundle.getnames()) == ["bag_demo/bag.db3.zstd", "bag_demo/manifest.json"]
