"""Write self-contained evidence reports for deployment acceptance plans."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path

from .acceptance_plan import AcceptanceCriteria, AcceptancePlan, evaluate_conclusion


@dataclass(frozen=True)
class ReportReference:
    html_filename: str
    csv_filename: str


class AcceptanceReportWriter:
    def __init__(self, report_dir: Path) -> None:
        self.report_dir = Path(report_dir)

    def write(self, plan: AcceptancePlan) -> ReportReference:
        self.report_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        stem = f"acceptance_{plan.plan_id}_{timestamp}"
        html_filename, csv_filename = f"{stem}.html", f"{stem}.csv"
        result = evaluate_conclusion(plan, AcceptanceCriteria.from_dict(plan.criteria_snapshot))
        with (self.report_dir / csv_filename).open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Plan_ID", "Filename", "Community", "Building", "Unit", "Floor", "Door", "Status", "Message", "SHA256", "Started_At", "Finished_At", "Duration_s"])
            for item in plan.items:
                p = item.parameters
                writer.writerow([plan.plan_id, item.filename, p.community, p.building, p.unit, p.floor, p.door, item.status, item.message, item.sha256, item.started_at, item.finished_at, item.duration_s])
        rows = "".join(
            "<tr>"
            f"<td>{escape(item.filename)}</td><td>{escape(item.status)}</td>"
            f"<td>{escape(item.message)}</td><td>{escape(item.sha256)}</td>"
            "</tr>"
            for item in plan.items
        )
        coverage = result.coverage.to_dict()
        summary = "".join(
            f"<li>{escape(level)}：物理楼宇单元 {values['physical_building']:.1f}% · 楼层 {values['floor']:.1f}% · 户 {values['door']:.1f}%</li>"
            for level, values in coverage.items()
        )
        (self.report_dir / html_filename).write_text(
            "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
            f"<title>部署验收报告 {escape(plan.plan_id)}</title>"
            "<style>body{font:14px/1.6 sans-serif;margin:32px;color:#13233b}table{border-collapse:collapse;width:100%}th,td{padding:8px;border:1px solid #ccd6e0;text-align:left;vertical-align:top}th{background:#eef4f8}code{word-break:break-all}</style>"
            "</head><body>"
            f"<h1>部署验收报告</h1><p>计划：<code>{escape(plan.plan_id)}</code>；范围：{escape(plan.community)}"
            f"{f' · {plan.building}栋{plan.unit}单元' if plan.building is not None and plan.unit is not None else (f' · {plan.building}栋' if plan.building is not None else '')}；随机种子：{plan.random_seed}</p>"
            f"<h2>结论：{escape(result.status or '未完成')}</h2><p>{escape(result.message)}</p>"
            f"<p>通过率：{result.pass_rate:.1f}%；失败任务：{result.failed_tasks}；人工干预：{plan.manual_interventions}</p>"
            f"<h2>覆盖</h2><ul>{summary}</ul>"
            "<h2>冻结任务与结果</h2><table><thead><tr><th>任务</th><th>结果</th><th>信息</th><th>SHA-256</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></body></html>",
            encoding="utf-8",
        )
        return ReportReference(html_filename, csv_filename)
