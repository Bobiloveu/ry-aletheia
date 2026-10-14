from __future__ import annotations

import threading
import sys
import types
import inspect
from unittest.mock import patch
import subprocess

import pytest

from autodrive_console.manual_map_markers import ManualMapMarker, ManualMapMarkerError
from autodrive_console.map_marker_navigation import (
    MapMarkerNavigationConflict,
    MapMarkerNavigationController,
    MapMarkerNavigationUnavailable,
    _RosNavigateToPoseTransport,
)
from autodrive_console.observation import ObservationManager


MAP_A = "a" * 16
MAP_B = "b" * 16


class _Observation:
    def __init__(self) -> None:
        self.checked: list[str] = []
        self.active_map_id = MAP_A
        self.allowed = True

    def active_manual_map_id(self):
        return self.active_map_id

    def verify_active_manual_map_id(self, map_id):
        self.checked.append(map_id)
        return (self.allowed and map_id == self.active_map_id, "当前地图匹配" if self.allowed else "当前地图不匹配")


class _Vehicle:
    def __init__(self) -> None:
        self.payload = {
            "actual_source": "navigation",
            "transition": None,
            "relocalization_hold": "idle",
            "session": {"present": False},
            "car_state_sync": {"emergency_stop": "confirmed"},
            "emergency_stop": {"state": "normal"},
        }

    def status(self):
        return self.payload


class _VehicleThatConfirmsEmergencyOnSecondRead(_Vehicle):
    """The controller's ROS timer resolves a pending service query while Nav2 waits."""

    def __init__(self) -> None:
        super().__init__()
        self.read_count = 0
        self.payload["car_state_sync"]["emergency_stop"] = "pending"
        self.payload["emergency_stop"]["state"] = "unknown"

    def status(self):
        self.read_count += 1
        if self.read_count == 2:
            self.payload["car_state_sync"]["emergency_stop"] = "confirmed"
            self.payload["emergency_stop"]["state"] = "normal"
        return self.payload


class _Localization:
    def __init__(self) -> None:
        self.payload = {"phase": "normal"}

    def status(self):
        return self.payload


class _MarkerStore:
    def __init__(self) -> None:
        self.marker = ManualMapMarker("opaque", MAP_A, "电梯厅待命点", -6.0, 5.0, 1.2)
        self.calls: list[tuple[str, object]] = []

    def resolve(self, map_id, marker_id):
        self.calls.append((map_id, marker_id))
        if map_id != MAP_A or marker_id != "opaque":
            raise ManualMapMarkerError("地图标记不存在或不属于当前地图")
        return self.marker


class _Transport:
    def __init__(self) -> None:
        self.goals = []
        self.cancelled = []
        self.done = None
        self.route_callback = None

    def send_goal(self, frame, x, y, yaw, done, route_callback=None):
        self.goals.append((frame, x, y, yaw))
        self.done = done
        self.route_callback = route_callback
        return object()

    def cancel(self, goal):
        self.cancelled.append(goal)


def _controller(*, observation=None, vehicle=None, localization=None, transport=None, active_run=lambda: False):
    return MapMarkerNavigationController(
        _MarkerStore(),
        observation or _Observation(),
        vehicle or _Vehicle(),
        localization or _Localization(),
        active_run_guard=active_run,
        transport=transport or _Transport(),
    )


def test_active_manual_map_id_uses_verified_static_identity_for_a_runtime_snapshot() -> None:
    """OccupancyGrid snapshot hashes and static map hashes are intentionally distinct."""
    manager = object.__new__(ObservationManager)
    manager._lock = threading.RLock()
    manager._active_task_map = (
        MAP_A,
        MAP_B,
        __import__("pathlib").Path("/opt/ry/maps/a.yaml"),
    )
    manager.active_map_id = lambda: MAP_A

    assert manager.active_manual_map_id() == MAP_B
    manager.active_map_id = lambda: "c" * 16
    assert manager.active_manual_map_id() is None


