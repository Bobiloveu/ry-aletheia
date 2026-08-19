from __future__ import annotations

import json
import os
import threading
import time
from math import atan2, cos, hypot, sin
from dataclasses import dataclass, replace
from typing import Any, Callable

from .map_assets import CachedMapAsset, MapAssetCache
from .navigation_status import NavigationStatusMonitor


class TrajectoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class ActiveMap:
    asset_id: str | None
    label: str
    load_time_ns: int
    resolution: float
    width: int
    height: int
    origin_x: float
    origin_y: float
    frame_id: str


class TrajectorySession:
    """单轮、低频率的 /odom 采集器；/map 仅在地图切换时进入回调。"""

    ROUTE_END_DISTANCE_M = 0.8
    ROUTE_END_PROGRESS = 0.98
    # 仅用于精确时间戳略晚于 TF 缓冲区的瞬时场景。超过此阈值的最新变换
    # 可能明显落后于车辆真实位姿，仍拒绝该点而不猜测坐标。
    LATEST_TF_MAX_LAG_NS = 500_000_000

    def __init__(self, maps: list[CachedMapAsset], route_plan: list[dict[str, Any]] | None = None, progress_callback: Callable[[dict[str, Any]], None] | None = None, sample_hz: float = 5.0, stagnation_timeout_s: float = 30.0, movement_threshold_m: float = 0.15, elevator_wait_timeout_s: float = 180.0, map_cache_dir=None) -> None:
        self.maps = list(maps)
        self.route_plan = [dict(item) for item in (route_plan or [])]
        self._map_cache = MapAssetCache(map_cache_dir) if map_cache_dir else None
        self.progress_callback = progress_callback
        self.minimum_interval = 1.0 / sample_hz
        self.stagnation_timeout_s = stagnation_timeout_s
        self.movement_threshold_m = movement_threshold_m
        self._navigation_status = NavigationStatusMonitor(elevator_wait_timeout_s)
        self._lock = threading.Lock()
        self._active_map: ActiveMap | None = None
        self._segments: dict[str, dict[str, Any]] = {}
        # /odom 在机器人上通常高于轨迹需要的 5 Hz。回调只保留最新一帧，
        # 由定时器按固定频率完成 TF、路线投影与文件记录，避免高频重复计算。
        self._latest_odom: dict[str, Any] | None = None
        self._latest_odom_sequence = 0
        self._processed_odom_sequence = 0
        self._samples_processed = 0
        self._node = None
        self._executor = None
        self._thread: threading.Thread | None = None
        self._route_index = 0
        self._route_progress: dict[int, float] = {}
        self._reported_percent = 0.0
        # TF 或 /map 切换的短暂空窗也要保留最后一次有效进度，不能让网页把
        # 已运行中的路线错误显示为 0%。
        self._last_progress: dict[str, Any] = {}
        self._started_at = 0.0
        self._last_odom_at: float | None = None
        self._movement_anchor: tuple[float, float] | None = None
        self._movement_anchor_at = 0.0
        self._stalled = False
        self._alert_id = 0
        self._elevator_timeout_alerted = False
        self._tf_buffer = None
        self._transform_listener = None
        self._tf_errors = 0
        self._tf_last_error = ""
        self._tf_latest_fallbacks = 0
        self._tf_last_fallback = ""
        self._odom_received = 0
        self._points_rejected = 0
        self._map_unmatched = 0
        self._map_last_error = ""
        self._map_epoch = 0

    def start(self) -> None:
        try:
            import rclpy
            from nav_msgs.msg import OccupancyGrid, Odometry
            from master_interfaces.msg import NavigateTodoorStatus
            from rclpy.executors import SingleThreadedExecutor
            from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
            from tf2_ros import Buffer, TransformListener
        except ImportError as exc:
            raise TrajectoryError(f"无法加载 ROS2 轨迹依赖：{exc}") from exc
        if not rclpy.ok():
            rclpy.init()
        self._started_at = time.monotonic()
        self._node = rclpy.create_node("autodrive_trajectory_recorder")
        # /odom 的 frame_id 不等于地图坐标系。必须经 TF 变换后才能叠加到 map.yaml/PGM。
        self._tf_buffer = Buffer()
        self._transform_listener = TransformListener(self._tf_buffer, self._node, spin_thread=False)
        map_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self._node.create_subscription(OccupancyGrid, "/map", self._on_map, map_qos)
        self._node.create_subscription(Odometry, "/odom", self._on_odom, 10)
        # VOLATILE + RELIABLE：每轮启动订阅，只处理最新任务阶段，不保留历史。
        self._node.create_subscription(NavigateTodoorStatus, "/navigate_todoor_detailed_status", self._on_navigation_status, 1)
        self._node.create_timer(self.minimum_interval, self._on_sample)
        self._node.create_timer(1.0, self._on_watchdog)
        self._executor = SingleThreadedExecutor()
        self._executor.add_node(self._node)
        self._thread = threading.Thread(target=self._executor.spin, daemon=True, name="trajectory-recorder")
        self._thread.start()

    def stop(self) -> dict[str, Any]:
        # 定时器最后一次采样可能尚未来得及触发。先在 ROS executor 仍活跃时把
        # 最新 /odom 刷入，避免任务服务刚返回时丢失最后一小段行驶轨迹。
        try:
            self._on_sample()
        except Exception:
            # 收尾采样只能补充证据，绝不能让已有轨迹因一次 TF 瞬态失败而丢失。
            pass
        if self._executor:
            self._executor.shutdown()
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._node:
            self._node.destroy_node()
        with self._lock:
            segments = list(self._segments.values())
            return {
                "sample_hz": round(1 / self.minimum_interval, 2),
                "points": sum(len(item["points"]) for item in segments),
                "segments": segments,
                "maps": [item.to_dict() for item in self.maps],
                "route_plan": self.route_plan,
                "diagnostics": {
                    "odom_received": self._odom_received,
                    "odom_processed": self._processed_odom_sequence,
                    "trajectory_samples": self._samples_processed,
                    "points_rejected": self._points_rejected,
                    "tf_errors": self._tf_errors,
                    "tf_last_error": self._tf_last_error,
                    "tf_latest_fallbacks": self._tf_latest_fallbacks,
                    "tf_last_fallback": self._tf_last_fallback,
                    "map_unmatched": self._map_unmatched,
                    "map_last_error": self._map_last_error,
                },
            }

    def _on_map(self, message) -> None:
        info = message.info
        load_time_ns = int(info.map_load_time.sec) * 1_000_000_000 + int(info.map_load_time.nanosec)
        resolution, width, height = float(info.resolution), int(info.width), int(info.height)
        origin_x, origin_y = float(info.origin.position.x), float(info.origin.position.y)
        frame_id = str(message.header.frame_id).strip()
        legacy_id = self._match_asset(resolution, width, height, origin_x, origin_y)
        legacy_asset = next((item for item in self.maps if item.id == legacy_id), None)
        runtime_asset = None
        if self._map_cache:
            try:
                runtime_asset = self._map_cache.cache_occupancy_grid(
                    resolution=resolution, width=width, height=height, origin=[origin_x, origin_y], frame_id=frame_id,
                    data=list(message.data), label=legacy_asset.label if legacy_asset else None, wall_source=legacy_asset,
                )
            except Exception as exc:
                with self._lock:
                    self._map_last_error = f"无法缓存 ROS2 /map：{exc}"
        asset_id = runtime_asset.id if runtime_asset else legacy_id
        if runtime_asset:
            with self._lock:
                # JSON 的 map_url 缓存与实际 ROS /map 的栅格内容可能存在极小差异，
                # 因而会得到不同 asset_id。它们的几何元数据相同，不能同时保留，
                # 否则报告会出现两个同名 P2：第一个是旧离线缓存、没有实测点，
                # 前端默认选中它后就会误以为“轨迹丢失”。实际地图必须替换该离线占位。
                if legacy_id and legacy_id != runtime_asset.id:
                    self.maps = [runtime_asset if item.id == legacy_id else item for item in self.maps]
                elif not any(item.id == runtime_asset.id for item in self.maps):
                    self.maps.append(runtime_asset)
                # 离线 map_url 正确时也必须切换到 ROS 实际地图；同步更新路线绑定，
                # 防止因静态缓存 ID 与运行时地图 ID 不同而误判“等待切图”。
                if legacy_id and legacy_id != runtime_asset.id:
                    for route in self.route_plan:
                        if route.get("map_id") == legacy_id:
                            route["map_id"], route["map_label"] = runtime_asset.id, runtime_asset.label
        active = ActiveMap(
            asset_id=asset_id,
            label=runtime_asset.label if runtime_asset else "未匹配任务地图", load_time_ns=load_time_ns, resolution=resolution, width=width, height=height,
            origin_x=origin_x, origin_y=origin_y, frame_id=frame_id,
        )
        if active.asset_id and not runtime_asset:
            active = replace(active, label=next(item.label for item in self.maps if item.id == active.asset_id))
        with self._lock:
            # 不能只依据 map_load_time：部分 map_server 在切图时保持该字段为 0。
            # ActiveMap 是不可变 dataclass，完整比较可覆盖地图尺寸、分辨率、原点、frame_id 与匹配资产。
            if self._active_map == active:
                return
            if not active.asset_id:
                self._map_unmatched += 1
                self._map_last_error = f"/map 元数据未匹配任务缓存地图（{active.width}×{active.height}，分辨率 {active.resolution}，原点 {active.origin_x:.3f},{active.origin_y:.3f}）"
            self._active_map = active
            self._map_epoch += 1
            map_epoch = self._map_epoch
        # 观测页只读取这个小型标记文件，绝不另起 /map 订阅。写入失败不应影响
        # 轨迹采集或任务执行，因此仅记录诊断信息。
        if active.asset_id and self._map_cache:
            try:
                self._write_active_map_marker(active, map_epoch)
            except OSError as exc:
                with self._lock:
                    self._map_last_error = f"无法更新实时观测地图标记：{exc}"

    def _write_active_map_marker(self, active: ActiveMap, map_epoch: int) -> None:
        if not self._map_cache or not active.asset_id:
            return
        target = self._map_cache.cache_dir / "active_map.json"
        payload = {
            "asset_id": active.asset_id, "label": active.label, "map_epoch": map_epoch,
            "updated_at_ns": time.time_ns(), "frame_id": active.frame_id,
        }
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(temporary, target)

    def _on_odom(self, message) -> None:
        """高频回调仅更新最新定位；重计算统一交给固定频率定时器。"""
        pose, stamp = message.pose.pose, message.header.stamp
        progress = None
        with self._lock:
            self._odom_received += 1
            self._last_odom_at = time.monotonic()
            self._latest_odom_sequence += 1
            self._latest_odom = {
                "sequence": self._latest_odom_sequence,
                "source_frame": str(message.header.frame_id).strip(),
                "stamp": stamp,
                "x": float(pose.position.x),
                "y": float(pose.position.y),
            }

    def _on_navigation_status(self, message) -> None:
        with self._lock:
            self._navigation_status.observe(message)

    def _on_sample(self) -> None:
        """以 sample_hz 处理最新 /odom，限制 TF 与路线计算的资源占用。"""
        now = time.monotonic()
        progress = None
        with self._lock:
            odom = self._latest_odom
            if odom is None or odom["sequence"] == self._processed_odom_sequence:
                return
            self._processed_odom_sequence = odom["sequence"]
            active = self._active_map
            elevator_wait = self._navigation_status.snapshot(now)
            transformed = self._to_map_coordinates(active, odom["source_frame"], odom["stamp"], odom["x"], odom["y"]) if active else None
            if transformed is None:
                self._points_rejected += 1
                progress = {
                    **self._last_progress,
                    "state": "等待 /map" if active is None else "等待 map←odom 坐标变换",
                    "percent": round(self._reported_percent, 1),
                    "points": sum(len(item["points"]) for item in self._segments.values()),
                    "tf_errors": self._tf_errors,
                    "tf_last_error": self._tf_last_error,
                }
                self._apply_elevator_wait(progress, elevator_wait)
            else:
                x, y = round(transformed[0], 5), round(transformed[1], 5)
                stall = self._observe_motion(now, x, y, suppress=elevator_wait.active)
                # 同图往返不一定触发 /map 切换。除地图进入批次外，还按已确认的
                # JSON 子任务路线段拆分，避免去程与回程被错误合并成同一条轨迹。
                route_index = self._route_index if self.route_plan else None
                route_name = self.route_plan[route_index]["name"] if route_index is not None and route_index < len(self.route_plan) else ""
                # 使用检测到的切图顺序而非 map_load_time；部分 map_server 会持续发布 0。
                key = f"{active.asset_id or 'unmatched'}_{self._map_epoch}_route_{route_index if route_index is not None else 'unknown'}"
                segment = self._segments.setdefault(key, {
                    "map_id": active.asset_id, "map_label": active.label, "map_load_time_ns": active.load_time_ns, "map_epoch": self._map_epoch,
                    "route_index": route_index, "route_name": route_name,
                    "map": {"resolution": active.resolution, "width": active.width, "height": active.height, "origin": [active.origin_x, active.origin_y], "frame_id": active.frame_id}, "points": [],
                })
                stamp = odom["stamp"]
                segment["points"].append({"timestamp_ns": int(stamp.sec) * 1_000_000_000 + int(stamp.nanosec), "x": x, "y": y})
                self._samples_processed += 1
                progress = self._estimate_progress(active, x, y, sum(len(item["points"]) for item in self._segments.values())) or {}
                progress.update(stall)
                self._apply_elevator_wait(progress, elevator_wait)
                self._last_progress = dict(progress)
        if progress and self.progress_callback:
            self.progress_callback(progress)

    def _to_map_coordinates(self, active: ActiveMap, source_frame: str, stamp, x: float, y: float) -> tuple[float, float] | None:
        """将 /odom 位姿严格转换到当前 OccupancyGrid 的 frame_id。

        旧实现直接把 odom 的数值当作 map 坐标，会在 map→odom 有平移或旋转时产生整体偏移。
        变换缺失时不使用猜测坐标，避免把错误数据写入正式报告。
        """
        if not active.frame_id:
            self._tf_errors += 1
            self._tf_last_error = "/map 消息缺少 frame_id"
            return None
        if not source_frame:
            self._tf_errors += 1
            self._tf_last_error = "/odom 消息缺少 frame_id"
            return None
        if source_frame == active.frame_id:
            return x, y
        try:
            from rclpy.time import Time
            transform = self._tf_buffer.lookup_transform(active.frame_id, source_frame, Time.from_msg(stamp))
        except Exception as exact_error:
            # /odom 与 /tf 经 DDS 到达的先后不完全一致。截图中的 "extrapolation
            # into the future" 仅差数毫秒，若直接拒绝会导致整轮大量丢点。此处只对
            # 明确的未来外推回退到最新 TF，其他坐标树错误仍保持严格拒绝。
            if not _is_future_extrapolation(exact_error):
                self._record_tf_error(active, source_frame, exact_error)
                return None
            try:
                transform = self._tf_buffer.lookup_transform(active.frame_id, source_frame, Time())
            except Exception as latest_error:
                self._record_tf_error(active, source_frame, latest_error, exact_error)
                return None
            lag_ns = _transform_lag_ns(transform, stamp)
            if lag_ns is not None and lag_ns > self.LATEST_TF_MAX_LAG_NS:
                self._tf_errors += 1
                self._tf_last_error = f"{active.frame_id}←{source_frame} 最新变换滞后 {lag_ns / 1_000_000:.0f} ms，超过允许的 {self.LATEST_TF_MAX_LAG_NS / 1_000_000:.0f} ms"
                return None
            self._tf_latest_fallbacks += 1
            lag_text = "静态变换" if lag_ns is None else f"滞后 {lag_ns / 1_000_000:.1f} ms"
            self._tf_last_fallback = f"精确时间戳短暂超前，已使用最新 {active.frame_id}←{source_frame} 变换（{lag_text}）"
        return _apply_planar_transform(transform.transform.translation, transform.transform.rotation, x, y)

    def _record_tf_error(self, active: ActiveMap, source_frame: str, error: Exception, exact_error: Exception | None = None) -> None:
        self._tf_errors += 1
        suffix = f"；精确查询错误：{exact_error}" if exact_error is not None else ""
        self._tf_last_error = f"{active.frame_id}←{source_frame} 变换不可用：{error}{suffix}"
    def _on_watchdog(self) -> None:
        now = time.monotonic()
        with self._lock:
            reference = self._last_odom_at if self._last_odom_at is not None else self._started_at
            if now - reference < self.stagnation_timeout_s or self._stalled:
                return
            self._stalled = True
            self._alert_id += 1
            reason = "连续未收到 /odom 定位数据" if self._last_odom_at is None else "连续未收到新的 /odom 定位数据"
            progress = {
                **self._last_progress,
                "state": "定位数据中断",
                "percent": round(self._reported_percent, 1),
                "points": sum(len(item["points"]) for item in self._segments.values()),
                "stalled": True,
                "alert": True,
                "alert_id": self._alert_id,
                "alert_reason": reason,
                "stalled_seconds": round(now - reference, 1),
            }
        if self.progress_callback:
            self.progress_callback(progress)

    def _apply_elevator_wait(self, progress: dict[str, Any], elevator_wait) -> None:
        if not elevator_wait.active:
            self._elevator_timeout_alerted = False
            return
        progress["elevator_wait"] = elevator_wait.to_dict()
        progress["state"] = "电梯流程预期等待"
        progress["stalled"] = elevator_wait.timed_out
        progress["alert"] = elevator_wait.timed_out
        progress["alert_reason"] = "电梯流程等待超时" if elevator_wait.timed_out else "电梯流程中，普通停滞提醒已暂停"
        progress["stalled_seconds"] = round(elevator_wait.elapsed_s, 1)
        if elevator_wait.timed_out and not self._elevator_timeout_alerted:
            self._elevator_timeout_alerted, self._alert_id = True, self._alert_id + 1
        progress["alert_id"] = self._alert_id if elevator_wait.timed_out else None

    def _observe_motion(self, now: float, x: float, y: float, suppress: bool = False) -> dict[str, Any]:
        if suppress:
            self._movement_anchor, self._movement_anchor_at, self._stalled = (x, y), now, False
            return {"stalled": False, "alert": False, "alert_id": None, "alert_reason": None, "stalled_seconds": 0.0}
        if self._movement_anchor is None:
            self._movement_anchor, self._movement_anchor_at = (x, y), now
        elif hypot(x - self._movement_anchor[0], y - self._movement_anchor[1]) >= self.movement_threshold_m:
            self._movement_anchor, self._movement_anchor_at, self._stalled = (x, y), now, False
        elapsed = now - self._movement_anchor_at
        if elapsed >= self.stagnation_timeout_s and not self._stalled:
            self._stalled, self._alert_id = True, self._alert_id + 1
        # alert 在停滞期间保持为真，避免 Web 轮询恰好错过首次告警事件。
        return {"stalled": self._stalled, "alert": self._stalled, "alert_id": self._alert_id if self._stalled else None, "alert_reason": "车辆位置持续无明显变化" if self._stalled else None, "stalled_seconds": round(elapsed, 1)}

    def _estimate_progress(self, active: ActiveMap | None, x: float, y: float, point_count: int) -> dict[str, Any] | None:
        if not self.route_plan:
            return {"state": "任务未提供可计算的理想路径", "points": point_count, "position": {"x": x, "y": y}}
        if self._route_index >= len(self.route_plan):
            return {"state": "全部线路已完成", "percent": 100.0, "points": point_count, "position": {"x": x, "y": y}}
        route = self.route_plan[self._route_index]
        if active and active.asset_id and route.get("map_id") is None:
            # JSON 地图地址不可用时，将当前子任务绑定到 ROS2 实际地图；坐标点仍来自任务 JSON。
            route["map_id"], route["map_label"] = active.asset_id, active.label
        if active and active.asset_id and route.get("map_id") and active.asset_id != route["map_id"]:
            # 当前地图与当前子任务不一致时，不能把位置投影到另一张地图后伪造
            # 0% 进度。保留本轮最后一个有效总进度；若尚无有效投影则明确标记为
            # “不可计算”，由前端显示占位符而非误导性的零进度。
            return {
                **self._last_progress,
                "state": "等待切换至当前子任务地图",
                "progress_available": bool(self._last_progress.get("progress_available", False)),
                "points": point_count,
                "position": {"x": x, "y": y},
                "map_label": active.label,
                "expected_map_label": route.get("map_label") or "任务地图",
                "route_name": route.get("name") or "当前子任务",
                "route_index": self._route_index + 1,
                "route_total": len(self.route_plan),
            }
        match_mode = "地图匹配" if active and active.asset_id else "位置匹配"
        # /map 短暂缺失时只回退匹配当前子任务，绝不按空间距离跳到后续线路。
        distance_to_route, distance, total = _project_route(route["points"], x, y)
        if not active and distance_to_route > 3.0:
            return {"state": "定位与当前理想路线距离较远，等待路线匹配", "points": point_count, "position": {"x": x, "y": y}, "map_label": route["map_label"]}
        if total <= 0:
            return None
        self._route_progress[self._route_index] = max(self._route_progress.get(self._route_index, 0.0), distance)
        at_route_end = (
            hypot(x - float(route["points"][-1]["x"]), y - float(route["points"][-1]["y"])) <= self.ROUTE_END_DISTANCE_M
            and self._route_progress[self._route_index] >= total * self.ROUTE_END_PROGRESS
        )
        if at_route_end and self._route_index + 1 < len(self.route_plan):
            self._route_progress[self._route_index] = total
            self._route_index += 1
            route = self.route_plan[self._route_index]
            distance, total = 0.0, _route_length(route["points"])
        current_progress = self._route_progress.setdefault(self._route_index, 0.0)
        completed = sum(_route_length(item["points"]) for item in self.route_plan[:self._route_index]) + current_progress
        full_length = sum(_route_length(item["points"]) for item in self.route_plan)
        percent = min(100.0, max(self._reported_percent, completed / full_length * 100 if full_length else 0.0))
        self._reported_percent = percent
        return {"state": "本轮线路进度", "progress_available": True, "match_mode": match_mode, "percent": round(percent, 1), "route_percent": round(current_progress / total * 100, 1), "route_name": route["name"], "route_index": self._route_index + 1, "route_total": len(self.route_plan), "map_label": active.label if active else route["map_label"], "points": point_count, "position": {"x": x, "y": y}}

    def _match_asset(self, resolution: float, width: int, height: int, origin_x: float, origin_y: float) -> str | None:
        matches = [
            asset.id for asset in self.maps
            if asset.resolution is not None and asset.origin is not None
            and asset.width == width and asset.height == height
            and abs(asset.resolution - resolution) < 1e-5
            and abs(asset.origin[0] - origin_x) < 1e-3
            and abs(asset.origin[1] - origin_y) < 1e-3
        ]
        # 仅当元数据能唯一对应一个离线地图时才替换。几何数据相同的不同地图
        # 无法安全判断，宁可将运行时地图作为独立资产，不能覆盖错误的路线/虚拟墙。
        return matches[0] if len(matches) == 1 else None


