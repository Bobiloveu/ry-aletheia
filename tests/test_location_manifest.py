from __future__ import annotations

import json
from pathlib import Path

import pytest

from autodrive_console.location_manifest import (
    LocationManifestError,
    RuntimeLayout,
    button_sequence,
    compile_location_manifest,
    physical_floor_index,
)


def test_button_sequence_skips_zero_and_uses_zero_based_physical_indexes():
    """Catches treating the elevator button label as the physical floor."""
    assert button_sequence(-2, 25)[:4] == (-2, -1, 1, 2)
    assert physical_floor_index(-2, 25, -2) == 0
    assert physical_floor_index(-2, 25, -1) == 1
    assert physical_floor_index(-2, 25, 1) == 2


def test_button_sequence_rejects_the_missing_zero_button_and_out_of_range_button():
    """Catches producing a physical index for an unusable elevator button."""
    with pytest.raises(LocationManifestError, match="0"):
        physical_floor_index(-2, 25, 0)
    with pytest.raises(LocationManifestError, match="范围"):
        physical_floor_index(-2, 25, 26)


def test_runtime_layout_generates_only_deterministic_package_relative_paths():
    """Catches user identity values escaping the controlled export layout."""
    layout = RuntimeLayout("site-a", "数创大厦")

    assert layout.localization_yaml("1", "1", "indoor").relative == (
        "runtime/localization/数创大厦/1_1/indoor.yaml"
    )
    assert layout.map_yaml("1", "1", "floor-2").relative == (
        "runtime/maps/数创大厦/1_1/floor-2/map.yaml"
    )


def test_runtime_layout_rejects_path_like_project_identities():
    """Catches path traversal through deployment metadata."""
    with pytest.raises(LocationManifestError):
        RuntimeLayout("site-a", "../unsafe")


def test_location_manifest_groups_bindings_by_building_unit_and_preserves_floor_template(
    tmp_path: Path,
):
    """Catches treating the floor layout template as a physical elevator floor."""
    map_root = tmp_path / "maps"
    indoor = map_root / "indoor" / "map.yaml"
    floor = map_root / "floor" / "map.yaml"
    for source in (indoor, floor):
        source.parent.mkdir(parents=True)
        source.with_name("map.pgm").write_bytes(b"P5\n1 1\n255\n\x00")
        source.write_text("image: map.pgm\nresolution: 1.0\norigin: [0.0, 0.0, 0.0]\n", encoding="utf-8")
    project = {
        "id": "site-a",
        "task_compiler": {"identity": {"community": "数创大厦"}},
        "map_assets": [
            {"id": "indoor", "source_yaml": str(indoor), "origin": [0.0, 0.0, 0.0], "resolution_m": 1.0, "width": 1, "height": 1},
            {"id": "floor", "source_yaml": str(floor), "origin": [0.0, 0.0, 0.0], "resolution_m": 1.0, "width": 1, "height": 1},
        ],
        "localization_bindings": [
            {
                "id": "binding-indoor", "map_asset_id": "indoor", "building": "1", "unit": "1", "type": "indoor",
            },
            {
                "id": "binding-floor", "map_asset_id": "floor", "building": "1", "unit": "1", "type": "floor", "floor_template": "2",
            },
        ],
        "waypoints": [
            {"id": "start", "map_asset_id": "indoor", "x": 0.0, "y": 0.0, "yaw": 0.0},
            {"id": "anchor", "map_asset_id": "indoor", "x": 0.0, "y": 0.0, "yaw": 0.0},
            {"id": "target", "map_asset_id": "floor", "x": 0.0, "y": 0.0, "yaw": 0.0},
        ],
        "components": [],
        "physical_elevators": [],
        "localization_routes": [{
            "id": "route", "building": "1", "unit": "1",
            "binding_ids": ["binding-indoor", "binding-floor"],
            "task_start_waypoint_id": "start", "task_target_waypoint_id": "target",
            "links": [{
                "from_binding_id": "binding-indoor", "to_binding_id": "binding-floor",
                "anchor": {"kind": "waypoint", "waypoint_id": "anchor"},
            }],
        }],
    }

    rendered = compile_location_manifest(project, map_root=map_root)
    document = json.loads(rendered.json_bytes)
    floor_entry = next(item for item in document["loc_yaml"][0]["yaml_index"] if item["type"] == "floor")

    assert document["community"] == "数创大厦"
    assert floor_entry["floor"] == "2"
    assert "runtime/loc_yaml_path.json" in {artifact.relative_path for artifact in rendered.artifacts}


