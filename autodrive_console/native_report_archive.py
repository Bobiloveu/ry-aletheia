"""Controlled, read-only native report evidence for the Mobile client.

This module deliberately has no dependency on HTML/SVG rendering, ROS, or the
current map cache.  It converts only already-saved structured trajectory JSON
and its explicitly referenced frozen PNG into a small, validated sidecar.
"""

from __future__ import annotations

import base64
import json
import logging
import math
import os
import re
import secrets
import struct
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

LOGGER = logging.getLogger("ry_aletheia.native_report_archive")


class NativeReportArchiveError(ValueError):
    """The request or persisted native-report evidence is invalid."""


class NativeReportNotFound(NativeReportArchiveError):
    """A syntactically valid report resource is not part of this archive."""


NATIVE_DIRNAME = ".native-reports"
SCHEMA_VERSION = 1
TOKEN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
TRAJECTORY_DIRECTORY = re.compile(r"^run_([0-9a-f]{12})_trajectory$")
TEST_REPORT_RUN = re.compile(r"_(?P<run>[0-9a-f]{12})\.html$")
ACCEPTANCE_REPORT = re.compile(r"^acceptance_[0-9a-f]{12}_\d{8}_\d{6}\.html$")
SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,180}$")
MAX_DISPLAY_POINTS = 2_000
MAX_TEXT = 200
MAX_DETAIL_TEXT = 2_000


def _finite_number(value: object, *, field: str) -> float:
    if isinstance(value, bool):
        raise NativeReportArchiveError(f"{field}无效")
    try:
        converted = float(value)
    except (TypeError, ValueError) as exc:
        raise NativeReportArchiveError(f"{field}无效") from exc
    if not math.isfinite(converted):
        raise NativeReportArchiveError(f"{field}无效")
    return converted


def _non_negative_int(value: object, *, field: str) -> int:
    converted = _finite_number(value, field=field)
    if converted < 0 or not converted.is_integer():
        raise NativeReportArchiveError(f"{field}无效")
    return int(converted)


def _safe_text(value: object, *, fallback: str, limit: int = MAX_TEXT) -> str:
    text = str(value).strip() if isinstance(value, str) else ""
    if not text or len(text) > limit or any(ord(char) < 32 or ord(char) == 127 for char in text):
        return fallback
    # Native reports must never turn a local path or a browser/file URL into
    # public diagnostic text.  Keep a neutral, controlled alternative instead.
    if "://" in text or "\\" in text or re.search(r"(?:^|\s)/[^\s]+", text):
        return fallback
    return text


def _controlled_text(value: object, *, limit: int, optional: bool = False) -> bool:
    if value is None:
        return optional
    if not isinstance(value, str) or not value:
        return False
    return _safe_text(value, fallback="", limit=limit) == value