def test_recent_verified_map_server_yaml_survives_a_temporary_ros_query_timeout(monkeypatch, tmp_path) -> None:
    """A slow ros2 CLI must not erase a live-map binding that is still bounded by /map."""
    manager = ObservationManager(tmp_path / "cache", tmp_path / "logs")
    verified = tmp_path / "maps" / "P2" / "map.yaml"
    verified.parent.mkdir(parents=True)
    verified.write_text("image: map.pgm\n", encoding="utf-8")
    manager._map_server_yaml = verified
    manager._map_server_yaml_checked_at = 89.0
    manager._map_server_yaml_verified_at = 98.0
    monkeypatch.setattr("autodrive_console.observation.time.monotonic", lambda: 100.0)
    monkeypatch.setattr("autodrive_console.observation.shutil.which", lambda _: "ros2")
    monkeypatch.setattr(
        "autodrive_console.observation.subprocess.run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired("ros2", 5)),
    )

    assert manager._map_server_yaml_path() == verified


def test_successful_map_server_refresh_renews_the_verified_yaml_age(monkeypatch, tmp_path) -> None:
    manager = ObservationManager(tmp_path / "cache", tmp_path / "logs")
    verified = tmp_path / "maps" / "P2" / "map.yaml"
    verified.parent.mkdir(parents=True)
    verified.write_text("image: map.pgm\n", encoding="utf-8")
    manager._map_server_yaml = verified
    manager._map_server_yaml_checked_at = 89.0
    manager._map_server_yaml_verified_at = 60.0
    monkeypatch.setattr("autodrive_console.observation.time.monotonic", lambda: 100.0)
    monkeypatch.setattr("autodrive_console.observation.shutil.which", lambda _: "ros2")
    monkeypatch.setattr("autodrive_console.observation.MapAssetCache.ALLOWED_ROOTS", (tmp_path,))
    monkeypatch.setattr(
        "autodrive_console.observation.subprocess.run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["ros2"], 0, stdout=f"String value is: {verified}\n", stderr="",
        ),
    )

    assert manager._map_server_yaml_path() == verified
    assert manager._map_server_yaml_verified_at == 100.0


def test_begin_rechecks_current_map_before_sending_goal() -> None:
    observation = _Observation()
    transport = _Transport()
    controller = _controller(observation=observation, transport=transport)

    snapshot = controller.begin_marker("opaque")

    assert snapshot["phase"] == "navigating"
    assert observation.checked == [MAP_A, MAP_A]
    assert transport.goals == [("map", -6.0, 5.0, 1.2)]


def test_marker_navigation_exposes_a_bounded_map_route_only_while_active() -> None:
    transport = _Transport()
    controller = _controller(transport=transport)

    controller.begin_marker("opaque")
    assert transport.route_callback is not None
    path = [(float(index), float(index % 7)) for index in range(600)]
    path[-1] = (-6.0, 5.0)
    transport.route_callback("map", path)

    route = controller.status()["route"]
    assert route is not None
    assert route["frame_id"] == "map"
    assert len(route["points"]) == 512
    assert route["points"][0] == {"x": 0.0, "y": 0.0}
    assert route["points"][-1] == {"x": -6.0, "y": 5.0}

    controller.cancel()

    assert controller.status()["route"] is None


def test_marker_navigation_keeps_a_plan_received_during_goal_acceptance() -> None:
    """A fast planner may publish before the HTTP call has returned its accepted ticket."""
    class _ImmediatePlanTransport(_Transport):
        def send_goal(self, *args, **kwargs):
            handle = super().send_goal(*args, **kwargs)
            self.route_callback("map", [(0.0, 0.0), (-6.0, 5.0)])
            return handle

    controller = _controller(transport=_ImmediatePlanTransport())

    snapshot = controller.begin_marker("opaque")

    assert snapshot["route"] == {
        "frame_id": "map",
        "points": [{"x": 0.0, "y": 0.0}, {"x": -6.0, "y": 5.0}],
    }


@pytest.mark.parametrize(
    "frame_id, path",
    [
        ("odom", [(0.0, 0.0), (-6.0, 5.0)]),
        ("map", [(0.0, 0.0), (99.0, 99.0)]),
        ("map", [(0.0, 0.0)]),
    ],
)
def test_marker_navigation_rejects_non_matching_or_incomplete_routes(frame_id, path) -> None:
    transport = _Transport()
    controller = _controller(transport=transport)

    controller.begin_marker("opaque")
    transport.route_callback(frame_id, path)

    assert controller.status()["route"] is None


