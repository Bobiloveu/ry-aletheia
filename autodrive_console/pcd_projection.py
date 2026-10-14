"""Bounded, offline PCD height projection; never interacts with ROS.

Only cells containing finite input XY evidence are supported. A cell without
height-band obstacles is a *projection* free cell, not proof of visibility or
traversability: sparse scans, occlusion, slopes and removed noise need review.
"""
from __future__ import annotations

import math
import hashlib
import json
import os
import struct
import tempfile
import threading
from pathlib import Path

import numpy as np
from pypcd4 import PointCloud


MAX_POINTS = 10_000_000
MAX_EXPANDED_BYTES = 512 * 1024 * 1024
MAX_GRID_CELLS = 16_000_000
MAX_GRID_DIMENSION = 16_384
MAX_HEADER_BYTES = 64 * 1024
MAX_SOURCE_PREVIEW_POINTS = 100_000
DETAIL_FORMAT = "xyz-rgba-intensity-v1"
DETAIL_DTYPE = np.dtype([("xyz", "<f4", (3,)), ("rgba", "u1", (4,)), ("intensity", "<f4")])
_PARAMETERS = {"z_min", "z_max", "resolution", "min_points", "denoise"}
_LIMITATION = "离线高度投影不证明可通行性；无点区域保持未知，请人工检查门洞、通道、遮挡与坡地。"


class ProjectionError(ValueError):
    """Invalid PCD input or projection parameters, safe to show to an operator."""


_XYZ_CACHE = None
_GEOMETRY_CACHE = None
_XYZ_CACHE_LOCK = threading.RLock()
_POINT_CHUNK = 262_144


def _load(path: Path, *, include_attributes=False):
    """Keep at most one validated XYZ array (<=240 MB), never a cache per preview."""
    global _XYZ_CACHE, _GEOMETRY_CACHE
    if include_attributes:
        return _load_uncached(path, include_attributes=True)
    try:
        path = Path(path).resolve()
        stamp = path.stat()
        # Small rewrites may share a filesystem timestamp tick; fingerprint them
        # fully. Large job inputs are immutable copies, guarded by file identity.
        small_digest = hashlib.sha256(path.read_bytes()).digest() if stamp.st_size <= 65536 else None
        key = (str(path), stamp.st_dev, stamp.st_ino, stamp.st_size, stamp.st_mtime_ns, stamp.st_ctime_ns, small_digest)
        with _XYZ_CACHE_LOCK:
            if _XYZ_CACHE is not None and _XYZ_CACHE[0] == key:
                return _XYZ_CACHE[1]
            _XYZ_CACHE = None
            _GEOMETRY_CACHE = None
            result = _load_uncached(path)
            after = path.stat()
            identity = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
            if any(getattr(stamp, field) != getattr(after, field) for field in identity):
                raise ProjectionError("读取过程中点云文件发生变化，请重试")
            result[0].setflags(write=False)
            _XYZ_CACHE = key, result
            return result
    except OSError as exc:
        raise ProjectionError("PCD 文件无法读取，请检查文件") from exc


def _bounds(xyz):
    # Separate strided reductions avoid NumPy's slow Nx3 axis-zero reduction.
    return (np.array([xyz[:, axis].min() for axis in range(xyz.shape[1])]),
            np.array([xyz[:, axis].max() for axis in range(xyz.shape[1])]))


def _grid_indices(xyz, origin, resolution, width, height):
    """Exact float64 cell mapping with bounded scratch space (about 4 MiB)."""
    indices = np.empty(len(xyz), dtype=np.uint32)
    size = min(len(xyz), _POINT_CHUNK)
    scratch = np.empty(size, dtype=np.float64)
    cells = np.empty((2, size), dtype=np.uint32)
    for start in range(0, len(xyz), size):
        stop = min(start + size, len(xyz))
        count = stop - start
        work = scratch[:count]
        for axis, limit in enumerate((width, height)):
            np.subtract(xyz[start:stop, axis], origin[axis], out=work)
            np.divide(work, resolution, out=work)
            np.nextafter(work, np.inf, out=work)
            np.floor(work, out=work)
            np.clip(work, 0, limit - 1, out=work)
            cells[axis, :count] = work
        np.multiply(cells[1, :count], width, out=indices[start:stop])
        np.add(indices[start:stop], cells[0, :count], out=indices[start:stop])
    indices.setflags(write=False)
    return indices


