from __future__ import annotations

import json

from autodrive_console.models import AttemptResult, RunRecord, TaskParameters, TestCase as RunTestCase
from autodrive_console.run_checkpoint import RunCheckpointStore


def _run() -> RunRecord:
    case = RunTestCase(
        "case-1",
        "case-1.json",
        "单轮测试",
        TaskParameters("园区", 1, 1, 2, 201),
        "/not-used-during-recovery.json",
    )
    return RunRecord(
        "123456789abc",
        case,
        10,
        3,
        status="running",
        started_at="2026-10-09T18:00:00+08:00",
        attempts=[AttemptResult(1, "passed", "已完成", 1.2, "2026-10-09T18:00:01+08:00")],
        active_attempt=2,
    )


def test_checkpoint_round_trip_keeps_only_report_scoped_evidence(tmp_path):
    reports = tmp_path / "reports"
    evidence = reports / "run_123456789abc_trajectory"
    evidence.mkdir(parents=True)
    trajectory = evidence / "T-001.json"
    trajectory.write_text("{}", encoding="utf-8")
    svg = evidence / "T-001_map.svg"
    svg.write_text("<svg/>", encoding="utf-8")
    run = _run()
    run.attempts[0].trajectory = {
        "file": str(trajectory),
        "visualizations": [{"file": str(svg), "map_id": "map", "label": "大厅"}],
    }

    store = RunCheckpointStore(reports)
    path = store.save(run, attempt_in_progress=True)

    assert path == reports / ".run-checkpoints" / "123456789abc.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema"] == 1
    assert payload["attempt_in_progress"] is True
    assert "/not-used-during-recovery.json" not in path.read_text(encoding="utf-8")
    restored = store.load_recoverable()
    assert len(restored) == 1
    assert restored[0].run.id == run.id
    assert restored[0].run.attempts[0].trajectory["file"] == str(trajectory.resolve())
    assert restored[0].run.attempts[0].trajectory["visualizations"][0]["file"] == str(svg.resolve())


def test_checkpoint_rejects_outside_report_evidence(tmp_path):
    reports = tmp_path / "reports"
    run = _run()
    run.attempts[0].trajectory = {"file": str(tmp_path / "outside.json")}

    store = RunCheckpointStore(reports)

    try:
        store.save(run, attempt_in_progress=False)
    except ValueError as exc:
        assert "报告目录" in str(exc)
    else:
        raise AssertionError("report-external evidence must be rejected")


def test_interrupted_summary_keeps_power_loss_unknown_out_of_pass_rate():
    run = _run()
    run.status = "interrupted"
    run.attempts.extend([
        AttemptResult(2, "failed", "服务失败", 1.0, "2026-10-09T18:00:02+08:00"),
        AttemptResult(3, "unknown_after_power_loss", "意外断电，结果未知", 0.0, "2026-10-09T18:00:03+08:00"),
    ])

    summary = run.to_dict()["summary"]

    assert summary == {
        "completed": 3,
        "passed": 1,
        "failed": 1,
        "cancelled": 0,
        "unknown": 1,
        "passRate": 50.0,
    }