def test_second_map_check_blocks_goal_after_map_changes() -> None:
    class _ChangingObservation(_Observation):
        def verify_active_manual_map_id(self, map_id):
            self.checked.append(map_id)
            if len(self.checked) == 2:
                self.active_map_id = "b" * 16
            return (map_id == self.active_map_id, "当前地图匹配" if map_id == self.active_map_id else "当前地图不匹配")

    transport = _Transport()
    controller = _controller(observation=_ChangingObservation(), transport=transport)

    with pytest.raises(MapMarkerNavigationConflict, match="当前地图不匹配"):
        controller.begin_marker("opaque")

    assert transport.goals == []


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda vehicle, localization: vehicle.payload.update(actual_source="miniapp"), "自动驾驶控制源"),
        (lambda vehicle, localization: vehicle.payload["emergency_stop"].update(state="stopped"), "急停状态"),
        (lambda vehicle, localization: localization.payload.update(phase="warning"), "定位状态"),
        (lambda vehicle, localization: vehicle.payload["session"].update(present=True), "手动控制或手动重定位"),
        (lambda vehicle, localization: vehicle.payload.update(relocalization_hold="calling_service"), "手动控制或手动重定位"),
    ],
)
def test_unsafe_vehicle_state_blocks_marker_navigation(mutate, expected) -> None:
    vehicle, localization, transport = _Vehicle(), _Localization(), _Transport()
    mutate(vehicle, localization)

    with pytest.raises(MapMarkerNavigationConflict, match=expected):
        _controller(vehicle=vehicle, localization=localization, transport=transport).begin_marker("opaque")

    assert transport.goals == []


def test_safety_loss_cancels_active_goal() -> None:
    vehicle, transport = _Vehicle(), _Transport()
    controller = _controller(vehicle=vehicle, transport=transport)
    controller.begin_marker("opaque")
    vehicle.payload["actual_source"] = "miniapp"

    snapshot = controller.status()

    assert snapshot["phase"] == "cancelling"
    assert len(transport.cancelled) == 1
    transport.done(False)
    assert controller.status()["phase"] == "cancelled"


def test_stale_normal_emergency_status_cannot_start_marker_navigation() -> None:
    """A displayed retained false must not bypass the fresh-confirmation gate."""
    vehicle, transport = _Vehicle(), _Transport()
    vehicle.payload["car_state_sync"]["emergency_stop"] = "pending"

    with pytest.raises(MapMarkerNavigationConflict, match="正在重新确认"):
        _controller(vehicle=vehicle, transport=transport).begin_marker("opaque")

    assert transport.goals == []


def test_marker_navigation_waits_for_the_bounded_emergency_reconfirmation(monkeypatch) -> None:
    """A fresh service confirmation may arrive just after marker safety checking starts."""
    vehicle, transport = _VehicleThatConfirmsEmergencyOnSecondRead(), _Transport()
    monkeypatch.setattr("autodrive_console.map_marker_navigation.time.sleep", lambda _seconds: None)

    snapshot = _controller(vehicle=vehicle, transport=transport).begin_marker("opaque")

    assert snapshot["phase"] == "navigating"
    assert vehicle.read_count >= 2
    assert transport.goals == [("map", -6.0, 5.0, 1.2)]


def test_background_monitor_cancels_without_a_status_poll() -> None:
    """The backend owns safety cancellation even if the browser stops polling."""
    class _ManualClock:
        now = 0.0
        def __call__(self):
            return self.now

    clock = _ManualClock()
    vehicle, transport = _Vehicle(), _Transport()
    controller = _controller(vehicle=vehicle, transport=transport)
    controller._clock = clock
    controller.begin_marker("opaque")
    vehicle.payload["actual_source"] = "miniapp"

    controller._monitor_once()

    assert transport.cancelled
    assert controller.status()["phase"] == "cancelling"


