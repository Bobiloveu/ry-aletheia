"""Self-contained hover evidence for archived trajectory reports."""

from __future__ import annotations

import json
from html import escape
from math import isfinite
from typing import Any


def _map_meta(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    try:
        resolution = float(raw.get("resolution"))
        width = float(raw.get("width"))
        height = float(raw.get("height"))
        origin = raw.get("origin")
        origin_x = float(origin[0]) if isinstance(origin, list) else float(raw.get("origin_x", 0))
        origin_y = float(origin[1]) if isinstance(origin, list) else float(raw.get("origin_y", 0))
    except (TypeError, ValueError, IndexError):
        return None
    if not all(isfinite(value) for value in (resolution, width, height, origin_x, origin_y)) or resolution <= 0 or width <= 0 or height <= 0:
        return None
    return {"resolution": resolution, "width": width, "height": height, "origin": [origin_x, origin_y]}


def trajectory_figure(view: dict[str, Any], svg: str, trajectory: object) -> str:
    """Wrap one inline SVG with optional point data and a report-local tooltip."""
    raw = trajectory if isinstance(trajectory, dict) else {}
    map_id = str(view.get("map_id") or "")
    segments = [item for item in raw.get("segments", []) if isinstance(item, dict) and str(item.get("map_id") or "") == map_id]
    map_data = next((_map_meta(item.get("map")) for item in segments if _map_meta(item.get("map"))), None)
    points: list[dict[str, Any]] = []
    for segment in segments:
        route_name = str(segment.get("route_name") or "轨迹采样")
        for point in segment.get("points", []) if isinstance(segment.get("points"), list) else []:
            if not isinstance(point, dict):
                continue
            try:
                x, y, timestamp = float(point["x"]), float(point["y"]), int(point.get("timestamp_ns") or 0)
            except (KeyError, TypeError, ValueError):
                continue
            if isfinite(x) and isfinite(y):
                points.append({"x": x, "y": y, "timestamp_ns": timestamp, "route_name": route_name, "sample_index": len(points) + 1})
    payload = None
    if map_data and points:
        evidence_height = 76 + sum(17 for item in segments if isinstance(item.get("points"), list) and item.get("points"))
        payload = {"map": map_data, "evidence_height": evidence_height, "points": points}
    data_attr = ""
    if payload:
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
        data_attr = f' data-trajectory-points="{escape(serialized, quote=True)}"'
    return f'<figure class="trajectory-report-figure"{data_attr}><figcaption>{escape(str(view.get("label") or map_id or "轨迹地图"))}</figcaption><div class="trajectory-report-stage">{svg}<span class="trajectory-report-cursor" hidden></span><div class="trajectory-report-tooltip" role="status" aria-live="polite" hidden></div></div></figure>'


REPORT_TRAJECTORY_CSS = r'''
.trajectory-report-figure { position: relative; }
.trajectory-report-stage { position: relative; }
.trajectory-report-stage > svg { position: relative; z-index: 1; }
.trajectory-report-cursor { position: absolute; z-index: 3; width: 11px; height: 11px; margin: -5px 0 0 -5px; border: 2px solid #fff; border-radius: 50%; background: #168cff; box-shadow: 0 0 0 4px rgba(22,140,255,.2), 0 0 14px rgba(22,140,255,.7); pointer-events: none; }
.trajectory-report-cursor::before { content: ""; position: absolute; left: 50%; top: -9999px; width: 1px; height: 19999px; transform: translateX(-50%); background: rgba(22,140,255,.28); }
.trajectory-report-tooltip { position: absolute; z-index: 4; min-width: 190px; max-width: min(260px, calc(100% - 16px)); padding: 10px 12px; border: 1px solid rgba(0,113,227,.58); border-radius: 9px; background: rgba(23,35,55,.96); color: #e8f4ff; box-shadow: 0 10px 24px rgba(23,35,55,.22); font: 11px/1.45 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; pointer-events: none; }
.trajectory-report-tooltip::after { content: ""; position: absolute; left: 50%; bottom: -6px; width: 10px; height: 10px; transform: translateX(-50%) rotate(45deg); border-right: 1px solid rgba(0,113,227,.58); border-bottom: 1px solid rgba(0,113,227,.58); background: rgba(23,35,55,.96); }
.trajectory-report-tooltip-kicker { color: #72c8ff; font-size: 10px; }
.trajectory-report-tooltip-time { display: block; margin-top: 3px; color: #fff; font-size: 13px; }
.trajectory-report-tooltip-route { margin-top: 2px; color: #a6bfd4; font-size: 10px; }
.trajectory-report-tooltip-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 7px; color: #89a7bf; font-size: 10px; }
.trajectory-report-tooltip-grid b { display: block; margin-top: 2px; color: #e7f4ff; }
'''


REPORT_TRAJECTORY_SCRIPT = r'''
(() => {
  const formatter = new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" });
  const timeOf = value => { const milliseconds = Number(value) / 1000000; if (!Number.isFinite(milliseconds) || milliseconds <= 0) return "时间未知"; const parts = Object.fromEntries(formatter.formatToParts(new Date(milliseconds)).map(item => [item.type, item.value])); return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`; };
  const hide = figure => { const cursor = figure.querySelector(".trajectory-report-cursor"); const tooltip = figure.querySelector(".trajectory-report-tooltip"); if (cursor) cursor.hidden = true; if (tooltip) tooltip.hidden = true; };
  document.querySelectorAll(".trajectory-report-figure[data-trajectory-points]").forEach(figure => {
    let payload; try { payload = JSON.parse(figure.dataset.trajectoryPoints); } catch { return; }
    const stage = figure.querySelector(".trajectory-report-stage"); const svg = stage?.querySelector("svg"); const cursor = figure.querySelector(".trajectory-report-cursor"); const tooltip = figure.querySelector(".trajectory-report-tooltip");
    if (!stage || !svg || !cursor || !tooltip || !payload?.map || !Array.isArray(payload.points)) return;
    const update = event => {
      if (event.pointerType && event.pointerType !== "mouse") return hide(figure);
      const svgRect = svg.getBoundingClientRect(); const view = svg.viewBox?.baseVal; if (!svgRect.width || !svgRect.height || !view?.width) return hide(figure);
      const scaleX = svgRect.width / view.width; const scaleY = svgRect.height / view.height; const pointer = { x: (event.clientX - svgRect.left) / scaleX + view.x, y: (event.clientY - svgRect.top) / scaleY + view.y }; const map = payload.map;
      let nearest = null;
      payload.points.forEach(point => { const x = (point.x - map.origin[0]) / map.resolution; const y = payload.evidence_height + map.height - (point.y - map.origin[1]) / map.resolution; const dx = x - pointer.x; const dy = y - pointer.y; const magnetic = Math.hypot(dx, dy * .38); if (!nearest || magnetic < nearest.magnetic) nearest = { point, x, y, magnetic }; });
      if (!nearest) return hide(figure);
      const screenX = (nearest.x - view.x) * scaleX; const screenY = (nearest.y - view.y) * scaleY; const stageRect = stage.getBoundingClientRect(); const figureRect = figure.getBoundingClientRect();
      cursor.hidden = false; cursor.style.left = `${screenX}px`; cursor.style.top = `${screenY}px`;
      tooltip.innerHTML = `<div class="trajectory-report-tooltip-kicker">磁吸采样点 ${nearest.point.sample_index}</div><strong class="trajectory-report-tooltip-time"></strong><div class="trajectory-report-tooltip-route"></div><div class="trajectory-report-tooltip-grid"><span>x <b></b></span><span>y <b></b></span></div>`;
      tooltip.querySelector(".trajectory-report-tooltip-time").textContent = timeOf(nearest.point.timestamp_ns); tooltip.querySelector(".trajectory-report-tooltip-route").textContent = nearest.point.route_name || "轨迹采样"; const values = tooltip.querySelectorAll(".trajectory-report-tooltip-grid b"); values[0].textContent = Number(nearest.point.x).toFixed(3); values[1].textContent = Number(nearest.point.y).toFixed(3);
      tooltip.hidden = false;
      const tooltipWidth = tooltip.offsetWidth; const tooltipHeight = tooltip.offsetHeight; const left = Math.max(8, Math.min(stageRect.width - tooltipWidth - 8, screenX - tooltipWidth / 2)); const top = Math.max(8, screenY - tooltipHeight - 14); tooltip.style.left = `${left}px`; tooltip.style.top = `${top}px`;
    };
    stage.addEventListener("pointermove", update); stage.addEventListener("pointerleave", () => hide(figure));
  });
})();
'''
