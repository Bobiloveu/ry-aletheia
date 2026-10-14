from __future__ import annotations

import logging
import re
import subprocess
from datetime import datetime, timezone
from typing import Callable

from .settings import SettingsStore

LOGGER = logging.getLogger("ry_aletheia.software_inventory")


DPKG_QUERY = "/usr/bin/dpkg-query"
DPKG_SHOW_FORMAT = "$" + "{binary:Package}\\t$" + "{Version}\\t$" + "{Architecture}\\t$" + "{db:Status-Abbrev}\\n"
PACKAGE_NAME = re.compile(r"ry-[a-z0-9][a-z0-9+.-]*\Z")
ARCHITECTURE = re.compile(r"[a-z0-9][a-z0-9-]*\Z")
VEHICLE_FIELDS = (
    ("vehicle_number", "车号", 1, 32),
    ("vin", "车架号", 5, 64),
    ("model", "车型", 1, 64),
    ("project", "项目/客户", 1, 96),
    ("location", "部署地点", 1, 96),
)
VIN = re.compile(r"[A-Za-z0-9_-]{5,64}\Z")


class SoftwareInventoryError(ValueError):
    """A controlled error which is safe to display to an operator."""


class SoftwareInventoryUnavailable(SoftwareInventoryError):
    """Package facts are temporarily unavailable, so writes must not proceed."""


