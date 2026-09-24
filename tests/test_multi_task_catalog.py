from __future__ import annotations

import json
from pathlib import Path

from autodrive_console.multi_task_catalog import MultiTaskCatalog


def write_json(path: Path, payload: dict | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload or {"subtasks": [{}]}), encoding="utf-8")


def make_community(root: Path) -> Path:
    community = root / "数创大厦"
    for name in (
        "floor/5_1_n_n01.json",
        "floor/5_1_n_n01_r.json",
        "floor/5_1_10_1001.json",
        "floor/5_1_10_1001_r.json",
        "indoor/5_1.json",
        "indoor/5_1_r.json",
        "outdoor/5_1.json",
        "outdoor/5_1_r.json",
        "sub_outdoor_eguard.json",
        "sub_outdoor_eguard_r.json",
    ):
        write_json(community / name)
    return community


def make_floor_only_community(root: Path) -> Path:
    community = root / "数创大厦"
    for name in (
        "floor/1_1_2_201.json",
        "floor/1_1_2_201_r.json",
    ):
        write_json(community / name)
    return community


def test_floor_only_directory_is_available_and_uses_concrete_filename_values(tmp_path):
    make_floor_only_community(tmp_path)

    snapshot = MultiTaskCatalog(tmp_path).scan()

    status = snapshot.building_status("数创大厦", 1, 1)
    assert status.available is True
    assert status.issues == ()
    result = snapshot.validate_destination("数创大厦", 1, 1, "2", "201")
    assert result.available is True
    assert result.source_kind == "special"
    assert result.physical_floor == 2
    wrong_floor = snapshot.validate_destination("数创大厦", 1, 1, "3", "201")
    assert wrong_floor.available is False
    assert "2" in wrong_floor.reason


def test_scan_separates_templates_special_points_and_validates_destinations(tmp_path):
    make_community(tmp_path)

    snapshot = MultiTaskCatalog(tmp_path).scan()

    assert snapshot.communities() == ["数创大厦"]
    assert snapshot.physical_buildings("数创大厦") == [(5, 1)]
    assert [item.door_suffix for item in snapshot.templates("数创大厦", 5, 1)] == ["01"]
    assert [(item.physical_floor, item.door) for item in snapshot.special_points("数创大厦", 5, 1)] == [(10, 1001)]

    template_match = snapshot.validate_destination("数创大厦", 5, 1, "5", "501")
    assert template_match.available is True
    assert template_match.source_kind == "template"

    special_match = snapshot.validate_destination("数创大厦", 5, 1, "10", "1001")
    assert special_match.available is True
    assert special_match.source_kind == "special"
    assert special_match.physical_floor == 10


def test_missing_return_pair_marks_building_and_destination_unavailable(tmp_path):
    community = make_community(tmp_path)
    (community / "floor/5_1_n_n01_r.json").unlink()

    snapshot = MultiTaskCatalog(tmp_path).scan()

    status = snapshot.building_status("数创大厦", 5, 1)
    assert status.available is False
    assert any("返程" in issue for issue in status.issues)
    result = snapshot.validate_destination("数创大厦", 5, 1, "5", "501")
    assert result.available is False
    assert "返程" in result.reason


def test_scan_ignores_symlinked_task_file_outside_root(tmp_path):
    make_community(tmp_path)
    outside = tmp_path / "outside.json"
    write_json(outside)
    link = tmp_path / "数创大厦/floor/5_1_n_n02.json"
    link.symlink_to(outside)

    snapshot = MultiTaskCatalog(tmp_path).scan()

    assert [item.door_suffix for item in snapshot.templates("数创大厦", 5, 1)] == ["01"]
    assert any("越过多点任务根目录" in issue.message for issue in snapshot.issues)
