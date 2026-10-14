"""Offline projection tests use real files, including all supported PCD encodings."""
import importlib
import struct

import numpy as np
import pytest
import yaml
from pypcd4 import Encoding, PointCloud


def core():
    return importlib.import_module("autodrive_console.pcd_projection")


def cloud(tmp_path, points, encoding=Encoding.ASCII, fields=("x", "y", "z")):
    path = tmp_path / "source.pcd"
    PointCloud.from_points(np.asarray(points, dtype=np.float32), fields,
                           (np.float32,) * len(fields)).save(path, encoding)
    return path


def parameters(**changes):
    return {"z_min": 0.5, "z_max": 1.5, "resolution": 1.0,
            "min_points": 1, "denoise": False, **changes}


def test_trajectory_preview_preserves_xy_detail_and_filters_nonfinite_without_sampling(tmp_path):
    source = cloud(tmp_path, [[1e6, 20, 0], [1e6 + .125, 20.25, 9],
                              [float('nan'), 20, 1]])
    original = source.read_bytes()
    body, meta = core().trajectory_preview(source)
    points = np.frombuffer(body, dtype='<f4').reshape(-1, 2)
    assert meta['point_count'] == 2
    assert meta['format'] == 'xy-v1'
    np.testing.assert_allclose(points + meta['origin'], [[1e6,20],[1e6+.125,20.25]])
    assert source.read_bytes() == original


def test_skinny_grid_is_bounded_per_axis_before_png_preview_allocation(tmp_path):
    source = cloud(tmp_path, [[0, 0, 1], [0, 17000, 1]])
    with pytest.raises(core().ProjectionError, match="边长"):
        core().project_pcd(source, tmp_path / 'out', parameters())


def test_recommendations_never_offer_a_known_empty_height_band(tmp_path):
    points = [[x, y, 0] for x in range(5) for y in range(5)] + [[0, 0, 1.5]]
    source = cloud(tmp_path, points)
    analysis = core().analyze_pcd(source)
    assert analysis['candidates']
    for candidate in analysis['candidates']:
        assert any(candidate['z_min'] <= z <= candidate['z_max'] for _, _, z in points)


def pixels(output):
    magic, size, maximum, data = (output / "map.pgm").read_bytes().split(b"\n", 3)
    assert magic == b"P5" and maximum == b"255"
    width, height = map(int, size.split())
    return np.frombuffer(data, dtype=np.uint8).reshape(height, width).tolist()


def test_projection_reports_completed_stages_without_changing_map_output(tmp_path):
    source = cloud(tmp_path, [[-2, 3, 0], [-1, 3, 1], [0, 5, 1]])
    updates = []
    baseline = core().project_pcd(source, tmp_path / 'baseline', parameters())
    result = core().project_pcd(source, tmp_path / 'progress', parameters(),
                                on_progress=lambda value, message: updates.append((value, message)))
    assert result == baseline
    assert (tmp_path / 'baseline/map.pgm').read_bytes() == (tmp_path / 'progress/map.pgm').read_bytes()
    values = [value for value, _ in updates]
    assert len(values) >= 4 and values == sorted(set(values))
    assert 0 < values[0] < values[-1] < 100
    assert any('栅格' in message for _, message in updates)
    assert any('保存' in message for _, message in updates)


@pytest.mark.parametrize("encoding", [Encoding.ASCII, Encoding.BINARY, Encoding.BINARY_COMPRESSED])
def test_real_encodings_preserve_origin_extrema_flip_and_unknown_cells(tmp_path, encoding):
    source = cloud(tmp_path, [[-2, 3, 0], [-1, 3, 1], [0, 5, 1]], encoding)
    result = core().project_pcd(source, tmp_path / "out", parameters())
    assert result["origin"] == [-2.0, 3.0, 0.0]
    assert (result["width"], result["height"]) == (3, 3)
    assert result["selected_points"] == 2
    assert result["occupied_cells"] == 2
    assert pixels(tmp_path / "out") == [[205, 205, 0], [205, 205, 205], [254, 0, 205]]
    metadata = yaml.safe_load((tmp_path / "out" / "map.yaml").read_text())
    assert metadata["image"] == "map.pgm"
    assert metadata["origin"] == [-2.0, 3.0, 0.0]
    assert metadata["resolution"] == 1.0
    assert all("path" not in key for key in result)