def _projection_geometry(xyz, resolution):
    """Cache one resolution for the current immutable source, at most 40 MB.

    Height, density and denoise choices are deliberately excluded: they must
    always be recomputed. Replacing the XYZ source clears this cache as well.
    """
    global _GEOMETRY_CACHE
    with _XYZ_CACHE_LOCK:
        if (_GEOMETRY_CACHE is not None and _GEOMETRY_CACHE[0] is xyz
                and _GEOMETRY_CACHE[1] == resolution):
            return _GEOMETRY_CACHE[2]
    low, high = _bounds(xyz[:, :2])
    scaled_low, scaled_high = low / resolution, high / resolution
    if not np.isfinite(scaled_low).all() or not np.isfinite(scaled_high).all():
        raise ProjectionError("点云范围或分辨率过大，无法生成有界栅格")
    origin = np.floor(np.nextafter(scaled_low, np.inf)) * resolution
    spans = (high - origin) / resolution
    if not np.isfinite(spans).all() or np.any(spans >= MAX_GRID_CELLS):
        raise ProjectionError("栅格超过 1600 万格限制，请增大分辨率")
    width, height = (math.floor(float(span)) + 1 for span in np.nextafter(spans, np.inf))
    if max(width, height) > MAX_GRID_DIMENSION:
        raise ProjectionError("地图边长超过 16384 格，请增大分辨率")
    if width * height > MAX_GRID_CELLS:
        raise ProjectionError("栅格超过 1600 万格限制，请增大分辨率")
    indices = _grid_indices(xyz, origin, resolution, width, height)
    origin.setflags(write=False)
    geometry = width, height, origin, indices
    with _XYZ_CACHE_LOCK:
        # A concurrent load may have replaced the source while mapping it.
        if _XYZ_CACHE is not None and _XYZ_CACHE[1][0] is xyz:
            _GEOMETRY_CACHE = xyz, resolution, geometry
    return geometry


