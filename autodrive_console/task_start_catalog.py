"""Read-only, fail-closed discovery of navigable task start points."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path


class TaskStartCatalogError(ValueError):
    """A candidate is unavailable or no longer represents the scanned file."""


@dataclass(frozen=True)
class TaskStartIssue:
    name: str
    message: str


@dataclass(frozen=True)
class TaskStartCandidate:
    id: str
    source: str
    label: str
    map_path: Path
    x: float
    y: float
    yaw: float
    member_count: int
    member_paths: tuple[Path, ...]
    fingerprint: str


@dataclass(frozen=True)
class TaskStartSnapshot:
    candidates: tuple[TaskStartCandidate, ...]
    issues: tuple[TaskStartIssue, ...]


class TaskStartCatalog:
    """Scan task roots without exposing or mutating their filesystem details."""

    MAX_FILES_PER_ROOT = 128

    def __init__(self, single_root: Path, multi_root: Path, case_root: Path | None = None) -> None:
        self.single_root = Path(single_root)
        self.multi_root = Path(multi_root)
        self.case_root = Path(case_root) if case_root is not None else None

    def scan(self) -> TaskStartSnapshot:
        parsed: list[tuple[Path, Path, str, float, float, float]] = []
        issues: list[TaskStartIssue] = []
        roots: list[tuple[Path, bool, str]] = [
            (self.single_root, False, "robot_task"),
            (self.multi_root, True, "robot_task"),
        ]
        if self.case_root is not None:
            roots.insert(0, (self.case_root, False, "case"))
        for root, is_multi, source in roots:
            root_path = root.resolve()
            if not root_path.is_dir():
                continue
            try:
                paths, truncated = self._sample_paths(root_path, is_multi=is_multi)
            except OSError:
                issues.append(TaskStartIssue(root_path.name, "任务目录无法扫描"))
                continue
            if truncated:
                issues.append(TaskStartIssue(root_path.name, "任务较多，已使用受限起点样本"))
            for path in paths:
                try:
                    resolved = path.resolve()
                    resolved.relative_to(root_path)
                    map_path, x, y, yaw = self._parse(resolved, is_multi=is_multi)
                    parsed.append((resolved, map_path, source, x, y, yaw))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError, TaskStartCatalogError) as exc:
                    issues.append(TaskStartIssue(path.name, str(exc)))

        groups: dict[tuple[str, str, float, float, float], list[Path]] = {}
        maps: dict[tuple[str, str, float, float, float], Path] = {}
        for path, map_path, source, x, y, yaw in parsed:
            key = (source, str(map_path), self._canonical(x), self._canonical(y), self._canonical(yaw))
            if source == "case":
                key = (*key, str(path))
            groups.setdefault(key, []).append(path)
            maps[key] = map_path
        candidates: list[TaskStartCandidate] = []
        for key in sorted(groups):
            paths = tuple(sorted(groups[key], key=str))
            fingerprint = self._fingerprint(paths)
            source = key[0]
            opaque = hashlib.sha256((source + "|" + repr(key) + "|" + fingerprint).encode("utf-8")).hexdigest()[:24]
            label = (paths[0].stem.replace("_", " · ") if source == "case" else f"车端常用任务起点（{len(paths)} 个样本）")
            candidates.append(TaskStartCandidate(
                id=opaque,
                source=source, label=label,
                map_path=maps[key], x=key[2], y=key[3], yaw=key[4],
                member_count=len(paths), member_paths=paths, fingerprint=fingerprint,
            ))
        return TaskStartSnapshot(tuple(candidates), tuple(issues))

    def _sample_paths(self, root_path: Path, *, is_multi: bool) -> tuple[tuple[Path, ...], bool]:
        """Return a deterministic, bounded sample without enumerating the whole tree."""
        paths: list[Path] = []
        for directory, dirnames, filenames in os.walk(root_path):
            dirnames[:] = sorted(name for name in dirnames if not name.startswith("."))
            for filename in sorted(filenames):
                if filename.startswith(".") or not filename.endswith(".json"):
                    continue
                path = Path(directory, filename)
                if is_multi and path.stem.endswith("_r"):
                    continue
                if not path.is_file():
                    continue
                paths.append(path)
                if len(paths) > self.MAX_FILES_PER_ROOT:
                    return tuple(paths[:-1]), True
        return tuple(paths), False

    def resolve(self, source: str, candidate_id: str) -> TaskStartCandidate:
        if source not in {"case", "robot_task"} or not isinstance(candidate_id, str):
            raise TaskStartCatalogError("起点来源无效")
        snapshot = self.scan()
        candidate = next((item for item in snapshot.candidates if item.id == candidate_id), None)
        if candidate is None:
            raise TaskStartCatalogError("任务文件已变更，请重新选择起点")
        if self._fingerprint(candidate.member_paths) != candidate.fingerprint:
            raise TaskStartCatalogError("任务文件已变更，请重新选择起点")
        return candidate

    @staticmethod
    def _canonical(value: float) -> float:
        return 0.0 if value == 0 else round(value, 9)

    @staticmethod
    def _fingerprint(paths: tuple[Path, ...]) -> str:
        digest = hashlib.sha256()
        for path in paths:
            try:
                payload = path.read_bytes()
            except OSError as exc:
                raise TaskStartCatalogError("任务文件已变更，请重新选择起点") from exc
            digest.update(str(path).encode("utf-8"))
            digest.update(b"\0")
            digest.update(payload)
            digest.update(b"\0")
        return digest.hexdigest()

    @staticmethod
    def _parse(path: Path, *, is_multi: bool) -> tuple[Path, float, float, float]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except UnicodeDecodeError as exc:
            raise TaskStartCatalogError("任务文件不是 UTF-8 编码") from exc
        if not isinstance(payload, dict):
            raise TaskStartCatalogError("任务 JSON 根节点无效")
        task = payload
        if not is_multi:
            subtasks = payload.get("subtasks")
            if not isinstance(subtasks, list) or not subtasks or not isinstance(subtasks[0], dict):
                raise TaskStartCatalogError("任务缺少首个子任务")
            task = subtasks[0]
        map_value = task.get("map_url")
        points = task.get("waypoints")
        if not isinstance(map_value, str) or not map_value or not isinstance(points, list) or not points or not isinstance(points[0], dict):
            raise TaskStartCatalogError("任务缺少有效地图或首个路点")
        pose = points[0].get("pose")
        if not isinstance(pose, dict) or not isinstance(pose.get("position"), dict) or not isinstance(pose.get("orientation"), dict):
            raise TaskStartCatalogError("首个路点位姿无效")
        position, orientation = pose["position"], pose["orientation"]
        try:
            x, y = float(position["x"]), float(position["y"])
            z, w = float(orientation["z"]), float(orientation["w"])
        except (KeyError, TypeError, ValueError) as exc:
            raise TaskStartCatalogError("首个路点坐标无效") from exc
        if not all(math.isfinite(value) for value in (x, y, z, w)) or math.hypot(z, w) <= 1e-9:
            raise TaskStartCatalogError("首个路点坐标或朝向无效")
        yaw = math.atan2(2.0 * z * w, 1.0 - 2.0 * z * z)
        if not math.isfinite(yaw):
            raise TaskStartCatalogError("首个路点朝向无效")
        return Path(map_value).resolve(), x, y, yaw
