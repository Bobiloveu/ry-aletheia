import io
import json
from pathlib import Path
import re
from http import HTTPStatus
from unittest.mock import Mock, patch

import pytest

import web_console
from autodrive_console import robot_logs
from autodrive_console.robot_logs import (
    RobotLogDownloadTracker,
    RobotLogError,
    RobotLogStore,
    convert_ros_time_to_beijing,
    iter_ros_time_converted_bytes,
)
from autodrive_console.settings import SettingsStore


def test_old_console_settings_get_default_robot_log_sources(tmp_path: Path) -> None:
    """升级旧 console.json 时，机器人日志页必须立即有可管理的默认目录。"""

    store = SettingsStore(tmp_path / "console.json")

    assert store.load().robot_logs == {
        "sources": [
            {
                "id": "drivers",
                "name": "drivers",
                "path": "/opt/ry/Log/supervisor-logs/stdout/today/drivers",
            },
            {
                "id": "modules",
                "name": "modules",
                "path": "/opt/ry/Log/supervisor-logs/stdout/today/modules",
            },
            {
                "id": "lightning",
                "name": "lightning",
                "path": "/opt/ry/workspace/lightning_logs",
            },
        ]
    }


def test_robot_log_settings_reject_sensitive_directory(tmp_path: Path) -> None:
    """若允许 /etc 成为源，网页日志下载就会越过其业务日志边界。"""

    store = SettingsStore(tmp_path / "console.json")

    with pytest.raises(ValueError, match="日志目录"):
        store.save({
            "robot_logs": {
                "sources": [{"id": "unsafe", "name": "不安全", "path": "/etc"}],
            },
        })


def test_robot_log_file_list_filters_direct_regular_files_without_paths(tmp_path: Path) -> None:
    """文件清单若递归、跟随链接或暴露路径，会让网页越过选定日志目录。"""

    logs = tmp_path / "robot-logs"
    logs.mkdir()
    (logs / "102-chassis_node.out.log").write_text("chassis", encoding="utf-8")
    (logs / "103-battery_node.out.log").write_text("battery", encoding="utf-8")
    (logs / "nested").mkdir()
    (logs / "nested" / "hidden.out.log").write_text("hidden", encoding="utf-8")
    (logs / "linked.out.log").symlink_to(logs / "103-battery_node.out.log")
    settings = SettingsStore(tmp_path / "console.json")
    settings.save({"robot_logs": {"sources": [{"id": "custom", "name": "自定义", "path": str(logs)}]}})

    records = RobotLogStore(settings).list_files("custom", query="chassis")

    assert len(records) == 1
    assert records[0]["name"] == "102-chassis_node.out.log"
    assert records[0]["size_bytes"] == 7
    assert set(records[0]) == {"id", "name", "size_bytes", "modified_at"}


def test_robot_log_download_rejects_a_file_replaced_after_listing(tmp_path: Path) -> None:
    """日志轮转后继续使用旧文件 ID 会下载错误文件，必须被拒绝。"""

    logs = tmp_path / "robot-logs"
    logs.mkdir()
    target = logs / "102-chassis_node.out.log"
    target.write_text("before", encoding="utf-8")
    settings = SettingsStore(tmp_path / "console.json")
    settings.save({"robot_logs": {"sources": [{"id": "custom", "name": "自定义", "path": str(logs)}]}})
    store = RobotLogStore(settings)
    previous_id = store.list_files("custom")[0]["id"]
    replacement = logs / ".102-chassis_node.out.log.rotating"
    replacement.write_text("after", encoding="utf-8")
    replacement.replace(target)

    with pytest.raises(RobotLogError, match="文件已变化"):
        store.open_file("custom", previous_id)


