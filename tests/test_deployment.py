import io
import json
from email.message import Message
from http import HTTPStatus
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

import web_console
from autodrive_console.deployment import DeploymentError, DeploymentStore


def _map(directory: Path) -> Path:
    directory.mkdir(parents=True)
    (directory / "map.pgm").write_bytes(b"P5\n2 2\n255\n\x00\xff\x80\x40")
    (directory / "map.yaml").write_text("image: map.pgm\nresolution: 0.05\norigin: [-1.0, -2.0, 0.0]\n", encoding="utf-8")
    (directory / "map_walls.yaml").write_text("virtual_walls:\n  coordinate_mode: world\n", encoding="utf-8")
    (directory / "0.pcd").write_text("# pcd fixture\n", encoding="utf-8")
    return directory / "map.yaml"


def test_project_imports_a_snapshot_without_modifying_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source_root = tmp_path / "robot-maps"
    source = _map(source_root / "site" / "P1")
    monkeypatch.setattr(DeploymentStore, "MAP_ROOT", source_root.resolve())
    store = DeploymentStore(tmp_path / "deployments")

    project = store.create("XX 花园")
    asset = store.import_map(project["id"], source, "大厅", "lobby")

    loaded = store.get(project["id"])
    assert asset["resolution_m"] == 0.05
    assert asset["files"]["pcd_count"] == 1
    assert len(loaded["map_assets"]) == 1
    assert store.map_image(project["id"], asset["id"]).read_bytes() == (source.parent / "map.pgm").read_bytes()
    assert source.exists()

    instance = store.add_map_instance(project["id"], {"map_id": asset["id"], "role": "lobby", "building": "2", "unit": "1", "floor": 1})
    waypoint = store.add_waypoint(project["id"], {"map_id": asset["id"], "kind": "start", "label": "起点", "x": -0.95, "y": -1.95})
    assert instance["map_asset_id"] == asset["id"]
    assert waypoint["kind"] == "start"
    store.delete_waypoint(project["id"], waypoint["id"])
    assert store.get(project["id"])["waypoints"] == []

    edited = store.update_map_edits(
        project["id"],
        {
            "action": "add",
            "map_id": asset["id"],
            "kind": "brush_erase",
            "radius_m": 0.2,
            "shape": "square",
            "points": [{"x": -0.98, "y": -1.98}, {"x": -0.93, "y": -1.93}],
        },
    )
    assert edited["map_edits"][0]["kind"] == "brush_erase"
    assert edited["map_edits"][0]["shape"] == "square"
    edited = store.update_map_edits(project["id"], {"action": "undo", "map_id": asset["id"]})
    assert edited["map_edits"] == []


def test_map_import_rejects_paths_outside_robot_map_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    allowed = tmp_path / "allowed"
    outside = _map(tmp_path / "outside")
    monkeypatch.setattr(DeploymentStore, "MAP_ROOT", allowed.resolve())
    store = DeploymentStore(tmp_path / "deployments")
    project = store.create("项目")
    with pytest.raises(DeploymentError, match="/opt/ry/data/maps"):
        store.import_map(project["id"], outside, "外部", "outdoor")