def _apply_planar_transform(translation, rotation, x: float, y: float) -> tuple[float, float]:
    """应用 map←source 的二维刚体变换；独立函数便于离线校验坐标方向。"""
    yaw = atan2(2.0 * (rotation.w * rotation.z + rotation.x * rotation.y), 1.0 - 2.0 * (rotation.y * rotation.y + rotation.z * rotation.z))
    return translation.x + cos(yaw) * x - sin(yaw) * y, translation.y + sin(yaw) * x + cos(yaw) * y


def _is_future_extrapolation(error: Exception) -> bool:
    """仅识别 TF 的未来外推，避免把真正的坐标树故障伪装成可接受回退。"""
    text = str(error).lower()
    return "extrapolation into the future" in text or "future extrapolation" in text


def _transform_lag_ns(transform, requested_stamp) -> int | None:
    """返回最新动态 TF 相对请求 Odom 的滞后；静态/无时间戳变换返回 None。"""
    header = getattr(transform, "header", None)
    stamp = getattr(header, "stamp", None)
    if stamp is None:
        return None
    transform_ns = int(getattr(stamp, "sec", 0)) * 1_000_000_000 + int(getattr(stamp, "nanosec", 0))
    if transform_ns <= 0:
        return None
    requested_ns = int(getattr(requested_stamp, "sec", 0)) * 1_000_000_000 + int(getattr(requested_stamp, "nanosec", 0))
    return max(0, requested_ns - transform_ns)