def test_analysis_uses_named_fields_and_discards_nonfinite_points(tmp_path):
    source = cloud(tmp_path, [[1, 9, -2, 3], [float("nan"), 8, 0, 4],
                              [2, 7, 0, 5]], fields=("z", "intensity", "x", "y"))
    result = core().analyze_pcd(source)
    assert result["point_count"] == 3
    assert result["finite_point_count"] == 2
    assert result["bounds"] == {"x": [-2.0, 0.0], "y": [3.0, 5.0], "z": [1.0, 2.0]}
    assert sum(result["z_histogram"]["counts"]) == 2
    assert result["warnings"]


def test_analysis_offers_multiple_horizontal_layers_as_uncertain_starting_points(tmp_path):
    ground = [[x, y, z] for z in (0, 3) for x in range(5) for y in range(5)]
    source = cloud(tmp_path, ground + [[0, 0, 1], [0, 0, 4]])
    result = core().analyze_pcd(source)
    assert any(abs(item["ground_z"]) < 0.15 for item in result["candidates"])
    assert any(abs(item["ground_z"] - 3) < 0.15 for item in result["candidates"])
    assert all(0 < item["confidence"] < 1 for item in result["candidates"])
    assert all(item["z_min"] < item["z_max"] for item in result["candidates"])
    assert result["warnings"]


def test_manual_absolute_height_is_not_constrained_to_recommended_bands(tmp_path):
    source = cloud(tmp_path, [[-0.2, -0.2, -100], [0.2, 0.2, -99]])
    result = core().project_pcd(source, tmp_path / "out", parameters(z_min=-100, z_max=-99))
    assert result["selected_points"] == 2
    assert result["origin"] == [-1.0, -1.0, 0.0]


def test_low_density_and_denoised_obstacles_remain_unknown(tmp_path):
    source = cloud(tmp_path, [[0, 0, 1], [1, 0, 1], [4, 0, 1], [6, 0, 0]])
    result = core().project_pcd(source, tmp_path / "out", parameters(denoise=True))
    assert result["occupied_cells"] == 2
    assert pixels(tmp_path / "out") == [[0, 0, 205, 205, 205, 205, 254]]
    result = core().project_pcd(source, tmp_path / "dense", parameters(min_points=2))
    assert result["occupied_cells"] == 0
    assert pixels(tmp_path / "dense") == [[205, 205, 205, 205, 205, 205, 254]]


@pytest.mark.parametrize("changes", [{"z_min": 2}, {"z_max": float("nan")},
    {"resolution": 0}, {"resolution": True}, {"min_points": 0},
    {"min_points": 1.5}, {"denoise": "false"}, {"extra": 1},
    {"resolution": 10 ** 400}])
def test_invalid_parameters_fail_before_writing(tmp_path, changes):
    source = cloud(tmp_path, [[0, 0, 1]])
    with pytest.raises(core().ProjectionError):
        core().project_pcd(source, tmp_path / "out", parameters(**changes))
    assert not (tmp_path / "out").exists()


def test_empty_slice_and_oversized_grid_are_rejected(tmp_path):
    source = cloud(tmp_path, [[0, 0, 1], [5000, 5000, 1]])
    with pytest.raises(core().ProjectionError):
        core().project_pcd(source, tmp_path / "out", parameters(z_min=10, z_max=11))
    with pytest.raises(core().ProjectionError):
        core().project_pcd(source, tmp_path / "out", parameters())


@pytest.mark.parametrize("mutation", ["points", "expanded", "compressed", "header", "truncated", "missing_xyz", "no_finite"])
def test_malformed_and_resource_exhaustion_inputs_are_rejected(tmp_path, mutation):
    source = cloud(tmp_path, [[0, 0, 1]], Encoding.BINARY_COMPRESSED)
    data = source.read_bytes()
    if mutation == "points":
        data = data.replace(b"POINTS 1\n", b"POINTS 10000001\n").replace(b"WIDTH 1\n", b"WIDTH 10000001\n")
    elif mutation == "expanded":
        data = data.replace(b"COUNT 1 1 1", b"COUNT 1 1 200000000")
    elif mutation == "compressed":
        start = data.index(b"DATA binary_compressed\n") + len(b"DATA binary_compressed\n")
        data = data[:start] + struct.pack("<II", 4, 600_000_000) + b"1234"
    elif mutation == "header":
        data = b"#" + b"x" * 70000 + b"\n" + data
    elif mutation == "truncated":
        data = data[:-1]
    elif mutation == "missing_xyz":
        data = data.replace(b"FIELDS x y z", b"FIELDS x y q")
    else:
        source = cloud(tmp_path, [[float("nan"), 0, 1]])
        data = source.read_bytes()
    source.write_bytes(data)
    with pytest.raises(core().ProjectionError):
        core().analyze_pcd(source)