def _route_project(tmp_path: Path, *, kinds: tuple[str, ...] = ("outdoor", "indoor", "floor"), with_elevator_anchor: bool = False):
    """Build a controlled multi-map route without relying on a browser payload."""
    map_root = tmp_path / "maps"
    assets = []
    bindings = []
    waypoints = []
    for index, kind in enumerate(kinds):
        source = map_root / f"map-{index}" / "map.yaml"
        source.parent.mkdir(parents=True)
        source.with_name("map.pgm").write_bytes(b"P5\n100 100\n255\n" + bytes(100 * 100))
        origins = ((-10.0, -10.0, 0.1), (-5.0, -30.0, 0.3), (0.0, 0.0, 0.0))
        origin = origins[index]
        source.write_text(
            f"image: map.pgm\nresolution: 1.0\norigin: [{origin[0]}, {origin[1]}, {origin[2]}]\n",
            encoding="utf-8",
        )
        asset_id = f"asset-{index}"
        binding_id = f"binding-{index}"
        assets.append({
            "id": asset_id,
            "source_yaml": str(source),
            "origin": list(origin),
            "resolution_m": 1.0,
            "width": 100,
            "height": 100,
        })
        bindings.append({
            "id": binding_id,
            "map_asset_id": asset_id,
            "building": "1",
            "unit": "1",
            "type": kind,
            **({"floor_template": "2"} if kind == "floor" else {}),
        })
    waypoints.extend([
        {"id": "start", "map_asset_id": assets[0]["id"], "x": 1.0, "y": 2.0, "yaw": 0.1},
        {"id": "target", "map_asset_id": assets[-1]["id"], "x": 20.0, "y": 21.0, "yaw": 0.0},
    ])
    links = []
    components = []
    for index in range(len(bindings) - 1):
        if with_elevator_anchor and index == 1:
            components.append({
                "id": "lobby-elevator",
                "map_asset_id": assets[index]["id"],
                "kind": "elevator",
                "x": 8.0,
                "y": 9.0,
                "yaw": 1.57,
                "attributes": {"physical_elevator_id": "physical-elevator"},
            })
            anchor = {"kind": "component_center", "component_id": "lobby-elevator"}
        else:
            waypoint_id = f"anchor-{index}"
            waypoints.append({
                "id": waypoint_id,
                "map_asset_id": assets[index]["id"],
                "x": 4.0 + index * 4.0,
                "y": 5.0 + index * 4.0,
                "yaw": 1.57 if index == 1 else 0.0,
            })
            anchor = {"kind": "waypoint", "waypoint_id": waypoint_id}
        links.append({
            "from_binding_id": bindings[index]["id"],
            "to_binding_id": bindings[index + 1]["id"],
            "anchor": anchor,
        })
    return {
        "id": "site-a",
        "task_compiler": {"identity": {"community": "高科一号"}},
        "map_assets": assets,
        "localization_bindings": bindings,
        "localization_routes": [{
            "id": "route-1",
            "building": "1",
            "unit": "1",
            "binding_ids": [item["id"] for item in bindings],
            "task_start_waypoint_id": "start",
            "task_target_waypoint_id": "target",
            "links": links,
        }],
        "waypoints": waypoints,
        "components": components,
        "physical_elevators": [{"id": "physical-elevator", "elevator_id": "10044"}],
    }, map_root


def test_manifest_uses_manual_start_then_yaml_origins_and_route_return_anchors(tmp_path: Path):
    """Catches reading stale manual binding poses instead of the controlled route."""
    project, map_root = _route_project(tmp_path)

    rendered = compile_location_manifest(project, map_root=map_root)

    entries = json.loads(rendered.json_bytes)["loc_yaml"][0]["yaml_index"]
    assert entries[0]["init_go"] == {"x": 1.0, "y": 2.0, "z": 0.0, "yaw": 0.1}
    assert entries[1]["init_go"] == {"x": -5.0, "y": -30.0, "z": 0.0, "yaw": 0.3}
    assert entries[1]["init_return"] == {"x": 8.0, "y": 9.0, "z": 0.0, "yaw": 1.57}
    assert entries[2]["init_return"] == {"x": 20.0, "y": 21.0, "z": 0.0, "yaw": 0.0}


def test_manifest_emits_deduplicated_route_elevator_id_list(tmp_path: Path):
    """Catches exporting all elevator landings instead of route-referenced IDs."""
    project, map_root = _route_project(tmp_path, with_elevator_anchor=True)

    rendered = compile_location_manifest(project, map_root=map_root)

    lifts = next(item for item in rendered.artifacts if item.relative_path == "runtime/lift_id_list.json")
    assert json.loads(lifts.content) == {
        "community": "高科一号",
        "lifts": [{"lift_id": "10044", "building": "1", "unit": "1"}],
    }
    assert lifts.content.endswith(b"\n")


def test_manifest_rejects_legacy_binding_missing_route_and_conflicting_lift_identity(tmp_path: Path):
    """Catches guessing a legacy route or a physical elevator's building identity."""
    project, map_root = _route_project(tmp_path)
    project["localization_routes"] = []
    project["localization_bindings"][0]["init_go"] = {"x": 1.0, "y": 2.0, "z": 0.0, "yaw": 0.1}
    with pytest.raises(LocationManifestError, match="迁移"):
        compile_location_manifest(project, map_root=map_root)

    project, map_root = _route_project(tmp_path / "conflict", with_elevator_anchor=True)
    duplicate = [dict(item) for item in project["localization_bindings"]]
    for item in duplicate:
        item["id"] = f"unit-2-{item['id']}"
        item["unit"] = "2"
    route = dict(project["localization_routes"][0])
    route["id"] = "route-2"
    route["unit"] = "2"
    route["binding_ids"] = [item["id"] for item in duplicate]
    route["links"] = [
        {
            **link,
            "from_binding_id": f"unit-2-{link['from_binding_id']}",
            "to_binding_id": f"unit-2-{link['to_binding_id']}",
        }
        for link in route["links"]
    ]
    project["localization_bindings"].extend(duplicate)
    project["localization_routes"].append(route)
    with pytest.raises(LocationManifestError, match="楼栋"):
        compile_location_manifest(project, map_root=map_root)
