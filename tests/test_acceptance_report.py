from __future__ import annotations

from autodrive_console.acceptance_plan import AcceptanceCriteria, AcceptancePlan, AcceptancePlanItem
from autodrive_console.acceptance_report import AcceptanceReportWriter
from autodrive_console.models import MultiDestination, MultiTaskRequest, TaskParameters


def test_multi_r6b_report_includes_chain_and_delivery_evidence(tmp_path):
    request = MultiTaskRequest(
        "数创大厦",
        False,
        True,
        (
            MultiDestination("5", "1", "5", "501", 1, "delivery-501"),
            MultiDestination("5", "1", "3", "301", 2, "delivery-301"),
        ),
        "task-001",
    )
    item = AcceptancePlanItem(
        filename="数创大厦_5_1_multi_task-001.json",
        source_path="/tmp/floor.json",
        parameters=TaskParameters("数创大厦", 5, 1, 5, 501, "multi_r6b"),
        task_group_name=None,
        warnings=[],
        sha256="0" * 64,
        status="passed",
        multi_request=request,
        delivery_evidence=[
            {"delivery_code": "delivery-501", "status": "passed", "message": "收到配送码事件"},
            {"delivery_code": "delivery-301", "status": "passed", "message": "收到配送码事件"},
        ],
    )
    plan = AcceptancePlan(
        plan_id="123456789abc",
        created_at="2026-09-22T10:00:00+08:00",
        updated_at="2026-09-22T10:01:00+08:00",
        scope_type="building",
        community="数创大厦",
        building=5,
        unit=1,
        mode="full",
        random_seed=1,
        task_pool_size=1,
        items=[item],
        criteria_snapshot=AcceptanceCriteria.empty().to_dict(),
        execution_mode="multi_r6b",
        multi_options={"out_eguard": False, "return_origin": True, "chain_mode": "chain", "chains": [{"task_uuid": "task-001", "destinations": [entry.to_dict() for entry in request.destinations]}]},
        status="completed",
    )

    reference = AcceptanceReportWriter(tmp_path).write(plan)
    html = (tmp_path / reference.html_filename).read_text(encoding="utf-8")
    csv = (tmp_path / reference.csv_filename).read_text(encoding="utf-8-sig")

    assert "R6B 多点配送" in html
    assert "delivery-501" in html and "上舱自动" in html
    assert "delivery-301" in csv and "下舱自动" in csv