def test_robot_log_download_allows_a_log_that_grew_after_listing(tmp_path: Path) -> None:
    """同一日志持续追加时，下载应取得当前内容而不是误判为轮转。"""

    logs = tmp_path / "robot-logs"
    logs.mkdir()
    target = logs / "102-chassis_node.out.log"
    target.write_text("before\n", encoding="utf-8")
    settings = SettingsStore(tmp_path / "console.json")
    settings.save({"robot_logs": {"sources": [{"id": "custom", "name": "自定义", "path": str(logs)}]}})
    store = RobotLogStore(settings)
    previous_id = store.list_files("custom")[0]["id"]
    with target.open("a", encoding="utf-8") as stream:
        stream.write("after\n")

    download = store.open_file("custom", previous_id)
    try:
        assert download.stream.read() == b"before\nafter\n"
    finally:
        download.stream.close()


def test_ros_timestamp_conversion_matches_the_legacy_log_tool() -> None:
    """秒、小数秒和 ROS2 纳秒时间必须按旧 RYLog 规则显示为北京时间。"""

    converted = convert_ros_time_to_beijing(
        "seconds=1700000000 fractional=1700000000.123456789 nanoseconds=1700000000000000000 untouched=999999999"
    )

    assert converted == (
        "seconds=2023-11-15 06:13:20 fractional=2023-11-15 06:13:20 "
        "nanoseconds=2023-11-15 06:13:20 untouched=999999999"
    )


def test_ros_timestamp_conversion_keeps_one_timestamp_together_across_stream_chunks() -> None:
    """文件读取边界不能让跨块的 ROS2 纳秒时间漏转或被截断。"""

    with patch.object(robot_logs, "_STREAM_CHUNK_BYTES", 13):
        converted = b"".join(iter_ros_time_converted_bytes(io.BytesIO(b"before 1700000000000000000 after")))

    assert converted == b"before 2023-11-15 06:13:20 after"


def test_ros_timestamp_conversion_respects_the_download_snapshot_size() -> None:
    """时间转换版也不能把下载开始后的新增日志混入当前文件。"""

    original = b"1700000000\n"
    stream = io.BytesIO(original + b"added-after-download-start\n")

    assert b"".join(iter_ros_time_converted_bytes(stream, maximum_bytes=len(original))) == b"2023-11-15 06:13:20\n"


def test_robot_log_store_assigns_ids_for_new_directory_sources(tmp_path: Path) -> None:
    """由网页伪造源 ID 会让后续文件下载的权限边界不可预测。"""

    logs = tmp_path / "robot-logs"
    logs.mkdir()
    settings = SettingsStore(tmp_path / "console.json")

    sources = RobotLogStore(settings).save_sources([{"name": "现场驱动", "path": str(logs)}])

    assert len(sources) == 1
    assert re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", sources[0]["id"])
    assert sources[0]["name"] == "现场驱动"
    assert sources[0]["path"] == str(logs)
    assert settings.load().robot_logs["sources"] == [
        {"id": sources[0]["id"], "name": "现场驱动", "path": str(logs)},
    ]


def test_robot_log_download_progress_tracks_one_file_without_storing_its_content() -> None:
    """进度状态只保存元数据，连续写入后必须能准确反映当前下载。"""

    tracker = RobotLogDownloadTracker()
    created = tracker.prepare("drivers", "0123456789abcdef01234567", "102-chassis_node.out.log", 100, convert_ros_time=True)
    tracker.start(created["id"])
    tracker.advance(created["id"], 40)

    progress = tracker.status(created["id"])

    assert progress == {
        "id": created["id"],
        "name": "102-chassis_node.out.log",
        "state": "streaming",
        "sent_bytes": 40,
        "total_bytes": 100,
        "convert_ros_time": True,
        "error": None,
    }


def test_robot_log_download_progress_expires_after_its_short_lifetime() -> None:
    """用户关闭页面后的进度记录必须自行过期，不能无限堆积在小车内存。"""

    now = [0.0]
    tracker = RobotLogDownloadTracker(clock=lambda: now[0])
    created = tracker.prepare("drivers", "0123456789abcdef01234567", "102-chassis_node.out.log", 100, convert_ros_time=False)
    now[0] += tracker.TTL_SECONDS + 1

    with pytest.raises(RobotLogError, match="已过期"):
        tracker.status(created["id"])


