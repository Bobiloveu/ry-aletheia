"""Write self-contained evidence reports for deployment acceptance plans."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path

from .acceptance_plan import (
    AcceptanceCriteria,
    AcceptancePlan,
    evaluate_conclusion,
    public_execution_preflight,
)


_TRAJECTORY_DIR = re.compile(r"run_[0-9a-f]{12}_trajectory")


@dataclass(frozen=True)
class ReportReference:
    html_filename: str
    csv_filename: str
    asset_manifest_filename: str | None = None


def _local_time(value: object) -> str:
    if not value:
        return "—"
    raw = str(value)
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return raw


def _duration(value: object) -> str:
    try:
        seconds = max(0, round(float(value)))
    except (TypeError, ValueError):
        return "—"
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} 小时 {minutes} 分 {seconds} 秒"
    if minutes:
        return f"{minutes} 分 {seconds} 秒"
    return f"{seconds} 秒"


def _scope_text(plan: AcceptancePlan) -> str:
    if plan.building is not None and plan.unit is not None:
        return f"{plan.community} · {plan.building} 栋 {plan.unit} 单元"
    return f"{plan.community} · 整个小区"


def _item_status(status: str) -> tuple[str, str]:
    labels = {
        "passed": ("通过", "passed"),
        "failed": ("未通过", "failed"),
        "cancelled": ("已取消", "cancelled"),
        "planned": ("未执行", "planned"),
        "running": ("执行中", "running"),
    }
    return labels.get(status, (status or "未知", "unknown"))


class AcceptanceReportWriter:
    def __init__(self, report_dir: Path) -> None:
        self.report_dir = Path(report_dir)

    def _inline_trajectory_cards(self, plan: AcceptancePlan) -> tuple[str, list[str]]:
        """Embed only renderer-owned SVG files and record their directories."""
        report_root = self.report_dir.resolve()
        owned_directories: set[str] = set()
        cards: list[str] = []
        for index, item in enumerate(plan.items, start=1):
            visualizations = (item.trajectory or {}).get("visualizations", [])
            figures: list[str] = []
            for view in visualizations if isinstance(visualizations, list) else []:
                if not isinstance(view, dict) or not isinstance(view.get("file"), str):
                    continue
                target = Path(view["file"]).resolve()
                if (
                    not target.is_relative_to(report_root)
                    or target.suffix != ".svg"
                    or not target.is_file()
                    or target.is_symlink()
                    or not _TRAJECTORY_DIR.fullmatch(target.parent.name)
                ):
                    continue
                try:
                    svg = target.read_text(encoding="utf-8")
                except OSError:
                    continue
                owned_directories.add(target.parent.name)
                label = escape(str(view.get("label") or view.get("map_id") or "轨迹地图"))
                figures.append(f'<figure><figcaption>{label}</figcaption>{svg}</figure>')
            status_label, status_class = _item_status(item.status)
            warning = (item.trajectory or {}).get("integrity_warning")
            notice = f'<p class="notice">{escape(str(warning))}</p>' if warning else ""
            evidence = "".join(figures) or '<p class="notice">未采集到可验证的地图坐标轨迹；该项轨迹证据不完整。</p>'
            cards.append(
                '<section class="evidence-card">'
                f'<div class="evidence-heading"><h3>#{index:02d} {escape(item.filename)}</h3>'
                f'<span class="status-badge {status_class}">{status_label}</span></div>'
                f"{notice}{evidence}</section>"
            )
        return "".join(cards) or '<p class="notice">本次验收未进入轨迹采集阶段，因此没有轨迹证据。</p>', sorted(owned_directories)

    def write(self, plan: AcceptancePlan) -> ReportReference:
        self.report_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        stem = f"acceptance_{plan.plan_id}_{timestamp}"
        html_filename, csv_filename = f"{stem}.html", f"{stem}.csv"
        manifest_filename = f"{stem}.assets.json"
        result = evaluate_conclusion(plan, AcceptanceCriteria.from_dict(plan.criteria_snapshot))
        with (self.report_dir / csv_filename).open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Plan_ID", "Filename", "Community", "Building", "Unit", "Floor", "Door", "Status", "Message", "SHA256", "Started_At", "Finished_At", "Duration_s"])
            for item in plan.items:
                p = item.parameters
                writer.writerow([plan.plan_id, item.filename, p.community, p.building, p.unit, p.floor, p.door, item.status, item.message, item.sha256, item.started_at, item.finished_at, item.duration_s])

        coverage = result.coverage.to_dict()["planned"]
        completed = sum(item.status in {"passed", "failed", "cancelled"} for item in plan.items)
        passed = sum(item.status == "passed" for item in plan.items)
        started = [item.started_at for item in plan.items if item.started_at]
        finished = [item.finished_at for item in plan.items if item.finished_at]
        elapsed = sum(float(item.duration_s or 0) for item in plan.items)
        preflight = public_execution_preflight(plan.execution_preflight) if plan.execution_preflight is not None else None
        preparation = "按常规验收流程执行"
        if preflight and (preflight["scenario_profile_name"] or preflight["dependency_plan_enabled"]):
            parts = []
            if preflight["scenario_profile_name"]:
                parts.append(f"场景方案：{preflight['scenario_profile_name']}")
            if preflight["dependency_plan_enabled"]:
                parts.append(f"Supervisor 依赖：{preflight['dependency_stage_count']} 个阶段、{preflight['dependency_node_count']} 个节点")
            preparation = "；".join(parts)
        evidence_html, trajectory_directories = self._inline_trajectory_cards(plan)
        with (self.report_dir / manifest_filename).open("w", encoding="utf-8") as handle:
            json.dump({"schema": 1, "trajectory_directories": trajectory_directories}, handle, ensure_ascii=False, separators=(",", ":"))

        status_label, status_class = _item_status("passed" if result.status and result.status.endswith("_pass") else "failed" if result.status else plan.status)
        rows = "".join(
            "<tr>"
            f"<td>#{index:02d}<br><small>{escape(item.filename)}</small></td>"
            f"<td>{item.parameters.building} 栋 {item.parameters.unit} 单元<br>{item.parameters.floor} 层 {item.parameters.door} 户</td>"
            f"<td>{_local_time(item.started_at)}</td><td>{_local_time(item.finished_at)}</td><td>{_duration(item.duration_s)}</td>"
            f"<td class=\"{_item_status(item.status)[1]}\">{_item_status(item.status)[0]}</td>"
            f"<td>{escape(item.message or '—')}</td></tr>"
            for index, item in enumerate(plan.items, start=1)
        ) or '<tr><td colspan="7">验收计划中没有可归档的任务。</td></tr>'

        status_color = "var(--success)" if result.status and result.status.endswith("_pass") else "var(--danger)" if result.status else "var(--muted)"
        html = f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>部署验收报告 · {escape(_scope_text(plan))}</title>
<style>
:root{{color-scheme:light;--canvas:#f5f5f7;--surface:#fff;--surface-subtle:#f5f5f7;--line:#d2d2d7;--line-subtle:#e5e5ea;--ink:#1d1d1f;--muted:#6e6e73;--blue:#0071e3;--success:#248a3d;--success-soft:#e9f8ed;--warning:#a86600;--warning-soft:#fff6e0;--danger:#c5221f;--danger-soft:#fff0ef;--shadow:0 10px 30px rgba(0,0,0,.06)}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--canvas);color:var(--ink);font:14px/1.55 -apple-system,BlinkMacSystemFont,"SF Pro Text","Noto Sans SC","Microsoft YaHei",sans-serif}}.report-shell{{max-width:1240px;margin:0 auto;padding:42px 28px 56px}}.report-header{{display:flex;align-items:flex-start;justify-content:space-between;gap:24px;padding:30px 32px;border:1px solid var(--line);border-radius:18px;background:var(--surface);box-shadow:var(--shadow)}}.eyebrow{{margin:0 0 8px;color:var(--blue);font:700 11px/1.2 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;letter-spacing:.1em}}h1{{margin:0;font-size:36px;line-height:1.15;letter-spacing:-.035em}}.header-copy{{max-width:760px;margin:12px 0 0;color:var(--muted)}}.status-badge{{display:inline-flex;align-items:center;gap:7px;padding:7px 10px;border:1px solid currentColor;border-radius:999px;font-size:12px;font-weight:700;white-space:nowrap}}.status-badge::before{{content:"";width:7px;height:7px;border-radius:50%;background:currentColor}}.status-badge.passed{{color:var(--success);background:var(--success-soft)}}.status-badge.failed{{color:var(--danger);background:var(--danger-soft)}}.status-badge.cancelled{{color:var(--warning);background:var(--warning-soft)}}.status-badge.unknown,.status-badge.planned,.status-badge.running{{color:var(--muted);background:var(--surface-subtle)}}.report-summary{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-top:16px}}.summary-metric{{min-height:112px;padding:18px;border:1px solid var(--line);border-radius:15px;background:var(--surface)}}.summary-metric small{{display:block;color:var(--muted);font-size:12px}}.summary-metric strong{{display:block;margin-top:8px;font-size:28px;line-height:1;letter-spacing:-.035em;font-variant-numeric:tabular-nums}}.metric-detail{{display:block;margin-top:8px;color:var(--muted);font-size:12px}}.section-card{{margin-top:16px;padding:24px;border:1px solid var(--line);border-radius:16px;background:var(--surface)}}.section-title,.evidence-heading{{display:flex;align-items:baseline;justify-content:space-between;gap:16px;margin-bottom:17px}}.section-title h2,.evidence-heading h3{{margin:0;font-size:17px;letter-spacing:-.02em}}.section-title p{{margin:0;color:var(--muted);font-size:12px}}.context-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:0}}.context-item{{min-width:0;padding:13px 14px;border-radius:12px;background:var(--surface-subtle)}}.context-item dt{{color:var(--muted);font-size:11px}}.context-item dd{{margin:4px 0 0;overflow-wrap:anywhere;font-weight:650}}.conclusion{{margin-top:16px;padding:18px 20px;border:1px solid var(--line);border-radius:15px;background:var(--surface)}}.conclusion b{{color:{status_color};font-size:17px}}.conclusion p{{margin:8px 0 0;color:var(--muted)}}.table-scroll{{overflow-x:auto;border:1px solid var(--line);border-radius:12px}}table{{width:100%;min-width:920px;border-collapse:collapse;font-size:13px}}th,td{{padding:13px 14px;border-bottom:1px solid var(--line-subtle);text-align:left;vertical-align:top}}tr:last-child td{{border-bottom:0}}th{{background:var(--surface-subtle);color:var(--muted);font-size:11px;letter-spacing:.04em;white-space:nowrap}}td{{overflow-wrap:anywhere}}td.passed{{color:var(--success);font-weight:700}}td.failed{{color:var(--danger);font-weight:700}}td.cancelled{{color:var(--warning);font-weight:700}}.evidence-card{{break-inside:avoid;margin-top:16px;padding:22px;border:1px solid var(--line);border-radius:16px;background:var(--surface)}}figure{{break-inside:avoid;margin:14px 0 0;padding:14px;border:1px solid var(--line-subtle);border-radius:12px;background:var(--surface-subtle)}}figcaption{{margin-bottom:10px;color:var(--muted);font-size:12px;font-weight:700}}figure svg{{display:block;width:100%;height:auto;border:1px solid var(--line);border-radius:8px;background:#fff}}.notice{{margin:0;padding:12px 14px;border:1px solid #efd594;border-radius:8px;background:var(--warning-soft);color:#684400}}.report-footer{{margin:22px 2px 0;color:var(--muted);font-size:12px}}@media(max-width:760px){{.report-shell{{padding:20px 14px 36px}}.report-header{{display:block;padding:24px 21px}}.report-header>.status-badge{{margin-top:16px}}.report-summary{{grid-template-columns:repeat(2,minmax(0,1fr)}}.section-card,.evidence-card{{padding:18px}}.context-grid{{grid-template-columns:1fr}}}}@media print{{@page{{margin:14mm}}body{{background:#fff;font-size:11pt;print-color-adjust:exact;-webkit-print-color-adjust:exact}}.report-shell{{max-width:none;padding:0}}.report-header,.summary-metric,.section-card,.evidence-card{{box-shadow:none;break-inside:avoid}}.report-summary{{grid-template-columns:repeat(4,minmax(0,1fr)}}thead{{display:table-header-group}}tr{{break-inside:avoid}}.table-scroll{{overflow:visible}}}}
</style></head><body><main class="report-shell">
<header class="report-header"><div><p class="eyebrow">RY ALETHEIA / DEPLOYMENT ACCEPTANCE</p><h1>部署验收报告</h1><p class="header-copy">验收范围：{escape(_scope_text(plan))} · 计划创建：{_local_time(plan.created_at)}</p></div><span class="status-badge {status_class}">{status_label}</span></header>
<section class="report-summary"><article class="summary-metric"><small>验收任务</small><strong>{len(plan.items)}</strong><span class="metric-detail">已完成 {completed} 项</span></article><article class="summary-metric"><small>通过 / 未通过</small><strong>{passed} / {result.failed_tasks}</strong><span class="metric-detail">人工干预 {plan.manual_interventions} 次</span></article><article class="summary-metric"><small>本次通过率</small><strong>{result.pass_rate:.1f}%</strong><span class="metric-detail">按冻结任务自动计算</span></article><article class="summary-metric"><small>累计执行时长</small><strong>{_duration(elapsed)}</strong><span class="metric-detail">不含等待人工恢复时间</span></article></section>
<section class="conclusion"><b>{escape(result.status or '尚未完成')}</b><p>{escape(result.message)}</p></section>
<section class="section-card"><div class="section-title"><h2>验收信息</h2><p>随报告归档 CSV：{escape(csv_filename)}</p></div><dl class="context-grid"><div class="context-item"><dt>验收范围</dt><dd>{escape(_scope_text(plan))}</dd></div><div class="context-item"><dt>计划方式</dt><dd>{'抽样验收' if plan.mode == 'sample' else '全量验收'}</dd></div><div class="context-item"><dt>运行准备</dt><dd>{escape(preparation)}</dd></div><div class="context-item"><dt>开始时间</dt><dd>{_local_time(min(started) if started else None)}</dd></div><div class="context-item"><dt>结束时间</dt><dd>{_local_time(max(finished) if finished else None)}</dd></div><div class="context-item"><dt>计划覆盖</dt><dd>{coverage['physical_building']:.1f}% 物理楼宇单元 · {coverage['floor']:.1f}% 楼层 · {coverage['door']:.1f}% 户</dd></div></dl></section>
<section class="section-card"><div class="section-title"><h2>冻结任务与结果</h2><p>每项均保留执行时间、结果与服务反馈</p></div><div class="table-scroll"><table><thead><tr><th>任务</th><th>位置</th><th>开始</th><th>结束</th><th>耗时</th><th>结果</th><th>反馈</th></tr></thead><tbody>{rows}</tbody></table></div></section>
<section class="section-card"><div class="section-title"><h2>地图运行轨迹证据</h2><p>实际轨迹、理想路线与虚拟墙以采集结果为准</p></div>{evidence_html}</section>
<footer class="report-footer">由 RY Aletheia 自动生成。该文件与 CSV 可独立离线归档。</footer></main></body></html>'''
        (self.report_dir / html_filename).write_text(html, encoding="utf-8")
        return ReportReference(html_filename, csv_filename, manifest_filename)
