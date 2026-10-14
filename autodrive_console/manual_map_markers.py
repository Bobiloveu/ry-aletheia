"""Operator-owned, map-scoped markers for the PC live observation page."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading


_MAP_ID = re.compile(r"[0-9a-f]{16}\Z")


class ManualMapMarkerError(ValueError):
    """A marker request or persisted marker record is not safe to use."""


@dataclass(frozen=True)
class ManualMapMarker:
    id: str
    map_id: str
    alias: str
    x: float
    y: float
    yaw: float

    def public(self) -> dict[str, object]:
        return {
            "id": self.id,
            "alias": self.alias,
            "x": self.x,
            "y": self.y,
            "yaw": self.yaw,
        }


class ManualMapMarkerStore:
    """Persist only finite operator points, partitioned by verified map identity."""

    SCHEMA = 1
    MAX_PER_MAP = 500
    MAX_ALIAS_LENGTH = 48
    MAX_COORDINATE_M = 100_000.0
    MAX_INPUT_YAW_RAD = 10_000.0

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def list_for_map(self, map_id: str) -> list[dict[str, object]]:
        checked_map_id = self._map_id(map_id)
        with self._lock:
            return [marker.public() for marker in self._load_locked() if marker.map_id == checked_map_id]

    def create(
        self,
        map_id: str,
        *,
        alias: object,
        x: object,
        y: object,
        yaw: object,
    ) -> dict[str, object]:
        marker = ManualMapMarker(
            id=secrets.token_urlsafe(12),
            map_id=self._map_id(map_id),
            alias=self._alias(alias),
            x=self._coordinate(x, "x"),
            y=self._coordinate(y, "y"),
            yaw=self._yaw(yaw),
        )
        with self._lock:
            markers = self._load_locked()
            if sum(item.map_id == marker.map_id for item in markers) >= self.MAX_PER_MAP:
                raise ManualMapMarkerError("当前地图标记数量已达上限")
            markers.append(marker)
            self._save_locked(markers)
        return marker.public()

    def resolve(self, map_id: str, marker_id: object) -> ManualMapMarker:
        checked_map_id = self._map_id(map_id)
        checked_marker_id = self._marker_id(marker_id)
        with self._lock:
            for marker in self._load_locked():
                if marker.id == checked_marker_id and marker.map_id == checked_map_id:
                    return marker
        raise ManualMapMarkerError("地图标记不存在或不属于当前地图")

    def remove(self, map_id: str, marker_id: object) -> None:
        checked_map_id = self._map_id(map_id)
        checked_marker_id = self._marker_id(marker_id)
        with self._lock:
            markers = self._load_locked()
            retained = [
                marker
                for marker in markers
                if not (marker.id == checked_marker_id and marker.map_id == checked_map_id)
            ]
            if len(retained) == len(markers):
                raise ManualMapMarkerError("地图标记不存在或不属于当前地图")
            self._save_locked(retained)

    def _load_locked(self) -> list[ManualMapMarker]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return []
        if not isinstance(payload, dict) or payload.get("schema") != self.SCHEMA:
            return []
        records = payload.get("markers")
        if not isinstance(records, list):
            return []
        markers: list[ManualMapMarker] = []
        known_ids: set[str] = set()
        per_map: dict[str, int] = {}
        for record in records:
            try:
                marker = self._from_record(record)
            except ManualMapMarkerError:
                continue
            if marker.id in known_ids or per_map.get(marker.map_id, 0) >= self.MAX_PER_MAP:
                continue
            known_ids.add(marker.id)
            per_map[marker.map_id] = per_map.get(marker.map_id, 0) + 1
            markers.append(marker)
        return markers

    def _save_locked(self, markers: list[ManualMapMarker]) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        body = {
            "schema": self.SCHEMA,
            "markers": [
                {
                    "id": marker.id,
                    "map_id": marker.map_id,
                    "alias": marker.alias,
                    "x": marker.x,
                    "y": marker.y,
                    "yaw": marker.yaw,
                }
                for marker in markers
            ],
        }
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(body, output, ensure_ascii=False, separators=(",", ":"))
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
            self._fsync_directory(self.path.parent)
        except Exception:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    @classmethod
    def _from_record(cls, record: object) -> ManualMapMarker:
        if not isinstance(record, dict) or set(record) != {"id", "map_id", "alias", "x", "y", "yaw"}:
            raise ManualMapMarkerError("地图标记记录无效")
        return ManualMapMarker(
            id=cls._marker_id(record["id"]),
            map_id=cls._map_id(record["map_id"]),
            alias=cls._alias(record["alias"]),
            x=cls._coordinate(record["x"], "x"),
            y=cls._coordinate(record["y"], "y"),
            yaw=cls._yaw(record["yaw"]),
        )

    @classmethod
    def _map_id(cls, value: object) -> str:
        if not isinstance(value, str) or not _MAP_ID.fullmatch(value):
            raise ManualMapMarkerError("当前地图尚未确认")
        return value

    @classmethod
    def _marker_id(cls, value: object) -> str:
        if not isinstance(value, str) or not value or len(value) > 96:
            raise ManualMapMarkerError("地图标记无效")
        return value

    @classmethod
    def _alias(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ManualMapMarkerError("标记名称无效")
        alias = value.strip()
        if not alias or len(alias) > cls.MAX_ALIAS_LENGTH:
            raise ManualMapMarkerError("标记名称应为 1 至 48 个字符")
        return alias

    @classmethod
    def _coordinate(cls, value: object, label: str) -> float:
        if isinstance(value, bool):
            raise ManualMapMarkerError(f"{label} 坐标无效")
        try:
            coordinate = float(value)
        except (TypeError, ValueError) as exc:
            raise ManualMapMarkerError(f"{label} 坐标无效") from exc
        if not math.isfinite(coordinate) or abs(coordinate) > cls.MAX_COORDINATE_M:
            raise ManualMapMarkerError(f"{label} 坐标无效")
        return 0.0 if coordinate == 0 else coordinate

    @classmethod
    def _yaw(cls, value: object) -> float:
        if isinstance(value, bool):
            raise ManualMapMarkerError("yaw 无效")
        try:
            yaw = float(value)
        except (TypeError, ValueError) as exc:
            raise ManualMapMarkerError("yaw 无效") from exc
        if not math.isfinite(yaw) or abs(yaw) > cls.MAX_INPUT_YAW_RAD:
            raise ManualMapMarkerError("yaw 无效")
        normalized = (yaw + math.pi) % math.tau - math.pi
        return 0.0 if normalized == 0 else normalized

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        try:
            descriptor = os.open(directory, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        except OSError:
            pass
        finally:
            os.close(descriptor)
