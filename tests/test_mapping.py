import io
from email.message import Message
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

import web_console
from autodrive_console.mapping import MappingConfig, MappingError, MappingSessionController
from autodrive_console.deployment import DeploymentStore


def _config(root: Path) -> Path:
    root.mkdir(parents=True)
    source = root / "rycx_loc_livox.yaml"
    source.write_text(
        "# 用户维护的建图模板\ncommon:\n  lidar_topic: /livox/lidar\n  livox_lidar_topic: /livox/lidar\nsystem:\n  with_loop_closing: false\n  with_ui: true\n  with_2dui: true\n  with_g2p5: true\n  step_on_kf: true\n",
        encoding="utf-8",
    )
    return source


def _uploaded_template(
    controller: MappingSessionController, project_id: str, source: Path
) -> dict[str, str]:
    """模拟浏览器将操作者本机 YAML 上传到 Aletheia 工作区。"""
    return controller.store_template(
        project_id, source.name, source.read_bytes()
    )


def test_prepare_uses_project_owned_uploaded_template_without_mutating_original(tmp_path: Path):
    source = _config(tmp_path / "operator-laptop")
    original = source.read_text(encoding="utf-8")
    controller = MappingSessionController(tmp_path / "deployments" / ".mapping-sessions")
    template = _uploaded_template(controller, "test-site", source)

    session = controller.prepare("test-site", template_id=template["id"], label="大厅", kind="lobby")

    assert Path(session["generated_yaml"]).read_text(encoding="utf-8") == original
    assert source.read_text(encoding="utf-8") == original
    assert Path(template["path"]).is_relative_to(tmp_path / "deployments" / "test-site")
    assert Path(template["path"]).read_text(encoding="utf-8") == original
    assert Path(session["generated_yaml"]).is_relative_to(tmp_path / "deployments" / ".mapping-sessions")
    assert session["source_yaml"] == template["name"]


def test_prepare_rejects_template_identifier_outside_current_project_workspace(tmp_path: Path):
    controller = MappingSessionController(tmp_path / "deployments" / ".mapping-sessions")

    with pytest.raises(MappingError, match="已上传的 YAML"):
        controller.prepare("test-site", template_id="../../robot-config.yaml", label="大厅", kind="lobby")


def test_prepare_accepts_a_lightning_template_with_only_lidar_topic(tmp_path: Path):
    """现有 Lightning 模板可只使用 common.lidar_topic，不需要兼容别名。"""
    source = tmp_path / "operator-laptop" / "rycx_loc_livox.yaml"
    source.parent.mkdir()
    source.write_text(
        "common:\n  lidar_topic: /livox/lidar\nsystem:\n  with_g2p5: true\n",
        encoding="utf-8",
    )
    controller = MappingSessionController(tmp_path / "sessions")
    template = _uploaded_template(controller, "test-site", source)

    session = controller.prepare("test-site", template_id=template["id"], label="大厅", kind="lobby")

    assert session["state"] == "prepared"


def test_discarding_a_prepared_session_releases_the_mapping_controller(tmp_path: Path):
    """未启动的会话可放弃，随后才能重新准备另一张地图。"""
    source = _config(tmp_path / "operator-laptop")
    controller = MappingSessionController(tmp_path / "sessions")
    template = _uploaded_template(controller, "test-site", source)
    session = controller.prepare("test-site", template_id=template["id"], label="大厅", kind="lobby")

    discarded = controller.discard(session["id"])
    replacement = controller.prepare("test-site", template_id=template["id"], label="新大厅", kind="lobby")

    assert discarded["state"] == "discarded"
    assert replacement["state"] == "prepared"
    assert replacement["id"] != session["id"]


