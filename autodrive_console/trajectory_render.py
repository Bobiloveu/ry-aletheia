from __future__ import annotations

import base64
import html
import struct
import zlib
from pathlib import Path

from .map_assets import CachedMapAsset


class TrajectoryRenderError(ValueError):
    pass


ACTUAL_PATH_COLORS = ("#168cff", "#9b6dff", "#00a98f", "#ff8c42", "#e75aa8", "#5b95d6")


def render_svg(asset: CachedMapAsset, segment: dict, target: Path, ideal_routes: list[dict] | None = None, virtual_walls: list[dict] | None = None) -> None:
    """将 PGM、虚拟墙、理想路线与实际轨迹渲染为独立 SVG。"""
    if asset.width is None or asset.height is None or asset.resolution is None or asset.origin is None:
        raise TrajectoryRenderError(f"地图元数据不完整：{asset.label}")
    width, height, pixels = _read_pgm(Path(asset.cache_image))
    if (width, height) != (asset.width, asset.height):
        raise TrajectoryRenderError(f"地图尺寸发生变化：{asset.label}")
    image = base64.b64encode(_png_gray(width, height, pixels)).decode("ascii")
    source_paths = segment.get("paths")
    if not isinstance(source_paths, list):
        # 兼容旧报告的单一 points 结构。
        source_paths = [segment.get("points", [])]
    paths: list[dict] = []
    for source_path in source_paths:
        source_points = source_path.get("points", []) if isinstance(source_path, dict) else source_path
        path_points = []
        for point in source_points if isinstance(source_points, list) else []:
            x = (float(point["x"]) - asset.origin[0]) / asset.resolution
            y = height - (float(point["y"]) - asset.origin[1]) / asset.resolution
            path_points.append((x, y))
        if path_points:
            paths.append({
                "points": path_points,
                "epoch": source_path.get("map_epoch") if isinstance(source_path, dict) else None,
                "route_index": source_path.get("route_index") if isinstance(source_path, dict) else None,
            })
    ideal_paths = []
    for route in ideal_routes or []:
        route_points = []
        for point in route.get("points", []):
            route_points.append(((float(point["x"]) - asset.origin[0]) / asset.resolution, height - (float(point["y"]) - asset.origin[1]) / asset.resolution))
        if len(route_points) > 1:
            ideal_paths.append(" ".join(f"{x:.2f},{y:.2f}" for x, y in route_points))
    wall_paths = []
    for wall in virtual_walls or []:
        wall_points = []
        for point in wall.get("points", []):
            if wall.get("coordinate_mode") == "image_relative":
                wall_points.append((float(point["x"]) / asset.resolution, height - float(point["y"]) / asset.resolution))
            else:
                wall_points.append(((float(point["x"]) - asset.origin[0]) / asset.resolution, height - (float(point["y"]) - asset.origin[1]) / asset.resolution))
        if len(wall_points) > 1:
            wall_paths.append(" ".join(f"{x:.2f},{y:.2f}" for x, y in wall_points))
    actual_defs, actual_layer, visit_layer, visit_legend = _actual_trajectory_layers(paths)
    # 理想路线刻意比实际轨迹细且稀疏；不使用描边，避免遮挡重合处的蓝色实际轨迹。
    ideal_layer = "".join(f'<polyline points="{item}" fill="none" stroke="#f5c84b" stroke-width="1.35" stroke-dasharray="5 8" stroke-linejoin="round" stroke-linecap="round"/>' for item in ideal_paths)
    wall_layer = "".join(f'<polyline points="{item}" fill="none" stroke="#d63142" stroke-width="4" stroke-linejoin="round" stroke-linecap="round" opacity="0.96"/>' for item in wall_paths)
    # 图例放在地图画面之外：避免遮挡墙体/轨迹，也避免边缘箭头与文字越界。
    # 图例组本身有 10px 顶部偏移，最后一项基线为 54 + N*17；
    # 这里按文本下降沿额外预留 9px，避免第二条及之后的说明越出深色图例框。
    evidence_height = 76 + len(paths) * 17
    legend_width = min(218, max(132, width - 24))
    legend = f'''<g transform="translate(12 10)"><rect width="{legend_width}" height="{evidence_height - 16}" rx="5" fill="#172337" fill-opacity="0.92"/><line x1="12" y1="17" x2="38" y2="17" stroke="#d63142" stroke-width="3"/><text x="47" y="21" fill="#ff9aa5" font-family="sans-serif" font-size="11">虚拟墙</text><line x1="12" y1="35" x2="38" y2="35" stroke="#d8ad38" stroke-width="1.2" stroke-dasharray="4 6"/><text x="47" y="39" fill="#f2ca58" font-family="sans-serif" font-size="11">理想路线</text>{visit_legend}</g>'''
    escaped_label = html.escape(asset.label)
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height + evidence_height}" viewBox="0 0 {width} {height + evidence_height}">
<title>{escaped_label} 运行轨迹</title>
<defs>{actual_defs}</defs>
<rect width="{width}" height="{evidence_height}" fill="#edf3f8"/>
{legend}
<g transform="translate(0 {evidence_height})">
<image width="{width}" height="{height}" href="data:image/png;base64,{image}"/>
{wall_layer}
{ideal_layer}
{actual_layer}
{visit_layer}
</g>
</svg>'''
    target.write_text(svg, encoding="utf-8")


def _actual_trajectory_layers(paths: list[dict]) -> tuple[str, str, str, str]:
    """按地图进入批次和任务路线段独立着色，不在地图上叠加方向箭头或端点标记。"""
    lines, legend = [], []
    for index, path in enumerate(paths, start=1):
        # 颜色必须由全局 JSON 子任务编号决定，不能由“当前地图里第几段”决定。
        # 否则 P1→P2→P1 或同图去返时，不同任务段会重新从蓝色开始而难以区分。
        route_index = path.get("route_index")
        color_slot = route_index if isinstance(route_index, int) and route_index >= 0 else index - 1
        color = ACTUAL_PATH_COLORS[color_slot % len(ACTUAL_PATH_COLORS)]
        points = path["points"]
        serialized = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
        lines.append(f'<polyline points="{serialized}" fill="none" stroke="{color}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round" opacity="0.94"><title>轨迹 {index}：独立任务路线段</title></polyline>')
        y = 54 + index * 17
        route_text = f"任务段 {int(route_index) + 1}" if isinstance(route_index, int) and route_index >= 0 else "独立轨迹段"
        legend.append(f'<line x1="12" y1="{y - 4}" x2="38" y2="{y - 4}" stroke="{color}" stroke-width="2.5"/><text x="47" y="{y}" fill="{color}" font-family="sans-serif" font-size="11">轨迹 {index} · {route_text}</text>')
    return "", "".join(lines), "", "".join(legend)


def _read_pgm(path: Path) -> tuple[int, int, bytes]:
    data = path.read_bytes()
    index = 0

    def token() -> bytes:
        nonlocal index
        while index < len(data) and data[index] in b" \t\r\n":
            index += 1
        while index < len(data) and data[index] == ord("#"):
            while index < len(data) and data[index] not in b"\r\n":
                index += 1
            while index < len(data) and data[index] in b" \t\r\n":
                index += 1
        start = index
        while index < len(data) and data[index] not in b" \t\r\n#":
            index += 1
        return data[start:index]

    magic, raw_width, raw_height, raw_max = token(), token(), token(), token()
    try:
        width, height, max_value = int(raw_width), int(raw_height), int(raw_max)
    except ValueError as exc:
        raise TrajectoryRenderError(f"无效 PGM 头：{path.name}") from exc
    if magic not in {b"P2", b"P5"} or width <= 0 or height <= 0 or max_value != 255:
        raise TrajectoryRenderError(f"仅支持 8 位 P2/P5 PGM：{path.name}")
    expected = width * height
    if magic == b"P5":
        # P5 头结束后只跨过一个分隔字符；不能跳过全部空白，首个像素可能正好是 0x0A 等值。
        if index < len(data) and data[index] in b" \t\r\n":
            index += 1
        pixels = data[index:index + expected]
    else:
        values = []
        while len(values) < expected:
            item = token()
            if not item:
                break
            values.append(int(item))
        pixels = bytes(values)
    if len(pixels) != expected:
        raise TrajectoryRenderError(f"PGM 像素数据不完整：{path.name}")
    return width, height, pixels


def _png_gray(width: int, height: int, pixels: bytes) -> bytes:
    raw = b"".join(b"\x00" + pixels[row * width:(row + 1) * width] for row in range(height))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xffffffff)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