def _preflight(fp) -> tuple[int, str]:
    """Validate declarations and payload bounds before the upstream decoder runs."""
    header = {}
    consumed = 0
    allowed = {"VERSION", "FIELDS", "SIZE", "TYPE", "COUNT", "WIDTH", "HEIGHT",
               "VIEWPOINT", "POINTS", "DATA"}
    while True:
        line = fp.readline(MAX_HEADER_BYTES + 1)
        consumed += len(line)
        if not line or consumed > MAX_HEADER_BYTES:
            raise ProjectionError("PCD 头部缺失或超过 64 KiB 限制")
        try:
            values = line.decode("ascii").strip().split()
        except UnicodeError as exc:
            raise ProjectionError("PCD 头部不是有效文本") from exc
        if not values or values[0].startswith("#"):
            continue
        key, *values = values
        if key not in allowed or key in header or not values:
            raise ProjectionError("PCD 头部字段无效或重复")
        header[key] = values
        if key == "DATA":
            break
    try:
        fields = header["FIELDS"]
        sizes = [int(value) for value in header["SIZE"]]
        types = header["TYPE"]
        counts = [int(value) for value in header.get("COUNT", ["1"] * len(fields))]
        points = int(header["POINTS"][0])
        width = int(header["WIDTH"][0])
        height = int(header.get("HEIGHT", ["1"])[0])
        encoding = header["DATA"][0]
    except (KeyError, ValueError, IndexError) as exc:
        raise ProjectionError("PCD 缺少有效的点数、尺寸或字段声明") from exc
    if any(len(header[key]) != 1 for key in ("POINTS", "WIDTH", "DATA")):
        raise ProjectionError("PCD 标量头部字段无效")
    if not 0 < points <= MAX_POINTS or width <= 0 or height <= 0 or width * height != points:
        raise ProjectionError("PCD 点数为空、不一致或超过 1000 万限制")
    if not 3 <= len(fields) <= 128 or not len(fields) == len(sizes) == len(types) == len(counts):
        raise ProjectionError("PCD 字段声明长度不一致或过多")
    named = [field for field in fields if field != "_"]
    if len(set(named)) != len(named) or not {"x", "y", "z"}.issubset(fields):
        raise ProjectionError("PCD 必须具有唯一的 x、y、z 字段")
    for field, size, kind, count in zip(fields, sizes, types, counts):
        if count < 1 or (kind, size) not in {("F", 4), ("F", 8), ("I", 1), ("I", 2),
                ("I", 4), ("I", 8), ("U", 1), ("U", 2), ("U", 4), ("U", 8)}:
            raise ProjectionError("PCD 字段类型或数量无效")
        if field in {"x", "y", "z"} and count != 1:
            raise ProjectionError("PCD 坐标字段必须为标量")
    stride = sum(size * count for size, count in zip(sizes, counts))
    expanded = points * stride
    if expanded > MAX_EXPANDED_BYTES or sum(counts) > 4096:
        raise ProjectionError("PCD 展开大小超过 512 MiB 或单点字段过多")
    data_start = fp.tell()
    file_size = fp.seek(0, 2)
    fp.seek(data_start)
    payload_size = file_size - data_start
    if encoding == "binary":
        if payload_size != expanded:
            raise ProjectionError("PCD 二进制数据长度与声明不符")
    elif encoding == "binary_compressed":
        declaration = fp.read(8)
        if len(declaration) != 8:
            raise ProjectionError("PCD 压缩数据声明损坏")
        compressed, uncompressed = struct.unpack("<II", declaration)
        if uncompressed != expanded or not 0 < compressed <= MAX_EXPANDED_BYTES or payload_size != compressed + 8:
            raise ProjectionError("PCD 压缩大小或展开大小与声明不符")
    elif encoding == "ascii":
        if payload_size > MAX_EXPANDED_BYTES:
            raise ProjectionError("PCD 文本数据超过 512 MiB 限制")
        rows = 0
        # Check row count before loadtxt: its allocation follows actual rows,
        # not POINTS. Bound each numeric row independently as well.
        max_line = max(4096, sum(counts) * 128)
        while line := fp.readline(max_line + 1):
            if len(line) > max_line:
                raise ProjectionError("PCD 文本数据行过长")
            stripped = line.strip()
            if not stripped or stripped.startswith(b"#"):
                continue
            if len(stripped.split()) != sum(counts):
                raise ProjectionError("PCD 文本数据列数不符")
            rows += 1
            if rows > points:
                raise ProjectionError("PCD 文本点数与声明不符")
        if rows != points:
            raise ProjectionError("PCD 文本点数与声明不符")
    else:
        raise ProjectionError("只支持 ASCII、binary 和 binary_compressed PCD")
    fp.seek(0)
    return points, encoding


class _AsciiWhitespace:
    """Normalize whitespace for pypcd4's single-space ASCII delimiter.

    Numeric conversion remains entirely in the open source decoder. The
    iterator streams lines rather than making another complete in-memory PCD.
    """
    def __init__(self, fp):
        self.fp = fp

    def __iter__(self):
        return self

    def __next__(self):
        line = self.fp.readline()
        if not line:
            raise StopIteration
        return b" ".join(line.split()) + b"\n"

    def seek(self, *args):
        return self.fp.seek(*args)


def _load_uncached(path: Path, *, include_attributes=False):
    try:
        # Keep the same open file through validation and decoding.
        with Path(path).open("rb") as fp:
            point_count, encoding = _preflight(fp)
            source_digest = hashlib.sha256()
            while chunk := fp.read(1024 * 1024):
                source_digest.update(chunk)
            fp.seek(0)
            reader = _AsciiWhitespace(fp) if encoding == "ascii" else fp
            cloud = PointCloud.from_fileobj(reader)
            # Decode once into the final float64 columns. Stacking first made
            # another complete Nx3 array before converting its numeric type.
            xyz = np.empty((point_count, 3), dtype=np.float64, order='F')
            for axis, name in enumerate(('x', 'y', 'z')):
                column = cloud.pc_data[name]
                if column.shape != (point_count,):
                    raise ProjectionError("PCD 解码后的坐标数量与声明不符")
                xyz[:, axis] = column
        if xyz.shape != (point_count, 3):
            raise ProjectionError("PCD 解码后的坐标数量与声明不符")
        finite = np.isfinite(xyz[:, 0])
        for axis in (1, 2):
            finite &= np.isfinite(xyz[:, axis])
        all_finite = bool(finite.all())
        if not all_finite:
            xyz = xyz[finite]
        if not len(xyz):
            raise ProjectionError("PCD 没有有效的有限坐标点")
        result = xyz, point_count, source_digest.hexdigest()
        if include_attributes:
            selected = slice(None) if all_finite else np.flatnonzero(finite)
            return *result, cloud.pc_data, selected
        return result
    except ProjectionError:
        raise
    except (OSError, ValueError, TypeError, KeyError, IndexError, RuntimeError, struct.error) as exc:
        raise ProjectionError("PCD 文件损坏或无法读取，请检查文件格式") from exc


