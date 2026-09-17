import io
import json
from email.message import Message
from http import HTTPStatus
from pathlib import Path
from unittest.mock import Mock, patch
from zipfile import ZipFile

import pytest

import web_console
from autodrive_console.deployment import DeploymentError, DeploymentStore
from autodrive_console.task_compiler import CompilationError


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


def _localization_binding_payload(
    map_asset_id: str,
    *,
    building: str = "1",
    unit: str = "1",
    binding_type: str = "indoor",
    floor_template: str | None = None,
) -> dict:
    payload = {
        "map_asset_id": map_asset_id,
        "building": building,
        "unit": unit,
        "type": binding_type,
    }
    if floor_template is not None:
        payload["floor_template"] = floor_template
    return payload


def test_localization_binding_allows_distinct_floor_templates_but_not_duplicate_indoor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Catches collapsing independently deployable floor templates into one binding."""
    map_root = tmp_path / "maps"
    first, second = _map(map_root / "site" / "first"), _map(map_root / "site" / "second")
    second.write_text(second.read_text(encoding="utf-8") + "# distinct fixture\n", encoding="utf-8")
    monkeypatch.setattr(DeploymentStore, "MAP_ROOT", map_root.resolve())
    store = DeploymentStore(tmp_path / "deployments")
    project = store.create("定位绑定")
    first_asset = store.import_map(project["id"], first, "大厅", "lobby")
    second_asset = store.import_map(project["id"], second, "用户层", "typical_floor")

    store.create_localization_binding(
        project["id"], _localization_binding_payload(first_asset["id"])
    )
    with pytest.raises(DeploymentError, match="indoor"):
        store.create_localization_binding(
            project["id"], _localization_binding_payload(second_asset["id"])
        )

    first_floor = store.create_localization_binding(
        project["id"],
        _localization_binding_payload(
            first_asset["id"], binding_type="floor", floor_template="2"
        ),
    )
    second_floor = store.create_localization_binding(
        project["id"],
        _localization_binding_payload(
            second_asset["id"], binding_type="floor", floor_template="3"
        ),
    )

    assert first_floor["floor_template"] == "2"
    assert second_floor["floor_template"] == "3"


def test_localization_binding_rejects_legacy_manual_initialization_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Catches accepting route-owned initialization data on a new binding."""
    map_root = tmp_path / "maps"
    source = _map(map_root / "site" / "first")
    monkeypatch.setattr(DeploymentStore, "MAP_ROOT", map_root.resolve())
    store = DeploymentStore(tmp_path / "deployments")
    project = store.create("定位边界")
    asset = store.import_map(project["id"], source, "大厅", "lobby")

    payload = _localization_binding_payload(asset["id"])
    payload["init_go"] = {"x": 9999, "y": -1.95, "z": 0.0, "yaw": 0.0}
    with pytest.raises(DeploymentError, match="未批准字段"):
        store.create_localization_binding(
            project["id"], payload
        )


