from __future__ import annotations

import json
from pathlib import Path

import pytest

import web_console
from autodrive_console.acceptance_catalog import AcceptanceTaskCatalog
from autodrive_console.acceptance_plan import (
    AcceptanceCriteria,
    AcceptancePlanFactory,
    AcceptancePlanStore,
    evaluate_conclusion,
)
from autodrive_console.acceptance_orchestrator import (
    AcceptanceConflict,
    AcceptanceOrchestrator,
)
from autodrive_console.acceptance_report import AcceptanceReportWriter
from autodrive_console.models import TaskParameters


def write_task(path: Path, payload: dict | None = None) -> None:
    path.write_text(
        json.dumps(payload or {"subtasks": [{}], "task_group_name": "示例"}),
        encoding="utf-8",
    )


def test_catalog_parses_community_from_right_and_ignores_nonformal_files(tmp_path):
    write_task(tmp_path / "成都_龙湖_6_1_3_303.json")
    write_task(tmp_path / "成都_龙湖_6_1_3_304_backup.json")
    write_task(tmp_path / ".hidden_6_1_3_305.json")
    write_task(tmp_path / "成都_龙湖_6_1_3_306_bak_copy.json")

    snapshot = AcceptanceTaskCatalog(tmp_path).scan()

    assert [task.filename for task in snapshot.valid_tasks] == ["成都_龙湖_6_1_3_303.json"]
    task = snapshot.valid_tasks[0]
    assert task.parameters == TaskParameters("成都_龙湖", 6, 1, 3, 303)
    assert task.sha256 and len(task.sha256) == 64


def test_catalog_keeps_invalid_files_as_issues_and_uses_filename_for_scope(tmp_path):
    write_task(tmp_path / "云_栖_6_1_3_301.json", {"subtasks": [{}], "task_group_name": "错误命名"})
    write_task(tmp_path / "云_栖_7_1_3_302.json", {"subtasks": []})
    (tmp_path / "云_栖_8_x_3_303.json").write_text("{}", encoding="utf-8")

    snapshot = AcceptanceTaskCatalog(tmp_path).scan()

    assert [item.parameters.building for item in snapshot.select("building", "云_栖", 6, 1)] == [6]
    assert snapshot.valid_tasks[0].warnings
    assert {issue.filename for issue in snapshot.issues} == {
        "云_栖_7_1_3_302.json",
        "云_栖_8_x_3_303.json",
    }


def test_catalog_scope_validation_and_order_are_stable(tmp_path):
    write_task(tmp_path / "园区_A_7_2_3_703.json")
    write_task(tmp_path / "园区_A_6_1_2_602.json")
    write_task(tmp_path / "园区_A_6_1_1_601.json")
    (tmp_path / "not-a-task.txt").write_text("ignored", encoding="utf-8")
    (tmp_path / "园区_A_8_1_1_801.json~").write_text("ignored", encoding="utf-8")

    snapshot = AcceptanceTaskCatalog(tmp_path).scan()

    assert [task.filename for task in snapshot.valid_tasks] == [
        "园区_A_6_1_1_601.json",
        "园区_A_6_1_2_602.json",
        "园区_A_7_2_3_703.json",
    ]
    assert snapshot.communities() == ["园区_A"]
    assert snapshot.physical_buildings("园区_A") == [(6, 1), (7, 2)]
    with pytest.raises(ValueError, match="小区"):
        snapshot.select("community", "不存在")
    with pytest.raises(ValueError, match="物理楼宇单元"):
        snapshot.select("building", "园区_A", 8, 1)
    with pytest.raises(ValueError, match="范围"):
        snapshot.select("floor", "园区_A")


def test_catalog_treats_connected_units_as_distinct_physical_buildings(tmp_path):
    write_task(tmp_path / "中铁阅山湖D区_5_1_28_2803.json")
    write_task(tmp_path / "中铁阅山湖D区_5_2_3_301.json")

    snapshot = AcceptanceTaskCatalog(tmp_path).scan()

    assert snapshot.physical_buildings("中铁阅山湖D区") == [(5, 1), (5, 2)]
    assert [item.filename for item in snapshot.select("building", "中铁阅山湖D区", 5, 2)] == ["中铁阅山湖D区_5_2_3_301.json"]
    with pytest.raises(ValueError, match="物理楼宇单元"):
        snapshot.select("building", "中铁阅山湖D区", 5, None)