def test_ascii_extra_rows_cannot_bypass_declared_point_limit(tmp_path):
    source = cloud(tmp_path, [[0, 0, 1]])
    source.write_bytes(source.read_bytes() + b"0 0 2\n")
    with pytest.raises(core().ProjectionError):
        core().analyze_pcd(source)


def test_ascii_accepts_standard_whitespace_between_numbers(tmp_path):
    source = cloud(tmp_path, [[0, 0, 0], [1, 2, 1]])
    data = source.read_bytes()
    header, payload = data.split(b"DATA ascii\n", 1)
    source.write_bytes(header + b"DATA ascii\n" + payload.replace(b" ", b"  \t "))
    result = core().project_pcd(source, tmp_path / "out", parameters())
    assert result["selected_points"] == 1
    assert pixels(tmp_path / "out") == [[205, 0], [205, 205], [254, 205]]


def test_decimal_grid_endpoints_use_their_expected_cells(tmp_path):
    source = tmp_path / "double.pcd"
    PointCloud.from_points(np.array([[0, 0, 1], [0.3, 0.3, 1]], dtype=np.float64),
                           ("x", "y", "z"), (np.float64,) * 3).save(source, Encoding.BINARY)
    result = core().project_pcd(source, tmp_path / "out", parameters(resolution=0.1))
    assert (result["width"], result["height"]) == (4, 4)
    assert pixels(tmp_path / "out")[0][3] == 0


def test_yaml_provenance_distinguishes_same_geometry_and_is_deterministic(tmp_path):
    source = cloud(tmp_path, [[0, 0, 0], [2, 2, 1], [0, 2, 1]])
    core().project_pcd(source, tmp_path / "first", parameters())
    core().project_pcd(source, tmp_path / "repeat", parameters())
    first_yaml = (tmp_path / "first" / "map.yaml").read_bytes()
    assert first_yaml == (tmp_path / "repeat" / "map.yaml").read_bytes()
    source = cloud(tmp_path, [[0, 0, 0], [2, 2, 1], [2, 0, 1]])
    core().project_pcd(source, tmp_path / "other", parameters())
    assert first_yaml != (tmp_path / "other" / "map.yaml").read_bytes()
    core().project_pcd(source, tmp_path / "different_slice", parameters(z_min=0, z_max=1))
    assert (tmp_path / "different_slice" / "map.yaml").read_bytes() != (tmp_path / "other" / "map.yaml").read_bytes()
    assert b"source_sha256" in first_yaml
    assert str(tmp_path).encode() not in first_yaml


def test_extreme_finite_coordinate_span_is_reported_as_projection_error(tmp_path):
    source = tmp_path / "extreme.pcd"
    PointCloud.from_points(np.array([[0, 0, -1e308], [1, 1, 1e308]], dtype=np.float64),
                           ("x", "y", "z"), (np.float64,) * 3).save(source, Encoding.BINARY)
    with pytest.raises(core().ProjectionError):
        core().analyze_pcd(source)


def test_source_sample_is_bounded_deterministic_finite_and_preserves_original(tmp_path):
    points = np.zeros((100_003, 3), dtype=np.float32)
    points[:, 0] = np.arange(len(points))
    points[:, 2] = 1
    points[-1] = [np.nan, 0, 1]
    source = cloud(tmp_path, points, Encoding.BINARY)
    original = source.read_bytes()
    first, repeat = tmp_path / "sample.bin", tmp_path / "repeat.bin"
    result = core().analyze_pcd(source, preview_output=first)
    core().analyze_pcd(source, preview_output=repeat)
    metadata = result["source_preview"]
    assert metadata["point_count"] == 100_000
    assert metadata["source_point_count"] == 100_003
    assert metadata["finite_point_count"] == 100_002
    assert metadata["origin"] == [50_000.5, 0.0, 1.0]
    assert metadata["bounds"] == [[0.0, 100_001.0], [0.0, 0.0], [1.0, 1.0]]
    data = np.frombuffer(first.read_bytes(), dtype="<f4").reshape(-1, 3)
    assert data.shape == (100_000, 3)
    assert np.isfinite(data).all()
    assert data[0].tolist() == [-50_000.5, 0, 0]
    assert data[-1].tolist() == [50_000.5, 0, 0]
    assert first.read_bytes() == repeat.read_bytes()
    assert source.read_bytes() == original


