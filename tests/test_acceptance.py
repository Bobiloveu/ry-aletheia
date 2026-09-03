from __future__ import annotations

import json
from pathlib import Path

import pytest

from autodrive_console.acceptance_catalog import AcceptanceTaskCatalog
from autodrive_console.acceptance_plan import (
    AcceptanceCriteria,
    AcceptancePlanFactory,
    AcceptancePlanStore,
    evaluate_conclusion,
)
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

    assert [item.parameters.building for item in snapshot.select("building", "云_栖", 6)] == [6]
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
    assert snapshot.buildings("园区_A") == [6, 7]
    with pytest.raises(ValueError, match="小区"):
        snapshot.select("community", "不存在")
    with pytest.raises(ValueError, match="楼栋"):
        snapshot.select("building", "园区_A", 8)
    with pytest.raises(ValueError, match="范围"):
        snapshot.select("floor", "园区_A")


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


def test_sample_plan_is_seeded_frozen_and_covers_buildings_before_duplicates(tmp_path):
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
    assert len({item.parameters.building for item in first.items}) == 3
    assert all(item.sha256 for item in first.items)
    assert first.criteria_snapshot == criteria.to_dict()


def test_criteria_requires_all_thresholds_for_formal_pass(tmp_path):
    snapshot = catalog_snapshot_for_plan(tmp_path)
    plan = AcceptancePlanFactory.create(
        snapshot,
        scope_type="community",
        community="园区_A",
        building=None,
        mode="full",
        sample_size=None,
        random_seed=7,
        criteria=AcceptanceCriteria.empty(),
    )
    for item in plan.items:
        item.status = "passed"
    plan.status = "completed"

    assert evaluate_conclusion(plan, AcceptanceCriteria.empty()).status == "CONDITIONAL_PASS"
    criteria = AcceptanceCriteria(
        min_pass_rate=100,
        min_building_coverage=100,
        min_unit_coverage=100,
        min_floor_coverage=100,
        min_door_coverage=100,
        max_failed_tasks=0,
        max_manual_interventions=0,
    )
    assert evaluate_conclusion(plan, criteria).status == "PASS"
    plan.items[0].status = "failed"
    assert evaluate_conclusion(plan, criteria).status == "FAIL"


def test_plan_store_preserves_frozen_plan_and_marks_inflight_run_interrupted(tmp_path):
    snapshot = catalog_snapshot_for_plan(tmp_path / "tasks")
    plan = AcceptancePlanFactory.create(
        snapshot,
        scope_type="building",
        community="园区_A",
        building=6,
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