def test_robot_log_sources_report_readable_and_missing_directories_independently(tmp_path: Path) -> None:
    """一个目录缺失时不能让其它可读日志源也无法使用。"""

    logs = tmp_path / "robot-logs"
    logs.mkdir()
    (logs / "102-chassis_node.out.log").write_text("ready", encoding="utf-8")
    settings = SettingsStore(tmp_path / "console.json")
    settings.save({"robot_logs": {"sources": [
        {"id": "ready", "name": "可读", "path": str(logs)},
        {"id": "missing", "name": "缺失", "path": str(tmp_path / "missing")},
    ]}})

    sources = RobotLogStore(settings).sources()

    by_id = {source["id"]: source for source in sources}
    assert by_id["ready"] == {
        "id": "ready", "name": "可读", "path": str(logs), "status": "available", "message": "可读取", "file_count": 1,
    }
    assert by_id["missing"] == {
        "id": "missing", "name": "缺失", "path": str(tmp_path / "missing"), "status": "missing", "message": "目录不存在", "file_count": 0,
    }


def test_console_streams_one_selected_robot_log_as_an_attachment(tmp_path: Path) -> None:
    """下载若被打包或缓冲为别的格式，维护电脑拿到的就不是原始日志。"""

    logs = tmp_path / "robot-logs"
    logs.mkdir()
    target = logs / "102-chassis_node.out.log"
    target.write_bytes(b"driver log\n")
    settings = SettingsStore(tmp_path / "console.json")
    settings.save({"robot_logs": {"sources": [{"id": "custom", "name": "自定义", "path": str(logs)}]}})
    store = RobotLogStore(settings)
    file_id = store.list_files("custom")[0]["id"]
    handler = object.__new__(web_console.ConsoleHandler)
    response = {"status": None, "headers": {}}
    handler.wfile = io.BytesIO()
    handler.send_response = lambda status: response.update(status=status)
    handler.send_header = lambda key, value: response["headers"].update({key: value})
    handler.end_headers = lambda: None

    with patch.object(web_console, "ROBOT_LOGS", store, create=True):
        handler._download_robot_log_file("custom", file_id)

    assert response["status"] == HTTPStatus.OK
    assert response["headers"]["Content-Length"] == "11"
    assert response["headers"]["Content-Disposition"] == "attachment; filename=102-chassis_node.out.log"
    assert handler.wfile.getvalue() == b"driver log\n"


def test_console_download_uses_the_size_observed_when_an_active_log_keeps_growing() -> None:
    """传输中的新日志不能越过本次下载的 Content-Length 快照。"""

    initial = b"before\n"
    appended = b"after\n"

    class GrowingStream(io.BytesIO):
        def __init__(self) -> None:
            super().__init__(initial)
            self._appended = False

        def read(self, size: int = -1) -> bytes:
            chunk = super().read(size)
            if not self._appended:
                position = self.tell()
                self.seek(0, io.SEEK_END)
                self.write(appended)
                self.seek(position)
                self._appended = True
            return chunk

    logs = Mock()
    logs.open_file.return_value = type("Download", (), {
        "name": "102-chassis_node.out.log",
        "size_bytes": len(initial),
        "stream": GrowingStream(),
    })()
    handler = object.__new__(web_console.ConsoleHandler)
    response = {"headers": {}}
    handler.wfile = io.BytesIO()
    handler.send_response = Mock()
    handler.send_header = lambda key, value: response["headers"].update({key: value})
    handler.end_headers = Mock()

    with patch.object(web_console, "ROBOT_LOGS", logs):
        assert handler._download_robot_log_file("custom", "0123456789abcdef01234567")

    assert response["headers"]["Content-Length"] == str(len(initial))
    assert handler.wfile.getvalue() == initial