def test_unconfirmed_cancel_remains_an_interlock_until_nav2_reports_a_terminal_result() -> None:
    class _ManualClock:
        now = 0.0
        def __call__(self):
            return self.now

    clock = _ManualClock()
    transport = _Transport()
    controller = _controller(transport=transport)
    controller._clock = clock
    controller.begin_marker("opaque")
    controller.cancel()
    clock.now += controller.CANCEL_CONFIRMATION_TIMEOUT_S + 0.01

    controller._monitor_once()

    snapshot = controller.status()
    assert snapshot["phase"] == "cancellation_unconfirmed"
    assert snapshot["can_begin"] is False
    assert snapshot["can_cancel"] is False
    assert controller.blocks_runs() is True
    transport.done(False)
    assert controller.status()["phase"] == "cancelled"


def test_transport_failure_hides_ros_detail_from_operator_and_logs_generic_message() -> None:
    class _UnavailableTransport:
        def send_goal(self, *_args):
            raise RuntimeError("DDS discovery timed out")

    controller = _controller(transport=_UnavailableTransport())

    with patch("autodrive_console.map_marker_navigation.LOGGER") as logger:
        with pytest.raises(MapMarkerNavigationUnavailable, match="导航服务不可用"):
            controller.begin_marker("opaque")

    logger.exception.assert_called_once_with("前往地图标记失败：导航服务不可用")


def test_nav2_transport_allows_ten_seconds_for_dds_action_discovery(monkeypatch) -> None:
    """A freshly-created ROS participant can need several seconds to discover Nav2."""
    observed: dict[str, float] = {}

    class _Node:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def destroy_node(self) -> None:
            pass

        def create_subscription(self, *_args, **_kwargs) -> None:
            pass

    class _Executor:
        def add_node(self, _node) -> None:
            pass

        def spin_once(self, *, timeout_sec: float) -> None:
            pass

        def shutdown(self) -> None:
            pass

    class _ActionClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def wait_for_server(self, *, timeout_sec: float) -> bool:
            observed["timeout"] = timeout_sec
            return False

    rclpy = types.ModuleType("rclpy")
    rclpy.ok = lambda: True
    action = types.ModuleType("rclpy.action")
    action.ActionClient = _ActionClient
    executors = types.ModuleType("rclpy.executors")
    executors.SingleThreadedExecutor = _Executor
    node = types.ModuleType("rclpy.node")
    node.Node = _Node
    geometry = types.ModuleType("geometry_msgs.msg")
    geometry.PoseStamped = object
    nav2 = types.ModuleType("nav2_msgs.action")
    nav2.NavigateToPose = object
    nav_msgs = types.ModuleType("nav_msgs.msg")
    nav_msgs.Path = object
    qos = types.ModuleType("rclpy.qos")
    qos.QoSProfile = lambda **_kwargs: object()
    qos.ReliabilityPolicy = types.SimpleNamespace(RELIABLE=object())
    qos.DurabilityPolicy = types.SimpleNamespace(VOLATILE=object())
    monkeypatch.setitem(sys.modules, "rclpy", rclpy)
    monkeypatch.setitem(sys.modules, "rclpy.action", action)
    monkeypatch.setitem(sys.modules, "rclpy.executors", executors)
    monkeypatch.setitem(sys.modules, "rclpy.node", node)
    monkeypatch.setitem(sys.modules, "geometry_msgs.msg", geometry)
    monkeypatch.setitem(sys.modules, "nav2_msgs.action", nav2)
    monkeypatch.setitem(sys.modules, "nav_msgs.msg", nav_msgs)
    monkeypatch.setitem(sys.modules, "rclpy.qos", qos)

    with pytest.raises(MapMarkerNavigationUnavailable, match="Nav2 导航服务不可用"):
        _RosNavigateToPoseTransport().send_goal("map", 0.0, 0.0, 0.0, lambda _result: None)

    assert observed["timeout"] == 10.0