def _identifier(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not TOKEN.fullmatch(value):
        raise NativeReportArchiveError(f"{field}无效")
    return value


def _report_filename(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 240
        or "/" in value
        or "\\" in value
        or ".." in value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise NativeReportArchiveError("报告文件名无效")
    return value


def _new_identifier(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(18).rstrip('=')}"


def _encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(f"v1:{offset}".encode("ascii")).decode("ascii").rstrip("=")


def _decode_cursor(cursor: object) -> int:
    if not isinstance(cursor, str) or not cursor or len(cursor) > 512:
        raise NativeReportArchiveError("分页标识无效")
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("ascii")
    except (UnicodeEncodeError, UnicodeDecodeError, ValueError):
        raise NativeReportArchiveError("分页标识无效") from None
    if not re.fullmatch(r"v1:(0|[1-9][0-9]*)", decoded):
        raise NativeReportArchiveError("分页标识无效")
    return int(decoded.removeprefix("v1:"))


def _paged(values: list[dict[str, Any]], cursor: str | None, limit: int, *, maximum: int) -> tuple[list[dict[str, Any]], str | None]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= maximum:
        raise NativeReportArchiveError("分页数量无效")
    offset = 0 if cursor is None else _decode_cursor(cursor)
    if offset > len(values):
        raise NativeReportArchiveError("分页标识无效")
    next_offset = offset + limit
    return values[offset:next_offset], _encode_cursor(next_offset) if next_offset < len(values) else None


def _display_points(points: list[dict[str, Any]]) -> list[dict[str, float]]:
    if len(points) <= MAX_DISPLAY_POINTS:
        return [{"x_m": point["x_m"], "y_m": point["y_m"]} for point in points]
    # Deterministic, endpoint-preserving uniform decimation.  Full samples
    # remain in the sidecar and are available through the samples endpoint.
    indices = [round(index * (len(points) - 1) / (MAX_DISPLAY_POINTS - 1)) for index in range(MAX_DISPLAY_POINTS)]
    return [{"x_m": points[index]["x_m"], "y_m": points[index]["y_m"]} for index in indices]


def _atomic_write(target: Path, body: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{secrets.token_hex(8)}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


class NativeReportArchive:
    """Own schema-v1 native-report sidecars under one report directory."""

    def __init__(
        self,
        report_dir: Path,
        *,
        max_png_bytes: int = 16 * 1024 * 1024,
        max_map_cells: int = 16_000_000,
    ) -> None:
        self.report_dir = Path(report_dir).resolve()
        self.native_dir = self.report_dir / NATIVE_DIRNAME
        self.max_png_bytes = max_png_bytes
        self.max_map_cells = max_map_cells

    def archive_historic_report(self, html_filename: str) -> bool:
        """Create a safe migration sidecar without ever interpreting HTML/SVG."""
        html = self._owned_html(html_filename)
        try:
            sources = list(self._historic_sources(html.name))
            if not sources:
                return False
            archive = self._build_archive(
                html_filename=html.name,
                kind="acceptance" if ACCEPTANCE_REPORT.fullmatch(html.name) else "test",
                title="部署验收报告" if ACCEPTANCE_REPORT.fullmatch(html.name) else "自动测试运行报告",
                created_at=datetime.fromtimestamp(html.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
                records=[self._historic_item(source, index) for index, source in enumerate(sources, start=1)],
            )
            self._write_archive(archive)
            LOGGER.info("Native report migration succeeded report=%s kind=%s items=%d",
                        archive['report']['report_id'], archive['report']['kind'], len(archive['items']))
            return True
        except (OSError, json.JSONDecodeError, NativeReportArchiveError):
            LOGGER.warning("Native report migration failed", exc_info=True)
            return False

    def archive_test_report(self, *, html_filename: str, run: object) -> dict[str, Any]:
        """Archive a newly completed ordinary test from its saved trajectory JSON."""
        html = self._owned_html(html_filename)
        attempts = getattr(run, "attempts", None)
        if not isinstance(attempts, list):
            raise NativeReportArchiveError("测试运行记录无效")
        records: list[dict[str, Any]] = []
        for index, attempt in enumerate(attempts, start=1):
            raw_trajectory = getattr(attempt, "trajectory", None)
            payload, source_dir = self._saved_trajectory(raw_trajectory)
            status = getattr(attempt, "status", None)
            records.append({
                "title": f"第 {index} 轮任务",
                "status": status,
                "duration_ms": self._duration_milliseconds(getattr(attempt, "duration_s", 0)),
                "summary": self._item_summary(status),
                "detail": None,
                "trajectory": payload,
                "trajectory_dir": source_dir,
            })
        archive = self._build_archive(
            html_filename=html.name,
            kind="test",
            title="自动测试运行报告",
            created_at=self._created_at(getattr(run, "started_at", None), html),
            records=records,
        )
        self._write_archive(archive)
        return dict(archive["report"])

    def archive_acceptance_report(self, *, html_filename: str, plan: object) -> dict[str, Any]:
        """Archive a newly generated acceptance report from frozen plan items."""
        html = self._owned_html(html_filename)
        source_items = getattr(plan, "items", None)
        if not isinstance(source_items, list):
            raise NativeReportArchiveError("验收计划无效")
        records: list[dict[str, Any]] = []
        for index, item in enumerate(source_items, start=1):
            payload, source_dir = self._saved_trajectory(getattr(item, "trajectory", None))
            status = self._normal_status(getattr(item, "status", None))
            records.append({
                "title": f"第 {index} 项验收任务",
                "status": status,
                "duration_ms": self._duration_milliseconds(getattr(item, "duration_s", 0) or 0),
                "summary": self._item_summary(status),
                "detail": None,
                "trajectory": payload,
                "trajectory_dir": source_dir,
            })
        archive = self._build_archive(
            html_filename=html.name,
            kind="acceptance",
            title="部署验收报告",
            created_at=self._created_at(getattr(plan, "created_at", None), html),
            records=records,
        )
        self._write_archive(archive)
        return dict(archive["report"])

    def summary_for_filename(self, html_filename: str) -> dict[str, Any] | None:
        try:
            html_filename = _report_filename(html_filename)
        except NativeReportArchiveError:
            return None
        for archive in self._archives():
            if archive.get("html_filename") == html_filename:
                report = archive.get("report")
                return dict(report) if isinstance(report, dict) else None
        return None

    def historic_filenames(self) -> list[str]:
        """Return only recognized legacy reports that still lack a sidecar."""
        if not self.report_dir.is_dir():
            return []
        candidates = []
        for target in self.report_dir.glob("*.html"):
            if target.parent != self.report_dir or target.is_symlink() or not target.is_file():
                continue
            if not (ACCEPTANCE_REPORT.fullmatch(target.name) or TEST_REPORT_RUN.search(target.name)):
                continue
            if self.summary_for_filename(target.name) is None:
                candidates.append(target)
        return [target.name for target in sorted(candidates, key=lambda item: item.stat().st_mtime, reverse=True)]

    def detail_page(self, report_id: str, cursor: str | None, limit: int) -> dict[str, Any]:
        archive = self._archive_for_report(report_id)
        items = archive["items"]
        page, next_cursor = _paged(items, cursor, limit, maximum=100)
        return {"report": archive["report"], "items": page, "next_cursor": next_cursor}

    def trajectory(self, report_id: str, trajectory_id: str) -> dict[str, Any]:
        record = self._trajectory_record(report_id, trajectory_id)
        return {
            "schema_version": SCHEMA_VERSION,
            "trajectory_id": record["trajectory_id"],
            "item_id": record["item_id"],
            "label": record["label"],
            "map": record["map"],
            "display_paths": record["display_paths"],
            "virtual_walls": record["virtual_walls"],
            "sample_count": len(record["samples"]),
            "integrity_warning": record.get("integrity_warning"),
            "samples_next_cursor": _encode_cursor(0) if record["samples"] else None,
        }

    def trajectory_map_png(self, report_id: str, trajectory_id: str) -> bytes:
        record = self._trajectory_record(report_id, trajectory_id)
        resource = record.get("png_resource")
        if not isinstance(resource, str) or not SAFE_FILENAME.fullmatch(resource):
            raise NativeReportNotFound("轨迹底图不存在")
        target = self._owned_native_child(resource)
        if not target.is_file() or target.is_symlink():
            raise NativeReportNotFound("轨迹底图不存在")
        body = target.read_bytes()
        self._validate_png(body, record["map"])
        return body

    def sample_page(self, report_id: str, trajectory_id: str, cursor: str | None, limit: int) -> dict[str, Any]:
        record = self._trajectory_record(report_id, trajectory_id)
        samples, next_cursor = _paged(record["samples"], cursor, limit, maximum=1000)
        return {"samples": samples, "next_cursor": next_cursor}

    def delete_for_filename(self, html_filename: str) -> None:
        try:
            html_filename = _report_filename(html_filename)
        except NativeReportArchiveError:
            return
        for archive in self._archives():
            if archive.get("html_filename") != html_filename:
                continue
            for record in archive.get("trajectories", {}).values() if isinstance(archive.get("trajectories"), dict) else ():
                if isinstance(record, dict) and isinstance(record.get("png_resource"), str):
                    resource = record["png_resource"]
                    if SAFE_FILENAME.fullmatch(resource):
                        candidate = self._owned_native_child(resource)
                        if candidate.is_file() and not candidate.is_symlink():
                            candidate.unlink()
            report_id = archive.get("report", {}).get("report_id") if isinstance(archive.get("report"), dict) else None
            if isinstance(report_id, str) and TOKEN.fullmatch(report_id):
                sidecar = self._owned_native_child(f"{report_id}.json")
                if sidecar.is_file() and not sidecar.is_symlink():
                    sidecar.unlink()

    def _historic_sources(self, html_filename: str) -> Iterable[Path]:
        if ACCEPTANCE_REPORT.fullmatch(html_filename):
            manifest = self._owned_report_child(Path(html_filename).with_suffix(".assets.json").name)
            if not manifest.is_file() or manifest.is_symlink():
                return ()
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            names = payload.get("trajectory_directories") if isinstance(payload, dict) and payload.get("schema") == 1 else None
            if not isinstance(names, list) or not names:
                raise NativeReportArchiveError("验收报告资产清单无效")
            directories = []
            for name in names:
                if not isinstance(name, str) or not TRAJECTORY_DIRECTORY.fullmatch(name):
                    raise NativeReportArchiveError("验收报告资产目录无效")
                directory = self._owned_report_child(name)
                if not directory.is_dir() or directory.is_symlink():
                    raise NativeReportArchiveError("验收报告资产目录不存在")
                directories.append(directory)
        else:
            match = TEST_REPORT_RUN.search(html_filename)
            if not match:
                raise NativeReportArchiveError("测试报告名称无效")
            directory = self._owned_report_child(f"run_{match.group('run')}_trajectory")
            if not directory.is_dir() or directory.is_symlink():
                return ()
            directories = [directory]
        sources: list[Path] = []
        for directory in directories:
            for source in sorted(directory.glob("T-*.json")):
                if source.parent == directory and source.is_file() and not source.is_symlink():
                    sources.append(source)
        return sources

    def _saved_trajectory(self, raw: object) -> tuple[dict[str, Any] | None, Path | None]:
        if not isinstance(raw, dict):
            return None, None
        value = raw.get("file")
        if not isinstance(value, str):
            return raw, None
        source = Path(value).resolve()
        parent = source.parent
        if (
            parent.parent != self.report_dir
            or not TRAJECTORY_DIRECTORY.fullmatch(parent.name)
            or source.suffix != ".json"
            or source.is_symlink()
            or not source.is_file()
        ):
            raise NativeReportArchiveError("轨迹记录来源无效")
        payload = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise NativeReportArchiveError("轨迹记录无效")
        return payload, parent

    @staticmethod
    def _duration_milliseconds(value: object) -> int:
        seconds = _finite_number(value, field="任务时长")
        if seconds < 0:
            raise NativeReportArchiveError("任务时长无效")
        return int(round(seconds * 1000))

    def _created_at(self, value: object, html: Path) -> str:
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is not None:
                    return parsed.isoformat(timespec="seconds")
            except ValueError:
                pass
        return datetime.fromtimestamp(html.stat().st_mtime).astimezone().isoformat(timespec="seconds")

    @staticmethod
    def _item_summary(status: object) -> str:
        return {
            "passed": "任务已完成。",
            "failed": "任务未通过。",
            "blocked": "任务被安全条件拦截。",
            "cancelled": "任务已取消。",
        }.get(status, "任务结果待确认。")

    @staticmethod
    def _normal_status(value: object) -> str:
        return value if value in {"passed", "failed", "blocked", "cancelled", "incomplete", "unknown"} else "incomplete"

    def _historic_item(self, source: Path, index: int) -> dict[str, Any]:
        payload = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise NativeReportArchiveError("轨迹记录无效")
        return {
            "title": f"第 {index} 项任务",
            "status": "unknown",
            "duration_ms": 0,
            "summary": "历史报告已归档。",
            "detail": None,
            "trajectory": payload,
            "trajectory_dir": source.parent,
        }

    def _build_archive(
        self,
        *,
        html_filename: str,
        kind: str,
        title: str,
        created_at: str,
        records: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if kind not in {"test", "acceptance"}:
            raise NativeReportArchiveError("报告类型无效")
        report_id = _new_identifier("rpt")
        items: list[dict[str, Any]] = []
        trajectories: dict[str, dict[str, Any]] = {}
        counts = {status: 0 for status in ("passed", "failed", "blocked")}
        total_duration = 0
        overall_status = "passed"
        for index, record in enumerate(records, start=1):
            item_id = _new_identifier("item")
            status = record.get("status") if record.get("status") in {"passed", "failed", "blocked", "cancelled", "incomplete", "unknown"} else "unknown"
            total_duration += _non_negative_int(record.get("duration_ms", 0), field="任务时长")
            if status in counts:
                counts[status] += 1
            if status != "passed":
                overall_status = status if overall_status == "passed" else overall_status
            references = self._archive_trajectory(
                item_id,
                record.get("trajectory"),
                report_id,
                record.get("trajectory_dir"),
            )
            items.append({
                "item_id": item_id,
                "title": _safe_text(record.get("title"), fallback=f"第 {index} 项任务"),
                "status": status,
                "duration_ms": _non_negative_int(record.get("duration_ms", 0), field="任务时长"),
                "summary": _safe_text(record.get("summary"), fallback="任务结果已归档", limit=500),
                "detail": _safe_text(record.get("detail"), fallback="任务详细信息未提供", limit=MAX_DETAIL_TEXT) if record.get("detail") else None,
                "trajectory_refs": references[0],
            })
            trajectories.update(references[1])
        total = len(items)
        if not total:
            overall_status = "incomplete"
        elif counts["failed"] or counts["blocked"]:
            overall_status = "failed" if counts["failed"] else "blocked"
        elif any(item["status"] == "cancelled" for item in items):
            overall_status = "cancelled"
        elif any(item["status"] in {"incomplete", "unknown"} for item in items):
            overall_status = "incomplete"
        pass_rate = round(counts["passed"] / total * 100, 1) if total else 0.0
        report = {
            "schema_version": SCHEMA_VERSION,
            "report_id": report_id,
            "kind": kind,
            "title": title,
            "status": overall_status,
            "created_at": created_at,
            "duration_ms": total_duration,
            "summary": {"total": total, "passed": counts["passed"], "failed": counts["failed"], "blocked": counts["blocked"], "pass_rate": pass_rate},
            "headline": self._headline(overall_status),
        }
        return {"schema_version": SCHEMA_VERSION, "html_filename": html_filename, "report": report, "items": items, "trajectories": trajectories}

    def _archive_trajectory(
        self,
        item_id: str,
        raw: object,
        report_id: str,
        trajectory_dir: object,
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        if not isinstance(raw, dict):
            return [], {}
        frozen_maps = raw.get("frozen_maps")
        known_maps = {entry.get("map_id"): entry for entry in frozen_maps if isinstance(entry, dict) and isinstance(entry.get("map_id"), str)} if isinstance(frozen_maps, list) else {}
        segments = raw.get("segments") if isinstance(raw.get("segments"), list) else []
        ideal_routes = raw.get("ideal_routes") if isinstance(raw.get("ideal_routes"), dict) else {}
        walls = raw.get("virtual_walls") if isinstance(raw.get("virtual_walls"), dict) else {}
        map_ids = []
        for segment in segments:
            map_id = segment.get("map_id") if isinstance(segment, dict) else None
            if isinstance(map_id, str) and map_id not in map_ids:
                map_ids.append(map_id)
        for map_id in known_maps:
            if map_id not in map_ids:
                map_ids.append(map_id)
        references: list[dict[str, Any]] = []
        trajectories: dict[str, dict[str, Any]] = {}
        for map_id in map_ids:
            info = known_maps.get(map_id)
            label = _safe_text((info or {}).get("label") or self._segment_label(segments, map_id), fallback="历史轨迹地图")
            trajectory_id = _new_identifier("traj")
            source_segments = [segment for segment in segments if isinstance(segment, dict) and segment.get("map_id") == map_id]
            if not isinstance(info, dict):
                references.append({"trajectory_id": trajectory_id, "label": label, "status": "unavailable", "sample_count": 0, "integrity_warning": "历史轨迹缺少冻结底图。"})
                continue
            try:
                map_meta, png_body = self._frozen_map(info, trajectory_dir)
                samples, actual_paths = self._samples_and_paths(source_segments)
                ideal_paths = self._ideal_paths(ideal_routes.get(map_id))
                display_paths = actual_paths + ideal_paths
                if not display_paths:
                    raise NativeReportArchiveError("轨迹没有可展示路径")
                virtual_walls = self._world_walls(walls.get(map_id), map_meta)
                resource = f"{report_id}_{trajectory_id}.png"
                _atomic_write(self._owned_native_child(resource), png_body)
                record = {
                    "trajectory_id": trajectory_id,
                    "item_id": item_id,
                    "label": label,
                    "map": map_meta,
                    "display_paths": display_paths,
                    "virtual_walls": virtual_walls,
                    "samples": samples,
                    "png_resource": resource,
                    "integrity_warning": _safe_text(raw.get("integrity_warning"), fallback="轨迹证据不完整", limit=500) if raw.get("integrity_warning") else None,
                }
                trajectories[trajectory_id] = record
                references.append({"trajectory_id": trajectory_id, "label": label, "status": "incomplete" if record["integrity_warning"] else "available", "sample_count": len(samples), "integrity_warning": record["integrity_warning"]})
            except (OSError, NativeReportArchiveError):
                references.append({"trajectory_id": trajectory_id, "label": label, "status": "unavailable", "sample_count": 0, "integrity_warning": "轨迹证据不可用。"})
        return references, trajectories

    def _frozen_map(self, info: dict[str, Any], trajectory_dir: object) -> tuple[dict[str, Any], bytes]:
        filename = info.get("filename")
        if not isinstance(filename, str) or not SAFE_FILENAME.fullmatch(filename) or not filename.endswith(".png"):
            raise NativeReportArchiveError("冻结地图资源无效")
        if not isinstance(trajectory_dir, Path):
            raise NativeReportArchiveError("冻结地图来源无效")
        source = (trajectory_dir / filename).resolve()
        if source.parent != trajectory_dir.resolve() or source.is_symlink():
            raise NativeReportArchiveError("冻结地图来源无效")
        if not source.is_file() or source.is_symlink():
            raise NativeReportArchiveError("冻结地图资源不存在")
        map_meta = {
            "label": _safe_text(info.get("label"), fallback="轨迹地图"),
            "resolution_m": _finite_number(info.get("resolution_m"), field="地图分辨率"),
            "width_cells": _non_negative_int(info.get("width_cells"), field="地图宽度"),
            "height_cells": _non_negative_int(info.get("height_cells"), field="地图高度"),
            "origin_x_m": _finite_number(info.get("origin_x_m"), field="地图原点"),
            "origin_y_m": _finite_number(info.get("origin_y_m"), field="地图原点"),
        }
        if map_meta["resolution_m"] <= 0 or map_meta["width_cells"] <= 0 or map_meta["height_cells"] <= 0 or map_meta["width_cells"] * map_meta["height_cells"] > self.max_map_cells:
            raise NativeReportArchiveError("冻结地图元数据无效")
        body = source.read_bytes()
        self._validate_png(body, map_meta)
        return map_meta, body

    def _samples_and_paths(self, segments: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        samples: list[dict[str, Any]] = []
        paths: list[dict[str, Any]] = []
        for segment_index, segment in enumerate(segments, start=1):
            route_name = _safe_text(segment.get("route_name"), fallback=f"轨迹段 {segment_index}")
            points = segment.get("points")
            if not isinstance(points, list):
                continue
            route_samples = []
            for point in points:
                if not isinstance(point, dict):
                    raise NativeReportArchiveError("轨迹点无效")
                sample = {
                    "x_m": _finite_number(point.get("x"), field="轨迹坐标"),
                    "y_m": _finite_number(point.get("y"), field="轨迹坐标"),
                    "timestamp_ns": _non_negative_int(point.get("timestamp_ns", 0), field="轨迹时间"),
                    "route_name": route_name,
                    "sample_index": len(samples),
                }
                samples.append(sample)
                route_samples.append(sample)
            if route_samples:
                paths.append({"kind": "actual", "route_name": route_name, "points": _display_points(route_samples)})
        return samples, paths

    def _ideal_paths(self, value: object) -> list[dict[str, Any]]:
        paths = []
        for index, route in enumerate(value if isinstance(value, list) else [], start=1):
            if not isinstance(route, dict) or not isinstance(route.get("points"), list):
                continue
            points = []
            for point in route["points"]:
                if not isinstance(point, dict):
                    raise NativeReportArchiveError("理想路线点无效")
                points.append({"x_m": _finite_number(point.get("x"), field="理想路线坐标"), "y_m": _finite_number(point.get("y"), field="理想路线坐标")})
            if points:
                paths.append({"kind": "ideal", "route_name": _safe_text(route.get("name"), fallback=f"理想路线 {index}"), "points": _display_points(points)})
        return paths

    def _world_walls(self, value: object, map_meta: dict[str, Any]) -> list[list[dict[str, float]]]:
        walls = []
        for wall in value if isinstance(value, list) else []:
            if not isinstance(wall, dict) or not isinstance(wall.get("points"), list):
                raise NativeReportArchiveError("虚拟墙无效")
            points = []
            for point in wall["points"]:
                if not isinstance(point, dict):
                    raise NativeReportArchiveError("虚拟墙点无效")
                x, y = _finite_number(point.get("x"), field="虚拟墙坐标"), _finite_number(point.get("y"), field="虚拟墙坐标")
                if wall.get("coordinate_mode") == "image_relative":
                    x += map_meta["origin_x_m"]
                    y += map_meta["origin_y_m"]
                points.append({"x_m": x, "y_m": y})
            if len(points) < 2:
                raise NativeReportArchiveError("虚拟墙点不足")
            walls.append(points)
        return walls

    def _segment_label(self, segments: list[dict[str, Any]], map_id: str) -> str:
        for segment in segments:
            if segment.get("map_id") == map_id:
                return _safe_text(segment.get("map_label"), fallback="历史轨迹地图")
        return "历史轨迹地图"

    def _write_archive(self, archive: dict[str, Any]) -> None:
        report_id = _identifier(archive.get("report", {}).get("report_id"), field="报告标识")
        try:
            _atomic_write(self._owned_native_child(f"{report_id}.json"), json.dumps(archive, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        except Exception:
            LOGGER.exception("Native report archive write failed report=%s", report_id)
            raise
        LOGGER.info("Native report archived report=%s items=%d trajectories=%d",
                    report_id, len(archive['items']), len(archive['trajectories']))

    def _archive_for_report(self, report_id: str) -> dict[str, Any]:
        report_id = _identifier(report_id, field="报告标识")
        sidecar = self._owned_native_child(f"{report_id}.json")
        if not sidecar.is_file() or sidecar.is_symlink():
            raise NativeReportNotFound("原生报告不存在")
        try:
            archive = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise NativeReportNotFound("原生报告不存在") from exc
        if not self._valid_archive(archive) or archive["report"]["report_id"] != report_id:
            raise NativeReportNotFound("原生报告不存在")
        return archive

    def _trajectory_record(self, report_id: str, trajectory_id: str) -> dict[str, Any]:
        trajectory_id = _identifier(trajectory_id, field="轨迹标识")
        archive = self._archive_for_report(report_id)
        record = archive["trajectories"].get(trajectory_id)
        if not isinstance(record, dict):
            raise NativeReportNotFound("原生轨迹不存在")
        return record

    def _archives(self) -> Iterable[dict[str, Any]]:
        if not self.native_dir.is_dir() or self.native_dir.is_symlink():
            return ()
        archives = []
        for target in self.native_dir.glob("rpt_*.json"):
            if target.parent != self.native_dir or target.is_symlink() or not target.is_file():
                continue
            try:
                document = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if self._valid_archive(document):
                archives.append(document)
        return archives

    def _valid_archive(self, archive: object) -> bool:
        if not isinstance(archive, dict) or archive.get("schema_version") != SCHEMA_VERSION:
            return False
        try:
            _report_filename(archive.get("html_filename"))
        except NativeReportArchiveError:
            return False
        report, items, trajectories = archive.get("report"), archive.get("items"), archive.get("trajectories")
        if not isinstance(report, dict) or not isinstance(items, list) or not isinstance(trajectories, dict):
            return False
        try:
            if report.get("schema_version") != SCHEMA_VERSION:
                return False
            _identifier(report.get("report_id"), field="报告标识")
            if report.get("kind") not in {"test", "acceptance"} or report.get("status") not in {"passed", "failed", "blocked", "cancelled", "incomplete", "unknown"}:
                return False
            if not _controlled_text(report.get("title"), limit=MAX_TEXT) or not _controlled_text(report.get("headline"), limit=400, optional=True):
                return False
            if not isinstance(report.get("created_at"), str) or datetime.fromisoformat(report["created_at"].replace("Z", "+00:00")) is None:
                return False
            _non_negative_int(report.get("duration_ms"), field="报告时长")
            metrics = report.get("summary")
            if not isinstance(metrics, dict):
                return False
            total = _non_negative_int(metrics.get("total"), field="统计")
            passed = _non_negative_int(metrics.get("passed"), field="统计")
            failed = _non_negative_int(metrics.get("failed"), field="统计")
            blocked = _non_negative_int(metrics.get("blocked"), field="统计")
            pass_rate = _finite_number(metrics.get("pass_rate"), field="统计")
            if passed + failed + blocked > total or not 0 <= pass_rate <= 100 or total != len(items):
                return False
            referenced_trajectories: set[str] = set()
            for item in items:
                if not isinstance(item, dict) or not TOKEN.fullmatch(str(item.get("item_id", ""))):
                    return False
                if (
                    item.get("status") not in {"passed", "failed", "blocked", "cancelled", "incomplete", "unknown"}
                    or not _controlled_text(item.get("title"), limit=MAX_TEXT)
                    or not _controlled_text(item.get("summary"), limit=500, optional=True)
                    or not _controlled_text(item.get("detail"), limit=MAX_DETAIL_TEXT, optional=True)
                    or not isinstance(item.get("trajectory_refs"), list)
                ):
                    return False
                _non_negative_int(item.get("duration_ms"), field="任务时长")
                for reference in item["trajectory_refs"]:
                    if not isinstance(reference, dict):
                        return False
                    trajectory_id = _identifier(reference.get("trajectory_id"), field="轨迹标识")
                    if (
                        not _controlled_text(reference.get("label"), limit=MAX_TEXT)
                        or reference.get("status") not in {"available", "incomplete", "unavailable"}
                        or not _controlled_text(reference.get("integrity_warning"), limit=500, optional=True)
                    ):
                        return False
                    _non_negative_int(reference.get("sample_count"), field="采样数量")
                    if reference["status"] == "unavailable":
                        if trajectory_id in trajectories:
                            return False
                    else:
                        referenced_trajectories.add(trajectory_id)
                        if trajectory_id not in trajectories:
                            return False
            for trajectory_id, record in trajectories.items():
                if not TOKEN.fullmatch(str(trajectory_id)) or not isinstance(record, dict):
                    return False
                if trajectory_id not in referenced_trajectories or record.get("trajectory_id") != trajectory_id or not isinstance(record.get("samples"), list) or not isinstance(record.get("display_paths"), list):
                    return False
                _identifier(record.get("item_id"), field="任务标识")
                if not _controlled_text(record.get("label"), limit=MAX_TEXT) or not _controlled_text(record.get("integrity_warning"), limit=500, optional=True):
                    return False
                if not isinstance(record.get("map"), dict) or not isinstance(record.get("virtual_walls"), list):
                    return False
                map_meta = record["map"]
                if not _controlled_text(map_meta.get("label"), limit=MAX_TEXT):
                    return False
                if _finite_number(map_meta.get("resolution_m"), field="地图分辨率") <= 0 or _non_negative_int(map_meta.get("width_cells"), field="地图宽度") <= 0 or _non_negative_int(map_meta.get("height_cells"), field="地图高度") <= 0:
                    return False
                _finite_number(map_meta.get("origin_x_m"), field="地图原点")
                _finite_number(map_meta.get("origin_y_m"), field="地图原点")
                if not SAFE_FILENAME.fullmatch(str(record.get("png_resource", ""))):
                    return False
                if not record["display_paths"]:
                    return False
                for path in record["display_paths"]:
                    if not isinstance(path, dict) or path.get("kind") not in {"actual", "ideal"} or not _controlled_text(path.get("route_name"), limit=MAX_TEXT) or not isinstance(path.get("points"), list) or not 1 <= len(path["points"]) <= MAX_DISPLAY_POINTS:
                        return False
                    for point in path["points"]:
                        if not isinstance(point, dict):
                            return False
                        _finite_number(point.get("x_m"), field="路线坐标")
                        _finite_number(point.get("y_m"), field="路线坐标")
                previous = -1
                for sample in record["samples"]:
                    if not isinstance(sample, dict):
                        return False
                    _finite_number(sample.get("x_m"), field="采样坐标")
                    _finite_number(sample.get("y_m"), field="采样坐标")
                    _non_negative_int(sample.get("timestamp_ns"), field="采样时间")
                    sample_index = _non_negative_int(sample.get("sample_index"), field="采样序号")
                    if sample_index <= previous or not _controlled_text(sample.get("route_name"), limit=MAX_TEXT):
                        return False
                    previous = sample_index
        except (NativeReportArchiveError, TypeError, ValueError):
            return False
        return True

    def _owned_html(self, filename: str) -> Path:
        filename = _report_filename(filename)
        if not filename.endswith(".html"):
            raise NativeReportArchiveError("报告文件名无效")
        target = self._owned_report_child(filename)
        if not target.is_file() or target.is_symlink():
            raise NativeReportArchiveError("报告不存在")
        return target

    def _owned_report_child(self, name: str) -> Path:
        target = (self.report_dir / name).resolve()
        if target.parent != self.report_dir or target.is_symlink():
            raise NativeReportArchiveError("报告归档来源无效")
        return target

    def _owned_native_child(self, name: str) -> Path:
        if not SAFE_FILENAME.fullmatch(name):
            raise NativeReportArchiveError("原生归档资源无效")
        target = (self.native_dir / name).resolve()
        if target.parent != self.native_dir or target.is_symlink():
            raise NativeReportArchiveError("原生归档资源无效")
        return target

    def _validate_png(self, body: bytes, map_meta: dict[str, Any]) -> None:
        if len(body) < 24 or len(body) > self.max_png_bytes or not body.startswith(b"\x89PNG\r\n\x1a\n"):
            raise NativeReportArchiveError("冻结地图 PNG 无效")
        length, kind = struct.unpack(">I4s", body[8:16])
        if kind != b"IHDR" or length != 13:
            raise NativeReportArchiveError("冻结地图 PNG 无效")
        width, height = struct.unpack(">II", body[16:24])
        if width != map_meta["width_cells"] or height != map_meta["height_cells"]:
            raise NativeReportArchiveError("冻结地图 PNG 尺寸无效")

    @staticmethod
    def _headline(status: str) -> str:
        return {
            "passed": "任务结果已归档。",
            "failed": "存在未通过的任务。",
            "blocked": "任务执行被安全条件拦截。",
            "cancelled": "任务已取消。",
            "incomplete": "报告证据不完整。",
        }.get(status, "任务结果等待确认。")
