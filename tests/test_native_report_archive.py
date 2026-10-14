from __future__ import annotations

import json
from pathlib import Path

import pytest

from autodrive_console.native_report_archive import (
    NativeReportArchive,
    NativeReportNotFound,
)
from autodrive_console.map_assets import CachedMapAsset
from autodrive_console.models import AttemptResult, RunRecord, TaskParameters, TestCase as RobotTestCase
from autodrive_console.trajectory_render import _png_gray, freeze_map_png


_HTML_NAME = "报告_20260928_100001_测试_123456789abc.html"


def _write_historic_report(
    root: Path,
    *,
    frozen_map: bool,
    samples: int = 3,
) -> Path:
    reports = root / "reports"
    reports.mkdir()
    (reports / _HTML_NAME).write_text("legacy HTML must never be parsed", encoding="utf-8")
    trajectory_dir = reports / "run_123456789abc_trajectory"
    trajectory_dir.mkdir()
    points = [
        {"x": float(index), "y": float(index + 1), "timestamp_ns": index + 1}
        for index in range(samples)
    ]
    document = {
        "segments": [
            {
                "map_id": "map_01",
                "map_label": "首层大厅",
                "route_name": "去程",
                "points": points,
            }
        ],
        "ideal_routes": {"map_01": [{"name": "去程", "points": [{"x": 0.0, "y": 1.0}, {"x": 2.0, "y": 3.0}]}]},
        "virtual_walls": {"map_01": [{"points": [{"x": 0.0, "y": 0.0}, {"x": 0.0, "y": 3.0}], "coordinate_mode": "world"}]},
        "frozen_maps": [
            {
                "map_id": "map_01",
                "filename": "T-001_map_01.map.png",
                "label": "首层大厅",
                "resolution_m": 0.05,
                "width_cells": 2,
                "height_cells": 2,
                "origin_x_m": -1.0,
                "origin_y_m": -2.0,
            }
        ]
        if frozen_map
        else [],
    }
    (trajectory_dir / "T-001.json").write_text(
        json.dumps(document, ensure_ascii=False), encoding="utf-8"
    )
    if frozen_map:
        (trajectory_dir / "T-001_map_01.map.png").write_bytes(
            _png_gray(2, 2, b"\xff\x00\xff\x00")
        )
    return reports


def _archive_fixture(tmp_path: Path, *, frozen_map: bool = True, samples: int = 3):
    reports = _write_historic_report(tmp_path, frozen_map=frozen_map, samples=samples)
    archive = NativeReportArchive(reports)
    assert archive.archive_historic_report(_HTML_NAME) is True
    summary = archive.summary_for_filename(_HTML_NAME)
    assert summary is not None
    return archive, summary


def test_archives_only_verified_trajectory_json_and_existing_frozen_png(tmp_path: Path):
    reports = _write_historic_report(tmp_path, frozen_map=True)

    archive = NativeReportArchive(reports)

    assert archive.historic_filenames() == [_HTML_NAME]
    assert archive.archive_historic_report(_HTML_NAME) is True
    native = archive.summary_for_filename(_HTML_NAME)
    assert native is not None
    assert native["schema_version"] == 1
    assert native["report_id"].startswith("rpt_")
    assert list((reports / ".native-reports").glob("*.png"))
    assert "legacy HTML" not in json.dumps(native, ensure_ascii=False)
    assert archive.historic_filenames() == []


def test_historic_json_without_frozen_png_exposes_unavailable_trajectory(tmp_path: Path):
    archive, summary = _archive_fixture(tmp_path, frozen_map=False)

    page = archive.detail_page(summary["report_id"], None, 50)

    assert page["items"][0]["trajectory_refs"][0]["status"] == "unavailable"