def test_console_streams_a_beijing_time_converted_copy_without_touching_source_file(tmp_path: Path) -> None:
    """时间转换只能发生在下载副本，绝不能回写机器人上的原始业务日志。"""

    logs = tmp_path / "robot-logs"
    logs.mkdir()
    target = logs / "102-chassis_node.out.log"
    original = b"[INFO] [1700000000.123] chassis ready\n"
    target.write_bytes(original)
    settings = SettingsStore(tmp_path / "console.json")
    settings.save({"robot_logs": {"sources": [{"id": "custom", "name": "自定义", "path": str(logs)}]}})
    store = RobotLogStore(settings)
    file_id = store.list_files("custom")[0]["id"]
    handler = object.__new__(web_console.ConsoleHandler)
    response = {"status": None, "headers": {}}
    handler.wfile = io.BytesIO()
    handler.send_response = lambda status: response.update(status=status)
    handler.send_header = lambda key, value: response["headers"].update({key: value})
    handler.end_headers = lambda: None

    with patch.object(web_console, "ROBOT_LOGS", store, create=True):
        handler._download_robot_log_file("custom", file_id, convert_ros_time=True)

    assert response["status"] == HTTPStatus.OK
    assert "Content-Length" not in response["headers"]
    assert handler.wfile.getvalue() == b"[INFO] [2023-11-15 06:13:20] chassis ready\n"
    assert target.read_bytes() == original


def test_converted_download_is_declared_as_utf8_text_even_when_log_name_has_no_text_suffix(tmp_path: Path) -> None:
    """启用转换后输出已经是 UTF-8 文本，不能继续按任意二进制 MIME 声明。"""

    logs = tmp_path / "robot-logs"
    logs.mkdir()
    target = logs / "chassis-output"
    target.write_bytes(b"1700000000\n")
    settings = SettingsStore(tmp_path / "console.json")
    settings.save({"robot_logs": {"sources": [{"id": "custom", "name": "自定义", "path": str(logs)}]}})
    store = RobotLogStore(settings)
    file_id = store.list_files("custom")[0]["id"]
    handler = object.__new__(web_console.ConsoleHandler)
    response = {"headers": {}}
    handler.wfile = io.BytesIO()
    handler.send_response = lambda status: None
    handler.send_header = lambda key, value: response["headers"].update({key: value})
    handler.end_headers = lambda: None

    with patch.object(web_console, "ROBOT_LOGS", store, create=True):
        handler._download_robot_log_file("custom", file_id, convert_ros_time=True)

    assert response["headers"]["Content-Type"] == "text/plain; charset=utf-8"


def test_converted_download_rejects_non_utf8_log_before_starting_response(tmp_path: Path) -> None:
    """二进制日志不能被损坏后伪装成已转换文本。"""

    logs = tmp_path / "robot-logs"
    logs.mkdir()
    (logs / "camera.bin").write_bytes(b"\xff\x00\x01")
    settings = SettingsStore(tmp_path / "console.json")
    settings.save({"robot_logs": {"sources": [{"id": "custom", "name": "自定义", "path": str(logs)}]}})
    store = RobotLogStore(settings)
    file_id = store.list_files("custom")[0]["id"]
    handler = object.__new__(web_console.ConsoleHandler)
    handler.send_error = Mock()
    handler.send_response = Mock()
    handler.send_header = Mock()
    handler.end_headers = Mock()
    handler.wfile = io.BytesIO()

    with patch.object(web_console, "ROBOT_LOGS", store, create=True):
        handler._download_robot_log_file("custom", file_id, convert_ros_time=True)

    handler.send_error.assert_called_once_with(HTTPStatus.UNPROCESSABLE_ENTITY, "日志不是 UTF-8 文本，无法转换 ROS 时间；请关闭转换后下载原始文件")
    handler.send_response.assert_not_called()


def test_console_closes_robot_log_stream_when_client_disconnects_before_headers() -> None:
    """浏览器在响应开始前断开时，打开的原始日志文件也必须立即关闭。"""

    stream = io.BytesIO(b"driver log\n")
    logs = Mock()
    logs.open_file.return_value = type("Download", (), {
        "name": "102-chassis_node.out.log",
        "size_bytes": 11,
        "stream": stream,
    })()
    handler = object.__new__(web_console.ConsoleHandler)
    handler.send_response = Mock(side_effect=BrokenPipeError("client closed"))
    handler.send_header = Mock()
    handler.end_headers = Mock()
    handler.wfile = io.BytesIO()

    with patch.object(web_console, "ROBOT_LOGS", logs, create=True):
        handler._download_robot_log_file("drivers", "abc123")

    assert stream.closed