def test_uploaded_client_map_is_snapshotted_without_requiring_robot_map_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Prevents browser-selected maps from being rejected as robot-local files."""
    robot_root = tmp_path / "robot-maps"
    upload_root = tmp_path / "browser-upload"
    source = _map(upload_root / "客户电脑地图" / "P1")
    monkeypatch.setattr(DeploymentStore, "MAP_ROOT", robot_root.resolve())
    store = DeploymentStore(tmp_path / "deployments")
    project = store.create("客户端导入")

    asset = store.import_uploaded_map(
        project["id"], source, "客户大厅", "lobby", upload_root
    )

    assert asset["label"] == "客户大厅"
    assert asset["source_yaml"] == str(source.resolve())
    assert store.map_image(project["id"], asset["id"]).read_bytes() == (source.parent / "map.pgm").read_bytes()


def test_browser_folder_upload_creates_a_project_map_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Exercises the actual multipart boundary instead of trusting browser-side file names."""
    store = DeploymentStore(tmp_path / "deployments")
    project = store.create("浏览器文件夹导入")
    boundary = "----AletheiaMapUpload"
    body = b"".join([
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"map_yaml\"\r\n\r\nP1/map.yaml\r\n".encode(),
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"label\"\r\n\r\n远程大厅\r\n".encode(),
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"kind\"\r\n\r\nlobby\r\n".encode(),
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"P1/map.yaml\"\r\nContent-Type: application/octet-stream\r\n\r\n".encode(),
        b"image: map.pgm\nresolution: 0.05\norigin: [-1.0, -2.0, 0.0]\n\r\n",
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"P1/map.pgm\"\r\nContent-Type: application/octet-stream\r\n\r\n".encode(),
        b"P5\n2 2\n255\n\x00\xff\x80\x40\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    handler = object.__new__(web_console.ConsoleHandler)
    headers = Message()
    headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    headers["Content-Length"] = str(len(body))
    handler.headers = headers
    handler.rfile = io.BytesIO(body)
    handler._json = Mock()

    with patch.object(web_console, "DEPLOYMENTS", store):
        handler._upload_deployment_map(project["id"])

    payload, status = handler._json.call_args.args
    assert status == HTTPStatus.CREATED, payload
    assert payload["map"]["label"] == "远程大厅"
    assert store.map_image(project["id"], payload["map"]["id"]).read_bytes() == b"P5\n2 2\n255\n\x00\xff\x80\x40"


def test_semantic_component_derives_task_points_and_virtual_wall(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "maps"; source = _map(root / "P1")
    monkeypatch.setattr(DeploymentStore, "MAP_ROOT", root.resolve())
    store = DeploymentStore(tmp_path / "deployments"); project = store.create("测试")
    asset = store.import_map(project["id"], source, "大厅", "lobby")
    elevator = store.add_component(project["id"], {"map_id": asset["id"], "kind": "start", "label": "出发点", "x": -0.95, "y": -1.95})
    assert len(elevator["generated_waypoint_ids"]) == 1
    wall = store.add_virtual_wall(project["id"], {"map_id": asset["id"], "points": [{"x": -0.99, "y": -1.99}, {"x": -0.9, "y": -1.99}, {"x": -0.9, "y": -1.9}]})
    assert wall["kind"] == "forbidden_zone"
    assert len(store.get(project["id"])["waypoints"]) == 1


def test_elevator_attributes_calculate_physical_floor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "maps"
    source = _map(root / "P1")
    (source.parent / "map.pgm").write_bytes(b"P5\n40 40\n255\n" + bytes(40 * 40))
    source.write_text(
        "image: map.pgm\nresolution: 0.05\norigin: [-2.0, -2.0, 0.0]\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(DeploymentStore, "MAP_ROOT", root.resolve())
    store = DeploymentStore(tmp_path / "deployments")
    project = store.create("电梯楼层测试")
    asset = store.import_map(project["id"], source, "大厅", "lobby")

    elevator = store.add_component(
        project["id"],
        {
            "map_id": asset["id"],
            "kind": "elevator",
            "x": -1.0,
            "y": -1.0,
            "attributes": {
                "elevator_id": "E-01",
                "min_floor": -2,
                "max_floor": 32,
                "map_floor": 1,
            },
        },
    )

    assert elevator["label"] == "电梯"
    assert elevator["attributes"]["physical_floor"] == 2
    updated = store.update_component(
        project["id"], elevator["id"], {"attributes": {"map_floor": 5}}
    )
    assert updated["attributes"]["physical_floor"] == 6
    with pytest.raises(DeploymentError, match="当前地图所在楼层"):
        store.update_component(
            project["id"], elevator["id"], {"attributes": {"map_floor": 33}}
        )
    with pytest.raises(DeploymentError, match="通信协议"):
        store.update_component(
            project["id"],
            elevator["id"],
            {"attributes": {"elevator_protocol": "unconfigured"}},
        )


def test_project_protocol_templates_start_with_bluetooth_and_4g(tmp_path: Path):
    store = DeploymentStore(tmp_path / "deployments")
    project = store.create("协议模板测试")

    templates = project["component_templates"]
    assert [item["id"] for item in templates["access_protocols"]] == ["bluetooth", "4g"]
    assert [item["label"] for item in templates["elevator_protocols"]] == ["蓝牙", "4G"]

    updated = store.add_component_protocol(project["id"], "elevator_protocols", "厂商专线")
    added = updated["component_templates"]["elevator_protocols"][-1]
    assert added["label"] == "厂商专线"
    updated = store.remove_component_protocol(project["id"], "elevator_protocols", added["id"])
    assert [item["id"] for item in updated["component_templates"]["elevator_protocols"]] == ["bluetooth", "4g"]


def _project_with_distinct_maps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, count: int):
    """Create distinct map snapshots so their content-addressed IDs differ."""
    root = tmp_path / "stage-maps"
    monkeypatch.setattr(DeploymentStore, "MAP_ROOT", root.resolve())
    store = DeploymentStore(tmp_path / "deployments")
    project = store.create("阶段拓扑测试")
    assets = []
    for index in range(count):
        source = _map(root / f"P{index + 1}")
        source.with_name("map.pgm").write_bytes(
            b"P5\n2 2\n255\n" + bytes((index, 255 - index, 128, 64))
        )
        # DeploymentStore uses the YAML hash for the map ID; retain valid map
        # metadata while making each fixture represent a distinct source map.
        source.write_text(
            source.read_text(encoding="utf-8") + f"# fixture-map-{index}\n",
            encoding="utf-8",
        )
        assets.append(store.import_map(project["id"], source, f"地图 {index + 1}", "custom"))
    return store, project, assets


def test_stage_plan_assigns_maps_in_scene_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Fails if the project cannot represent its required map-stage order."""
    store, project, assets = _project_with_distinct_maps(tmp_path, monkeypatch, 3)
    store.set_scene_model(project["id"], "indoor_outdoor")

    assert store.stage_plan(project["id"])["current_stage"] == "outdoor"
    store.assign_map_stage(project["id"], assets[0]["id"], "outdoor")
    store.assign_map_stage(project["id"], assets[1]["id"], "lobby")
    plan = store.assign_map_stage(project["id"], assets[2]["id"], "target_floor")

    assert [item["stage"] for item in plan["stages"]] == [
        "outdoor",
        "lobby",
        "target_floor",
    ]
    assert plan["current_stage"] is None


def test_stage_assignment_rejects_duplicate_map_and_invalid_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Fails if one map can occupy two stages or bypass the selected model."""
    store, project, assets = _project_with_distinct_maps(tmp_path, monkeypatch, 2)
    store.set_scene_model(project["id"], "indoor")
    store.assign_map_stage(project["id"], assets[0]["id"], "lobby")

    with pytest.raises(DeploymentError, match="已绑定"):
        store.assign_map_stage(project["id"], assets[0]["id"], "target_floor")
    with pytest.raises(DeploymentError, match="不属于当前场景模型"):
        store.assign_map_stage(project["id"], assets[1]["id"], "outdoor")


def _three_stage_project_with_transition_points(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store, project, maps = _project_with_distinct_maps(tmp_path, monkeypatch, 3)
    store.set_scene_model(project["id"], "indoor_outdoor")
    for stage, asset in zip(("outdoor", "lobby", "target_floor"), maps):
        store.assign_map_stage(project["id"], asset["id"], stage)
    points = {}
    for index, asset in enumerate(maps):
        entry = store.add_waypoint(
            project["id"],
            {"map_id": asset["id"], "kind": "map_transition", "label": f"阶段{index + 1}入口", "x": -0.99, "y": -1.99},
        )
        exit_point = store.add_waypoint(
            project["id"],
            {"map_id": asset["id"], "kind": "map_transition", "label": f"阶段{index + 1}出口", "x": -0.91, "y": -1.91},
        )
        points[f"{index}-entry"] = entry["id"]
        points[f"{index}-exit"] = exit_point["id"]
    return store, project, maps, points


def test_transition_links_adjacent_assigned_maps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Fails if adjacent-map hand-offs cannot be persisted with waypoint references."""
    store, project, maps, points = _three_stage_project_with_transition_points(tmp_path, monkeypatch)

    transition = store.add_map_transition(
        project["id"],
        {
            "from_map_asset_id": maps[0]["id"],
            "from_waypoint_id": points["0-exit"],
            "to_map_asset_id": maps[1]["id"],
            "to_waypoint_id": points["1-entry"],
            "label": "室外至大厅",
        },
    )

    assert transition["from_map_asset_id"] == maps[0]["id"]
    assert store.get(project["id"])["map_transitions"] == [transition]


def test_transition_rejects_same_map_and_skipped_stage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Fails if a transition permits one coordinate system or skips an intermediate map."""
    store, project, maps, points = _three_stage_project_with_transition_points(tmp_path, monkeypatch)

    with pytest.raises(DeploymentError, match="不同地图"):
        store.add_map_transition(
            project["id"],
            {
                "from_map_asset_id": maps[0]["id"],
                "from_waypoint_id": points["0-exit"],
                "to_map_asset_id": maps[0]["id"],
                "to_waypoint_id": points["0-entry"],
            },
        )
    with pytest.raises(DeploymentError, match="相邻阶段"):
        store.add_map_transition(
            project["id"],
            {
                "from_map_asset_id": maps[0]["id"],
                "from_waypoint_id": points["0-exit"],
                "to_map_asset_id": maps[2]["id"],
                "to_waypoint_id": points["2-entry"],
            },
        )


def test_route_is_limited_to_one_map(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Fails if a visual route can silently join Waypoints from different PGM maps."""
    store, project, maps, points = _three_stage_project_with_transition_points(tmp_path, monkeypatch)

    route = store.save_route(
        project["id"],
        {
            "map_asset_id": maps[1]["id"],
            "label": "大厅路线",
            "waypoint_ids": [points["1-entry"], points["1-exit"]],
        },
    )

    assert route["waypoint_ids"] == [points["1-entry"], points["1-exit"]]
    with pytest.raises(DeploymentError, match="同一张地图"):
        store.save_route(
            project["id"],
            {
                "map_asset_id": maps[1]["id"],
                "label": "错误路线",
                "waypoint_ids": [points["1-entry"], points["2-entry"]],
            },
        )


def test_topology_reports_broken_chain_then_accepts_complete_three_map_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Fails if deployment preview mistakes imported maps for a complete delivery chain."""
    store, project, maps, points = _three_stage_project_with_transition_points(tmp_path, monkeypatch)

    broken = store.validate_topology(project["id"])
    assert not broken["valid"]
    assert any("Transition" in error for error in broken["errors"])

    store.add_waypoint(
        project["id"],
        {"map_id": maps[0]["id"], "kind": "start", "label": "配送起点", "x": -0.98, "y": -1.98},
    )
    store.add_waypoint(
        project["id"],
        {"map_id": maps[2]["id"], "kind": "target", "label": "配送目标", "x": -0.92, "y": -1.92},
    )
    store.add_map_transition(
        project["id"],
        {
            "from_map_asset_id": maps[0]["id"],
            "from_waypoint_id": points["0-exit"],
            "to_map_asset_id": maps[1]["id"],
            "to_waypoint_id": points["1-entry"],
        },
    )
    store.add_map_transition(
        project["id"],
        {
            "from_map_asset_id": maps[1]["id"],
            "from_waypoint_id": points["1-exit"],
            "to_map_asset_id": maps[2]["id"],
            "to_waypoint_id": points["2-entry"],
        },
    )

    topology = store.validate_topology(project["id"])
    assert topology["valid"]
    assert all(stage["status"] == "complete" for stage in topology["stages"])


def _deployment_handler(path: str, payload: dict | None = None):
    handler = object.__new__(web_console.ConsoleHandler)
    handler.path = path
    encoded = json.dumps(payload or {}).encode("utf-8")
    handler.headers = {"Content-Length": str(len(encoded))}
    handler.rfile = io.BytesIO(encoded)
    handler._json = Mock()
    return handler


def test_topology_http_request_uses_store_without_ros():
    """Fails if the topology URL is interpreted as a project ID instead of a read-only Store call."""
    handler = _deployment_handler("/api/deployments/site/topology")
    expected = {"valid": False, "errors": ["缺少地图"], "stages": []}

    with patch.object(web_console.DEPLOYMENTS, "validate_topology", return_value=expected) as validate:
        handler.do_GET()

    validate.assert_called_once_with("site")
    assert handler._json.call_args.args == ({"topology": expected},)


def test_transition_http_rejects_invalid_store_input():
    """Fails if a malformed transition bypasses DeploymentStore validation."""
    handler = _deployment_handler(
        "/api/deployments/site/transitions", {"from_waypoint_id": "missing"}
    )
    with patch.object(
        web_console.DEPLOYMENTS,
        "add_map_transition",
        side_effect=DeploymentError("Transition Waypoint 不存在"),
    ):
        handler.do_POST()

    assert handler._json.call_args.args[1] == HTTPStatus.BAD_REQUEST
    assert "error" in handler._json.call_args.args[0]