def catalog_snapshot_for_plan(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    for building, unit, floor, door in (
        (1, 1, 1, 101),
        (2, 1, 2, 201),
        (3, 2, 3, 301),
        (6, 1, 1, 601),
    ):
        write_task(tmp_path / f"园区_A_{building}_{unit}_{floor}_{door}.json")
    return AcceptanceTaskCatalog(tmp_path).scan()


def test_sample_plan_is_seeded_frozen_and_covers_physical_buildings_before_duplicates(tmp_path):
    snapshot = catalog_snapshot_for_plan(tmp_path)
    criteria = AcceptanceCriteria.empty()
    first = AcceptancePlanFactory.create(
        snapshot,
        scope_type="community",
        community="园区_A",
        building=None,
        mode="sample",
        sample_size=3,
        random_seed=41,
        criteria=criteria,
    )
    second = AcceptancePlanFactory.create(
        snapshot,
        scope_type="community",
        community="园区_A",
        building=None,
        mode="sample",
        sample_size=3,
        random_seed=41,
        criteria=criteria,
    )

    assert [item.filename for item in first.items] == [item.filename for item in second.items]
    assert len({(item.parameters.building, item.parameters.unit) for item in first.items}) == 3
    assert all(item.sha256 for item in first.items)
    assert first.criteria_snapshot == criteria.to_dict()


def test_sample_plan_counts_physical_buildings_and_hides_seed_from_public_payload(tmp_path):
    write_task(tmp_path / "中铁阅山湖D区_5_1_28_2803.json")
    write_task(tmp_path / "中铁阅山湖D区_5_2_3_301.json")
    write_task(tmp_path / "中铁阅山湖D区_6_1_8_801.json")
    plan = AcceptancePlanFactory.create(
        AcceptanceTaskCatalog(tmp_path).scan(),
        scope_type="community", community="中铁阅山湖D区", building=None, unit=None,
        mode="sample", sample_size=2, random_seed=1, criteria=AcceptanceCriteria.empty(),
    )

    public = plan.to_public_dict()

    assert public["selection_summary"]["physical_buildings"] == 2
    assert "random_seed" not in public
    assert not any("不足以覆盖全部楼层" in warning for warning in public["warnings"])


def test_completed_sample_is_passed_only_when_every_selected_task_passes(tmp_path):
    snapshot = catalog_snapshot_for_plan(tmp_path)
    plan = AcceptancePlanFactory.create(
        snapshot,
        scope_type="community",
        community="园区_A",
        building=None,
        mode="sample",
        sample_size=4,
        random_seed=7,
        criteria=AcceptanceCriteria.empty(),
    )
    for item in plan.items:
        item.status = "passed"
    plan.status = "completed"

    result = evaluate_conclusion(plan, AcceptanceCriteria.empty())

    assert result.status == "sample_pass"
    assert result.pass_rate == 100
    assert "本次抽样通过" in result.message
    assert "不代表全小区全量验收" in result.message
    plan.items[0].status = "failed"
    result = evaluate_conclusion(plan, AcceptanceCriteria.empty())
    assert result.status == "sample_fail"
    assert result.pass_rate == 75
    assert "本次抽样不通过" in result.message


def test_completed_full_plan_uses_the_same_all_tasks_must_pass_rule(tmp_path):
    plan = AcceptancePlanFactory.create(
        catalog_snapshot_for_plan(tmp_path),
        scope_type="community", community="园区_A", building=None,
        mode="full", sample_size=None, random_seed=7, criteria=AcceptanceCriteria.empty(),
    )
    for item in plan.items:
        item.status = "passed"
    plan.status = "completed"

    assert evaluate_conclusion(plan, AcceptanceCriteria.empty()).status == "full_pass"


def test_plan_store_preserves_frozen_plan_and_marks_inflight_run_interrupted(tmp_path):
    snapshot = catalog_snapshot_for_plan(tmp_path / "tasks")
    plan = AcceptancePlanFactory.create(
        snapshot,
        scope_type="building",
        community="园区_A",
        building=6,
        unit=1,
        mode="full",
        sample_size=None,
        random_seed=9,
        criteria=AcceptanceCriteria.empty(),
    )
    plan.status = "running"
    plan.current_index = 0
    store = AcceptancePlanStore(tmp_path / "state")
    store.save(plan)

    recovered = AcceptancePlanStore(tmp_path / "state").mark_interrupted_runs()[0]

    assert recovered.status == "interrupted"
    assert recovered.items[0].status == "unknown_after_restart"
    assert recovered.random_seed == 9
    assert not list((tmp_path / "state").rglob("*.tmp"))


class _NoopRunManager:
    def start_sequence(self, *_args, **_kwargs):
        raise AssertionError("源文件变化时不得开始执行")


def make_orchestrator(task_dir: Path, state_dir: Path, manager=None) -> AcceptanceOrchestrator:
    return AcceptanceOrchestrator(
        catalog=AcceptanceTaskCatalog(task_dir),
        plan_store=AcceptancePlanStore(state_dir / "acceptance"),
        run_manager=manager or _NoopRunManager(),
        report_dir=state_dir / "reports",
    )


def test_orchestrator_blocks_changed_source_before_start(tmp_path):
    task_dir = tmp_path / "origin_tasks"
    snapshot = catalog_snapshot_for_plan(task_dir)
    orchestrator = make_orchestrator(task_dir, tmp_path / "state")
    plan = orchestrator.create_plan({
        "scope_type": "building",
        "community": "园区_A",
        "building": 6,
        "unit": 1,
        "mode": "full",
    })
    changed = task_dir / plan["items"][0]["filename"]
    changed.write_text(json.dumps({"subtasks": [{"changed": True}]}), encoding="utf-8")

    with pytest.raises(AcceptanceConflict, match="正式任务文件已变化"):
        orchestrator.start(plan["plan_id"])
    assert orchestrator.current()["status"] == "blocked"


def test_orchestrator_exposes_physical_buildings_and_rejects_partial_scope(tmp_path):
    task_dir = tmp_path / "origin_tasks"
    task_dir.mkdir()
    write_task(task_dir / "中铁阅山湖D区_5_1_28_2803.json")
    write_task(task_dir / "中铁阅山湖D区_5_2_3_301.json")
    orchestrator = make_orchestrator(task_dir, tmp_path / "state")

    catalog = orchestrator.catalog_summary()

    assert catalog["communities"][0]["physical_buildings"] == [
        {"building": 5, "unit": 1, "label": "5栋1单元"},
        {"building": 5, "unit": 2, "label": "5栋2单元"},
    ]
    with pytest.raises(ValueError, match="栋号和单元"):
        orchestrator.create_plan({
            "scope_type": "building", "community": "中铁阅山湖D区", "building": 5,
            "mode": "full",
        })


def test_orchestrator_marks_inflight_plan_interrupted_when_recreated(tmp_path):
    task_dir = tmp_path / "origin_tasks"
    catalog_snapshot_for_plan(task_dir)
    state_dir = tmp_path / "state"
    first = make_orchestrator(task_dir, state_dir)
    plan = first.create_plan({"scope_type": "community", "community": "园区_A", "mode": "full"})
    stored = AcceptancePlanStore(state_dir / "acceptance").load_current()
    stored.status = "running"
    stored.current_index = 0
    AcceptancePlanStore(state_dir / "acceptance").save(stored)

    restarted = make_orchestrator(task_dir, state_dir)

    assert restarted.current()["status"] == "interrupted"
    assert restarted.current()["items"][0]["status"] == "unknown_after_restart"
    assert restarted.current()["plan_id"] == plan["plan_id"]


def test_acceptance_report_escapes_task_content_and_records_full_pass(tmp_path):
    snapshot = catalog_snapshot_for_plan(tmp_path / "tasks")
    plan = AcceptancePlanFactory.create(
        snapshot,
        scope_type="community",
        community="园区_A",
        building=None,
        mode="full",
        sample_size=None,
        random_seed=10,
        criteria=AcceptanceCriteria.empty(),
    )
    for item in plan.items:
        item.status = "passed"
        item.message = "<script>alert(1)</script>"
    plan.status = "completed"

    report = AcceptanceReportWriter(tmp_path / "reports").write(plan)

    text = (tmp_path / "reports" / report.html_filename).read_text(encoding="utf-8")
    assert report.html_filename.startswith(f"acceptance_{plan.plan_id}_")
    assert "full_pass" in text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text


def test_console_registers_desktop_acceptance_route_without_mobile_redirect():
    source = Path("web_console.py").read_text(encoding="utf-8")

    assert 'path == "/acceptance-test.html"' in source
    assert 'path.startswith("/api/acceptance/")' in source
    assert "acceptance-test.html" not in web_console.MOBILE_PAGE_NAMES