def test_console_lists_robot_log_files_through_the_controlled_api(tmp_path: Path) -> None:
    """若清单路由退回静态路径或读取正文，网页无法安全地筛选日志文件。"""

    logs = tmp_path / "robot-logs"
    logs.mkdir()
    (logs / "102-chassis_node.out.log").write_text("chassis", encoding="utf-8")
    settings = SettingsStore(tmp_path / "console.json")
    settings.save({"robot_logs": {"sources": [{"id": "custom", "name": "自定义", "path": str(logs)}]}})
    handler = object.__new__(web_console.ConsoleHandler)
    handler.path = "/api/robot-logs/sources/custom/files?query=chassis"
    handler.headers = {"User-Agent": "test"}
    handler._json = Mock()
    handler._static_from = Mock()

    with patch.object(web_console, "ROBOT_LOGS", RobotLogStore(settings)):
        handler.do_GET()

    payload = handler._json.call_args.args[0]
    assert len(payload["files"]) == 1
    assert payload["files"][0]["name"] == "102-chassis_node.out.log"
    assert "path" not in payload["files"][0]


def test_console_download_route_only_enables_time_conversion_for_explicit_beijing_query() -> None:
    """下载 URL 的可选转换参数必须明确，缺省路径仍保留原始文件语义。"""

    handler = object.__new__(web_console.ConsoleHandler)
    handler.headers = {"User-Agent": "test"}
    handler._download_robot_log_file = Mock()
    handler._static_from = Mock()
    handler.path = "/api/robot-logs/sources/drivers/files/0123456789abcdef01234567/download?ros_time=beijing"

    handler.do_GET()

    handler._download_robot_log_file.assert_called_once_with(
        "drivers", "0123456789abcdef01234567", convert_ros_time=True,
    )


def test_console_saves_configured_robot_log_directories_through_the_controlled_api(tmp_path: Path) -> None:
    """目录管理若不能持久化，维护人员每次重启都要重新配置日志源。"""

    logs = tmp_path / "robot-logs"
    logs.mkdir()
    settings = SettingsStore(tmp_path / "console.json")
    payload = {"sources": [{"name": "现场驱动", "path": str(logs)}]}
    encoded = json.dumps(payload).encode("utf-8")
    handler = object.__new__(web_console.ConsoleHandler)
    handler.path = "/api/robot-logs/sources"
    handler.headers = {"Content-Length": str(len(encoded))}
    handler.rfile = io.BytesIO(encoded)
    handler._json = Mock()

    with patch.object(web_console, "ROBOT_LOGS", RobotLogStore(settings)):
        handler.do_PUT()

    response = handler._json.call_args.args[0]
    assert response["sources"][0]["name"] == "现场驱动"
    assert response["sources"][0]["status"] == "available"
    assert settings.load().robot_logs["sources"][0]["path"] == str(logs)


def test_console_creates_a_tracked_robot_log_download(tmp_path: Path) -> None:
    """进度条必须先取得后端受控 token，不能把文件路径或临时队列交给网页。"""

    logs = tmp_path / "robot-logs"
    logs.mkdir()
    (logs / "102-chassis_node.out.log").write_bytes(b"driver log\n")
    settings = SettingsStore(tmp_path / "console.json")
    settings.save({"robot_logs": {"sources": [{"id": "custom", "name": "自定义", "path": str(logs)}]}})
    store = RobotLogStore(settings)
    file_id = store.list_files("custom")[0]["id"]
    payload = json.dumps({"source_id": "custom", "file_id": file_id, "ros_time": "beijing"}).encode("utf-8")
    handler = object.__new__(web_console.ConsoleHandler)
    handler.path = "/api/robot-logs/downloads"
    handler.headers = {"Content-Length": str(len(payload))}
    handler.rfile = io.BytesIO(payload)
    handler._json = Mock()
    tracker = RobotLogDownloadTracker()

    with patch.object(web_console, "ROBOT_LOGS", store, create=True), patch.object(web_console, "ROBOT_LOG_DOWNLOADS", tracker, create=True):
        handler.do_POST()

    response = handler._json.call_args.args[0]["download"]
    assert response["name"] == "102-chassis_node.out.log"
    assert response["state"] == "prepared"
    assert response["total_bytes"] == 11
    assert re.fullmatch(r"[0-9a-f]{32}", response["id"])