def _source_preview(xyz, low, high, point_count, output: Path) -> dict:
    count = min(len(xyz), MAX_SOURCE_PREVIEW_POINTS)
    indices = (np.arange(count, dtype=np.int64) * (len(xyz) - 1) // (count - 1)
               if count > 1 else np.array([0]))
    origin = low / 2 + high / 2
    try:
        with np.errstate(over="raise", invalid="raise"):
            sample = (xyz[indices] - origin).astype("<f4")
    except FloatingPointError as exc:
        raise ProjectionError("点云坐标范围过大，无法生成有限的三维显示样本") from exc
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".source-preview-", delete=False) as fp:
            temporary = Path(fp.name)
            fp.write(sample.tobytes())
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {"point_count": count, "source_point_count": point_count, "finite_point_count": len(xyz),
            "origin": origin.tolist(), "bounds": [[float(low[i]), float(high[i])] for i in range(3)]}


def build_source_detail(path: Path, output: Path) -> dict:
    """Background-only full finite cloud cache; preserve every point and its attributes."""
    if Path(output).resolve() == Path(path).resolve():
        raise ProjectionError("点云显示样本不能覆盖原始点云")
    xyz, total, _, fields, finite_indices = _load(path, include_attributes=True)
    count = len(xyz)
    low, high = _bounds(xyz)
    origin = low / 2 + high / 2
    sample = np.zeros(count, dtype=DETAIL_DTYPE)
    with np.errstate(over="raise", invalid="raise"):
        try:
            np.subtract(xyz, origin, out=sample['xyz'], casting='unsafe')
        except FloatingPointError as exc:
            raise ProjectionError("点云坐标范围过大，无法生成三维显示样本") from exc
    selected = finite_indices
    names = {name.lower(): name for name in fields.dtype.names}
    rgb = False
    packed = names.get('rgb') or names.get('rgba')
    if packed and fields[packed].ndim == 1 and fields[packed].dtype.itemsize == 4:
        values = fields[packed][selected]
        if values.dtype.kind == 'f':
            bits = values.astype('<f4', copy=False).view('<u4')
        elif values.dtype.kind in 'ui':
            bits = values.astype('<u4', copy=False)
        else:
            bits = None
        if bits is not None:
            sample['rgba'][:, :3] = np.column_stack(((bits >> 16) & 255, (bits >> 8) & 255, bits & 255))
            sample['rgba'][:, 3] = 255
            rgb = True
    elif all(name in names for name in ('r', 'g', 'b')):
        channels = [fields[names[name]][selected] for name in ('r', 'g', 'b')]
        if all(channel.ndim == 1 for channel in channels):
            values = np.column_stack(channels)
            valid = np.isfinite(values).all(axis=1) & (values >= 0).all(axis=1) & (values <= 255).all(axis=1)
            sample['rgba'][valid, :3] = values[valid].astype('u1')
            sample['rgba'][valid, 3] = 255
            rgb = bool(valid.any())
    sample['intensity'] = np.nan
    intensity = names.get('intensity')
    if intensity and fields[intensity].ndim == 1:
        with np.errstate(over='ignore', invalid='ignore'):
            sample['intensity'] = fields[intensity][selected]
        sample['intensity'][~np.isfinite(sample['intensity'])] = np.nan
    valid_intensity = sample['intensity'][np.isfinite(sample['intensity'])]
    intensity_range = np.quantile(valid_intensity, [.02, .98]).tolist() if len(valid_intensity) else None
    # Quantiles are independent per axis; copy one column at a time instead of
    # another full Nx3 float64 cloud. All points still participate exactly.
    display_bounds = [np.quantile(xyz[:, axis], [.005, .995]).tolist() for axis in range(3)]
    metadata = {"format": DETAIL_FORMAT, "point_count": count, "source_point_count": total,
                "finite_point_count": len(xyz), "origin": origin.tolist(), "bounds": np.column_stack((low, high)).tolist(),
                "attributes": {"rgb": rgb, "intensity": bool(len(valid_intensity)),
                               "intensity_range": intensity_range, "display_bounds": display_bounds}}
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix='.source-detail-', delete=False) as fp:
            temporary = Path(fp.name)
            sample.tofile(fp)
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return metadata