def test_source_sample_centers_large_world_coordinates_before_float32(tmp_path):
    source = tmp_path / "large-offset.pcd"
    points = np.array([[1e9, -1e9, 1e6], [1e9 + 0.25, -1e9 + 0.5, 1e6 + 1]], dtype=np.float64)
    PointCloud.from_points(points, ("x", "y", "z"), (np.float64,) * 3).save(source, Encoding.BINARY)
    output = tmp_path / "sample.bin"
    result = core().analyze_pcd(source, preview_output=output)
    assert result["source_preview"]["origin"] == [1e9 + 0.125, -1e9 + 0.25, 1e6 + 0.5]
    assert np.frombuffer(output.read_bytes(), dtype="<f4").reshape(-1, 3).tolist() == [
        [-0.125, -0.25, -0.5], [0.125, 0.25, 0.5]]


def test_same_source_reuses_bounded_read_only_xyz_and_invalidates_after_replacement(tmp_path, monkeypatch):
    module=core()
    source=cloud(tmp_path, [[0,0,0],[1,1,1]], Encoding.BINARY)
    original_loader=module.PointCloud.from_fileobj
    reads=[]
    def counted(fp):
        reads.append(1)
        return original_loader(fp)
    monkeypatch.setattr(module.PointCloud,'from_fileobj',counted)
    first=module._load(source)
    second=module._load(source)
    assert len(reads)==1 and first[0] is second[0]
    assert first[0].flags.writeable is False
    PointCloud.from_xyz_points(np.array([[0,0,0],[2,2,2]],dtype='f4')).save(source,Encoding.BINARY)
    third=module._load(source)
    assert len(reads)==2 and third[2]!=first[2]
    assert third[0][1].tolist()==[2,2,2]


def test_read_access_timestamp_change_does_not_invalidate_source(tmp_path, monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace
    module = core()
    source = cloud(tmp_path, [[0,0,0],[1,1,1]], Encoding.BINARY)
    real_stat = Path.stat
    calls = 0
    def accessed(path, *args, **kwargs):
        nonlocal calls
        stamp = real_stat(path, *args, **kwargs)
        if path == source:
            calls += 1
            values = {name: getattr(stamp, name) for name in dir(stamp) if name.startswith('st_')}
            # Simulate only the access time changing on a read.
            values['st_atime'] += calls
            values['st_atime_ns'] += calls * 1_000_000_000
            return SimpleNamespace(**values)
        return stamp
    monkeypatch.setattr(Path, 'stat', accessed)
    assert module._load(source)[0].tolist() == [[0,0,0],[1,1,1]]


def test_projection_geometry_reuses_only_current_source_and_resolution(tmp_path):
    module = core()
    source = cloud(tmp_path, [[-2,3,0],[-1,3,1],[0,5,2]], Encoding.BINARY)
    xyz = module._load(source)[0]
    first = module._projection_geometry(xyz, 1.0)
    repeat = module._projection_geometry(xyz, 1.0)
    assert first is repeat
    width, height, origin, indices = first
    assert (width, height, origin.tolist(), indices.tolist()) == (3,3,[-2,3],[0,1,8])
    assert not indices.flags.writeable
    coarse = module._projection_geometry(xyz, 2.0)
    assert (coarse[0],coarse[1],coarse[2].tolist(),coarse[3].tolist()) == (2,2,[-2,2],[0,0,3])
    # Source replacement must not use the previous file's cached pixel indices.
    cloud(tmp_path, [[-2,3,0],[-1,3,1],[0,4,2]], Encoding.BINARY)
    fresh = module._projection_geometry(module._load(source)[0], 1.0)
    assert (fresh[0],fresh[1],fresh[3].tolist()) == (3,2,[0,1,5])


def test_chunked_grid_indices_keep_decimal_extrema_and_point_order(monkeypatch):
    module = core()
    monkeypatch.setattr(module, '_POINT_CHUNK', 7)
    xyz = np.tile(np.array([[0,0,1],[.3,.3,1],[.1,.2,1]],dtype=np.float64),(11,1))
    indices = module._grid_indices(xyz, np.array([0.,0.]), .1, 4, 4)
    assert indices.tolist() == [0,15,9]*11


def test_cached_geometry_does_not_cache_height_density_or_denoise(tmp_path):
    source = cloud(tmp_path, [[0,0,0],[1,0,1],[1,0,1],[2,0,2]], Encoding.BINARY)
    cases = [({'z_min':.5,'z_max':1.5},[[254,0,254]]),
             ({'z_min':1.5,'z_max':2.5},[[254,254,0]]),
             ({'z_min':1.5,'z_max':2.5,'min_points':2},[[254,254,205]]),
             ({'z_min':1.5,'z_max':2.5,'denoise':True},[[254,254,205]])]
    for i,(changes,want) in enumerate(cases):
        output = tmp_path / str(i)
        core().project_pcd(source, output, parameters(**changes))
        assert pixels(output) == want
