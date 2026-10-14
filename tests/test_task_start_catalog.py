from __future__ import annotations

import json
from pathlib import Path

import pytest

from autodrive_console.task_start_catalog import TaskStartCatalog, TaskStartCatalogError


MAP_PATH = "/opt/ry/config/localization/config/demo.yaml"


def _waypoint(x: float = -6.0, y: float = 5.0) -> dict:
    return {
        "pose": {
            "position": {"x": x, "y": y},
            "orientation": {"z": 0.0, "w": 1.0},
        }
    }


def _single_task(x: float = -6.0, y: float = 5.0) -> dict:
    return {"subtasks": [{"map_url": MAP_PATH, "waypoints": [_waypoint(x, y)]}]}


def _multi_task(x: float = -6.0, y: float = 5.0) -> dict:
    return {"map_url": MAP_PATH, "waypoints": [_waypoint(x, y)]}


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_scan_groups_matching_forward_task_starts_and_excludes_return_fragments(tmp_path: Path) -> None:
    single_root = tmp_path / "origin_tasks"
    multi_root = tmp_path / "multi_tasks"
    _write(single_root / "demo_1_1_1_101.json", _single_task())
    _write(multi_root / "demo" / "floor" / "1_1_1_101.json", _multi_task())
    _write(multi_root / "demo" / "floor" / "1_1_1_101_r.json", _multi_task(99.0, 99.0))
    _write(multi_root / "demo" / "floor" / "bad.json", {"map_url": MAP_PATH, "waypoints": []})

    snapshot = TaskStartCatalog(single_root, multi_root).scan()

    starts = [item for item in snapshot.candidates if item.source == "robot_task"]
    assert [(item.member_count, item.x, item.y) for item in starts] == [(2, -6.0, 5.0)]
    assert snapshot.issues


def test_scan_rejects_nonfinite_and_zero_norm_quaternion(tmp_path: Path) -> None:
    single_root = tmp_path / "origin_tasks"
    multi_root = tmp_path / "multi_tasks"
    malformed = _single_task()
    malformed["subtasks"][0]["waypoints"][0]["pose"]["position"]["x"] = float("nan")
    _write(single_root / "demo_1_1_1_101.json", malformed)
    zero_quaternion = _multi_task()
    zero_quaternion["waypoints"][0]["pose"]["orientation"] = {"z": 0.0, "w": 0.0}
    _write(multi_root / "demo" / "floor" / "1_1_1_101.json", zero_quaternion)

    snapshot = TaskStartCatalog(single_root, multi_root).scan()

    assert snapshot.candidates == ()
    assert len(snapshot.issues) == 2


def test_resolve_rejects_candidate_when_representative_file_changed(tmp_path: Path) -> None:
    single_root = tmp_path / "origin_tasks"
    multi_root = tmp_path / "multi_tasks"
    path = single_root / "demo_1_1_1_101.json"
    _write(path, _single_task())
    catalog = TaskStartCatalog(single_root, multi_root)
    candidate = catalog.scan().candidates[0]
    path.write_text("{}", encoding="utf-8")

    with pytest.raises(TaskStartCatalogError, match="任务文件已变更"):
        catalog.resolve(candidate.source, candidate.id)


def test_case_starts_remain_individually_selectable_while_robot_starts_are_deduplicated(tmp_path: Path) -> None:
    case_root, single_root, multi_root = tmp_path / "cases", tmp_path / "origin", tmp_path / "multi"
    _write(case_root / "demo_1_1_1_101.json", _single_task())
    _write(case_root / "demo_1_1_1_102.json", _single_task())
    _write(single_root / "demo_1_1_1_101.json", _single_task())

    snapshot = TaskStartCatalog(single_root, multi_root, case_root).scan()

    assert len([item for item in snapshot.candidates if item.source == "case"]) == 2
    assert len([item for item in snapshot.candidates if item.source == "robot_task"]) == 1


def test_scan_uses_a_bounded_task_sample_for_large_robot_directories(tmp_path: Path) -> None:
    single_root, multi_root = tmp_path / "origin", tmp_path / "multi"
    for index in range(TaskStartCatalog.MAX_FILES_PER_ROOT + 2):
        _write(single_root / f"task_{index:03}.json", _single_task())

    snapshot = TaskStartCatalog(single_root, multi_root).scan()

    candidate = next(item for item in snapshot.candidates if item.source == "robot_task")
    assert candidate.member_count == TaskStartCatalog.MAX_FILES_PER_ROOT
    assert any("受限起点样本" in issue.message for issue in snapshot.issues)