def test_nav2_worker_forwards_plan_only_after_its_goal_is_accepted(monkeypatch) -> None:
    """The ROS worker, rather than HTTP callers, owns the `/plan` subscription."""
    subscriptions = []
    accepted_handle = None

    class _Future:
        def __init__(self, result=None) -> None:
            self._result = result
            self._callbacks = []

        def result(self):
            return self._result

        def add_done_callback(self, callback) -> None:
            self._callbacks.append(callback)
            if self._result is not None:
                callback(self)

        def complete(self, result) -> None:
            self._result = result
            for callback in self._callbacks:
                callback(self)

    class _GoalHandle:
        accepted = True

        def __init__(self) -> None:
            self.result_future = _Future()

        def get_result_async(self):
            return self.result_future

        def cancel_goal_async(self):
            return _Future()

    class _Node:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def get_clock(self):
            return types.SimpleNamespace(now=lambda: types.SimpleNamespace(to_msg=lambda: object()))

        def create_subscription(self, message_type, topic, callback, qos):
            subscriptions.append((message_type, topic, callback, qos))
            return object()

        def destroy_node(self) -> None:
            pass

    class _Executor:
        def add_node(self, _node) -> None:
            pass

        def spin_once(self, *, timeout_sec: float) -> None:
            pass

        def shutdown(self) -> None:
            pass

    class _ActionClient:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def wait_for_server(self, *, timeout_sec: float) -> bool:
            return True

        def send_goal_async(self, _goal):
            nonlocal accepted_handle
            accepted_handle = _GoalHandle()
            return _Future(accepted_handle)

    class _PoseStamped:
        def __init__(self) -> None:
            self.header = types.SimpleNamespace(frame_id="", stamp=None)
            self.pose = types.SimpleNamespace(
                position=types.SimpleNamespace(x=0.0, y=0.0),
                orientation=types.SimpleNamespace(z=0.0, w=0.0),
            )

    class _NavigateToPose:
        class Goal:
            pass

    class _Path:
        def __init__(self) -> None:
            self.header = types.SimpleNamespace(frame_id="map")
            self.poses = [
                types.SimpleNamespace(pose=types.SimpleNamespace(position=types.SimpleNamespace(x=1.0, y=2.0))),
                types.SimpleNamespace(pose=types.SimpleNamespace(position=types.SimpleNamespace(x=3.0, y=4.0))),
            ]

    rclpy = types.ModuleType("rclpy")
    rclpy.ok = lambda: True
    action = types.ModuleType("rclpy.action")
    action.ActionClient = _ActionClient
    executors = types.ModuleType("rclpy.executors")
    executors.SingleThreadedExecutor = _Executor
    node = types.ModuleType("rclpy.node")
    node.Node = _Node
    geometry = types.ModuleType("geometry_msgs.msg")
    geometry.PoseStamped = _PoseStamped
    nav2 = types.ModuleType("nav2_msgs.action")
    nav2.NavigateToPose = _NavigateToPose
    nav_msgs = types.ModuleType("nav_msgs.msg")
    nav_msgs.Path = _Path
    qos = types.ModuleType("rclpy.qos")
    qos.QoSProfile = lambda **_kwargs: object()
    qos.ReliabilityPolicy = types.SimpleNamespace(RELIABLE=object())
    qos.DurabilityPolicy = types.SimpleNamespace(VOLATILE=object())
    for name, module in {
        "rclpy": rclpy,
        "rclpy.action": action,
        "rclpy.executors": executors,
        "rclpy.node": node,
        "geometry_msgs.msg": geometry,
        "nav2_msgs.action": nav2,
        "nav_msgs.msg": nav_msgs,
        "rclpy.qos": qos,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    routed, completed = [], []
    transport = _RosNavigateToPoseTransport()
    try:
        transport.send_goal(
            "map", 3.0, 4.0, 0.0, completed.append,
            lambda frame_id, points: routed.append((frame_id, points)),
        )
        assert len(subscriptions) == 1
        message_type, topic, callback, _qos = subscriptions[0]
        assert message_type is _Path
        assert topic == "/plan"

        callback(_Path())

        assert routed == [("map", [(1.0, 2.0), (3.0, 4.0)])]
        accepted_handle.result_future.complete(types.SimpleNamespace(status=4))
        assert completed == [True]
    finally:
        transport.close()


def test_nav2_transport_has_one_worker_owned_executor_without_cross_thread_spin() -> None:
    source = inspect.getsource(_RosNavigateToPoseTransport)
    worker_source = inspect.getsource(__import__("autodrive_console.map_marker_navigation", fromlist=["_RosNavigateToPoseWorker"])._RosNavigateToPoseWorker)

    assert "spin_until_future_complete" not in source + worker_source
    assert "SingleThreadedExecutor" in worker_source
    assert "queue.Queue" in worker_source
