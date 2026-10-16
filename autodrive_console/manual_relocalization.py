"""Server-owned manual relocalization coordinator for the PC observation view."""
from __future__ import annotations

import logging
from functools import wraps
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
import math
import os
import re
import uuid
from collections import OrderedDict
from pathlib import Path
import threading
import time
from collections.abc import Callable
from typing import Any

from .current_map_reader import CurrentMapReader, CurrentMapUnavailable
from .map_assets import MapAssetCache
from .scenario_setup import ScenarioSetupStore
from .relocalization_config import RelocalizationConfigError, localizer_runtime_identity
from .relocalization_files import LocalizationConfigFiles, LocalizationConfigFileError
from .vehicle_control import VehicleControlConflict, VehicleControlController, VehicleControlUnavailable


LOGGER = logging.getLogger("ry_aletheia.manual_relocalization")


class ManualRelocalizationError(RuntimeError):
    pass


class ManualRelocalizationConflict(ManualRelocalizationError):
    pass


class ManualRelocalizationUnavailable(ManualRelocalizationError):
    pass


def _exclusive_action(method):
    @wraps(method)
    def run(self, *args, **kwargs):
        if not self._action_lock.acquire(blocking=False):
            raise ManualRelocalizationConflict('手动重定位请求正在执行，请等待本次结果')
        try:
            return method(self, *args, **kwargs)
        finally:
            self._action_lock.release()
    return run


