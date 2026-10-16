"""Bounded read-only plan display, independent of marker navigation control."""

from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable


LOGGER = logging.getLogger("ry_aletheia.navigation_route")


class NavigationRouteSnapshot:
    STATUS_TOPICS = (
        "/navigate_to_pose/_action/status",
        "/navigate_through_poses/_action/status",
        "/follow_path/_action/status",
    )
    MAX_POINTS = 512
    MAX_INPUT_POINTS = 65_536
    CANDIDATE_GRACE_S = 2.0

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.RLock()
        self._map_id: str | None = None
        self._map_epoch = 0
        self._generation = 0
        self._goals: dict[str, dict[bytes, int]] = {}
        self._points: tuple[tuple[float, float], ...] = ()
        self._owner: tuple[str, bytes, int] | None = None
        self._plan_stamp_ns = 0
        self._min_stamp_ns = 0
        self._terminal_stamp_ns = 0
        self._received_at = 0.0

    def set_map(self, map_id: str | None, epoch: int = 0) -> None:
        with self._lock:
            self._generation += 1
            self._map_id, self._map_epoch = map_id, epoch
            self._points = ()
            self._owner = None
            self._plan_stamp_ns = 0
            self._min_stamp_ns = epoch
            self._terminal_stamp_ns = 0

    def clear(self) -> None:
        with self._lock:
            self.set_map(None)
            self._goals.clear()

    def on_plan(self, message: object) -> None:
        with self._lock:
            generation, epoch = self._generation, self._min_stamp_ns
            active = self._active_goal()
            if active:
                epoch = max(epoch, self._goal_plan_floor(active))
        points = ()
        stamp_ns = 0
        try:
            poses = message.poses
            stamp = message.header.stamp
            stamp_ns = int(stamp.sec) * 1_000_000_000 + int(stamp.nanosec)
            if (message.header.frame_id.strip().lstrip("/") != "map"
                    or not 2 <= len(poses) <= self.MAX_INPUT_POINTS
                    or (stamp_ns <= 0 or stamp_ns < epoch)):
                raise ValueError("invalid plan metadata")
            # Validate all input, including points omitted by downsampling.
            values = [(float(p.pose.position.x), float(p.pose.position.y)) for p in poses]
            if any(not math.isfinite(v) or abs(v) > 100_000 for xy in values for v in xy):
                raise ValueError("invalid plan coordinates")
            count = min(len(values), self.MAX_POINTS)
            points = tuple(values[round(i * (len(values) - 1) / (count - 1))] for i in range(count))
        except (AttributeError, TypeError, ValueError, OverflowError):
            pass
        with self._lock:
            if generation != self._generation:
                return
            self._points = points
            self._owner = self._active_goal()
            self._plan_stamp_ns = stamp_ns
            self._received_at = self._clock()

    def on_status(self, topic: str, message: object, *, received_ros_ns: int = 0) -> None:
        if topic not in self.STATUS_TOPICS:
            return
        goals = {}
        try:
            if len(message.status_list) > 256:
                raise ValueError("too many goals")
            for entry in message.status_list:
                if entry.status not in (1, 2):  # accepted/executing; canceling hides
                    continue
                goal_id = bytes(entry.goal_info.goal_id.uuid)
                stamp = entry.goal_info.stamp
                accepted_ns = int(stamp.sec) * 1_000_000_000 + int(stamp.nanosec)
                if len(goal_id) != 16 or not any(goal_id) or accepted_ns <= 0:
                    raise ValueError("invalid goal identity or timestamp")
                goals[goal_id] = accepted_ns
        except (AttributeError, TypeError, ValueError, OverflowError):
            goals.clear()
        self._update_goals(topic, goals, received_ros_ns)

    def _active_goal(self) -> tuple[str, bytes, int] | None:
        # The upper navigation action owns the route across FollowPath replans.
        # Direct controller users are supported when there is no upper action.
        upper = [(topic, goal, stamp) for topic, goals in self._goals.items()
                 if topic != self.STATUS_TOPICS[-1] for goal, stamp in goals.items()]
        candidates = upper or [(self.STATUS_TOPICS[-1], goal, stamp)
                              for goal, stamp in self._goals.get(self.STATUS_TOPICS[-1], {}).items()]
        return max(candidates, key=lambda item: (item[2], item[0], item[1]), default=None)

    def _discard_plan(self, received_ros_ns: int, *, terminal: bool = False) -> None:
        self._generation += 1
        self._points = ()
        self._owner = None
        # A queued plan from before the terminal callback must not become the
        # next goal's candidate. Compare ROS stamps, never wall/monotonic time.
        self._min_stamp_ns = max(self._min_stamp_ns, received_ros_ns or self._plan_stamp_ns + 1)
        if terminal:
            self._terminal_stamp_ns = self._min_stamp_ns

    def _goal_plan_floor(self, goal: tuple[str, bytes, int]) -> int:
        grace_ns = int(self.CANDIDATE_GRACE_S * 1e9) if goal[0] == self.STATUS_TOPICS[-1] else 0
        return max(self._map_epoch, self._terminal_stamp_ns, goal[2] - grace_ns)

    def _update_goals(self, topic: str, goals: dict[bytes, int], received_ros_ns: int = 0) -> None:
        with self._lock:
            previous = self._active_goal()
            self._goals[topic] = goals
            active = self._active_goal()
            new_goal = active and (not previous or previous[:2] != active[:2])
            if new_goal:
                self._generation += 1
            upper_ended = previous and previous[0] != self.STATUS_TOPICS[-1] and (
                not active or active[0] == self.STATUS_TOPICS[-1])
            if (previous and not active) or upper_ended:
                self._discard_plan(received_ros_ns, terminal=True)
            elif active and self._points:
                if self._owner is None:
                    grace_ns = int(self.CANDIDATE_GRACE_S * 1e9) if active[0] == self.STATUS_TOPICS[-1] else 0
                    if (self._clock() - self._received_at > self.CANDIDATE_GRACE_S
                            or self._plan_stamp_ns < active[2] - grace_ns):
                        self._discard_plan(received_ros_ns)
                    else:
                        self._owner = active
                elif self._owner[:2] != active[:2]:
                    if self._plan_stamp_ns >= active[2] and (
                        active[2] > self._owner[2] or self._owner[0] == self.STATUS_TOPICS[-1]
                    ):
                        self._owner = active
                    else:
                        self._discard_plan(received_ros_ns)
            if new_goal and not upper_ended:
                # New goals may predate delivery of the previous terminal
                # status. Their accepted stamp, not callback execution time,
                # is the lower bound for their single published plan.
                self._min_stamp_ns = self._goal_plan_floor(active)
            if bool(previous) != bool(active):
                LOGGER.info("规划路线观测导航状态改变：active=%s", bool(active))

    def remove_source(self, topic: str) -> None:
        if topic in self.STATUS_TOPICS:
            self._update_goals(topic, {})

    def snapshot(self, map_id: str | None) -> dict[str, object] | None:
        with self._lock:
            if not map_id or map_id != self._map_id or not self._active_goal() or not self._points:
                return None
            return {"map_id": map_id, "frame_id": "map",
                    "points": [{"x": x, "y": y} for x, y in self._points]}
