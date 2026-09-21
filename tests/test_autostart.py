import subprocess
from pathlib import Path

from autodrive_console.autostart import AutostartManager


def test_autostart_manager_writes_user_service_without_touching_system_units(tmp_path):
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    home = tmp_path / "home"
    manager = AutostartManager(
        workspace=tmp_path / "workspace",
        home=home,
        launcher=["/usr/bin/ry-aletheia"],
        runner=runner,
    )

    enabled = manager.apply(True)

    unit = home / ".config/systemd/user/ry-aletheia.service"
    assert enabled["enabled"] is True
    assert enabled["mode"] == "systemd-user"
    assert unit.is_file()
    assert "ExecStart=/usr/bin/ry-aletheia" in unit.read_text(encoding="utf-8")
    assert "WantedBy=default.target" in unit.read_text(encoding="utf-8")
    assert "Environment=ROS_DOMAIN_ID=66" in unit.read_text(encoding="utf-8")
    assert all("/etc/systemd" not in " ".join(command) for command, _ in calls)

    disabled = manager.apply(False)

    assert disabled["enabled"] is False
    assert not unit.exists()


def test_autostart_manager_falls_back_to_desktop_autostart_when_user_systemd_is_unavailable(tmp_path):
    def runner(command, **kwargs):
        raise FileNotFoundError(command[0])

    home = tmp_path / "home"
    manager = AutostartManager(
        workspace=tmp_path / "workspace",
        home=home,
        launcher=["/usr/bin/ry-aletheia"],
        runner=runner,
    )

    state = manager.apply(True)

    desktop = home / ".config/autostart/ry-aletheia.desktop"
    assert state["enabled"] is True
    assert state["mode"] == "desktop-autostart"
    assert desktop.is_file()
    assert "Exec=env ROS_DOMAIN_ID=66 /usr/bin/ry-aletheia" in desktop.read_text(encoding="utf-8")
    assert "ROS_DOMAIN_ID=66" in desktop.read_text(encoding="utf-8")


def test_autostart_uses_persisted_video_ros_domain_over_inherited_environment(tmp_path, monkeypatch):
    config = tmp_path / "workspace/config/video.json"
    config.parent.mkdir(parents=True)
    config.write_text('{"ros_domain_id": 42}\n', encoding="utf-8")
    monkeypatch.setenv("ROS_DOMAIN_ID", "0")

    manager = AutostartManager(
        workspace=tmp_path / "workspace",
        home=tmp_path / "home",
        launcher=["/usr/bin/ry-aletheia"],
        runner=lambda command, **kwargs: subprocess.CompletedProcess(command, 0),
    )

    manager.apply(True)

    unit = (tmp_path / "home/.config/systemd/user/ry-aletheia.service").read_text(encoding="utf-8")
    assert "Environment=ROS_DOMAIN_ID=42" in unit