def test_elevator_landing_rejects_zero_as_a_panel_button(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Catches accepting the skipped zero button as an elevator landing level."""
    map_root = tmp_path / "maps"
    source = _map(map_root / "site" / "lobby")
    source.write_text("image: map.pgm\nresolution: 1.0\norigin: [-1.0, -2.0, 0.0]\n", encoding="utf-8")
    monkeypatch.setattr(DeploymentStore, "MAP_ROOT", map_root.resolve())
    store = DeploymentStore(tmp_path / "deployments")
    project = store.create("电梯按钮")
    asset = store.import_map(project["id"], source, "大厅", "lobby")
    elevator = store.add_physical_elevator(
        project["id"],
        {"elevator_id": "A", "elevator_protocol": "bluetooth", "min_floor": -2, "max_floor": 25},
    )

    with pytest.raises(DeploymentError, match="按钮 0"):
        store.add_component(
            project["id"],
            {
                "map_id": asset["id"],
                "kind": "elevator",
                "x": 0.0,
                "y": -1.0,
                "attributes": {
                    "physical_elevator_id": elevator["id"],
                    "button_floor": 0,
                },
            },
        )


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
    assert Path(asset["source_yaml"]).is_relative_to(store._project_dir(project["id"]) / "maps")
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


def test_elevator_landing_keeps_local_geometry_and_references_shared_elevator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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
    shared = store.add_physical_elevator(
        project["id"],
        {
            "elevator_id": "E-01",
            "elevator_protocol": "bluetooth",
            "min_floor": -2,
            "max_floor": 32,
        },
    )

    elevator = store.add_component(
        project["id"],
        {
            "map_id": asset["id"],
            "kind": "elevator",
            "x": -1.0,
            "y": -1.0,
            "attributes": {
                "physical_elevator_id": shared["id"],
                "wait_distance_m": 1.5,
            },
        },
    )

    assert elevator["label"] == "电梯"
    assert elevator["attributes"]["physical_elevator_id"] == shared["id"]
    assert "elevator_protocol" not in elevator["attributes"]
    updated = store.update_component(
        project["id"], elevator["id"], {"attributes": {"wait_distance_m": 2.0}}
    )
    assert updated["attributes"]["wait_distance_m"] == 2.0
    with pytest.raises(DeploymentError, match="候梯距离"):
        store.update_component(
            project["id"], elevator["id"], {"attributes": {"wait_distance_m": 0.4}}
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


def test_new_elevator_uses_the_first_configured_lift_protocol(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "maps"
    source = _map(root / "P1")
    (source.parent / "map.pgm").write_bytes(b"P5\n40 40\n255\n" + bytes(40 * 40))
    source.write_text(
        "image: map.pgm\nresolution: 0.05\norigin: [-2.0, -2.0, 0.0]\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(DeploymentStore, "MAP_ROOT", root.resolve())
    store = DeploymentStore(tmp_path / "deployments")
    project = store.create("自定义梯控协议")
    mqtt = store.add_component_protocol(project["id"], "elevator_protocols", "MQTT")
    mqtt_id = mqtt["component_templates"]["elevator_protocols"][-1]["id"]
    store.add_component_protocol(project["id"], "elevator_protocols", "LoRa")
    store.remove_component_protocol(project["id"], "elevator_protocols", "bluetooth")
    store.remove_component_protocol(project["id"], "elevator_protocols", "4g")
    asset = store.import_map(project["id"], source, "15F", "typical_floor")

    shared = store.add_physical_elevator(
        project["id"],
        {
            "elevator_id": "E-01",
            "elevator_protocol": mqtt_id,
            "min_floor": 1,
            "max_floor": 15,
        },
    )
    elevator = store.add_component(
        project["id"],
        {
            "map_id": asset["id"],
            "kind": "elevator",
            "x": -1.0,
            "y": -1.0,
            "attributes": {"physical_elevator_id": shared["id"]},
        },
    )

    assert elevator["attributes"]["physical_elevator_id"] == shared["id"]
    assert store.get(project["id"])["physical_elevators"][0]["elevator_protocol"] == mqtt_id


def test_legacy_elevator_landings_migrate_to_one_shared_physical_elevator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "maps"
    source = _map(root / "P1")
    monkeypatch.setattr(DeploymentStore, "MAP_ROOT", root.resolve())
    store = DeploymentStore(tmp_path / "deployments")
    project = store.create("旧项目电梯迁移")
    asset = store.import_map(project["id"], source, "大厅", "lobby")
    document = store.get(project["id"])
    document["components"] = [
        {
            "id": "component-lobby-elevator",
            "map_asset_id": asset["id"],
            "kind": "elevator",
            "label": "电梯",
            "x": -0.8,
            "y": -1.2,
            "yaw": 0.0,
            "attributes": {
                "elevator_id": "10014",
                "elevator_protocol": "bluetooth",
                "min_floor": 1,
                "max_floor": 15,
                "map_floor": 1,
                "wait_distance_m": 1.5,
            },
            "generated_waypoint_ids": [],
        },
        {
            "id": "component-target-elevator",
            "map_asset_id": asset["id"],
            "kind": "elevator",
            "label": "电梯",
            "x": -0.2,
            "y": -1.6,
            "yaw": 3.141592653589793,
            "attributes": {
                "elevator_id": "10014",
                "elevator_protocol": "bluetooth",
                "min_floor": 1,
                "max_floor": 15,
                "map_floor": 15,
                "wait_distance_m": 2.0,
            },
            "generated_waypoint_ids": [],
        },
    ]
    document.pop("physical_elevators", None)
    store._write_json(store._document_path(project["id"]), document)

    migrated = store.get(project["id"])

    assert len(migrated["physical_elevators"]) == 1
    shared_id = migrated["physical_elevators"][0]["id"]
    assert {
        item["attributes"]["physical_elevator_id"]
        for item in migrated["components"]
    } == {shared_id}
    assert [item["yaw"] for item in migrated["components"]] == [0.0, 3.141592653589793]
    assert [item["attributes"]["wait_distance_m"] for item in migrated["components"]] == [1.5, 2.0]


def test_migration_links_one_unambiguous_legacy_landing_to_the_only_shared_elevator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "maps"
    first = _map(root / "P1")
    second = _map(root / "P2")
    second.write_text(
        "image: map.pgm\nresolution: 0.05\norigin: [-1.0, -2.0, 0.0]\n# second map\n",
        encoding="utf-8",
    )
    for source in (first, second):
        source.with_name("map.pgm").write_bytes(b"P5\n100 100\n255\n" + bytes(100 * 100))
    monkeypatch.setattr(DeploymentStore, "MAP_ROOT", root.resolve())
    store = DeploymentStore(tmp_path / "deployments")
    project = store.create("补全旧电梯落点")
    first_map = store.import_map(project["id"], first, "大厅", "lobby")
    second_map = store.import_map(project["id"], second, "目标层", "typical_floor")
    shared = store.add_physical_elevator(
        project["id"],
        {"elevator_id": "10014", "elevator_protocol": "bluetooth", "min_floor": 1, "max_floor": 15},
    )
    linked = store.add_component(
        project["id"],
        {"map_id": first_map["id"], "kind": "elevator", "x": 0.0, "y": 0.0, "attributes": {"physical_elevator_id": shared["id"]}},
    )
    document_path = store._document_path(project["id"])
    document = json.loads(document_path.read_text(encoding="utf-8"))
    document["components"].append(
        {
            "id": "legacy-target-elevator",
            "map_asset_id": second_map["id"],
            "kind": "elevator",
            "label": "电梯",
            "x": 0.5,
            "y": 0.5,
            "yaw": 3.141592653589793,
            "attributes": {"width_m": 1.8, "height_m": 2.0, "wait_distance_m": 1.5},
            "generated_waypoint_ids": [],
        }
    )
    document_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    migrated = store.get(project["id"])

    legacy = next(item for item in migrated["components"] if item["id"] == "legacy-target-elevator")
    assert linked["attributes"]["physical_elevator_id"] == shared["id"]
    assert legacy["attributes"]["physical_elevator_id"] == shared["id"]
    assert legacy["yaw"] == 3.141592653589793


def test_physical_elevator_identifier_is_unique_within_a_project(tmp_path: Path):
    store = DeploymentStore(tmp_path / "deployments")
    project = store.create("共享电梯编号")
    first = store.add_physical_elevator(
        project["id"],
        {
            "elevator_id": "10014",
            "elevator_protocol": "bluetooth",
            "min_floor": 1,
            "max_floor": 15,
        },
    )

    assert first["elevator_id"] == "10014"
    with pytest.raises(DeploymentError, match="电梯编号已存在"):
        store.add_physical_elevator(
            project["id"],
            {
                "elevator_id": "10014",
                "elevator_protocol": "bluetooth",
                "min_floor": 1,
                "max_floor": 15,
            },
        )


def test_updating_a_physical_elevator_requires_an_object_payload(tmp_path: Path):
    store = DeploymentStore(tmp_path / "deployments")
    project = store.create("共享电梯参数")
    elevator = store.add_physical_elevator(
        project["id"],
        {
            "elevator_id": "10014",
            "elevator_protocol": "bluetooth",
            "min_floor": 1,
            "max_floor": 15,
        },
    )

    with pytest.raises(DeploymentError, match="物理电梯属性无效"):
        store.update_physical_elevator(project["id"], elevator["id"], ["invalid"])


def test_elevator_landings_must_reference_one_existing_shared_elevator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "maps"
    first_source = _map(root / "P1")
    second_source = _map(root / "P2")
    for floor, source in (("P1", first_source), ("P2", second_source)):
        (source.parent / "map.pgm").write_bytes(b"P5\n40 40\n255\n" + bytes(40 * 40))
        source.write_text(
            f"image: map.pgm\nresolution: 0.05\norigin: [-2.0, -2.0, 0.0]\n# {floor}\n",
            encoding="utf-8",
        )
    monkeypatch.setattr(DeploymentStore, "MAP_ROOT", root.resolve())
    store = DeploymentStore(tmp_path / "deployments")
    project = store.create("共享电梯落点")
    first_map = store.import_map(project["id"], first_source, "大厅", "lobby")
    second_map = store.import_map(project["id"], second_source, "15F", "typical_floor")
    elevator = store.add_physical_elevator(
        project["id"],
        {
            "elevator_id": "10014",
            "elevator_protocol": "bluetooth",
            "min_floor": 1,
            "max_floor": 15,
        },
    )

    first_landing = store.add_component(
        project["id"],
        {
            "map_id": first_map["id"],
            "kind": "elevator",
            "x": -1.0,
            "y": -1.0,
            "yaw": 0.0,
            "attributes": {"physical_elevator_id": elevator["id"], "wait_distance_m": 1.5},
        },
    )
    second_landing = store.add_component(
        project["id"],
        {
            "map_id": second_map["id"],
            "kind": "elevator",
                "x": -0.5,
                "y": -0.5,
            "yaw": 3.141592653589793,
            "attributes": {"physical_elevator_id": elevator["id"], "wait_distance_m": 2.0},
        },
    )

    assert first_landing["attributes"]["physical_elevator_id"] == elevator["id"]
    assert second_landing["attributes"]["physical_elevator_id"] == elevator["id"]
    assert [first_landing["yaw"], second_landing["yaw"]] == [0.0, 3.141592653589793]
    with pytest.raises(DeploymentError, match="物理电梯不存在"):
        store.add_component(
            project["id"],
            {
                "map_id": second_map["id"],
                "kind": "elevator",
                    "x": -1.0,
                    "y": -1.0,
                "attributes": {"physical_elevator_id": "physical-elevator-missing"},
            },
        )
    with pytest.raises(DeploymentError, match="正在被物理电梯使用"):
        store.remove_component_protocol(project["id"], "elevator_protocols", "bluetooth")
    with pytest.raises(DeploymentError, match="物理电梯仍有地图落点"):
        store.delete_physical_elevator(project["id"], elevator["id"])


def test_deployment_editor_groups_side_rails_around_the_map_canvas():
    root = Path(__file__).resolve().parents[1] / "autodrive_console/web"
    html = (root / "deployment.html").read_text(encoding="utf-8")
    css = (root / "deployment.css").read_text(encoding="utf-8")

    assert 'class="deployment-left-rail"' in html
    assert 'class="deployment-inspector-rail"' in html
    assert "grid-template-columns: minmax(264px, 300px) minmax(0, 1fr) minmax(300px, 340px);" in css


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


def _project_with_four_maps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Build one project with four independent map snapshots for route tests."""
    return _project_with_distinct_maps(tmp_path, monkeypatch, 4)


def _persisted_localization_binding(
    store: DeploymentStore,
    project: dict,
    asset: dict,
    binding_type: str,
) -> dict:
    """Persist a controlled binding fixture without testing the binding endpoint here."""
    binding = {
        "id": f"localization-{len(store.get(project['id'])['localization_bindings']) + 1}",
        "map_asset_id": asset["id"],
        "building": "1",
        "unit": "1",
        "type": binding_type,
    }
    if binding_type == "floor":
        binding["floor_template"] = "2"
    document = store.get(project["id"])
    document["localization_bindings"].append(binding)
    store._write_json(store._document_path(project["id"]), document)
    return binding


def _route_fixture(store: DeploymentStore, project: dict, assets: list[dict]) -> tuple[dict, list[dict], dict]:
    bindings = [
        _persisted_localization_binding(store, project, asset, binding_type)
        for asset, binding_type in zip(assets, ("ferry", "outdoor", "indoor", "floor"))
    ]
    start = store.add_waypoint(
        project["id"], {"map_id": assets[0]["id"], "kind": "start", "x": -0.95, "y": -1.95}
    )
    target = store.add_waypoint(
        project["id"], {"map_id": assets[-1]["id"], "kind": "target", "x": -0.95, "y": -1.95}
    )
    ferry_anchor = store.add_waypoint(
        project["id"], {"map_id": assets[0]["id"], "kind": "map_transition", "x": -0.95, "y": -1.95}
    )
    outdoor_anchor = store.add_waypoint(
        project["id"], {"map_id": assets[1]["id"], "kind": "map_transition", "x": -0.95, "y": -1.95}
    )
    lobby_elevator = {"id": "component-route-elevator", "map_asset_id": assets[2]["id"], "kind": "elevator"}
    document = store.get(project["id"])
    document["components"].append(lobby_elevator)
    store._write_json(store._document_path(project["id"]), document)
    payload = {
        "building": "1", "unit": "1", "binding_ids": [item["id"] for item in bindings],
        "task_start_waypoint_id": start["id"], "task_target_waypoint_id": target["id"],
        "links": [
            {"from_binding_id": bindings[0]["id"], "to_binding_id": bindings[1]["id"], "anchor": {"kind": "waypoint", "waypoint_id": ferry_anchor["id"]}},
            {"from_binding_id": bindings[1]["id"], "to_binding_id": bindings[2]["id"], "anchor": {"kind": "waypoint", "waypoint_id": outdoor_anchor["id"]}},
            {"from_binding_id": bindings[2]["id"], "to_binding_id": bindings[3]["id"], "anchor": {"kind": "component_center", "component_id": lobby_elevator["id"]}},
        ],
    }
    return payload, bindings, {"outdoor_anchor": outdoor_anchor, "lobby_elevator": lobby_elevator}


def test_localization_route_allows_ferry_anywhere_and_derives_references(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Catches rejecting a valid ferry-to-floor localization chain."""
    store, project, assets = _project_with_four_maps(tmp_path, monkeypatch)
    payload, bindings, _ = _route_fixture(store, project, assets)

    route = store.create_localization_route(project["id"], payload)

    assert route["binding_ids"] == [item["id"] for item in bindings]


def test_localization_route_rejects_non_floor_tail_and_mismatched_anchor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Catches accepting a chain without a floor tail or a foreign cut-over anchor."""
    store, project, assets = _project_with_four_maps(tmp_path, monkeypatch)
    bad_tail, bindings, _ = _route_fixture(store, project, assets)
    bad_tail["binding_ids"] = [item["id"] for item in bindings[:3]]
    bad_tail["links"] = bad_tail["links"][:2]
    bad_tail["task_target_waypoint_id"] = store.add_waypoint(
        project["id"], {"map_id": assets[2]["id"], "kind": "target", "x": -0.95, "y": -1.95}
    )["id"]
    with pytest.raises(DeploymentError, match="最后"):
        store.create_localization_route(project["id"], bad_tail)

    foreign, _, references = _route_fixture(store, project, assets)
    foreign["links"][0]["anchor"]["waypoint_id"] = references["outdoor_anchor"]["id"]
    with pytest.raises(DeploymentError, match="切图锚点"):
        store.create_localization_route(project["id"], foreign)


def test_localization_route_allows_auto_door_component_center(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Catches rejecting a map-owned automatic-door cut-over center as non-elevator."""
    store, project, assets = _project_with_four_maps(tmp_path, monkeypatch)
    payload, _, _ = _route_fixture(store, project, assets)
    auto_door = {
        "id": "component-route-auto-door", "map_asset_id": assets[2]["id"], "kind": "auto_door",
    }
    document = store.get(project["id"])
    document["components"].append(auto_door)
    store._write_json(store._document_path(project["id"]), document)
    payload["links"][-1]["anchor"] = {"kind": "component_center", "component_id": auto_door["id"]}

    route = store.create_localization_route(project["id"], payload)

    assert route["links"][-1]["anchor"] == {
        "kind": "component_center", "component_id": "component-route-auto-door",
    }


def test_localization_route_rejects_missing_component_center(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Catches accepting a component-center anchor that does not exist on the source map."""
    store, project, assets = _project_with_four_maps(tmp_path, monkeypatch)
    payload, _, _ = _route_fixture(store, project, assets)
    payload["links"][-1]["anchor"] = {"kind": "component_center", "component_id": "component-missing"}

    with pytest.raises(DeploymentError, match="切图锚点组件"):
        store.create_localization_route(project["id"], payload)


def test_legacy_manual_localization_binding_remains_readable_but_is_marked_for_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Catches normalizing legacy manual initialization fields away during reads."""
    store, project, assets = _project_with_four_maps(tmp_path, monkeypatch)
    legacy = {
        "id": "localization-legacy", "map_asset_id": assets[0]["id"], "building": "1", "unit": "1", "type": "ferry",
        "init_go": {"x": -0.95, "y": -1.95, "z": 0.0, "yaw": 0.0},
        "init_return": {"x": -0.95, "y": -1.95, "z": 0.0, "yaw": 0.0},
    }
    store._write_json(store._document_path(project["id"]), {**project, "localization_bindings": [legacy]})

    saved = store.get(project["id"])

    assert saved["localization_bindings"][0]["init_go"] == legacy["init_go"]
    assert saved["localization_routes"] == []


def test_localization_route_rejects_updates_to_referenced_bindings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Catches mutating a route tail so its saved target no longer matches."""
    store, project, assets = _project_with_four_maps(tmp_path, monkeypatch)
    payload, bindings, _ = _route_fixture(store, project, assets)
    store.create_localization_route(project["id"], payload)

    with pytest.raises(DeploymentError, match="定位路线"):
        store.update_localization_binding(
            project["id"],
            bindings[-1]["id"],
            {
                "map_asset_id": assets[0]["id"], "building": "1", "unit": "1",
                "type": "floor", "floor_template": "2",
            },
        )


def test_localization_route_protects_component_generated_waypoints_from_cascade_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Catches a component delete cascading through a route endpoint it generated."""
    store, project, assets = _project_with_four_maps(tmp_path, monkeypatch)
    payload, _, _ = _route_fixture(store, project, assets)
    generated_component = {
        "id": "component-route-start", "map_asset_id": assets[0]["id"], "kind": "start",
    }
    generated_waypoint = {
        "id": "waypoint-route-start", "map_asset_id": assets[0]["id"], "kind": "start",
        "generated_by": generated_component["id"],
    }
    document = store.get(project["id"])
    document["components"].append(generated_component)
    document["waypoints"].append(generated_waypoint)
    store._write_json(store._document_path(project["id"]), document)
    payload["task_start_waypoint_id"] = generated_waypoint["id"]
    store.create_localization_route(project["id"], payload)

    with pytest.raises(DeploymentError, match="Waypoint"):
        store.delete_component(project["id"], generated_component["id"])


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


def test_physical_elevator_http_creates_project_owned_shared_entity():
    payload = {
        "elevator_id": "10014",
        "elevator_protocol": "bluetooth",
        "min_floor": 1,
        "max_floor": 15,
    }
    entity = {"id": "physical-elevator-10014", **payload}
    handler = _deployment_handler("/api/deployments/site/physical-elevators", payload)

    with patch.object(web_console.DEPLOYMENTS, "add_physical_elevator", return_value=entity) as create, patch.object(
        web_console.DEPLOYMENTS, "get", return_value={"id": "site", "physical_elevators": [entity]}
    ) as get:
        handler.do_POST()

    create.assert_called_once_with("site", payload)
    get.assert_called_once_with("site")
    assert handler._json.call_args.args == (
        {"physical_elevator": entity, "project": {"id": "site", "physical_elevators": [entity]}},
        HTTPStatus.CREATED,
    )


def test_localization_binding_http_persists_only_project_owned_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Catches routing a binding request around the Store ownership checks."""
    map_root = tmp_path / "maps"
    source = _map(map_root / "site" / "lobby")
    monkeypatch.setattr(DeploymentStore, "MAP_ROOT", map_root.resolve())
    store = DeploymentStore(tmp_path / "deployments")
    project = store.create("HTTP 定位")
    asset = store.import_map(project["id"], source, "大厅", "lobby")
    payload = _localization_binding_payload(asset["id"])
    handler = _deployment_handler(f"/api/deployments/{project['id']}/localization-bindings", payload)

    with patch.object(web_console, "DEPLOYMENTS", store):
        handler.do_POST()

    body, status = handler._json.call_args.args
    assert status == HTTPStatus.CREATED
    assert body["localization_binding"]["map_asset_id"] == asset["id"]
    assert store.get(project["id"])["localization_bindings"] == [body["localization_binding"]]


def test_localization_route_http_forwards_only_project_owned_payload():
    """Catches a route collection URL falling through to the generic deployment routes."""
    payload = {
        "building": "1", "unit": "1", "binding_ids": ["a"],
        "task_start_waypoint_id": "s", "task_target_waypoint_id": "t", "links": [],
    }
    handler = _deployment_handler("/api/deployments/site/localization-routes", payload)

    with patch.object(web_console.DEPLOYMENTS, "create_localization_route", return_value={"id": "route-a"}) as create:
        handler.do_POST()

    create.assert_called_once_with("site", payload)
    assert handler._json.call_args.args[0]["localization_route"] == {"id": "route-a"}


def test_task_compiler_http_preview_returns_store_preview():
    handler = _deployment_handler("/api/deployments/site/task-compiler/preview", {})

    with patch.object(
        web_console.DEPLOYMENTS, "task_compiler_preview", return_value={"status": "ready"}
    ) as preview:
        handler.do_POST()

    preview.assert_called_once_with("site")
    assert handler._json.call_args.args == ({"preview": {"status": "ready"}},)


def test_task_compiler_http_config_requires_exact_community_payload():
    handler = _deployment_handler(
        "/api/deployments/site/task-compiler/config", {"community": "高科一号", "path": "/tmp"}
    )

    with patch.object(web_console.DEPLOYMENTS, "update_task_compiler_config") as update:
        handler.do_POST()

    update.assert_not_called()
    assert handler._json.call_args.args[1] == HTTPStatus.BAD_REQUEST


def test_task_compiler_http_config_rejects_malformed_json():
    handler = _deployment_handler("/api/deployments/site/task-compiler/config")
    handler.headers = {"Content-Length": "1"}
    handler.rfile = io.BytesIO(b"{")

    with patch.object(web_console.DEPLOYMENTS, "update_task_compiler_config") as update:
        handler.do_POST()

    update.assert_not_called()
    assert handler._json.call_args.args[1] == HTTPStatus.BAD_REQUEST


def test_task_compiler_http_config_returns_persisted_configuration():
    handler = _deployment_handler("/api/deployments/site/task-compiler/config", {"community": "高科一号"})
    expected = {"profile": "indoor_elevator_v1", "identity": {"community": "高科一号"}}

    with patch.object(web_console.DEPLOYMENTS, "update_task_compiler_config", return_value=expected) as update:
        handler.do_POST()

    update.assert_called_once_with("site", {"community": "高科一号"})
    assert handler._json.call_args.args == ({"task_compiler": expected},)


def test_task_compiler_http_preview_maps_compilation_error_to_unprocessable_entity():
    handler = _deployment_handler("/api/deployments/site/task-compiler/preview", {})

    with patch.object(
        web_console.DEPLOYMENTS, "task_compiler_preview", side_effect=CompilationError("缺少组件")
    ):
        handler.do_POST()

    assert handler._json.call_args.args == ({"error": "缺少组件"}, HTTPStatus.UNPROCESSABLE_ENTITY)


def test_task_compiler_http_preview_maps_store_error_to_bad_request():
    handler = _deployment_handler("/api/deployments/site/task-compiler/preview", {})

    with patch.object(
        web_console.DEPLOYMENTS, "task_compiler_preview", side_effect=DeploymentError("项目不存在")
    ):
        handler.do_POST()

    assert handler._json.call_args.args == ({"error": "项目不存在"}, HTTPStatus.BAD_REQUEST)


def test_task_compiler_http_get_preview_returns_store_preview():
    handler = _deployment_handler("/api/deployments/site/task-compiler/preview")

    with patch.object(
        web_console.DEPLOYMENTS, "task_compiler_preview", return_value={"status": "ready"}
    ) as preview:
        handler.do_GET()

    preview.assert_called_once_with("site")
    assert handler._json.call_args.args == ({"preview": {"status": "ready"}},)


def test_task_compiler_http_download_has_safe_zip_attachment_headers():
    handler = _deployment_handler("/api/deployments/site/task-compiler/download")
    handler.send_response = Mock()
    handler.send_header = Mock()
    handler.end_headers = Mock()
    handler.wfile = io.BytesIO()

    with patch.object(
        web_console.DEPLOYMENTS, "task_compiler_bundle", return_value=("高科一号_experimental.zip", b"zip")
    ) as bundle:
        handler.do_GET()

    bundle.assert_called_once_with("site")
    handler.send_response.assert_called_once_with(HTTPStatus.OK)
    assert handler.send_header.call_args_list == [
        (("Content-Type", "application/zip"),),
        (("Content-Disposition", "attachment; filename=task-compiler-experimental.zip; filename*=UTF-8''%E9%AB%98%E7%A7%91%E4%B8%80%E5%8F%B7_experimental.zip"),),
        (("Content-Length", "3"),),
        (("X-Content-Type-Options", "nosniff"),),
    ]
    assert handler.wfile.getvalue() == b"zip"


def test_elevator_symbol_marks_the_existing_yaw_direction():
    """The elevator-door marker must remain coupled to the persisted component yaw."""
    source = (Path(__file__).resolve().parents[1] / "autodrive_console/web/deployment.js").read_text(
        encoding="utf-8"
    )

    assert "function drawElevatorDoorMarker(width, height)" in source
    assert "drawElevatorDoorMarker(width, height);" in source
    assert "context.rotate(-item.yaw || 0);" in source


def test_deployment_editor_offers_shared_elevator_landing_association():
    root = Path(__file__).resolve().parents[1] / "autodrive_console/web"
    html = (root / "deployment.html").read_text(encoding="utf-8")
    source = (root / "deployment.js").read_text(encoding="utf-8")

    assert 'id="elevatorLandingDialog"' in html
    assert "关联已有电梯" in html
    assert "新建物理电梯" in html
    assert "编辑共享电梯" in source
    assert "openElevatorLandingDialog" in source
    assert "physical_elevator_id" in source
    assert "/physical-elevators" in source


def test_deployment_page_uses_component_task_compiler_routes():
    """The PC deployment workflow must stay component-first and export-only."""
    root = Path(__file__).resolve().parents[1]
    source = (root / "autodrive_console/web/deployment.js").read_text(encoding="utf-8")
    html = (root / "autodrive_console/web/deployment.html").read_text(encoding="utf-8")

    assert "/task-compiler/config" in source
    assert "/task-compiler/preview" in source
    assert "/task-compiler/download" in source


def test_deployment_page_offers_controlled_localization_bindings_without_runtime_path_inputs():
    """Catches exposing YAML destinations that must be derived by the export package."""
    root = Path(__file__).resolve().parents[1] / "autodrive_console/web"
    html = (root / "deployment.html").read_text(encoding="utf-8")
    source = (root / "deployment.js").read_text(encoding="utf-8")

    assert 'id="localizationBindingDialog"' in html
    assert 'id="localizationFloorTemplate"' in html
    assert "/localization-bindings" in source
    assert "2D_yaml" not in html
    assert "定位 YAML 路径" not in html
    assert "任务编译预览" in html
    assert 'data-waypoint-kind="map_transition"' not in html
    assert 'data-waypoint-kind="route_link"' not in html


def test_deployment_page_uses_generic_map_import_and_has_no_manual_localization_pose_inputs():
    """Catches keeping manual init-pose controls after bindings became identity-only."""
    html = (Path(__file__).resolve().parents[1] / "autodrive_console/web/deployment.html").read_text(
        encoding="utf-8"
    )

    assert "导入地图" in html
    assert "Lightning 地图" not in html
    assert 'id="localizationGoX"' not in html
    assert 'id="localizationReturnX"' not in html
    assert 'id="localizationRouteDialog"' in html


def test_route_editor_markup_exposes_derived_sources_and_not_raw_runtime_paths():
    """Catches hiding derived pose provenance or restoring a runtime-path input."""
    html = (Path(__file__).resolve().parents[1] / "autodrive_console/web/deployment.html").read_text(
        encoding="utf-8"
    )

    assert 'id="localizationRouteDialog"' in html
    assert 'id="localizationRouteLinks"' in html
    assert "YAML 原点" in html
    assert "定位 YAML 路径" not in html


def test_deployment_contract_documents_identity_only_bindings_and_route_derived_poses():
    """Catches documenting removed manual poses as a binding API contract."""
    contract = (Path(__file__).resolve().parents[1] / "shared/contracts/deployment.md").read_text(
        encoding="utf-8"
    )

    assert "绑定身份字段只有 `map_asset_id`、`building`、`unit`、`type`" in contract
    assert "定位位姿由 `localization_routes` 推导" in contract
    assert "首图使用人工选择的任务起点" in contract
    assert "后续地图使用其 YAML `origin`" in contract
    assert "旧记录中的 `init_go` / `init_return` 只读兼容" in contract


def test_deployment_contract_documents_route_derived_init_poses_and_lift_list():
    """Catches a contract that weakens route payload or export safety boundaries."""
    contract = (Path(__file__).resolve().parents[1] / "shared/contracts/deployment.md").read_text(
        encoding="utf-8"
    )

    assert "| `POST` | `/api/deployments/{project_id}/localization-routes` |" in contract
    assert "| `POST` | `/api/deployments/{project_id}/localization-routes/{route_id}` |" in contract
    assert "| `DELETE` | `/api/deployments/{project_id}/localization-routes/{route_id}` |" in contract
    assert '''{
  "building": "1",
  "unit": "1",
  "binding_ids": ["localization-a", "localization-b"],
  "task_start_waypoint_id": "waypoint-start",
  "task_target_waypoint_id": "waypoint-target",
  "links": [''' in contract
    assert "除上述六个键外不接受其他键" in contract
    assert "| 首项（包括唯一项） | `init_go` | 首项（包括唯一项）使用人工选择的任务起点 `task_start_waypoint_id`" in contract
    assert "| 仅非首项 | `init_go` | 只有非首项使用其 YAML `origin` 的 `x`、`y`、`yaw`（`z: 0.0`）" in contract
    assert "| 非最终项 | `init_return` | 该图出向链接的受控锚点 |" in contract
    assert "| 最终项 | `init_return` | 最终项使用人工选择的任务目标 `task_target_waypoint_id` |" in contract
    assert '`{ "community": "…", "loc_yaml": [{ "building": "…", "unit": "…", "yaml_index": [ … ] }] }`' in contract
    assert "每个 `yaml_index` 条目包含 `type`、`yaml`、`2D_yaml`、`init_go` 和 `init_return`" in contract
    assert "包含 `floor`，其值等于绑定的 `floor_template`" in contract
    assert '"lifts": [{ "lift_id": "…", "building": "…", "unit": "…" }]' in contract
    assert "排序并去重" in contract
    assert (
        "后端在绑定仍被路线引用时阻止更新或删除；在 Waypoint、组件中心或组件生成的 Waypoint 仍被路线\n"
        "引用时也阻止删除，必须先更新或删除路线。"
    ) in contract
    assert "旧记录中的 `init_go` / `init_return` 只读兼容" in contract
    assert "旧手填位姿而没有 `localization_routes` 的项目不能导出新的定位\n清单，必须先迁移为路线" in contract
    assert "`robot_backend` 校验、派生并生成清单；PC `web_console` 仅提交和编辑项目意图。Mobile 不是消费者" in contract
    assert "不写机器人运行时目录、不调用 ROS 或 Supervisor" in contract


def test_deployment_binding_panel_is_hidden_before_a_map_is_selected():
    """Catches a newly added panel bypassing the compact first-run states."""
    css = (Path(__file__).resolve().parents[1] / "autodrive_console/web/deployment.css").read_text(
        encoding="utf-8"
    )

    assert "body.deployment-no-project:has(#mapWorkspace) .localization-binding-panel" in css
    assert (
        "body:not(.deployment-no-project).deployment-no-map:has(#mapWorkspace) .localization-binding-panel"
        in css
    )


def test_deployment_empty_states_use_compact_layout_and_svg_brand_mark():
    root = Path(__file__).resolve().parents[1] / "autodrive_console/web"
    deployment_css = (root / "deployment.css").read_text(encoding="utf-8")
    shell_css = (root / "app_shell.css").read_text(encoding="utf-8")
    shell_js = (root / "app_shell.js").read_text(encoding="utf-8")

    assert "body:not(.deployment-no-project).deployment-no-map:has(#mapWorkspace) .page-grid" in deployment_css
    assert "body:not(.deployment-no-project).deployment-no-map:has(#mapWorkspace) .map-workspace" in deployment_css
    assert "height: min(400px, calc(100vh - 250px));" in deployment_css
    assert "grid-template-columns: minmax(280px, 360px) minmax(0, 1fr);" in deployment_css
    # 共享壳将品牌图形统一为可缓存的 /aletheia.svg 图片资源；不再维护
    # 已移除的内嵌 SVG fallback。
    assert ".mark img {" in shell_css
    assert 'img[src="/aletheia.svg"]' in shell_js

    deployment_js = (root / "deployment.js").read_text(encoding="utf-8")
    assert "mapImage.onerror" in deployment_js
    assert "地图预览加载失败" in deployment_js


def test_deployment_first_run_uses_one_connected_setup_rail_and_hides_later_stages():
    """First-run should read as one workflow, not disconnected disabled cards."""
    root = Path(__file__).resolve().parents[1] / "autodrive_console/web"
    html = (root / "deployment.html").read_text(encoding="utf-8")
    css = (root / "deployment.css").read_text(encoding="utf-8")

    assert 'class="deployment-setup-rail"' in html
    assert "body.deployment-no-project:has(#mapWorkspace) .deployment-setup-rail" in css
    assert "> .deployment-setup-project" in css
    assert ".deployment-map-import" in css
    assert ".topology-panel" in css
    assert ".task-compiler-panel" in css


def _task_compiler_source_map(root: Path, floor: str) -> Path:
    source = _map(root / "gk1" / floor)
    source.with_name("map.pgm").write_bytes(b"P5\n40 40\n255\n" + bytes(40 * 40))
    source.write_text(
        "image: map.pgm\nresolution: 0.2\norigin: [-2.0, -2.0, 0.0]\n"
        f"# compiler fixture {floor}\n",
        encoding="utf-8",
    )
    return source


def _compiler_ready_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    map_root = tmp_path / "robot-maps"
    monkeypatch.setattr(DeploymentStore, "MAP_ROOT", map_root.resolve())
    store = DeploymentStore(tmp_path / "deployments")
    project = store.create("任务编译器")
    store.set_scene_model(project["id"], "indoor")
    lobby = store.import_map(project["id"], _task_compiler_source_map(map_root, "P1"), "大厅", "lobby")
    target = store.import_map(project["id"], _task_compiler_source_map(map_root, "P2"), "目标层", "typical_floor")
    store.add_map_instance(project["id"], {"map_id": lobby["id"], "role": "lobby", "building": "1", "unit": "1", "floor": 1})
    store.add_map_instance(project["id"], {"map_id": target["id"], "role": "typical_floor", "building": "1", "unit": "1", "floor": 15})
    store.add_component(project["id"], {"map_id": lobby["id"], "kind": "start", "x": -1.0, "y": -1.0})
    elevator = store.add_physical_elevator(project["id"], {"elevator_id": "A", "elevator_protocol": "bluetooth", "min_floor": 1, "max_floor": 15})
    lobby_elevator = store.add_component(project["id"], {"map_id": lobby["id"], "kind": "elevator", "x": 0.0, "y": 0.0, "attributes": {"physical_elevator_id": elevator["id"], "button_floor": 1}})
    store.add_component(project["id"], {"map_id": target["id"], "kind": "elevator", "x": 0.0, "y": 1.0, "yaw": 3.141592653589793, "attributes": {"physical_elevator_id": elevator["id"], "button_floor": 15}})
    target_component = store.add_component(project["id"], {"map_id": target["id"], "kind": "target", "x": 1.0, "y": 1.0})
    indoor = store.create_localization_binding(project["id"], {
        "map_asset_id": lobby["id"], "building": "1", "unit": "1", "type": "indoor",
    })
    floor = store.create_localization_binding(project["id"], {
        "map_asset_id": target["id"], "building": "1", "unit": "1", "type": "floor", "floor_template": "2",
    })
    start = store.add_waypoint(project["id"], {"map_id": lobby["id"], "kind": "start", "x": -1.0, "y": -1.0})
    target_waypoint = store.add_waypoint(project["id"], {"map_id": target["id"], "kind": "target", "x": 1.0, "y": 1.0})
    store.create_localization_route(project["id"], {
        "building": "1", "unit": "1",
        "binding_ids": [indoor["id"], floor["id"]],
        "task_start_waypoint_id": start["id"],
        "task_target_waypoint_id": target_waypoint["id"],
        "links": [{
            "from_binding_id": indoor["id"], "to_binding_id": floor["id"],
            "anchor": {"kind": "component_center", "component_id": lobby_elevator["id"]},
        }],
    })
    return store, project, target_component


def test_task_compiler_migrates_legacy_project_and_persists_safe_identity(tmp_path: Path):
    store = DeploymentStore(tmp_path / "deployments")
    project = store.create("旧项目")
    path = store._document_path(project["id"])
    legacy = json.loads(path.read_text(encoding="utf-8"))
    legacy.pop("task_compiler", None)
    path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")

    loaded = store.get(project["id"])

    assert loaded["task_compiler"] == {
        "profile": "indoor_elevator_v1",
        "identity": {"community": "", "last_preview_input_sha256": None},
    }
    saved = store.update_task_compiler_config(project["id"], {"community": " 高科一号 "})
    assert saved["identity"] == {"community": "高科一号", "last_preview_input_sha256": None}
    for invalid in ("", "../gk1", "高" * 81):
        with pytest.raises(DeploymentError):
            store.update_task_compiler_config(project["id"], {"community": invalid})


def test_task_compiler_component_attributes_invalidate_preview(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store, project, target = _compiler_ready_store(tmp_path, monkeypatch)
    store.update_task_compiler_config(project["id"], {"community": "高科一号"})
    store.update_component(project["id"], target["id"], {"attributes": {"door": "1509"}})
    preview = store.task_compiler_preview(project["id"])
    assert preview["input_sha256"]

    updated = store.update_component(project["id"], target["id"], {"attributes": {"door": "1510"}})

    assert updated["attributes"]["door"] == "1510"
    assert store.get(project["id"])["task_compiler"]["identity"]["last_preview_input_sha256"] is None
    with pytest.raises(DeploymentError):
        store.update_component(project["id"], target["id"], {"attributes": {"door": "../1509"}})


def test_task_compiler_route_change_produces_a_new_preview_fingerprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Catches reusing an export fingerprint after a route anchor changes."""
    store, project, target = _compiler_ready_store(tmp_path, monkeypatch)
    store.update_task_compiler_config(project["id"], {"community": "高科一号"})
    store.update_component(project["id"], target["id"], {"attributes": {"door": "1509"}})
    first = store.task_compiler_preview(project["id"])["input_sha256"]
    anchor = store.add_waypoint(
        project["id"], {"map_id": store.get(project["id"])["map_stage_assignments"][0]["map_asset_id"], "kind": "map_transition", "x": 0.2, "y": 0.0}
    )
    document = store.get(project["id"])
    document["localization_routes"][0]["links"][0]["anchor"] = {
        "kind": "waypoint", "waypoint_id": anchor["id"],
    }
    store._write_json(store._document_path(project["id"]), document)
    second = store.task_compiler_preview(project["id"])["input_sha256"]

    assert second != first


def test_task_compiler_bundle_contains_both_controlled_location_json_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Catches omitting a route-derived controlled JSON artifact from the ZIP."""
    store, project, target = _compiler_ready_store(tmp_path, monkeypatch)
    store.update_task_compiler_config(project["id"], {"community": "高科一号"})
    store.update_component(project["id"], target["id"], {"attributes": {"door": "1509"}})

    preview = store.task_compiler_preview(project["id"])
    _, body = store.task_compiler_bundle(project["id"])

    with ZipFile(io.BytesIO(body)) as archive:
        assert "runtime/loc_yaml_path.json" in archive.namelist()
        assert "runtime/lift_id_list.json" in archive.namelist()
    assert preview["manifest"]["location_manifest"] == {
        "community": "高科一号",
        "binding_count": 2,
        "lift_count": 1,
        "artifacts": ["runtime/loc_yaml_path.json", "runtime/lift_id_list.json"],
        "bindings": [
            {"building": "1", "unit": "1", "type": "indoor"},
            {"building": "1", "unit": "1", "type": "floor", "floor_template": "2"},
        ],
    }


def test_task_compiler_preview_writes_only_project_owned_exports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store, project, target = _compiler_ready_store(tmp_path, monkeypatch)
    target = store.update_component(project["id"], target["id"], {"attributes": {"door": "1509"}})
    store.update_task_compiler_config(project["id"], {"community": "高科一号"})
    runtime_root = tmp_path / "runtime" / "origin_tasks"
    runtime_root.mkdir(parents=True)
    sentinel = runtime_root / "sentinel.json"
    sentinel.write_bytes(b"runtime task must remain unchanged")
    monkeypatch.setattr(DeploymentStore, "RUNTIME_TASK_ROOT", runtime_root.resolve(), raising=False)

    preview = store.task_compiler_preview(project["id"])
    export_root = store._project_dir(project["id"]) / "exports" / preview["input_sha256"]

    assert target["attributes"]["door"] == "1509"
    assert (export_root / "manifest.json").is_file()
    assert (export_root / "tasks" / "高科一号_1_1_15_1509.json").is_file()
    assert sentinel.read_bytes() == b"runtime task must remain unchanged"
    assert store.get(project["id"])["task_compiler"]["identity"]["last_preview_input_sha256"] == preview["input_sha256"]
