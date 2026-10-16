from types import SimpleNamespace as NS
import http.client
import json
import threading
from http.server import ThreadingHTTPServer

import pytest

from autodrive_console.navigation_route import NavigationRouteSnapshot


MAP_A, MAP_B = "a" * 16, "b" * 16
POSE, THROUGH, FOLLOW = NavigationRouteSnapshot.STATUS_TOPICS


def plan(points=((0, 0), (1, 2)), *, frame="map", stamp=20):
    return NS(header=NS(frame_id=frame, stamp=NS(sec=stamp, nanosec=0)),
              poses=[NS(pose=NS(position=NS(x=x, y=y))) for x, y in points])


def status(code=2, goal=1, stamp=18):
    return NS(status_list=[NS(status=code, goal_info=NS(
        goal_id=NS(uuid=[goal] * 16), stamp=NS(sec=stamp, nanosec=0)))])


@pytest.fixture
def snapshot():
    now = [100.0]
    route = NavigationRouteSnapshot(clock=lambda: now[0])
    route.set_map(MAP_A, 10_000_000_000)
    return route, now


@pytest.mark.parametrize("topic", [POSE, THROUGH, FOLLOW])
def test_any_navigation_source_displays_plan_without_marker_goal(snapshot, topic):
    route, now = snapshot
    route.on_plan(plan())  # planner publishes before FollowPath acceptance
    route.on_status(topic, status())
    assert route.snapshot(MAP_A)["points"] == [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 2.0}]
    now[0] += 600  # no 5-second TTL for a long, single-published route
    assert route.snapshot(MAP_A)
    route.on_plan(plan(((3, 4), (5, 6))))
    assert route.snapshot(MAP_A)["points"][0] == {"x": 3.0, "y": 4.0}


@pytest.mark.parametrize("code", [3, 4, 5, 6])
def test_terminal_or_canceling_navigation_clears_and_does_not_resurrect(snapshot, code):
    route, _ = snapshot
    route.on_status(FOLLOW, status())
    route.on_plan(plan())
    route.on_status(FOLLOW, status(code))
    assert route.snapshot(MAP_A) is None
    route.on_status(FOLLOW, status(2, goal=2))
    assert route.snapshot(MAP_A) is None


def test_controller_replanning_does_not_hide_executing_upper_navigation(snapshot):
    route, _ = snapshot
    route.on_status(POSE, status())
    route.on_status(FOLLOW, status(goal=2))
    route.on_plan(plan())
    route.on_status(FOLLOW, status(4, goal=2))
    assert route.snapshot(MAP_A)
    route.on_status(POSE, status(4))
    assert route.snapshot(MAP_A) is None


def test_idle_and_old_candidate_not_displayed_when_navigation_starts(snapshot):
    route, now = snapshot
    route.on_plan(plan())
    assert route.snapshot(MAP_A) is None
    now[0] += 3
    route.on_status(FOLLOW, status())
    assert route.snapshot(MAP_A) is None
    route.on_plan(plan(stamp=21))
    assert route.snapshot(MAP_A)


@pytest.mark.parametrize("message", [plan(()), plan(((1, 2),)), plan(frame="odom"),
    plan(((0, 0), (float("nan"), 2))), plan(((0, 0), (100001, 0))), plan(stamp=9), plan(stamp=0)])
def test_invalid_empty_or_pre_map_plan_clears_current_route(snapshot, message):
    route, _ = snapshot
    route.on_status(FOLLOW, status())
    route.on_plan(plan())
    route.on_plan(message)
    assert route.snapshot(MAP_A) is None


def test_new_map_reset_stop_and_publisher_loss_clear_route(snapshot):
    route, _ = snapshot
    route.on_status(FOLLOW, status())
    route.on_plan(plan())
    assert route.snapshot(MAP_B) is None
    route.set_map(MAP_B, 21_000_000_000)
    assert route.snapshot(MAP_B) is None
    route.on_plan(plan(stamp=22))
    assert route.snapshot(MAP_B)
    route.remove_source(FOLLOW)
    assert route.snapshot(MAP_B) is None
    route.on_status(FOLLOW, status(goal=3))
    route.on_plan(plan(stamp=23))
    route.clear()
    assert route.snapshot(MAP_B) is None


def test_route_is_bounded_preserves_endpoints_and_returns_independent_copy(snapshot):
    route, _ = snapshot
    route.on_status(FOLLOW, status())
    route.on_plan(plan([(i, i) for i in range(2000)]))
    result = route.snapshot(MAP_A)
    assert len(result["points"]) == 512
    assert result["points"][-1] == {"x": 1999.0, "y": 1999.0}
    result["points"].clear()
    assert len(route.snapshot(MAP_A)["points"]) == 512
    route.on_plan(plan([(0, 0)] * 65537))
    assert route.snapshot(MAP_A) is None