class SoftwareInventory:
    def __init__(
        self,
        settings: SettingsStore,
        *,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings
        self._runner = runner
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._inventory_available: bool | None = None

    @staticmethod
    def _empty_vehicle() -> dict[str, str]:
        return {key: "" for key, _, _, _ in VEHICLE_FIELDS}

    def _query_packages(self) -> list[dict]:
        command = [
            DPKG_QUERY,
            "--show",
            f"--showformat={DPKG_SHOW_FORMAT}",
        ]
        # Query the database itself, then filter locally. A wildcard with no
        # matches exits 1 even when the database is readable.
        try:
            result = self._runner(
                command,
                capture_output=True,
                check=False,
                input="",
                shell=False,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SoftwareInventoryUnavailable("当前无法读取软件清单，请稍后刷新。") from exc
        if result.returncode != 0:
            raise SoftwareInventoryUnavailable("当前无法读取软件清单，请稍后刷新。")

        packages: list[dict] = []
        for line in result.stdout.splitlines():
            fields = line.split("\t")
            if len(fields) != 4:
                raise SoftwareInventoryUnavailable("当前无法读取软件清单，请稍后刷新。")
            package_name, version, architecture, status = fields
            if len(status) != 3:
                raise SoftwareInventoryUnavailable("当前无法读取软件清单，请稍后刷新。")
            # dpkg can retain not-installed placeholders with no version or
            # architecture. They are not inventory rows and must be skipped.
            # The second character is the current state; the first is the
            # desired selection (e.g. hold), which does not uninstall a package.
            if status[1] != "i":
                continue
            package_name = package_name.removesuffix(f":{architecture}")
            if not PACKAGE_NAME.fullmatch(package_name):
                continue
            if not version or not ARCHITECTURE.fullmatch(architecture):
                raise SoftwareInventoryUnavailable("当前无法读取软件清单，请稍后刷新。")
            packages.append({
                "package_name": package_name,
                "version": version,
                "architecture": architecture,
                "installed": True,
                "package_filename": f"{package_name}_{version}_{architecture}.deb",
            })
        return sorted(packages, key=lambda item: item["package_name"])

    @staticmethod
    def _clean_text(value: object, label: str, minimum: int, maximum: int) -> str:
        if not isinstance(value, str):
            raise SoftwareInventoryError(f"{label}不能为空。")
        cleaned = value.strip()
        if any(ord(character) < 32 or ord(character) == 127 for character in cleaned):
            raise SoftwareInventoryError(f"{label}不能包含换行或控制字符。")
        if not minimum <= len(cleaned) <= maximum:
            raise SoftwareInventoryError(f"{label}长度必须介于 {minimum} 和 {maximum} 个字符。")
        return cleaned

    @classmethod
    def _validate_vehicle(cls, vehicle: object) -> dict[str, str]:
        if not isinstance(vehicle, dict) or set(vehicle) != {key for key, _, _, _ in VEHICLE_FIELDS}:
            raise SoftwareInventoryError("请补全车辆档案。")
        normalized = {
            key: cls._clean_text(vehicle.get(key), label, minimum, maximum)
            for key, label, minimum, maximum in VEHICLE_FIELDS
        }
        if not VIN.fullmatch(normalized["vin"]):
            raise SoftwareInventoryError("车架号仅允许字母、数字、连字符和下划线。")
        return normalized

    @staticmethod
    def _normalize_notes(notes: object, package_names: set[str]) -> dict[str, dict[str, str]]:
        if not isinstance(notes, dict):
            raise SoftwareInventoryError("软件说明格式无效。")
        normalized: dict[str, dict[str, str]] = {}
        for package_name, note in notes.items():
            if package_name not in package_names:
                raise SoftwareInventoryError("软件说明只能保存当前已安装的 ry-* 软件包。")
            if not isinstance(note, dict) or set(note) != {"maintainer", "description"}:
                raise SoftwareInventoryError("软件说明格式无效。")
            maintainer = SoftwareInventory._clean_text(note["maintainer"], "维护人", 0, 96)
            description = SoftwareInventory._clean_text(note["description"], "说明", 0, 320)
            normalized[package_name] = {
                "maintainer": maintainer,
                "description": description,
            }
        return normalized

    @staticmethod
    def _stored_data(settings) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
        inventory = settings.software_inventory
        if not isinstance(inventory, dict):
            return SoftwareInventory._empty_vehicle(), {}
        vehicle = inventory.get("vehicle")
        notes = inventory.get("package_notes")
        return (
            dict(vehicle) if isinstance(vehicle, dict) else SoftwareInventory._empty_vehicle(),
            dict(notes) if isinstance(notes, dict) else {},
        )

    def _snapshot_from_packages(self, packages: list[dict], *, message: str = "") -> dict:
        vehicle, notes = self._stored_data(self._settings.load())
        for package in packages:
            note = notes.get(package["package_name"])
            package["maintainer"] = note.get("maintainer", "") if isinstance(note, dict) else ""
            package["description"] = note.get("description", "") if isinstance(note, dict) else ""
        return {
            "inventory_status": "available",
            "message": message,
            "discovered_at": self._now().astimezone(timezone.utc).isoformat(),
            "vehicle": vehicle,
            "packages": packages,
        }

    def snapshot(self) -> dict:
        try:
            snapshot = self._snapshot_from_packages(self._query_packages())
            if self._inventory_available is not True:
                LOGGER.info("Software inventory available packages=%d", len(snapshot['packages']))
            self._inventory_available = True
            return snapshot
        except SoftwareInventoryError as exc:
            if self._inventory_available is not False:
                LOGGER.warning("Software inventory unavailable reason=%s", type(exc.__cause__ or exc).__name__)
            self._inventory_available = False
            vehicle, _ = self._stored_data(self._settings.load())
            return {
                "inventory_status": "unavailable",
                "message": "当前无法读取软件清单，请稍后刷新。",
                "discovered_at": None,
                "vehicle": vehicle,
                "packages": [],
            }

    def save(self, payload: object) -> dict:
        if not isinstance(payload, dict):
            raise SoftwareInventoryError("提交内容格式无效。")
        packages = self._query_packages()
        vehicle = self._validate_vehicle(payload.get("vehicle"))
        notes = self._normalize_notes(payload.get("package_notes"), {item["package_name"] for item in packages})
        LOGGER.info("Software inventory saving packages=%d notes=%d", len(packages), len(notes))
        try:
            self._settings.save({"software_inventory": {"vehicle": vehicle, "package_notes": notes}})
        except ValueError as exc:
            LOGGER.warning("Software inventory save rejected reason=%s", type(exc).__name__)
            raise SoftwareInventoryError("无法保存车辆档案，请检查填写内容。") from exc
        except Exception:
            LOGGER.exception("Software inventory save failed")
            raise
        LOGGER.info("Software inventory saved packages=%d notes=%d", len(packages), len(notes))
        return self._snapshot_from_packages(packages, message="车辆档案和软件说明已保存。")