def analyze_pcd(path: Path, *, preview_output: Path | None = None) -> dict:
    """Return height evidence and uncertain, manually adjustable ground candidates."""
    if preview_output is not None and Path(preview_output).resolve() == Path(path).resolve():
        raise ProjectionError("点云显示样本不能覆盖原始点云")
    xyz, point_count, _ = _load(path)
    low, high = _bounds(xyz)
    z_span = float(high[2]) - float(low[2])
    if not math.isfinite(z_span):
        raise ProjectionError("点云高度跨度过大，无法分析")
    bins = max(1, math.ceil(min(128.0, z_span / 0.1)))
    counts, edges = np.histogram(xyz[:, 2], bins=bins)
    # Estimate horizontal support on a bounded deterministic sample. Dense
    # vertical scans alone should not outrank broadly observed floor surfaces.
    sample = xyz[::max(1, math.ceil(len(xyz) / 200_000))]
    sample_bins = np.clip(np.searchsorted(edges, sample[:, 2], side="right") - 1, 0, bins - 1)
    xy = np.floor((sample[:, :2] - low[:2]) / 0.5)
    total_support = max(1, len(np.unique(xy, axis=0)))
    ranked = []
    for index in np.flatnonzero(counts):
        mask = sample_bins == index
        support = len(np.unique(xy[mask], axis=0))
        ground = float(np.median(sample[mask, 2])) if mask.any() else float((edges[index] + edges[index + 1]) / 2)
        ranked.append((support, int(counts[index]), ground))
    candidates = []
    for support, _, ground in sorted(ranked, reverse=True):
        if any(abs(candidate["ground_z"] - ground) < 0.4 for candidate in candidates):
            continue
        # Highest surfaces often look floor-like in a height histogram. Do not
        # recommend their above-surface band when it contains no sample points.
        if not np.any((sample[:, 2] >= ground + 0.15) & (sample[:, 2] <= ground + 1.5)):
            continue
        candidates.append({"label": f"候选地面 {len(candidates) + 1}", "ground_z": ground,
                           "z_min": ground + 0.15, "z_max": ground + 1.5,
                           "confidence": round(min(0.85, 0.2 + 0.65 * support / total_support), 3)})
        if len(candidates) == 3:
            break
    warnings = [_LIMITATION, "候选地面依据高度分布与水平覆盖估计；多层、密集立面和坡地可能误判，请核对绝对高度。"]
    if len(xyz) != point_count:
        warnings.append(f"已忽略 {point_count - len(xyz)} 个非有限坐标点。")
    result = {"point_count": point_count, "finite_point_count": len(xyz),
            "bounds": {axis: [float(low[index]), float(high[index])] for index, axis in enumerate("xyz")},
            "z_histogram": {"edges": edges.tolist(), "counts": counts.tolist()},
            "candidates": candidates, "warnings": warnings}
    if preview_output is not None:
        result["source_preview"] = _source_preview(xyz, low, high, point_count, preview_output)
    return result


