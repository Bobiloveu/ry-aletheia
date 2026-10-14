from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from autodrive_console.manual_map_markers import ManualMapMarkerError, ManualMapMarkerStore


MAP_A = "a" * 16
MAP_B = "b" * 16


def test_create_normalizes_yaw_and_isolates_map_records(tmp_path: Path) -> None:
    store = ManualMapMarkerStore(tmp_path / "live_map_markers.json")

    created = store.create(
        MAP_A,
        alias="  电梯厅待命点  ",
        x=12.4,
        y=-5.8,
        yaw=math.tau + 0.25,
    )

    assert created["alias"] == "电梯厅待命点"
    assert created["x"] == 12.4
    assert created["y"] == -5.8
    assert created["yaw"] == pytest.approx(0.25)
    assert isinstance(created["id"], str) and created["id"]
    assert store.list_for_map(MAP_A) == [created]
    assert store.list_for_map(MAP_B) == []
    payload = json.loads((tmp_path / "live_map_markers.json").read_text(encoding="utf-8"))
    assert payload == {
        "schema": 1,
        "markers": [{**created, "map_id": MAP_A}],
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {"alias": "", "x": 0, "y": 0, "yaw": 0},
        {"alias": "x" * 49, "x": 0, "y": 0, "yaw": 0},
        {"alias": "点", "x": float("nan"), "y": 0, "yaw": 0},
        {"alias": "点", "x": 0, "y": 100001, "yaw": 0},
        {"alias": "点", "x": 0, "y": 0, "yaw": 10001},
    ],
)
def test_create_rejects_invalid_operator_input(tmp_path: Path, kwargs: dict[str, object]) -> None:
    store = ManualMapMarkerStore(tmp_path / "markers.json")

    with pytest.raises(ManualMapMarkerError):
        store.create(MAP_A, **kwargs)


def test_first_read_is_empty_and_remove_persists_only_current_map(tmp_path: Path) -> None:
    path = tmp_path / "markers.json"
    store = ManualMapMarkerStore(path)

    assert store.list_for_map(MAP_A) == []
    marker_a = store.create(MAP_A, alias="A", x=1, y=2, yaw=0)
    marker_b = store.create(MAP_B, alias="B", x=3, y=4, yaw=1)
    store.remove(MAP_A, marker_a["id"])

    assert store.list_for_map(MAP_A) == []
    assert store.list_for_map(MAP_B) == [marker_b]
    assert json.loads(path.read_text(encoding="utf-8"))["markers"] == [{**marker_b, "map_id": MAP_B}]


def test_create_rejects_the_501st_marker_for_one_map(tmp_path: Path) -> None:
    store = ManualMapMarkerStore(tmp_path / "markers.json")
    for index in range(500):
        store.create(MAP_A, alias=f"点{index}", x=index, y=0, yaw=0)

    with pytest.raises(ManualMapMarkerError, match="当前地图标记数量已达上限"):
        store.create(MAP_A, alias="超额", x=501, y=0, yaw=0)


def test_load_skips_damaged_records_but_keeps_valid_marker(tmp_path: Path) -> None:
    path = tmp_path / "markers.json"
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "markers": [
                    {"id": "valid-id", "map_id": MAP_A, "alias": "有效", "x": 1, "y": 2, "yaw": 0},
                    {"id": "broken", "map_id": MAP_A, "alias": "", "x": "nan", "y": 2, "yaw": 0},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert ManualMapMarkerStore(path).list_for_map(MAP_A) == [
        {"id": "valid-id", "alias": "有效", "x": 1.0, "y": 2.0, "yaw": 0.0},
    ]


def test_resolve_and_remove_reject_marker_from_another_map(tmp_path: Path) -> None:
    store = ManualMapMarkerStore(tmp_path / "markers.json")
    marker = store.create(MAP_A, alias="仅 A", x=0, y=0, yaw=0)

    with pytest.raises(ManualMapMarkerError, match="不属于当前地图"):
        store.resolve(MAP_B, marker["id"])
    with pytest.raises(ManualMapMarkerError, match="不属于当前地图"):
        store.remove(MAP_B, marker["id"])