def test_console_tracked_download_reports_completed_bytes_after_streaming(tmp_path: Path) -> None:
    """只有实际写入浏览器的字节才可以把进度标记为完成。"""

    logs = tmp_path / "robot-logs"
    logs.mkdir()
    (logs / "102-chassis_node.out.log").write_bytes(b"driver log\n")
    settings = SettingsStore(tmp_path / "console.json")
    settings.save({"robot_logs": {"sources": [{"id": "custom", "name": "自定义", "path": str(logs)}]}})
    store = RobotLogStore(settings)
    record = store.list_files("custom")[0]
    tracker = RobotLogDownloadTracker()
    prepared = tracker.prepare("custom", record["id"], record["name"], record["size_bytes"], convert_ros_time=False)
    handler = object.__new__(web_console.ConsoleHandler)
    handler.wfile = io.BytesIO()
    handler.send_response = Mock()
    handler.send_header = Mock()
    handler.end_headers = Mock()
    handler.send_error = Mock()

    with patch.object(web_console, "ROBOT_LOGS", store, create=True), patch.object(web_console, "ROBOT_LOG_DOWNLOADS", tracker, create=True):
        handler._download_tracked_robot_log_file(prepared["id"])

    progress = tracker.status(prepared["id"])
    assert progress["state"] == "completed"
    assert progress["sent_bytes"] == 11
    assert handler.wfile.getvalue() == b"driver log\n"
    handler.send_error.assert_not_called()


def test_console_tracked_download_marks_progress_failed_when_browser_disconnects(tmp_path: Path) -> None:
    """刷新或关闭网页打断连接时，进度必须显示失败而不是永远卡在下载中。"""

    logs = tmp_path / "robot-logs"
    logs.mkdir()
    (logs / "102-chassis_node.out.log").write_bytes(b"driver log\n")
    settings = SettingsStore(tmp_path / "console.json")
    settings.save({"robot_logs": {"sources": [{"id": "custom", "name": "自定义", "path": str(logs)}]}})
    store = RobotLogStore(settings)
    record = store.list_files("custom")[0]
    tracker = RobotLogDownloadTracker()
    prepared = tracker.prepare("custom", record["id"], record["name"], record["size_bytes"], convert_ros_time=False)
    handler = object.__new__(web_console.ConsoleHandler)
    handler.wfile = Mock()
    handler.wfile.write.side_effect = BrokenPipeError("browser closed")
    handler.send_response = Mock()
    handler.send_header = Mock()
    handler.end_headers = Mock()
    handler.send_error = Mock()

    with patch.object(web_console, "ROBOT_LOGS", store, create=True), patch.object(web_console, "ROBOT_LOG_DOWNLOADS", tracker, create=True):
        handler._download_tracked_robot_log_file(prepared["id"])

    assert tracker.status(prepared["id"])["state"] == "failed"


def test_robot_logs_page_is_a_desktop_only_operator_surface() -> None:
    """若缺少管理/筛选/下载控件，维护人员只能回到旧 Qt 工具处理日志。"""

    page = (web_console.WEB_ROOT / "robot-logs.html").read_text(encoding="utf-8")

    assert 'id="sourceDirectoryList"' in page
    assert 'id="saveSources"' in page
    assert 'id="fileKeyword"' in page
    assert 'id="downloadSelected"' in page
    assert 'id="convertRosTime"' in page
    assert 'id="downloadLocationHelp"' in page
    assert 'id="downloadProgress"' in page
    assert "下载前询问每个文件的保存位置" in page
    assert 'src="/robot_logs.js"' in page
    assert "robot-logs.html" not in web_console.MOBILE_PAGE_NAMES