def test_goal_replacement_cannot_inherit_route_through_old_controller_goal(snapshot):
    route, _ = snapshot
    route.on_status(POSE, status())
    route.on_status(FOLLOW, status(goal=2))
    route.on_plan(plan())
    route.on_status(POSE, status(goal=3, stamp=30))
    assert route.snapshot(MAP_A) is None
    route.on_status(FOLLOW, status(4, goal=2))
    assert route.snapshot(MAP_A) is None
    route.on_plan(plan(stamp=31))
    assert route.snapshot(MAP_A)


def test_delayed_old_plan_after_terminal_cannot_reappear_on_next_goal(snapshot):
    route, _ = snapshot
    route.on_status(FOLLOW, status())
    route.on_plan(plan())
    route.on_status(FOLLOW, status(4), received_ros_ns=21_000_000_000)
    route.on_plan(plan(stamp=20))
    route.on_status(FOLLOW, status(goal=2, stamp=22))
    assert route.snapshot(MAP_A) is None
    route.on_plan(plan(stamp=23))
    assert route.snapshot(MAP_A)


def test_upper_goal_terminal_clears_even_if_controller_terminal_is_delayed(snapshot):
    route, _ = snapshot
    route.on_status(POSE, status())
    route.on_status(FOLLOW, status(goal=2))
    route.on_plan(plan())
    route.on_status(POSE, status(4))
    assert route.snapshot(MAP_A) is None


def test_plan_for_new_goal_can_arrive_before_its_status_without_losing_single_plan(snapshot):
    route, _ = snapshot
    route.on_status(POSE, status())
    route.on_plan(plan())
    route.on_plan(plan(((10, 10), (20, 20)), stamp=31))
    route.on_status(POSE, status(goal=3, stamp=30))
    assert route.snapshot(MAP_A)["points"][0] == {"x": 10.0, "y": 10.0}


def test_old_plan_delivered_after_new_goal_status_is_rejected(snapshot):
    route, _ = snapshot
    route.on_status(POSE, status(goal=3, stamp=30))
    route.on_plan(plan(stamp=20))
    assert route.snapshot(MAP_A) is None


def test_handoff_uses_goal_acceptance_not_delayed_status_callback_time(snapshot):
    route, _ = snapshot
    route.on_status(POSE, status())
    route.on_plan(plan())
    route.on_status(POSE, status(goal=3, stamp=30), received_ros_ns=32_000_000_000)
    route.on_plan(plan(stamp=31))
    assert route.snapshot(MAP_A)


def test_follow_path_candidate_grace_never_undoes_previous_terminal_fence(snapshot):
    route, _ = snapshot
    route.on_status(FOLLOW, status(stamp=10))
    route.on_plan(plan(stamp=20))
    route.on_status(FOLLOW, status(4, stamp=10), received_ros_ns=21_000_000_000)
    route.on_status(FOLLOW, status(goal=2, stamp=22))
    route.on_plan(plan(stamp=20))
    assert route.snapshot(MAP_A) is None
    route.on_plan(plan(stamp=23))
    assert route.snapshot(MAP_A)


def test_opt_in_http_route_snapshot_preserves_plain_active_map_response(monkeypatch):
    import web_console
    calls = []
    class Observation:
        def active_map_id(self): return MAP_A
        def navigation_route(self, map_id):
            calls.append(map_id)
            return {"map_id": map_id, "frame_id": "map", "points": [{"x": 0, "y": 0}, {"x": 1, "y": 2}]}
    monkeypatch.setattr(web_console, "OBSERVATION", Observation())
    server = ThreadingHTTPServer(("127.0.0.1", 0), web_console.ConsoleHandler)
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
    worker.start()
    try:
        for suffix, expected in [("", False), ("?include_route=false", False), ("?include_route=true", True)]:
            connection = http.client.HTTPConnection(*server.server_address, timeout=2)
            try:
                connection.request("GET", "/api/observation/active-map" + suffix)
                response = connection.getresponse()
                payload = json.loads(response.read())
                assert response.status == 200
                assert payload["active_map_id"] == MAP_A
                assert ("navigation_route" in payload) == expected
            finally:
                connection.close()
        assert calls == [MAP_A]
    finally:
        server.shutdown()
        worker.join(timeout=2)
        server.server_close()
