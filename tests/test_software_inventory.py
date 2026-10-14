from __future__ import annotations

from subprocess import CompletedProcess, TimeoutExpired
import subprocess
import sys
from pathlib import Path

import pytest

from autodrive_console.settings import SettingsStore


VALID_VEHICLE = {
    "vehicle_number": "01号车",
    "vin": "RY-CHASSIS-001",
    "model": "RY 标准小车",
    "project": "园区配送",
    "location": "A 栋一层",
}


def completed(stdout: str, returncode: int = 0) -> CompletedProcess[str]:
    return CompletedProcess(["/usr/bin/dpkg-query"], returncode, stdout, "")


@pytest.fixture
def package_database(tmp_path):
    """Query a private dpkg database without touching installed packages."""
    if sys.platform != "linux" or not Path("/usr/bin/dpkg-query").is_file():
        pytest.skip("requires dpkg-query")
    directory = tmp_path / "dpkg"
    directory.mkdir()
    status = directory / "status"
    status.write_text("")

    def runner(argv, **kwargs):
        return subprocess.run([argv[0], f"--admindir={directory}", *argv[1:]], **kwargs)

    return status, runner


def test_readable_database_without_ry_packages_is_available_and_allows_profile_save(tmp_path, package_database):
    from autodrive_console.software_inventory import SoftwareInventory

    status, runner = package_database
    status.write_text(
        "Package: unrelated\nStatus: install ok installed\nArchitecture: amd64\n"
        "Version: 1.0\nMaintainer: Test <test@example.invalid>\nDescription: Fixture\n\n"
    )
    inventory = SoftwareInventory(SettingsStore(tmp_path / "console.json"), runner=runner)
    snapshot = inventory.snapshot()
    assert snapshot["inventory_status"] == "available"
    assert snapshot["packages"] == []
    saved = inventory.save({"vehicle": VALID_VEHICLE, "package_notes": {}})
    assert saved["vehicle"] == VALID_VEHICLE


def test_uninstalled_dpkg_placeholder_does_not_hide_installed_ry_packages(tmp_path, package_database):
    from autodrive_console.software_inventory import SoftwareInventory

    status, runner = package_database
    status.write_text(
        "Package: ry-runtime\nStatus: install ok installed\nArchitecture: amd64\n"
        "Version: 1.2.3\nMaintainer: Test <test@example.invalid>\nDescription: Fixture\n\n"
        "Package: ry-removed\nStatus: unknown ok not-installed\n\n"
    )
    snapshot = SoftwareInventory(SettingsStore(tmp_path / "console.json"), runner=runner).snapshot()
    assert snapshot["inventory_status"] == "available"
    assert [item["package_name"] for item in snapshot["packages"]] == ["ry-runtime"]


@pytest.mark.parametrize("selection,multiarch", [
    ("hold", ""),
    ("deinstall", ""),
    ("install", "Multi-Arch: same\n"),
])
def test_installed_packages_remain_visible_regardless_of_selection_or_arch_suffix(tmp_path, package_database, selection, multiarch):
    from autodrive_console.software_inventory import SoftwareInventory

    status, runner = package_database
    status.write_text(
        f"Package: ry-runtime\nStatus: {selection} ok installed\nArchitecture: amd64\n"
        f"{multiarch}Version: 1.2.3\nMaintainer: Test <test@example.invalid>\nDescription: Fixture\n\n"
    )
    inventory = SoftwareInventory(SettingsStore(tmp_path / "console.json"), runner=runner)
    snapshot = inventory.snapshot()
    assert snapshot["inventory_status"] == "available"
    assert [item["package_name"] for item in snapshot["packages"]] == ["ry-runtime"]
    assert snapshot["packages"][0]["package_filename"] == "ry-runtime_1.2.3_amd64.deb"
    saved = inventory.save({
        "vehicle": VALID_VEHICLE,
        "package_notes": {"ry-runtime": {"maintainer": "Test", "description": "Fixture"}},
    })
    assert saved["packages"][0]["maintainer"] == "Test"


def test_snapshot_queries_fixed_argv_without_shell_and_builds_standard_filename(tmp_path):
    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return completed("ry-runtime\t1.2.3\tamd64\tii \n")

    from autodrive_console.software_inventory import SoftwareInventory

    snapshot = SoftwareInventory(SettingsStore(tmp_path / "console.json"), runner=runner).snapshot()

    format_string = "$" + "{binary:Package}\\t$" + "{Version}\\t$" + "{Architecture}\\t$" + "{db:Status-Abbrev}\\n"
    assert calls == [(
        [
            "/usr/bin/dpkg-query",
            "--show",
            "--showformat=" + format_string,
        ],
        {"capture_output": True, "check": False, "input": "", "shell": False, "text": True, "timeout": 5},
    )]
    assert snapshot["inventory_status"] == "available"
    assert snapshot["packages"] == [{
        "package_name": "ry-runtime",
        "version": "1.2.3",
        "architecture": "amd64",
        "installed": True,
        "package_filename": "ry-runtime_1.2.3_amd64.deb",
        "maintainer": "",
        "description": "",
    }]