def test_browser_uploads_mapping_template_into_the_project_workspace(tmp_path: Path):
    """浏览器上传不能触碰机器人配置目录，也不能只相信前端文件名。"""
    controller = MappingSessionController(tmp_path / "deployments" / ".mapping-sessions")
    store = DeploymentStore(tmp_path / "deployments")
    project = store.create("浏览器建图模板")
    boundary = "----AletheiaMappingTemplate"
    body = b"".join([
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"template\"; filename=\"mapping.yaml\"\r\nContent-Type: application/x-yaml\r\n\r\n".encode(),
        b"common:\n  lidar_topic: /livox/lidar\n  livox_lidar_topic: /livox/lidar\nsystem:\n  with_g2p5: true\n\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    handler = object.__new__(web_console.ConsoleHandler)
    headers = Message()
    headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    headers["Content-Length"] = str(len(body))
    handler.headers = headers
    handler.rfile = io.BytesIO(body)
    handler._json = Mock()

    with patch.object(web_console, "MAPPING", controller), patch.object(web_console, "DEPLOYMENTS", store):
        handler._upload_mapping_template(project["id"])

    payload, status = handler._json.call_args.args
    assert status == HTTPStatus.CREATED, payload
    assert payload["template"]["name"] == "mapping.yaml"
    copied = Path(payload["template"]["path"])
    assert copied.is_relative_to(tmp_path / "deployments" / project["id"])
    assert copied.read_text(encoding="utf-8").startswith("common:")


def test_prepare_requires_user_to_enable_grid_and_set_livox_topic(tmp_path: Path):
    source = _config(tmp_path / "operator-laptop")
    source.write_text(
        "common:\n  lidar_topic: /livox/lidar\nsystem:\n  with_g2p5: false\n",
        encoding="utf-8",
    )
    controller = MappingSessionController(tmp_path / "sessions")
    template = _uploaded_template(controller, "test-site", source)
    with pytest.raises(MappingError, match="with_g2p5"):
        controller.prepare("test-site", template_id=template["id"], label="大厅", kind="lobby")


def test_grid_preview_is_written_only_for_a_running_session(tmp_path: Path):
    source = _config(tmp_path / "operator-laptop")
    controller = MappingSessionController(tmp_path / "sessions")
    template = _uploaded_template(controller, "test-site", source)
    session = controller.prepare("test-site", template_id=template["id"], label="大厅", kind="lobby")
    with controller._lock:  # Simulate the ROS callback phase without importing ROS2 in unit tests.
        controller._session["state"] = "running"

    controller.ingest_grid(
        resolution=0.2, width=2, height=2, origin=[-1.0, -2.0, 0.0],
        frame_id="map", data=[0, 100, -1, 0],
    )

    preview = controller.status()["session"]["preview"]
    assert preview["revision"] == 1
    assert preview["origin"] == [-1.0, -2.0, 0.0]
    assert controller.preview_pgm(session["id"]).read_bytes().startswith(b"P5\n2 2\n255\n")


def test_runtime_probe_requires_online_lightning_executable(tmp_path: Path, monkeypatch):
    config_root = tmp_path / "robot-config"
    _config(config_root)
    monkeypatch.setattr("autodrive_console.mapping.shutil.which", lambda _: "/usr/bin/ros2")
    controller = MappingSessionController(
        tmp_path / "sessions",
        config=MappingConfig(config_root=config_root),
        run=lambda *args, **kwargs: SimpleNamespace(stdout="lightning run_loc_online\n"),
    )
    status = controller.status()
    assert not status["available"]
    assert "run_slam_online" in status["reason"]


class _ExitedProcess:
    """Minimal child-process fixture; no ROS2 process is launched in tests."""

    pid = 4321

    def __init__(self, exit_code: int | None) -> None:
        self.exit_code = exit_code

    def poll(self):
        return self.exit_code


def test_status_reports_an_unexpected_lightning_exit_before_any_map_is_saved(tmp_path: Path, monkeypatch):
    """A dead SLAM process must not look like a running white-canvas session."""
    source = _config(tmp_path / "operator-laptop")
    controller = MappingSessionController(
        tmp_path / "sessions",
        popen=lambda *_args, **_kwargs: _ExitedProcess(17),
    )
    monkeypatch.setattr(controller, "_probe_lightning", lambda **_kwargs: (True, "可用"))
    monkeypatch.setattr(controller, "_start_preview_listener", lambda: None)
    monkeypatch.setattr(controller, "_stop_preview_listener", lambda: None)
    template = _uploaded_template(controller, "test-site", source)
    session = controller.prepare("test-site", template_id=template["id"], label="大厅", kind="lobby")

    controller.start(session["id"])
    status = controller.status()["session"]

    assert status["state"] == "failed"
    assert "退出码 17" in status["error"]
    assert status["preview"]["state"] == "unavailable"


def test_stop_rejects_a_save_response_without_the_expected_map_files(tmp_path: Path, monkeypatch):
    """The save service returning is insufficient: editable PGM/YAML must exist."""
    source = _config(tmp_path / "operator-laptop")
    controller = MappingSessionController(tmp_path / "sessions")
    monkeypatch.setattr(controller, "_stop_preview_listener", lambda: None)
    template = _uploaded_template(controller, "test-site", source)
    session = controller.prepare("test-site", template_id=template["id"], label="大厅", kind="lobby")
    with controller._lock:
        controller._session["state"] = "running"
    controller._process = _ExitedProcess(None)
    monkeypatch.setattr(controller, "_save_map", lambda _map_id: None)

    stopped = controller.stop(session["id"], save=True)

    assert stopped["state"] == "stopped"
    assert "map.yaml" in stopped["error"]


def test_save_map_rejects_a_nonzero_lightning_service_response(tmp_path: Path):
    """A ROS CLI exit code alone cannot turn a rejected SaveMap request into success."""
    config_root = tmp_path / "robot-config"
    _config(config_root)
    controller = MappingSessionController(
        tmp_path / "sessions",
        config=MappingConfig(config_root=config_root),
        run=lambda *_args, **_kwargs: SimpleNamespace(
            stdout="response:\nlightning.srv.SaveMap_Response(response=7)\n",
            stderr="",
            returncode=0,
        ),
    )

    with pytest.raises(MappingError, match="response=7"):
        controller._save_map("mapping-test")


def test_finished_capture_can_be_promoted_to_editable_project_map(tmp_path: Path):
    store = DeploymentStore(tmp_path / "deployments")
    project = store.create("实时建图")
    session_root = tmp_path / "sessions"
    captured = session_root / "mapping-a" / "data" / "mapping-a"
    captured.mkdir(parents=True)
    (captured / "map.pgm").write_bytes(b"P5\n2 2\n255\n\x00\xff\x80\x40")
    (captured / "map.yaml").write_text(
        "image: map.pgm\nresolution: 0.2\norigin: [-1.0, -2.0, 0.0]\n",
        encoding="utf-8",
    )

    asset = store.import_captured_map(
        project["id"], captured / "map.yaml", "实时大厅", "lobby", session_root
    )

    assert asset["label"] == "实时大厅"
    assert store.map_image(project["id"], asset["id"]).is_file()