class ManualRelocalizationController:
    """Serialize one manual relocalization operation without exposing ROS to the browser."""

    SERVICE = "/localizer/relocalize"
    RESULT_CONFIRM_TIMEOUT_S = 30.0
    RESULT_POLL_INTERVAL_S = 0.1

    def __init__(
        self,
        vehicle_control: VehicleControlController,
        scenario_setup: ScenarioSetupStore,
        *,
        invoke: Callable[[dict[str, Any], int], object] | None = None,
        localization_status: object | None = None,
        switch_map: Callable[[Path, int], object] | None = None,
        config_files: LocalizationConfigFiles | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._vehicle_control = vehicle_control
        # Keep existing callers compatible; startup YAML is not a source here.
        self._runtime_identity = localizer_runtime_identity
        self._bound_runtime: tuple[int, str] | None = None
        self._invoke = invoke
        self._switch_map = switch_map
        self._localization_status = localization_status
        self._config_files = config_files if config_files is not None else LocalizationConfigFiles()
        self._map_reader = CurrentMapReader()
        self._expected_map_yaml: Path | None = None
        self._target_map_id: str | None = None
        self._bound_map: Path | None = None
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.RLock()
        self._action_lock = threading.Lock()
        self._last_snapshot = None
        self._source_map_id = None
        self._operation_id = None
        self._operation_outcome = None
        self._admission_lock = threading.Lock()
        self._operation_results = OrderedDict()
        self._phase = "idle"
        self._detail = "可开始手动重定位"

    def status(self, settings: object) -> dict[str, object]:
        if not self._lock.acquire(blocking=False):
            return dict(self._last_snapshot or {'phase':'switching_to_miniapp', 'can_begin':False,
                'can_apply':False, 'can_cancel':False, 'can_recover_navigation':False,
                'label':'正在确认停车', 'detail':'正在核验本次重定位', 'vehicle_source':'unknown'})
        try:
            hold = str(self._vehicle_control.status().get("relocalization_hold", "idle"))
            if self._phase == "switching_to_miniapp" and hold == "active":
                self._phase, self._detail = "calibrating", "车辆已停车，请拖拽车体与点云对齐"
            elif self._phase == "switching_to_navigation" and hold == "idle":
                self._phase, self._detail = "idle", "已恢复自动驾驶"
            elif self._phase in {"switching_to_miniapp", "switching_to_navigation", "calibrating"} and hold == "failed":
                if self._phase == 'switching_to_navigation' and self._operation_outcome == 'succeeded':
                    self._operation_outcome = 'failed'
                self._phase, self._detail = "failed", "控制源切换未确认，车辆保持停车"
            return self._snapshot(hold)
        finally:
            self._lock.release()

    @_exclusive_action
    def begin(self, settings: object) -> dict[str, object]:
        with self._lock:
            if self._phase not in {"idle", "failed"}:
                raise ManualRelocalizationConflict("手动重定位正在进行")
            try:
                state = self._vehicle_control.begin_relocalization_hold()
            except (VehicleControlConflict, VehicleControlUnavailable) as exc:
                raise ManualRelocalizationConflict(str(exc)) from exc
            hold = str(state.get("relocalization_hold", "switching"))
            self._phase = "switching_to_miniapp"
            # Keep previous outcomes queryable without attaching them to this
            # new parking attempt or overwriting their bound map evidence.
            self._operation_id = self._operation_outcome = None
            self._detail = "正在核验当前地图与定位实例" if hold == "active" else "正在确认车辆停车"
            self._snapshot(hold)
            try:
                self._expected_map_yaml = None
                self._target_map_id = None
                self._bound_map = self._start_current_map_watch()
                self._source_map_id = self._map_reader.source_map_id
                self._bound_runtime = self._runtime_identity()
            except RelocalizationConfigError as exc:
                LOGGER.warning("手动重定位开始失败：%s", exc)
                self._fail(str(exc))
                return self._snapshot("failed")
            except ManualRelocalizationError as exc:
                LOGGER.warning("手动重定位开始失败：%s", exc)
                self._fail(str(exc))
                return self._snapshot("failed")
            except Exception:
                LOGGER.warning("手动重定位开始失败：当前地图无法确认")
                self._fail("当前地图无法确认")
                return self._snapshot("failed")
            return self.status(settings)

    @_exclusive_action
    def apply(self, settings: object, pose: object) -> dict[str, object]:
        normalized = self._pose(pose)
        with self._lock:
            self.status(settings)
            hold = self._vehicle_control.status().get("relocalization_hold")
            if self._phase != "calibrating" or hold != "active":
                raise ManualRelocalizationConflict("车辆尚未确认停车，不能下发重定位")
            if 'source_map_id' in pose:
                source_map_id = pose['source_map_id']
                if not isinstance(source_map_id, str) or not re.fullmatch(r'[a-f0-9]{16}', source_map_id):
                    raise ManualRelocalizationError('预览源地图标识无效，请重新加载地图')
                if source_map_id != self._source_map_id:
                    raise ManualRelocalizationConflict('当前地图与预览源地图不一致，请在当前地图重新设置位姿')
            raw_config = pose.get("config_path", "")
            if not isinstance(raw_config, str):
                raise ManualRelocalizationError("定位配置选择格式无效")
            selection = None
            if raw_config:
                try:
                    selection = self._config_files.select(raw_config, self._bound_map)
                except LocalizationConfigFileError as exc:
                    LOGGER.warning("手动重定位配置选择被拒绝：%s", exc)
                    raise ManualRelocalizationError(str(exc)) from exc
            request_id = self._request_id(pose['request_id']) if 'request_id' in pose else uuid.uuid4().hex
            with self._admission_lock:
                if request_id in self._operation_results:
                    raise ManualRelocalizationConflict('本次重定位请求已处理，请查询结果，不要重复提交')
                self._operation_id, self._operation_outcome = request_id, 'running'
                self._phase, self._detail = "calling_service", "正在下发重定位"
                self._remember_operation(self._operation_result(request_id, 'running'))
            self._snapshot('active')
            try:
                config = self._configuration(settings)
                self._check_current_map()
                self._check_current_runtime()
                LOGGER.info("手动重定位已核验运行实例，配置模式=%s",
                            "手选定位 YAML" if selection else "沿用定位节点当前配置")
                request = {
                    "map_path": str(selection.path) if selection else "",
                    **normalized,
                    "z": config["z"],
                    "roll": config["roll"],
                    "pitch": config["pitch"],
                }
                timeout = int(config["service_timeout_seconds"])
                LOGGER.info(
                    "手动重定位执行环境：ROS_DOMAIN_ID=%s",
                    os.environ.get("ROS_DOMAIN_ID", "未设置（ROS 默认域）"),
                )
                LOGGER.info(
                    "手动重定位提交位姿：x=%.3f y=%.3f yaw=%.3f",
                    normalized["x"],
                    normalized["y"],
                    normalized["yaw"],
                )
                # 车辆端 Relocalize 是两阶段协议：先以 true 关闭当前定位轮速
                # 里程计，再以相同配置选择与位姿、false 启动重定位。自动空路径
                # 由节点沿用当前配置；手选路径允许主动加载其他地图。第二阶段
                # 不能在第一阶段被拒绝时继续执行，车辆会保持 miniapp 停车。
                self._check_current_map()
                if selection is not None:
                    self._config_files.revalidate(selection, self._bound_map)
                self._check_hold()
                def before_preparation_send() -> None:
                    self._check_current_map()
                    self._check_current_runtime()
                    if selection is not None:
                        self._config_files.revalidate(selection, self._bound_map)
                    self._check_hold()
                response = self._invoke_service({**request, "use_wheel_odom": True}, timeout, before_send=before_preparation_send)
                self._require_service_success(response, "准备")
                LOGGER.info("手动重定位服务已确认准备阶段")
                event_cursor = None
                def before_initialization_send() -> None:
                    nonlocal event_cursor
                    self._check_current_map()
                    self._check_current_runtime()
                    if selection is not None:
                        self._config_files.revalidate(selection, self._bound_map)
                    # Exclude changes during validation and service discovery;
                    # retain fast transitions after the actual request send.
                    self._check_hold()
                    event_cursor = self._localization_event_cursor()
                def initialize() -> None:
                    response = self._invoke_service(
                        {**request, "use_wheel_odom": False}, timeout,
                        before_send=before_initialization_send,
                    )
                    self._require_service_success(response, "初始化")
                    LOGGER.info("手动重定位服务已接受初始化请求")

                if selection is None:
                    initialize()
                else:
                    # Both operations keep miniapp STOP. Each mutation is sent
                    # once; completion requires both results and a fresh map read.
                    self._expected_map_yaml = selection.map_yaml
                    self._map_reader.allow_map_change()
                    def switch() -> None:
                        def before_map_send() -> None:
                            self._check_current_map()
                            self._check_current_runtime()
                            self._config_files.revalidate(selection, self._bound_map)
                            self._check_hold()
                        if self._switch_map is None:
                            response = self._call_ros_map_service(selection.map_yaml, timeout,
                                before_send=before_map_send)
                        else:
                            before_map_send()
                            response = self._switch_map(selection.map_yaml, timeout)
                        result = getattr(response, "result", None)
                        if isinstance(result, bool) or not isinstance(result, int) or result != 0:
                            raise ManualRelocalizationUnavailable("二维地图切换未确认成功")
                        LOGGER.info("手动重定位二维地图切换服务已确认成功")
                        return response
                    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="relocalization") as executor:
                        map_future = executor.submit(copy_context().run, switch)
                        localization_future = executor.submit(copy_context().run, initialize)
                        failures = []
                        map_response = None
                        for label, future in (("二维地图切换", map_future), ("定位初始化", localization_future)):
                            try:
                                response = future.result()
                                if future is map_future: map_response = response
                            except Exception as exc:
                                LOGGER.warning("%s分支未完成：%s", label, self._public_detail(str(exc)))
                                failures.append(exc)
                        if map_response is not None:
                            self._confirm_loaded_map(selection.map_yaml, getattr(map_response, "map", None))
                        if failures:
                            raise failures[0]
                    self._check_hold()
                    self._config_files.revalidate(selection, self._bound_map)
                    self._bound_map = selection.map_yaml
                    self._expected_map_yaml = None
                    LOGGER.info("手动重定位已核验目标二维地图")
                self._wait_for_localization_confirmation(event_cursor)
                self._check_current_map()
                self._check_current_runtime()
            except (RelocalizationConfigError, LocalizationConfigFileError, ManualRelocalizationError, VehicleControlConflict, VehicleControlUnavailable) as exc:
                LOGGER.warning("手动重定位未完成：%s", exc)
                self._fail(str(exc))
                return self._snapshot("failed")
            except Exception:
                # Tool logs are operator-facing.  Keep this failure diagnosable
                # without persisting a ROS traceback or request internals.
                LOGGER.warning("手动重定位服务调用失败（受控异常）")
                self._fail("重定位服务不可用或超时")
                return self._snapshot("failed")
            try:
                self._check_hold()
                self._vehicle_control.finish_relocalization_hold(success=True)
                state = self._vehicle_control.recover_navigation_after_relocalization()
            except (ManualRelocalizationError, VehicleControlConflict, VehicleControlUnavailable) as exc:
                self._fail(str(exc))
                return self._snapshot("failed")
            self._operation_outcome = 'succeeded'
            self._phase, self._detail = "switching_to_navigation", "重定位已确认，正在恢复自动驾驶"
            return self._snapshot(str(state.get("relocalization_hold", "recovering")))

    def browse_configs(self, path: str = "") -> dict:
        try:
            return self._config_files.browse(path)
        except LocalizationConfigFileError as exc:
            raise ManualRelocalizationError(str(exc)) from exc

    @staticmethod
    def _request_id(value: object) -> str:
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', value):
            raise ManualRelocalizationError('重定位请求标识无效')
        return value

    def _operation_result(self, request_id: str, outcome: str) -> dict:
        result = dict(self._last_snapshot or {})
        result.update(operation_id=request_id, operation_outcome=outcome,
                      can_apply=False, can_begin=False, can_cancel=False, can_recover_navigation=False)
        return result

    def _remember_operation(self, result: dict) -> None:
        # Caller holds the metadata lock. No ROS, vehicle or main-lock work here.
        self._operation_results[result['operation_id']] = dict(result)
        while len(self._operation_results) > 64:
            # Metadata queries must never evict the current accepted operation:
            # an unknown-result barrier would otherwise mislabel it unadmitted.
            oldest = next(key for key in self._operation_results if key != self._operation_id)
            del self._operation_results[oldest]

    def operation_status(self, request_id: str) -> dict:
        request_id = self._request_id(request_id)
        with self._admission_lock:
            return dict(self._operation_results.get(request_id) or self._operation_result(request_id, 'unknown'))

    def resolve_operation(self, request_id: str) -> dict:
        request_id = self._request_id(request_id)
        with self._admission_lock:
            if request_id not in self._operation_results:
                # Fence an unadmitted delayed POST before allowing another
                # explicit Confirm. This never replays or cancels ROS work.
                result = self._operation_result(request_id, 'not_admitted')
                result['detail'] = '本次请求未接纳，可调整预览后再次确认'
                self._remember_operation(result)
            return dict(self._operation_results[request_id])

    @_exclusive_action
    def cancel(self) -> dict[str, object]:
        with self._lock:
            if self._phase != "calibrating":
                raise ManualRelocalizationConflict("当前不能取消手动重定位")
            return self._recover("已取消手动重定位，正在恢复自动驾驶")

    @_exclusive_action
    def recover_navigation(self) -> dict[str, object]:
        with self._lock:
            if self._phase != "failed":
                raise ManualRelocalizationConflict("当前没有待恢复的手动重定位")
            return self._recover("正在恢复自动驾驶")

    def _recover(self, detail: str) -> dict[str, object]:
        try:
            state = self._vehicle_control.recover_navigation_after_relocalization()
        except (VehicleControlConflict, VehicleControlUnavailable) as exc:
            self._fail(str(exc))
            return self._snapshot("failed")
        self._phase, self._detail = "switching_to_navigation", detail
        return self._snapshot(str(state.get("relocalization_hold", "recovering")))

    def _fail(self, detail: str) -> None:
        if self._operation_outcome == 'running':
            self._operation_outcome = 'failed'
        try:
            self._vehicle_control.finish_relocalization_hold(success=False)
        except VehicleControlConflict:
            pass
        self._phase, self._detail = "failed", self._public_detail(detail)

    @staticmethod
    def _pose(value: object) -> dict[str, float]:
        if not isinstance(value, dict):
            raise ManualRelocalizationError("重定位位姿格式无效")
        result: dict[str, float] = {}
        for key, limit in (("x", 10000.0), ("y", 10000.0), ("yaw", 8 * math.pi)):
            raw = value.get(key)
            if isinstance(raw, bool):
                raise ManualRelocalizationError("重定位位姿必须是有限数字")
            try:
                number = float(raw)
            except (TypeError, ValueError) as exc:
                raise ManualRelocalizationError("重定位位姿必须是有限数字") from exc
            if not math.isfinite(number) or abs(number) > limit:
                raise ManualRelocalizationError("重定位位姿超出允许范围")
            result[key] = number
        return result

    @staticmethod
    def _require_service_success(response: object, stage: str) -> None:
        """A ROS future without an explicit positive result is never success."""
        if response is None or getattr(response, "success", None) is not True:
            raise ManualRelocalizationUnavailable(f"重定位服务未确认{stage}请求")

    def _localization_event_cursor(self) -> int | None:
        if self._localization_status is None:
            return None
        cursor = getattr(self._localization_status, "state_cursor", None)
        if not callable(cursor):
            cursor = getattr(self._localization_status, "cursor", None)
        if not callable(cursor):
            return None
        try:
            return int(cursor())
        except (TypeError, ValueError):
            return None

    def _wait_for_localization_confirmation(self, event_cursor: int | None) -> None:
        """Keep the vehicle stopped until the accepted request has really converged."""
        if self._localization_status is None:
            raise ManualRelocalizationUnavailable("定位状态监控不可用，不能确认重定位结果")
        deadline = self._clock() + self.RESULT_CONFIRM_TIMEOUT_S
        saw_reset = False
        state_events_since = getattr(self._localization_status, "state_events_since", None)
        has_state_history = callable(state_events_since)
        next_map_check = self._clock()
        while True:
            self._check_hold()
            if self._clock() >= next_map_check:
                self._check_current_map()
                next_map_check = self._clock() + 1.0
            if event_cursor is not None:
                events_since = state_events_since if has_state_history else getattr(
                    self._localization_status, "events_since", None)
                if callable(events_since):
                    try:
                        event_cursor, events = events_since(event_cursor)
                    except (TypeError, ValueError):
                        events = []
                    for event in events:
                        reset_state = event.get("state") if isinstance(event, dict) else None
                        if reset_state in {"initializing", "relocalizing"}:
                            if not saw_reset:
                                LOGGER.info("手动重定位已观察到 /localization/status %s",
                                            "初始化中" if reset_state == "initializing" else "重定位中")
                            saw_reset = True
            snapshot = self._localization_status.status()
            phase = str(snapshot.get("phase", "unavailable")) if isinstance(snapshot, dict) else "unavailable"
            # With a state history, a pre-request snapshot is never evidence.
            if not has_state_history and phase in {"initializing", "relocalizing"}:
                if not saw_reset:
                    LOGGER.info("手动重定位已观察到 /localization/status %s",
                                "初始化中" if phase == "initializing" else "重定位中")
                saw_reset = True
            elif saw_reset and phase == "normal":
                LOGGER.info("手动重定位已由 /localization/status 确认完成")
                return
            if self._clock() >= deadline:
                break
            self._sleep(min(self.RESULT_POLL_INTERVAL_S, max(0.0, deadline - self._clock())))
        raise ManualRelocalizationUnavailable("等待定位状态确认超时")

    @staticmethod
    def _configuration(settings: object) -> dict[str, object]:
        observation = getattr(settings, "live_observation", {})
        configured = observation.get("manual_relocalization") if isinstance(observation, dict) else None
        if not isinstance(configured, dict):
            raise ManualRelocalizationError("手动重定位配置不可读取")
        try:
            z_m = float(configured["z_m"])
            timeout = int(configured["service_timeout_seconds"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ManualRelocalizationError("手动重定位配置不可读取") from exc
        if not math.isfinite(z_m) or not 0.0 <= z_m <= 2.0 or not 1 <= timeout <= 30:
            raise ManualRelocalizationError("手动重定位配置不可读取")
        return {"z": z_m, "roll": 0.0, "pitch": 0.0, "service_timeout_seconds": timeout}

    def _snapshot(self, hold: str) -> dict[str, object]:
        phase = self._phase
        result = {
            "phase": phase,
            "label": {"idle": "手动重定位", "switching_to_miniapp": "正在停车", "calibrating": "拖拽对齐", "calling_service": "重定位中", "switching_to_navigation": "恢复自动驾驶", "failed": "保持停车"}.get(phase, "手动重定位"),
            "detail": self._detail,
            "can_begin": phase in {"idle", "failed"},
            "can_apply": phase == "calibrating",
            "can_cancel": phase == "calibrating",
            "can_recover_navigation": phase == "failed",
            "vehicle_source": self._vehicle_control.status().get("actual_source", "unknown"),
            **({"target_map_id": self._target_map_id} if self._target_map_id else {}),
            **({"source_map_id": self._source_map_id} if self._source_map_id else {}),
            **({"operation_id": self._operation_id, "operation_outcome": self._operation_outcome} if self._operation_id else {}),
        }
        self._last_snapshot = result
        if self._operation_id:
            with self._admission_lock:
                self._remember_operation(result)
        return dict(result)

    @staticmethod
    def _public_detail(detail: str) -> str:
        if detail in {
            "当前地图查询响应超时", "当前地图服务未就绪", "当前地图参数无效", "当前地图无法确认",
            "当前地图路径不受支持", "当前定位进程无法唯一确认",
            "定位进程的 ROS 域无法确认，不能证明运行实例唯一", "等待定位状态确认超时",
            "手动重定位期间地图发生变化，请恢复后重新对齐",
            "手动重定位期间定位进程发生变化，请恢复后重新对齐",
            "重定位服务未确认准备请求", "重定位服务未确认初始化请求", "手动重定位停车控制权已失效",
            "二维地图切换未确认成功", "二维地图切换后当前地图未确认",
            "二维地图切换服务未就绪", "二维地图切换响应超时", "二维地图切换服务不可用",
            "当前二维地图已变化", "当前二维地图数据无效", "当前二维地图服务未就绪", "当前二维地图查询超时",
        }:
            return f"{detail}；车辆保持停车，可调整预览后再次确认或恢复自动驾驶"
        return "重定位未完成，车辆保持停车，可调整预览后再次确认"

    def _check_hold(self) -> None:
        state = self._vehicle_control.status()
        if state.get("relocalization_hold") != "active" or state.get("actual_source") != "miniapp":
            raise ManualRelocalizationUnavailable("手动重定位停车控制权已失效")

    def _check_current_map(self) -> None:
        current = self._read_current_map()
        if self._bound_map is None or (current != self._bound_map and
                current != self._expected_map_yaml):
            raise ManualRelocalizationUnavailable("手动重定位期间地图发生变化，请恢复后重新对齐")

    def _check_current_runtime(self) -> None:
        if self._bound_runtime is None or self._runtime_identity() != self._bound_runtime:
            raise ManualRelocalizationUnavailable("手动重定位期间定位进程发生变化，请恢复后重新对齐")

    def _start_current_map_watch(self) -> Path:
        try:
            return self._map_reader.start()
        except CurrentMapUnavailable as exc:
            raise ManualRelocalizationUnavailable(str(exc)) from exc

    def _confirm_loaded_map(self, target: Path, grid) -> None:
        try:
            self._map_reader.bind_loaded_map(target, grid)
            info = grid.info
            self._target_map_id, _ = MapAssetCache.occupancy_grid_identity(
                resolution=float(info.resolution), width=int(info.width), height=int(info.height),
                origin=[float(info.origin.position.x),float(info.origin.position.y)],
                frame_id=str(grid.header.frame_id).strip() or 'map', data=grid.data)
        except CurrentMapUnavailable as exc:
            raise ManualRelocalizationUnavailable(str(exc)) from exc

    def _read_current_map(self) -> Path:
        try:
            return self._map_reader.read()
        except CurrentMapUnavailable as exc:
            raise ManualRelocalizationUnavailable(str(exc)) from exc

    def close(self) -> None:
        self._map_reader.close()

    def _invoke_service(
        self, values: dict[str, Any], timeout_s: int,
        *, before_send: Callable[[], None] | None = None,
    ) -> object:
        if self._invoke is None:
            return self._call_ros_service(values, timeout_s, before_send=before_send)
        # Injected transports represent the send boundary, not ROS discovery.
        if before_send is not None:
            before_send()
        return self._invoke(values, timeout_s)

    @classmethod
    def _call_ros_service(
        cls, values: dict[str, Any], timeout_s: int,
        *, before_send: Callable[[], None] | None = None,
    ) -> object:
        try:
            from lightning.srv import Relocalize
        except Exception as exc:
            raise ManualRelocalizationUnavailable("该车未提供重定位服务接口") from exc
        return cls._call_ros_request(Relocalize, cls.SERVICE, values, timeout_s,
                                     before_send=before_send, label="重定位")

    @classmethod
    def _call_ros_map_service(cls, map_yaml: Path, timeout_s: int,
                             *, before_send: Callable[[], None] | None = None) -> object:
        try:
            from nav2_msgs.srv import LoadMap
        except Exception as exc:
            raise ManualRelocalizationUnavailable("二维地图切换服务不可用") from exc
        return cls._call_ros_request(LoadMap, "/map_server/load_map", {"map_url": str(map_yaml)},
                                     timeout_s, before_send=before_send, label="二维地图切换")

    @staticmethod
    def _call_ros_request(service_type, service_name, values, timeout_s, *, before_send, label):
        node = executor = None
        try:
            import rclpy
            from rclpy.executors import SingleThreadedExecutor
            if not rclpy.ok():
                rclpy.init()
            suffix = "map" if label == "二维地图切换" else "pose"
            node = rclpy.create_node("ry_aletheia_manual_relocalization_" + suffix)
            executor = SingleThreadedExecutor()
            executor.add_node(node)
            client = node.create_client(service_type, service_name)
            if not client.wait_for_service(timeout_sec=float(timeout_s)):
                raise ManualRelocalizationUnavailable(label + "服务未就绪")
            LOGGER.info("%s ROS 服务已就绪：ROS_DOMAIN_ID=%s", label,
                        os.environ.get("ROS_DOMAIN_ID", "未设置（ROS 默认域）"))
            request = service_type.Request()
            for key, value in values.items():
                setattr(request, key, value)
            if before_send is not None:
                before_send()
            future = client.call_async(request)
            executor.spin_until_future_complete(future, timeout_sec=float(timeout_s))
            if not future.done():
                future.cancel()
                raise ManualRelocalizationUnavailable(label + "响应超时")
            response = future.result()
            if response is None:
                raise ManualRelocalizationUnavailable(label + "服务不可用")
            return response
        except ManualRelocalizationError:
            raise
        except Exception as exc:
            raise ManualRelocalizationUnavailable(label + "服务不可用") from exc
        finally:
            try:
                if executor is not None:
                    executor.shutdown()
            finally:
                if node is not None:
                    node.destroy_node()