def _parameters(parameters: dict) -> dict:
    if not isinstance(parameters, dict) or set(parameters) != _PARAMETERS:
        raise ProjectionError("请提供高度上下限、分辨率、最少点数和去噪设置")
    result = dict(parameters)
    for key in ("z_min", "z_max", "resolution"):
        value = result[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ProjectionError("高度和分辨率必须为有限数值")
        try:
            result[key] = float(value)
        except OverflowError as exc:
            raise ProjectionError("高度和分辨率必须为有限数值") from exc
        if not math.isfinite(result[key]):
            raise ProjectionError("高度和分辨率必须为有限数值")
    if result["z_min"] >= result["z_max"] or result["resolution"] <= 0:
        raise ProjectionError("高度下限必须小于上限，分辨率必须大于零")
    if type(result["min_points"]) is not int or not 1 <= result["min_points"] <= MAX_POINTS:
        raise ProjectionError("最少点数必须为 1 至 1000 万之间的整数")
    if type(result["denoise"]) is not bool:
        raise ProjectionError("去噪设置必须为布尔值")
    return result


def trajectory_preview(path: Path):
    """Full finite XY for a temporary display overlay, with a precise local origin."""
    xyz, _, _ = _load(path)
    low, high = _bounds(xyz[:, :2])
    origin = low + (high - low) / 2
    points = np.asarray(xyz[:, :2] - origin, dtype='<f4')
    if not np.isfinite(points).all():
        raise ProjectionError('轨迹范围过大，无法生成预览')
    return points.tobytes(), {'point_count': len(points), 'origin': origin.tolist(), 'format': 'xy-v1'}


def project_pcd(path: Path, output_dir: Path, parameters: dict, *, on_progress=None) -> dict:
    """Write map.pgm/map.yaml without changing the source or world XY frame."""
    params = _parameters(parameters)
    report = on_progress or (lambda _value, _message: None)
    report(5, "正在读取点云。")
    xyz, point_count, source_sha256 = _load(path)
    report(20, "点云读取完成，正在筛选截面。")
    selected = (xyz[:, 2] >= params["z_min"]) & (xyz[:, 2] <= params["z_max"])
    if not selected.any():
        raise ProjectionError("所选高度范围没有点，请调整高度上下限")
    resolution = params["resolution"]
    width, height, origin, indices = _projection_geometry(xyz, resolution)
    report(35, "截面筛选完成，正在生成地图栅格。")
    grid = np.full(width * height, 205, dtype=np.uint8)
    grid[indices] = 254
    obstacle_indices = indices[selected]
    report(65, "地图栅格已生成，正在处理障碍细节。")
    if params["min_points"] == 1:
        occupied = np.zeros(width * height, dtype=bool)
        occupied[obstacle_indices] = True
        occupied = occupied.reshape(height, width)
        grid[obstacle_indices] = 205
    else:
        counts = np.bincount(obstacle_indices, minlength=width * height)
        occupied = (counts >= params["min_points"]).reshape(height, width)
        # Weak obstacle evidence remains unknown rather than silently becoming free.
        grid[counts > 0] = 205
    warnings = [_LIMITATION]
    if params["denoise"]:
        padded = np.pad(occupied, 1)
        neighbors = np.zeros_like(occupied, dtype=np.uint8)
        for dy in range(3):
            for dx in range(3):
                if (dy, dx) != (1, 1):
                    neighbors += padded[dy:dy + height, dx:dx + width]
        occupied &= neighbors > 0
        warnings.append("去噪仅将孤立障碍格改为未知；点密度和邻接关系不能证明安全，请人工核对细小障碍。")
    grid[occupied.ravel()] = 0
    if len(xyz) != point_count:
        warnings.append(f"已忽略 {point_count - len(xyz)} 个非有限坐标点。")
    output = Path(output_dir)
    report(85, "障碍处理完成，正在保存地图预览。")
    output.mkdir(parents=True, exist_ok=True)
    with (output / "map.pgm").open("wb") as fp:
        fp.write(f"P5\n{width} {height}\n255\n".encode("ascii"))
        fp.write(grid.reshape(height, width)[::-1].tobytes())
    origin_list = [float(origin[0]), float(origin[1]), 0.0]
    provenance = json.dumps({"algorithm": "height_projection_v1", "source_sha256": source_sha256,
                             "parameters": params}, sort_keys=True, separators=(",", ":"))
    (output / "map.yaml").write_text(
        f"# projection: {provenance}\nimage: map.pgm\nresolution: {resolution!r}\norigin: {origin_list!r}\n"
        "negate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.196\n", encoding="utf-8")
    report(95, "地图文件已保存，正在核对转换结果。")
    return {"width": width, "height": height, "resolution_m": resolution,
            "origin": origin_list, "selected_points": int(selected.sum()),
            "occupied_cells": int(occupied.sum()), "parameters": params, "warnings": warnings,
            "source_sha256": source_sha256}