def test_snapshot_keeps_only_installed_valid_ry_packages_and_merges_saved_notes(tmp_path):
    store = SettingsStore(tmp_path / "console.json")
    store.save({
        "software_inventory": {
            "vehicle": VALID_VEHICLE,
            "package_notes": {
                "ry-runtime": {"maintainer": "甘怡训", "description": "ry 固件底层依赖"},
                "ry-removed": {"maintainer": "不应显示", "description": "未安装"},
            },
        },
    })

    def runner(*_args, **_kwargs):
        return completed(
            "ry-runtime\t1.2.3\tamd64\tii \n"
            "ry-not-installed\t1.0\tamd64\trc \n"
            "not-ry\t1.0\tamd64\tii \n"
            "ry bad\t1.0\tamd64\tii \n"
            "ry-master-interfaces\t2:4.5\tarm64\tii \n"
        )

    from autodrive_console.software_inventory import SoftwareInventory

    snapshot = SoftwareInventory(store, runner=runner).snapshot()

    assert [item["package_name"] for item in snapshot["packages"]] == ["ry-master-interfaces", "ry-runtime"]
    runtime = snapshot["packages"][1]
    assert runtime["maintainer"] == "甘怡训"
    assert runtime["description"] == "ry 固件底层依赖"
    assert snapshot["vehicle"] == VALID_VEHICLE


@pytest.mark.parametrize("failure", [
    lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutExpired("/usr/bin/dpkg-query", 5)),
    lambda *_args, **_kwargs: completed("", returncode=1),
    lambda *_args, **_kwargs: completed("not-a-usable-dpkg-row\n"),
    lambda *_args, **_kwargs: completed("ry-runtime\t1.2.3\tamd64\tii \nry-broken\tmissing-fields\n"),
])
def test_snapshot_returns_user_safe_unavailable_state_when_package_query_fails(tmp_path, failure):
    from autodrive_console.software_inventory import SoftwareInventory

    snapshot = SoftwareInventory(SettingsStore(tmp_path / "console.json"), runner=failure).snapshot()

    assert snapshot["inventory_status"] == "unavailable"
    assert snapshot["packages"] == []
    assert snapshot["message"] == "当前无法读取软件清单，请稍后刷新。"
    assert "/usr/bin" not in snapshot["message"]


def test_save_requires_all_vehicle_fields_and_current_package_keys_only(tmp_path):
    def runner(*_args, **_kwargs):
        return completed("ry-runtime\t1.2.3\tamd64\tii \n")

    from autodrive_console.software_inventory import SoftwareInventory, SoftwareInventoryError

    inventory = SoftwareInventory(SettingsStore(tmp_path / "console.json"), runner=runner)
    with pytest.raises(SoftwareInventoryError, match="车架号"):
        inventory.save({"vehicle": {**VALID_VEHICLE, "vin": ""}, "package_notes": {}})
    with pytest.raises(SoftwareInventoryError, match="当前已安装"):
        inventory.save({
            "vehicle": VALID_VEHICLE,
            "package_notes": {"ry-not-installed": {"maintainer": "A", "description": "B"}},
        })


def test_save_normalizes_notes_and_snapshot_uses_only_current_discovered_packages(tmp_path):
    def runner(*_args, **_kwargs):
        return completed("ry-runtime\t1.2.3\tamd64\tii \n")

    from autodrive_console.software_inventory import SoftwareInventory

    store = SettingsStore(tmp_path / "console.json")
    snapshot = SoftwareInventory(store, runner=runner).save({
        "vehicle": {key: f"  {value}  " for key, value in VALID_VEHICLE.items()},
        "package_notes": {
            "ry-runtime": {"maintainer": "  甘怡训  ", "description": "  运行时  "},
        },
    })

    assert snapshot["vehicle"] == VALID_VEHICLE
    assert snapshot["packages"][0]["maintainer"] == "甘怡训"
    assert snapshot["packages"][0]["description"] == "运行时"
    persisted = store.load().software_inventory
    assert persisted["package_notes"] == {
        "ry-runtime": {"maintainer": "甘怡训", "description": "运行时"},
    }


def test_inventory_save_uses_atomic_settings_replace(tmp_path, monkeypatch):
    import autodrive_console.settings as settings_module
    from autodrive_console.software_inventory import SoftwareInventory

    replacements = []
    real_replace = __import__("os").replace

    def capture_replace(source, target):
        replacements.append((source, target))
        real_replace(source, target)

    monkeypatch.setattr(settings_module.os, "replace", capture_replace)

    def runner(*_args, **_kwargs):
        return completed("ry-runtime\t1.2.3\tamd64\tii \n")

    target = tmp_path / "console.json"
    SoftwareInventory(SettingsStore(target), runner=runner).save({
        "vehicle": VALID_VEHICLE,
        "package_notes": {"ry-runtime": {"maintainer": "", "description": ""}},
    })

    assert replacements
    assert replacements[-1][1] == target
    assert target.read_text(encoding="utf-8").startswith("{")
