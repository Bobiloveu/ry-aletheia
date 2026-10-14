from __future__ import annotations

import io
import json
from http import HTTPStatus
from unittest.mock import Mock, patch

import web_console
from autodrive_console.software_inventory import SoftwareInventoryError, SoftwareInventoryUnavailable


VALID_VEHICLE = {
    "vehicle_number": "01号车",
    "vin": "RY-CHASSIS-001",
    "model": "RY 标准小车",
    "project": "园区配送",
    "location": "A 栋一层",
}


class InventoryApi:
    def __init__(self):
        self.saved = []
        self.available = True

    def snapshot(self):
        if not self.available:
            return {
                "inventory_status": "unavailable",
                "message": "当前无法读取软件清单，请稍后刷新。",
                "vehicle": VALID_VEHICLE,
                "packages": [],
                "discovered_at": None,
            }
        return {
            "inventory_status": "available",
            "message": "",
            "vehicle": VALID_VEHICLE,
            "packages": [{"package_name": "ry-runtime"}],
            "discovered_at": "2026-10-09T10:00:00+00:00",
        }

    def save(self, payload):
        if not self.available:
            raise SoftwareInventoryUnavailable("当前无法读取软件清单，请稍后刷新。")
        if not payload["vehicle"]["vin"]:
            raise SoftwareInventoryError("车架号不能为空。")
        if set(payload["package_notes"]) - {"ry-runtime"}:
            raise SoftwareInventoryError("软件说明只能保存当前已安装的 ry-* 软件包。")
        self.saved.append(payload)
        return {**self.snapshot(), "message": "车辆档案和软件说明已保存。"}


def handler(path: str, payload: object | None = None):
    item = object.__new__(web_console.ConsoleHandler)
    item.path = path
    item.headers = {"User-Agent": "test"}
    item._json = Mock()
    item._static_from = Mock()
    if payload is not None:
        encoded = json.dumps(payload).encode("utf-8")
        item.headers = {"Content-Length": str(len(encoded))}
        item.rfile = io.BytesIO(encoded)
    return item


def test_inventory_get_returns_available_and_unavailable_snapshots():
    api = InventoryApi()
    item = handler("/api/software-inventory")
    with patch.object(web_console, "SOFTWARE_INVENTORY", api, create=True):
        item.do_GET()
    assert item._json.call_args.args == (api.snapshot(),)

    api.available = False
    item = handler("/api/software-inventory")
    with patch.object(web_console, "SOFTWARE_INVENTORY", api, create=True):
        item.do_GET()
    assert item._json.call_args.args == (api.snapshot(),)


def test_inventory_post_saves_complete_profile_and_rejects_validation_errors():
    api = InventoryApi()
    payload = {
        "vehicle": VALID_VEHICLE,
        "package_notes": {"ry-runtime": {"maintainer": "甘怡训", "description": "运行时"}},
    }
    item = handler("/api/software-inventory", payload)
    with patch.object(web_console, "SOFTWARE_INVENTORY", api, create=True):
        item.do_POST()
    assert api.saved == [payload]
    assert item._json.call_args.args == ({**api.snapshot(), "message": "车辆档案和软件说明已保存。"},)

    item = handler("/api/software-inventory", {**payload, "vehicle": {**VALID_VEHICLE, "vin": ""}})
    with patch.object(web_console, "SOFTWARE_INVENTORY", api, create=True):
        item.do_POST()
    assert item._json.call_args.args[1] == HTTPStatus.BAD_REQUEST

    item = handler("/api/software-inventory", {**payload, "package_notes": {"ry-nope": {"maintainer": "", "description": ""}}})
    with patch.object(web_console, "SOFTWARE_INVENTORY", api, create=True):
        item.do_POST()
    assert item._json.call_args.args[1] == HTTPStatus.BAD_REQUEST


def test_inventory_post_returns_service_unavailable_when_package_discovery_is_unavailable():
    api = InventoryApi()
    api.available = False
    item = handler("/api/software-inventory", {"vehicle": VALID_VEHICLE, "package_notes": {}})
    with patch.object(web_console, "SOFTWARE_INVENTORY", api, create=True):
        item.do_POST()
    assert item._json.call_args.args == (
        {"error": "当前无法读取软件清单，请稍后刷新。"},
        HTTPStatus.SERVICE_UNAVAILABLE,
    )