def _route_length(points: list[dict[str, Any]]) -> float:
    return sum(hypot(float(right["x"]) - float(left["x"]), float(right["y"]) - float(left["y"])) for left, right in zip(points, points[1:]))


def _project_distance(points: list[dict[str, Any]], x: float, y: float) -> tuple[float, float]:
    """返回坐标在线段串上的最近投影累计距离与路线总长。"""
    _distance, along, total = _project_route(points, x, y)
    return along, total


def _project_route(points: list[dict[str, Any]], x: float, y: float) -> tuple[float, float, float]:
    """返回到路线的最近距离、路线累计投影距离和路线总长。"""
    total = _route_length(points)
    if total <= 0:
        return float("inf"), 0.0, total
    best_distance, best_along, traversed = float("inf"), 0.0, 0.0
    for left, right in zip(points, points[1:]):
        dx, dy = float(right["x"]) - float(left["x"]), float(right["y"]) - float(left["y"])
        length = hypot(dx, dy)
        if length <= 1e-9:
            continue
        ratio = max(0.0, min(1.0, ((x - float(left["x"])) * dx + (y - float(left["y"])) * dy) / (length * length)))
        px, py = float(left["x"]) + ratio * dx, float(left["y"]) + ratio * dy
        distance = hypot(x - px, y - py)
        if distance < best_distance:
            best_distance, best_along = distance, traversed + ratio * length
        traversed += length
    return best_distance, best_along, total