def test_pages_samples_and_hide_internal_names(tmp_path: Path):
    archive, summary = _archive_fixture(tmp_path, samples=3)

    page = archive.detail_page(summary["report_id"], None, 1)
    reference = page["items"][0]["trajectory_refs"][0]
    details = archive.trajectory(summary["report_id"], reference["trajectory_id"])
    samples = archive.sample_page(
        summary["report_id"],
        reference["trajectory_id"],
        details["samples_next_cursor"],
        1,
    )

    assert page["next_cursor"] is None
    assert [sample["sample_index"] for sample in samples["samples"]] == [0]
    assert archive.trajectory_map_png(
        summary["report_id"], reference["trajectory_id"]
    ).startswith(b"\x89PNG\r\n\x1a\n")
    assert "run_" not in json.dumps([page, details, samples], ensure_ascii=False)
    assert "T-001" not in json.dumps([page, details, samples], ensure_ascii=False)


def test_valid_missing_and_cross_report_identifiers_are_not_found(tmp_path: Path):
    archive, summary = _archive_fixture(tmp_path)

    with pytest.raises(NativeReportNotFound):
        archive.trajectory(summary["report_id"], "traj_other_report")


def test_rejects_tampered_sidecar_before_it_can_expose_a_local_path(tmp_path: Path):
    archive, summary = _archive_fixture(tmp_path)
    sidecar = tmp_path / "reports" / ".native-reports" / f"{summary['report_id']}.json"
    document = json.loads(sidecar.read_text(encoding="utf-8"))
    document["items"][0]["summary"] = "/opt/ry/private/trajectory.json"
    sidecar.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    assert archive.summary_for_filename(_HTML_NAME) is None
    with pytest.raises(NativeReportNotFound):
        archive.detail_page(summary["report_id"], None, 50)


def test_filename_delete_removes_only_backend_owned_native_payload(tmp_path: Path):
    archive, _summary = _archive_fixture(tmp_path)

    archive.delete_for_filename(_HTML_NAME)

    assert archive.summary_for_filename(_HTML_NAME) is None
    assert not list((tmp_path / "reports" / ".native-reports").glob("*"))
    assert (tmp_path / "reports" / "run_123456789abc_trajectory" / "T-001.json").is_file()


def test_freezes_verified_pgm_as_a_bounded_png_with_map_metadata(tmp_path: Path):
    source = tmp_path / "map.pgm"
    source.write_bytes(b"P5\n2 2\n255\n\xff\x00\xff\x00")
    asset = CachedMapAsset(
        "map_01", "首层大厅", "", "", str(source), 0.05, [-1.0, -2.0, 0.0], 2, 2
    )
    target = tmp_path / "T-001_map_01.map.png"

    metadata = freeze_map_png(asset, target, maximum_bytes=1024)

    assert target.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert metadata == {
        "map_id": "map_01",
        "filename": "T-001_map_01.map.png",
        "label": "首层大厅",
        "resolution_m": 0.05,
        "width_cells": 2,
        "height_cells": 2,
        "origin_x_m": -1.0,
        "origin_y_m": -2.0,
    }


def test_archives_new_test_report_from_its_saved_structured_trajectory(tmp_path: Path):
    reports = _write_historic_report(tmp_path, frozen_map=True)
    source = reports / "run_123456789abc_trajectory" / "T-001.json"
    trajectory = json.loads(source.read_text(encoding="utf-8"))
    trajectory["file"] = str(source)
    case = RobotTestCase(
        "case_01", "case_01.json", "测试", TaskParameters("园区", 1, 1, 1, 1), "unused.json"
    )
    run = RunRecord(
        "123456789abc", case, 1, 0, status="completed", started_at="2026-09-28T10:00:00+08:00"
    )
    run.attempts.append(
        AttemptResult(1, "passed", "未经控制的原始服务内容", 3.5, run.started_at, trajectory)
    )
    archive = NativeReportArchive(reports)

    summary = archive.archive_test_report(html_filename=_HTML_NAME, run=run)

    assert summary["kind"] == "test"
    assert summary["summary"] == {
        "total": 1,
        "passed": 1,
        "failed": 0,
        "blocked": 0,
        "pass_rate": 100.0,
    }
    assert archive.detail_page(summary["report_id"], None, 50)["items"][0]["summary"] != "未经控制的原始服务内容"
