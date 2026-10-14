from pathlib import Path
from types import SimpleNamespace

import pytest
import threading

import autodrive_console.manual_relocalization as manual_relocalization_module
from autodrive_console.localization_status import LocalizationStatusMonitor
from autodrive_console.relocalization_files import LocalizationConfigFiles
from autodrive_console.manual_relocalization import (
    ManualRelocalizationConflict,
    ManualRelocalizationController,
)


_REAL_MAP_CALL = ManualRelocalizationController._call_ros_map_service

class _Vehicle:
    def __init__(self):
        self.hold = "idle"
        self.source = "navigation"

    def status(self):
        return {"relocalization_hold": self.hold, "actual_source": self.source}

    def begin_relocalization_hold(self):
        self.hold, self.source = "active", "miniapp"
        return self.status()

    def finish_relocalization_hold(self, *, success):
        self.hold = "active" if success else "failed"
        return self.status()

    def recover_navigation_after_relocalization(self):
        self.hold = "recovering"
        return self.status()


class _Scenario:
    template = Path("/opt/ry/config/localization/config/current.yaml")

    def active_lightning_config(self):
        return self.template


class _Response:
    success = True


class _LocalizationStatus:
    def __init__(self, phases):
        self._phases = iter(phases)
        self._last = {"phase": "unavailable"}

    def status(self):
        self._last = {"phase": next(self._phases, self._last["phase"])}
        return self._last


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class _EventLocalizationStatus:
    def __init__(self):
        self._cursor = 5
        self._events = [(6, {"state": "relocalizing"})]
        self._statuses = iter([{"phase": "normal"}, {"phase": "normal"}])

    def cursor(self):
        return self._cursor

    def events_since(self, cursor):
        events = [event for sequence, event in self._events if sequence > cursor]
        self._cursor = 6
        return self._cursor, events

    def status(self):
        return next(self._statuses, {"phase": "normal"})


def _settings():
    return SimpleNamespace(live_observation={"manual_relocalization": {"z_m": 0.4, "service_timeout_seconds": 12}})


def test_failed_manual_attempt_can_retry_while_stopped_in_automatic_relocalization():
    clock = _Clock()
    monitor = LocalizationStatusMonitor(clock=clock)
    monitor.observe(SimpleNamespace(state=4, error_code=0, fault_id=0))
    vehicle = _Vehicle()
    calls = []
    controller = ManualRelocalizationController(vehicle, _Scenario(),
        invoke=lambda request, timeout: calls.append(request) or _Response(),
        localization_status=monitor, clock=clock, sleep=clock.sleep)
    assert controller.begin(_settings())["can_apply"] is True
    assert controller.apply(_settings(), {"x": 1, "y": 2, "yaw": 0})["phase"] == "failed"
    assert vehicle.source == "miniapp"
    assert controller.status(_settings())["can_begin"] is True
    retry = controller.begin(_settings())
    assert retry["can_apply"] is True
    assert vehicle.source == "miniapp"
    assert len(calls) == 2  # Retry only prepares editing; it never sends a pose itself.


@pytest.mark.parametrize("initial_state", [0, 2, 3, 4])
def test_manual_initialization_can_interrupt_non_normal_localization(initial_state):
    clock = _Clock()
    monitor = LocalizationStatusMonitor(clock=clock)
    monitor.observe(SimpleNamespace(state=initial_state, error_code=0, fault_id=0))
    vehicle = _Vehicle()
    calls = []
    def invoke(request, timeout):
        calls.append(request)
        if not request["use_wheel_odom"]:
            monitor.observe(SimpleNamespace(state=0, error_code=0, fault_id=0))
            monitor.observe(SimpleNamespace(state=1, error_code=0, fault_id=0))
        return _Response()
    controller = ManualRelocalizationController(vehicle, _Scenario(), invoke=invoke,
        localization_status=monitor, clock=clock, sleep=clock.sleep)
    assert controller.begin(_settings())["can_apply"] is True
    assert controller.apply(_settings(), {"x": 3, "y": 4, "yaw": 1})["phase"] == "switching_to_navigation"
    assert [request["use_wheel_odom"] for request in calls] == [True, False]


@pytest.fixture(autouse=True)
def localization_files(tmp_path, monkeypatch):
    current = tmp_path / "maps" / "P2" / "map.yaml"
    current.parent.mkdir(parents=True)
    current.write_text("image: map.pgm\n", encoding="utf-8")
    template = tmp_path / "startup-localization.yaml"
    template.write_text(
        "# vehicle calibration\ncommon:\n  imu_topic: /livox/imu\nsystem:\n"
        f"  map_path: {current.parent} # original map\n"
        "  init_pose: {x: -6.23, y: 5.70, z: 0.4, roll: 0.0, pitch: 0.0, yaw: -1.58}\n"
        "lio:\n  extrinsic_T: [0.12, 0.03, 0.25]\n", encoding="utf-8",
    )
    monkeypatch.setattr(_Scenario, "template", template)
    monkeypatch.setattr(manual_relocalization_module.LocalizationConfigFiles, "ROOT", tmp_path)
    from autodrive_console.map_assets import MapAssetCache
    monkeypatch.setattr(MapAssetCache, "ALLOWED_ROOTS", (current.parent.parent,))
    active = [current]
    def load(map_yaml, timeout, *, before_send=None):
        if before_send: before_send()
        active[0] = map_yaml
        return SimpleNamespace(result=0)
    monkeypatch.setattr(ManualRelocalizationController, "_call_ros_map_service", staticmethod(load))
    monkeypatch.setattr(ManualRelocalizationController, "_start_current_map_watch", lambda self:self._read_current_map())
    def confirm(self, target, grid):
        if self._read_current_map() != target:
            raise manual_relocalization_module.ManualRelocalizationUnavailable('二维地图切换后当前地图未确认')
    monkeypatch.setattr(ManualRelocalizationController, "_confirm_loaded_map", confirm)
    # External ROS boundaries only; YAML and filesystem operations remain real.
    monkeypatch.setattr(ManualRelocalizationController, "_read_current_map", staticmethod(lambda: active[0]), raising=False)
    monkeypatch.setattr(manual_relocalization_module, "verify_current_config_runtime", lambda: (2813, "12345"), raising=False)
    monkeypatch.setattr(manual_relocalization_module, "localizer_runtime_identity", lambda: (2813, "12345"), raising=False)
    return template, current


def test_apply_uses_vehicle_two_stage_relocalize_protocol_without_browser_map_path():
    calls = []
    controller = ManualRelocalizationController(
        _Vehicle(),
        _Scenario(),
        invoke=lambda request, timeout: calls.append((request, timeout)) or _Response(),
        localization_status=_LocalizationStatus(["relocalizing", "normal"]),
    )

    controller.begin(_settings())
    state = controller.apply(_settings(), {"x": 1.25, "y": -2.5, "yaw": 0.75, "map_path": "/tmp/nope.yaml"})

    request = {
        "map_path": calls[0][0]["map_path"],
        "x": 1.25, "y": -2.5, "yaw": 0.75, "z": 0.4,
        "roll": 0.0, "pitch": 0.0,
    }
    assert calls == [
        ({**request, "use_wheel_odom": True}, 12),
        ({**request, "use_wheel_odom": False}, 12),
    ]
    assert request["map_path"] == ""
    assert state["phase"] == "switching_to_navigation"


def test_apply_does_not_start_second_stage_when_first_stage_is_rejected(monkeypatch):
    warnings = []
    monkeypatch.setattr(
        manual_relocalization_module.LOGGER,
        "warning",
        lambda template, *args: warnings.append(template % args),
    )
    calls = []
    controller = ManualRelocalizationController(
        _Vehicle(),
        _Scenario(),
        invoke=lambda request, timeout: calls.append((request, timeout)) or SimpleNamespace(success=False),
    )

    controller.begin(_settings())
    state = controller.apply(_settings(), {"x": 0, "y": 0, "yaw": 0})

    assert [request["use_wheel_odom"] for request, _timeout in calls] == [True]
    assert state["phase"] == "failed"
    assert warnings == ["手动重定位未完成：重定位服务未确认准备请求"]


def test_empty_prepare_response_is_a_failure_and_keeps_miniapp_stopped():
    calls = []
    vehicle = _Vehicle()
    controller = ManualRelocalizationController(
        vehicle,
        _Scenario(),
        invoke=lambda request, timeout: calls.append((request, timeout)),
    )

    controller.begin(_settings())
    state = controller.apply(_settings(), {"x": 1.25, "y": -2.5, "yaw": 0.75})

    assert calls == [
        ({
            "map_path": calls[0][0]["map_path"],
            "x": 1.25,
            "y": -2.5,
            "yaw": 0.75,
            "z": 0.4,
            "roll": 0.0,
            "pitch": 0.0,
            "use_wheel_odom": True,
        }, 12),
    ]
    assert state["phase"] == "failed"
    assert state["vehicle_source"] == "miniapp"
    assert vehicle.hold == "failed"


def test_apply_waits_for_relocalizing_then_normal_before_restoring_navigation():
    vehicle = _Vehicle()
    controller = ManualRelocalizationController(
        vehicle,
        _Scenario(),
        invoke=lambda *_: _Response(),
        localization_status=_LocalizationStatus(["normal", "relocalizing", "normal"]),
    )

    controller.begin(_settings())
    state = controller.apply(_settings(), {"x": 1.25, "y": -2.5, "yaw": 0.75})

    assert state["phase"] == "switching_to_navigation"
    assert vehicle.hold == "recovering"


def test_apply_records_domain_and_localization_confirmation_in_tool_log(monkeypatch):
    messages = []
    monkeypatch.setenv("ROS_DOMAIN_ID", "66")
    monkeypatch.setattr(
        manual_relocalization_module.LOGGER,
        "info",
        lambda template, *args: messages.append(template % args),
    )
    controller = ManualRelocalizationController(
        _Vehicle(),
        _Scenario(),
        invoke=lambda *_: _Response(),
        localization_status=_LocalizationStatus(["relocalizing", "normal"]),
    )

    controller.begin(_settings())
    controller.apply(_settings(), {"x": 1.25, "y": -2.5, "yaw": 0.75})

    assert "手动重定位执行环境：ROS_DOMAIN_ID=66" in messages
    assert "手动重定位服务已确认准备阶段" in messages
    assert "手动重定位服务已接受初始化请求" in messages
    assert "手动重定位已观察到 /localization/status 重定位中" in messages
    assert "手动重定位已由 /localization/status 确认完成" in messages
    assert not any("current.yaml" in message for message in messages)


def test_apply_accepts_a_fast_relocalizing_event_before_status_returns_normal():
    vehicle = _Vehicle()
    controller = ManualRelocalizationController(
        vehicle,
        _Scenario(),
        invoke=lambda *_: _Response(),
        localization_status=_EventLocalizationStatus(),
    )

    controller.begin(_settings())
    state = controller.apply(_settings(), {"x": 1.25, "y": -2.5, "yaw": 0.75})

    assert state["phase"] == "switching_to_navigation"
    assert vehicle.hold == "recovering"


def test_apply_without_a_confirmed_localization_cycle_keeps_miniapp_stopped():
    vehicle = _Vehicle()
    clock = _Clock()
    controller = ManualRelocalizationController(
        vehicle,
        _Scenario(),
        invoke=lambda *_: _Response(),
        localization_status=_LocalizationStatus(["normal"]),
        clock=clock,
        sleep=clock.sleep,
    )

    controller.begin(_settings())
    state = controller.apply(_settings(), {"x": 1.25, "y": -2.5, "yaw": 0.75})

    assert state["phase"] == "failed"
    assert state["vehicle_source"] == "miniapp"
    assert vehicle.hold == "failed"


def test_apply_requires_confirmed_miniapp_hold():
    vehicle = _Vehicle()
    vehicle.hold, vehicle.source = "switching", "navigation"
    controller = ManualRelocalizationController(vehicle, _Scenario(), invoke=lambda *_: _Response())
    controller._phase = "calibrating"

    with pytest.raises(ManualRelocalizationConflict, match="尚未确认停车"):
        controller.apply(_settings(), {"x": 0, "y": 0, "yaw": 0})


def test_status_uses_manual_relocalization_copy_for_operator_actions():
    controller = ManualRelocalizationController(_Vehicle(), _Scenario(), invoke=lambda *_: _Response())

    idle = controller.status(_settings())
    active = controller.begin(_settings())

    assert idle["label"] == "手动重定位"
    assert active["label"] == "拖拽对齐"
    assert "校准" not in str(idle) + str(active)


def test_service_failure_keeps_vehicle_in_failed_miniapp_hold_without_raw_exception_log(monkeypatch):
    vehicle = _Vehicle()
    warnings: list[str] = []
    monkeypatch.setattr(
        manual_relocalization_module.LOGGER,
        "warning",
        lambda message, *args: warnings.append(message % args if args else message),
    )
    controller = ManualRelocalizationController(
        vehicle,
        _Scenario(),
        invoke=lambda *_: (_ for _ in ()).throw(TimeoutError("timeout")),
    )

    controller.begin(_settings())
    state = controller.apply(_settings(), {"x": 0, "y": 0, "yaw": 0})

    assert state["phase"] == "failed"
    assert state["vehicle_source"] == "miniapp"
    assert vehicle.hold == "failed"
    assert warnings == ["手动重定位服务调用失败（受控异常）"]


def test_relocalization_reuses_current_config_without_creating_any_files(localization_files):
    template, current = localization_files
    before = template.read_bytes()
    files_before = set(template.parent.rglob("*"))
    calls = []

    def invoke(request, timeout):
        calls.append(request)
        assert request["map_path"] == ""
        assert template.read_bytes() == before
        return _Response()

    controller = ManualRelocalizationController(
        _Vehicle(), _Scenario(), invoke=invoke,
        localization_status=_LocalizationStatus(["relocalizing", "normal"]),
    )
    controller.begin(_settings())
    result = controller.apply(_settings(), {"x": -2, "y": -95, "yaw": -2.73})

    assert result["phase"] == "switching_to_navigation"
    assert len(calls) == 2
    assert calls[0]["map_path"] == calls[1]["map_path"]
    assert calls[0]["x"] == -2 and calls[0]["yaw"] == -2.73
    assert template.read_bytes() == before
    assert set(template.parent.rglob("*")) == files_before


@pytest.mark.parametrize("stage", ["editing", "prepared", "confirming"])
def test_map_switch_keeps_vehicle_stopped_and_never_uses_the_wrong_map(localization_files, monkeypatch, stage):
    _template, current = localization_files
    other = current.parent.parent / "P1" / "map.yaml"
    other.parent.mkdir()
    other.write_text("image: map.pgm\n")
    active = [current]
    calls = []
    vehicle = _Vehicle()
    monkeypatch.setattr(ManualRelocalizationController, "_read_current_map", staticmethod(lambda: active[0]))

    def invoke(request, timeout):
        calls.append(request)
        if stage == "prepared" or (stage == "confirming" and len(calls) == 2):
            active[0] = other
        return _Response()

    controller = ManualRelocalizationController(
        vehicle, _Scenario(), invoke=invoke,
        localization_status=_LocalizationStatus(["relocalizing", "normal"]),
    )
    controller.begin(_settings())
    if stage == "editing":
        active[0] = other
    result = controller.apply(_settings(), {"x": 0, "y": 0, "yaw": 0})
    assert result["phase"] == "failed"
    assert vehicle.hold == "failed" and vehicle.source == "miniapp"
    assert len(calls) == {"editing": 0, "prepared": 1, "confirming": 2}[stage]


@pytest.mark.parametrize("contents", [
    "system: {}\n", "system: {map_path: /old, map_path: /other}\n",
    "system: {map_path: /old}\nsystem: {map_path: /other}\n",
    "system: {map_path: [wrong]}\n", "system: [wrong]\n", "[wrong]\n",
])
def test_current_config_reuse_does_not_read_or_change_startup_yaml(localization_files, contents):
    template, _current = localization_files
    template.write_text(contents)
    calls = []
    vehicle = _Vehicle()
    controller = ManualRelocalizationController(vehicle, _Scenario(),
        invoke=lambda *args: calls.append(args) or _Response(),
        localization_status=_LocalizationStatus(["relocalizing", "normal"]))
    controller.begin(_settings())
    result = controller.apply(_settings(), {"x": 0, "y": 0, "yaw": 0})
    assert result["phase"] == "switching_to_navigation"
    assert len(calls) == 2
    assert template.read_text() == contents


def test_relocalization_does_not_need_any_config_write(localization_files, monkeypatch):
    template, _current = localization_files
    before = template.read_bytes()
    calls = []
    vehicle = _Vehicle()

    def fail_publish(*args):
        raise AssertionError("relocalization must not write configuration")

    monkeypatch.setattr(manual_relocalization_module.os, "replace", fail_publish)
    controller = ManualRelocalizationController(vehicle, _Scenario(),
        invoke=lambda *args: calls.append(args) or _Response(),
        localization_status=_LocalizationStatus(["relocalizing", "normal"]))
    controller.begin(_settings())
    result = controller.apply(_settings(), {"x": 0, "y": 0, "yaw": 0})
    assert result["phase"] == "switching_to_navigation"
    assert len(calls) == 2
    assert template.read_bytes() == before


def test_current_map_query_failure_does_not_fall_back_to_startup_map(localization_files, monkeypatch):
    calls = []
    vehicle = _Vehicle()
    controller = ManualRelocalizationController(vehicle, _Scenario(), invoke=lambda *args: calls.append(args))
    controller.begin(_settings())

    def unavailable():
        raise TimeoutError("private map path must not leak")

    monkeypatch.setattr(ManualRelocalizationController, "_read_current_map", staticmethod(unavailable))
    result = controller.apply(_settings(), {"x": 0, "y": 0, "yaw": 0})
    assert result["phase"] == "failed"
    assert calls == []
    assert vehicle.hold == "failed"
    assert "private" not in str(result)


def test_map_change_at_normal_confirmation_does_not_restore_navigation(localization_files, monkeypatch):
    _template, current = localization_files
    active = [current]
    vehicle = _Vehicle()
    calls = []
    monkeypatch.setattr(ManualRelocalizationController, "_read_current_map", staticmethod(lambda: active[0]))

    class Status:
        phases = iter(["relocalizing", "normal"])

        def status(self):
            phase = next(self.phases)
            if phase == "normal":
                active[0] = current.parent.parent / "P1" / "map.yaml"
            return {"phase": phase}

    controller = ManualRelocalizationController(vehicle, _Scenario(),
        invoke=lambda request, timeout: calls.append(request) or _Response(), localization_status=Status())
    controller.begin(_settings())
    assert controller.apply(_settings(), {"x": 0, "y": 0, "yaw": 0})["phase"] == "failed"
    assert len(calls) == 2
    assert vehicle.hold == "failed"


def test_current_config_reuse_ignores_a_startup_yaml_for_another_map(localization_files):
    template, current = localization_files
    text = template.read_text().replace(str(current.parent), "/opt/ry/data/maps/old")
    template.write_text(text)
    calls = []
    vehicle = _Vehicle()
    controller = ManualRelocalizationController(vehicle, _Scenario(),
        invoke=lambda *args: calls.append(args) or _Response(),
        localization_status=_LocalizationStatus(["relocalizing", "normal"]))
    controller.begin(_settings())
    assert controller.apply(_settings(), {"x": 0, "y": 0, "yaw": 0})["phase"] == "switching_to_navigation"
    assert len(calls) == 2
    assert all(request["map_path"] == "" for request, timeout in calls)
    assert template.read_text() == text


def test_unknown_current_config_protocol_keeps_vehicle_stopped(monkeypatch):
    from autodrive_console.relocalization_config import RelocalizationConfigError
    def unsupported():
        raise RelocalizationConfigError('当前定位版本尚未核验沿用配置能力')
    monkeypatch.setattr(manual_relocalization_module, 'verify_current_config_runtime', unsupported)
    vehicle = _Vehicle()
    calls = []
    controller = ManualRelocalizationController(vehicle, _Scenario(), invoke=lambda *args: calls.append(args))
    assert controller.begin(_settings())['can_apply'] is True
    assert vehicle.hold == 'active'
    assert calls == []
    result = controller.apply(_settings(), {'x': 1, 'y': 2, 'yaw': 0})
    assert result['phase'] == 'failed'
    assert '手动选择定位 YAML' in result['detail']
    assert vehicle.hold == 'failed'
    assert calls == []


def test_explicit_yaml_remains_usable_when_empty_path_capability_is_unknown(localization_files, monkeypatch):
    from autodrive_console.relocalization_config import RelocalizationConfigError
    def unsupported():
        raise RelocalizationConfigError('当前定位版本尚未核验沿用配置能力')
    monkeypatch.setattr(manual_relocalization_module, 'verify_current_config_runtime', unsupported)
    template, _ = localization_files
    calls = []
    controller = ManualRelocalizationController(_Vehicle(), _Scenario(),
        invoke=lambda request, timeout: calls.append(request) or _Response(),
        localization_status=_LocalizationStatus(['initializing', 'normal']))
    assert controller.begin(_settings())['can_apply'] is True
    result = controller.apply(_settings(), {'x': 1, 'y': 2, 'yaw': 0, 'config_path': str(template)})
    assert result['phase'] == 'switching_to_navigation'
    assert len(calls) == 2
    assert all(request['map_path'] == str(template) for request in calls)


def test_explicit_yaml_still_refuses_a_localizer_restart(localization_files, monkeypatch):
    identity = [(2813, '12345')]
    monkeypatch.setattr(manual_relocalization_module, 'localizer_runtime_identity', lambda: identity[0])
    calls = []
    vehicle = _Vehicle()
    controller = ManualRelocalizationController(vehicle, _Scenario(), invoke=lambda *args: calls.append(args))
    assert controller.begin(_settings())['can_apply'] is True
    identity[0] = (3000, '13000')
    assert controller.apply(_settings(), {'x': 1, 'y': 2, 'yaw': 0,
        'config_path': str(localization_files[0])})['phase'] == 'failed'
    assert calls == []
    assert vehicle.hold == 'failed'


@pytest.mark.parametrize('source', ['b'*16, '', 123, '../map', 'A'*16])
def test_preview_source_map_must_match_actual_begin_map_before_any_ros_call(source):
    calls=[]
    controller=ManualRelocalizationController(_Vehicle(), _Scenario(), invoke=lambda *args:calls.append(args))
    controller._map_reader._source_map_id='a'*16
    controller.begin(_settings())
    with pytest.raises(manual_relocalization_module.ManualRelocalizationError):
        controller.apply(_settings(), {'x':1,'y':2,'yaw':0,'source_map_id':source})
    assert calls==[]


def test_matching_preview_source_map_can_apply():
    calls=[]
    controller=ManualRelocalizationController(_Vehicle(),_Scenario(),
        invoke=lambda request,timeout:calls.append(request) or _Response(),
        localization_status=_LocalizationStatus(['initializing','normal']))
    controller._map_reader._source_map_id='a'*16
    controller.begin(_settings())
    assert controller.apply(_settings(),{'x':1,'y':2,'yaw':0,'source_map_id':'a'*16})['phase']=='switching_to_navigation'
    assert len(calls)==2
    assert all('source_map_id' not in call for call in calls)


def test_request_identity_records_outcome_and_prevents_late_duplicate_mutation():
    calls=[];vehicle=_Vehicle()
    controller=ManualRelocalizationController(vehicle,_Scenario(),
        invoke=lambda request,timeout:calls.append(request) or _Response(),
        localization_status=_LocalizationStatus(['initializing','normal']))
    controller.begin(_settings())
    payload={'x':1,'y':2,'yaw':0,'request_id':'manual-test-1'}
    result=controller.apply(_settings(),payload)
    assert result['operation_id']=='manual-test-1' and result['operation_outcome']=='succeeded'
    assert all('request_id' not in call for call in calls)
    vehicle.hold='idle';controller.status(_settings());controller.begin(_settings())
    with pytest.raises(ManualRelocalizationConflict):controller.apply(_settings(),payload)
    assert len(calls)==2


def test_failed_outcome_is_not_changed_to_success_by_explicit_navigation_recovery():
    vehicle=_Vehicle();controller=ManualRelocalizationController(vehicle,_Scenario(),
        invoke=lambda *args:SimpleNamespace(success=False))
    controller.begin(_settings())
    result=controller.apply(_settings(),{'x':1,'y':2,'yaw':0,'request_id':'manual-failed'})
    assert result['operation_outcome']=='failed'
    controller.recover_navigation();vehicle.hold='idle'
    result=controller.status(_settings())
    assert result['phase']=='idle' and result['operation_outcome']=='failed'


def test_resolve_unadmitted_request_fences_its_late_delivery_without_ros():
    calls=[]
    controller=ManualRelocalizationController(_Vehicle(),_Scenario(),invoke=lambda *args:calls.append(args))
    controller.begin(_settings())
    assert controller.operation_status('lost-request')['operation_outcome']=='unknown'
    assert controller.resolve_operation('lost-request')['operation_outcome']=='not_admitted'
    with pytest.raises(ManualRelocalizationConflict):
        controller.apply(_settings(),{'x':1,'y':2,'yaw':0,'request_id':'lost-request'})
    assert calls==[]


def test_previous_request_outcome_survives_another_attempt():
    vehicle=_Vehicle()
    controller=ManualRelocalizationController(vehicle,_Scenario(),
        invoke=lambda *args:SimpleNamespace(success=False))
    controller.begin(_settings())
    first=controller.apply(_settings(),{'x':1,'y':2,'yaw':0,'request_id':'first'})
    controller.begin(_settings())
    controller.apply(_settings(),{'x':3,'y':4,'yaw':0,'request_id':'second'})
    assert controller.operation_status('first')==first
    assert controller.resolve_operation('first')==first


def test_outcome_resolution_does_not_block_on_another_ros_request():
    from concurrent.futures import ThreadPoolExecutor
    started=threading.Event(); release=threading.Event()
    def invoke(*args):started.set();release.wait(2);return _Response()
    controller=ManualRelocalizationController(_Vehicle(),_Scenario(),invoke=invoke,
        localization_status=_LocalizationStatus(['initializing','normal']))
    controller.begin(_settings())
    with ThreadPoolExecutor(max_workers=2) as executor:
        first=executor.submit(controller.apply,_settings(),{'x':1,'y':2,'yaw':0,'request_id':'running'})
        assert started.wait(1)
        try:
            assert executor.submit(controller.resolve_operation,'running').result(timeout=.3)['operation_outcome']=='running'
            assert executor.submit(controller.resolve_operation,'missing').result(timeout=.3)['operation_outcome']=='not_admitted'
            for i in range(70):controller.resolve_operation(f'other-missing-{i}')
            assert controller.operation_status('running')['operation_outcome']=='running'
            assert controller.resolve_operation('running')['operation_outcome']=='running'
            assert len(controller._operation_results)==64
        finally:release.set()
        first.result(timeout=2)


def test_operation_history_is_bounded_and_rejects_invalid_identifiers():
    controller=ManualRelocalizationController(_Vehicle(),_Scenario())
    for i in range(70):controller.resolve_operation(f'missing-{i}')
    assert len(controller._operation_results)==64
    assert controller.operation_status('missing-0')['operation_outcome']=='unknown'
    assert controller.operation_status('missing-69')['operation_outcome']=='not_admitted'
    for invalid in ('',None,'bad/id','x'*65):
        with pytest.raises(manual_relocalization_module.ManualRelocalizationError):
            controller.resolve_operation(invalid)


@pytest.mark.parametrize('change',['map','process'])
def test_first_prepare_rechecks_evidence_after_service_discovery(change,monkeypatch,localization_files):
    calls=[]; identity=[(2813,'12345')]
    monkeypatch.setattr(manual_relocalization_module,'localizer_runtime_identity',lambda:identity[0])
    controller=ManualRelocalizationController(_Vehicle(),_Scenario(),invoke=lambda *args:calls.append(args) or _Response())
    controller.begin(_settings())
    original=controller._invoke_service
    def discover(request,timeout,*,before_send=None):
        if change=='process':identity[0]=(3000,'13000')
        else:monkeypatch.setattr(controller,'_read_current_map',lambda:Path('/different/map.yaml'))
        return original(request,timeout,before_send=before_send)
    monkeypatch.setattr(controller,'_invoke_service',discover)
    assert controller.apply(_settings(),{'x':1,'y':2,'yaw':0})['phase']=='failed'
    assert calls==[]


@pytest.mark.parametrize('action',['begin','apply','status'])
def test_inflight_action_never_blocks_another_action_or_status_reader(action):
    from concurrent.futures import ThreadPoolExecutor, TimeoutError
    started=threading.Event(); release=threading.Event()
    def invoke(*args):started.set();release.wait(2);return _Response()
    controller=ManualRelocalizationController(_Vehicle(),_Scenario(),invoke=invoke,
        localization_status=_LocalizationStatus(['initializing','normal']))
    controller.begin(_settings())
    with ThreadPoolExecutor(max_workers=2) as executor:
        first=executor.submit(controller.apply,_settings(),{'x':1,'y':2,'yaw':0})
        assert started.wait(1)
        try:
            if action=='status':
                response=executor.submit(controller.status,_settings()).result(timeout=.3)
                assert response['phase']=='calling_service'
            else:
                second=executor.submit(controller.begin,_settings()) if action=='begin' else executor.submit(controller.apply,_settings(),{'x':3,'y':4,'yaw':0})
                with pytest.raises(ManualRelocalizationConflict):second.result(timeout=.3)
        finally:release.set()
        first.result(timeout=2)


def test_restarted_localizer_cannot_accept_a_preview_from_before_restart(monkeypatch):
    identity = [(2813, '12345')]
    monkeypatch.setattr(manual_relocalization_module, 'verify_current_config_runtime', lambda: identity[0])
    vehicle = _Vehicle()
    calls = []
    controller = ManualRelocalizationController(vehicle, _Scenario(), invoke=lambda *args: calls.append(args))
    controller.begin(_settings())
    identity[0] = (3000, '13000')
    assert controller.apply(_settings(), {'x': 0, 'y': 0, 'yaw': 0})['phase'] == 'failed'
    assert calls == []
    assert vehicle.hold == 'failed'


@pytest.mark.parametrize('reset_state', [0, 4])
def test_fast_manual_reset_without_fault_id_is_confirmed_even_after_many_normal_frames(reset_state):
    clock = _Clock()
    monitor = LocalizationStatusMonitor(clock=clock, max_events=4)
    monitor.observe(SimpleNamespace(state=1, error_code=0, fault_id=0))
    vehicle = _Vehicle()
    def invoke(request, timeout):
        if not request['use_wheel_odom']:
            monitor.observe(SimpleNamespace(state=reset_state, error_code=0, fault_id=0))
            monitor.observe(SimpleNamespace(state=1, error_code=0, fault_id=0))
            for _ in range(20):
                monitor.observe(SimpleNamespace(state=1, error_code=0, fault_id=0))
        return _Response()
    controller = ManualRelocalizationController(vehicle, _Scenario(), invoke=invoke,
        localization_status=monitor, clock=clock, sleep=clock.sleep)
    controller.begin(_settings())
    result = controller.apply(_settings(), {'x': 0, 'y': 0, 'yaw': 0})
    assert result['phase'] == 'switching_to_navigation'
    assert vehicle.hold == 'recovering'
    assert monitor.events_since(0) == (0, [])


def test_initializing_before_request_and_only_normal_after_request_cannot_confirm_completion():
    clock = _Clock()
    monitor = LocalizationStatusMonitor(clock=clock)
    monitor.observe(SimpleNamespace(state=0, error_code=0, fault_id=0))
    monitor.observe(SimpleNamespace(state=1, error_code=0, fault_id=0))
    vehicle = _Vehicle()
    def invoke(request, timeout):
        monitor.observe(SimpleNamespace(state=1, error_code=0, fault_id=0))
        return _Response()
    controller = ManualRelocalizationController(vehicle, _Scenario(), invoke=invoke,
        localization_status=monitor, clock=clock, sleep=clock.sleep)
    controller.begin(_settings())
    assert controller.apply(_settings(), {'x': 0, 'y': 0, 'yaw': 0})['phase'] == 'failed'
    assert vehicle.hold == 'failed'


@pytest.mark.parametrize('fresh_reset', [False, True])
def test_initializing_snapshot_from_before_request_needs_a_new_reset_sample(fresh_reset):
    clock = _Clock()
    monitor = LocalizationStatusMonitor(clock=clock)
    monitor.observe(SimpleNamespace(state=0, error_code=0, fault_id=0))
    vehicle = _Vehicle()
    def invoke(request, timeout):
        if not request['use_wheel_odom'] and fresh_reset:
            monitor.observe(SimpleNamespace(state=0, error_code=0, fault_id=0))
        return _Response()
    def sleep(seconds):
        clock.sleep(seconds)
        monitor.observe(SimpleNamespace(state=1, error_code=0, fault_id=0))
    controller = ManualRelocalizationController(vehicle, _Scenario(), invoke=invoke,
        localization_status=monitor, clock=clock, sleep=sleep)
    controller.begin(_settings())
    result = controller.apply(_settings(), {'x': 0, 'y': 0, 'yaw': 0})
    assert result['phase'] == ('switching_to_navigation' if fresh_reset else 'failed')
    assert vehicle.hold == ('recovering' if fresh_reset else 'failed')


def test_reset_during_runtime_check_before_send_cannot_confirm_request(monkeypatch):
    clock = _Clock()
    monitor = LocalizationStatusMonitor(clock=clock)
    monitor.observe(SimpleNamespace(state=1, error_code=0, fault_id=0))
    checks = []
    def verify():
        checks.append(True)
        if len(checks) == 2:
            monitor.observe(SimpleNamespace(state=0, error_code=0, fault_id=0))
            monitor.observe(SimpleNamespace(state=1, error_code=0, fault_id=0))
        return (2813, '12345')
    monkeypatch.setattr(manual_relocalization_module, 'verify_current_config_runtime', verify)
    vehicle = _Vehicle()
    controller = ManualRelocalizationController(vehicle, _Scenario(), invoke=lambda *args: _Response(),
        localization_status=monitor, clock=clock, sleep=clock.sleep)
    controller.begin(_settings())
    assert controller.apply(_settings(), {'x': 0, 'y': 0, 'yaw': 0})['phase'] == 'failed'
    assert vehicle.hold == 'failed'


@pytest.mark.parametrize('reset_after_send', [False, True])
def test_service_discovery_state_is_excluded_from_request_confirmation(monkeypatch, reset_after_send):
    import sys
    clock = _Clock()
    monitor = LocalizationStatusMonitor(clock=clock)
    monitor.observe(SimpleNamespace(state=1, error_code=0, fault_id=0))
    calls = []
    destroyed = []
    def reset():
        monitor.observe(SimpleNamespace(state=0, error_code=0, fault_id=0))
        monitor.observe(SimpleNamespace(state=1, error_code=0, fault_id=0))
    class Client:
        def wait_for_service(self, **kwargs):
            reset()  # An old initialization completes during service discovery.
            return True
        def call_async(self, request):
            calls.append(request.use_wheel_odom)
            if not request.use_wheel_odom and reset_after_send:
                reset()
            return SimpleNamespace(done=lambda: True, result=lambda: _Response())
    class Node:
        def create_client(self, *args):
            return Client()
        def destroy_node(self):
            destroyed.append(True)
    monkeypatch.setitem(sys.modules, 'rclpy', SimpleNamespace(
        ok=lambda: True, create_node=lambda *args: Node(),
        spin_until_future_complete=lambda *args, **kwargs: None))
    class Executor:
        def add_node(self, node): pass
        def spin_until_future_complete(self, *args, **kwargs): pass
        def shutdown(self): pass
    monkeypatch.setitem(sys.modules, 'rclpy.executors', SimpleNamespace(SingleThreadedExecutor=Executor))
    monkeypatch.setitem(sys.modules, 'lightning.srv', SimpleNamespace(
        Relocalize=SimpleNamespace(Request=SimpleNamespace)))
    vehicle = _Vehicle()
    controller = ManualRelocalizationController(vehicle, _Scenario(),
        localization_status=monitor, clock=clock, sleep=clock.sleep)
    controller.begin(_settings())
    result = controller.apply(_settings(), {'x': 0, 'y': 0, 'yaw': 0})
    assert calls == [True, False]
    assert len(destroyed) == 2
    assert result['phase'] == ('switching_to_navigation' if reset_after_send else 'failed')
    assert vehicle.hold == ('recovering' if reset_after_send else 'failed')


def test_completed_reset_with_expired_normal_feedback_still_keeps_vehicle_stopped():
    clock = _Clock()
    monitor = LocalizationStatusMonitor(clock=clock)
    vehicle = _Vehicle()
    def invoke(request, timeout):
        if not request['use_wheel_odom']:
            monitor.observe(SimpleNamespace(state=0, error_code=0, fault_id=0))
            monitor.observe(SimpleNamespace(state=1, error_code=0, fault_id=0))
            clock.sleep(5)  # Feedback stops while the accepted service returns.
        return _Response()
    controller = ManualRelocalizationController(vehicle, _Scenario(), invoke=invoke,
        localization_status=monitor, clock=clock, sleep=clock.sleep)
    controller.begin(_settings())
    assert controller.apply(_settings(), {'x': 0, 'y': 0, 'yaw': 0})['phase'] == 'failed'
    assert vehicle.hold == 'failed'


def test_manual_yaml_is_passed_to_both_stages_without_persisting_selection(localization_files):
    template, current = localization_files
    before = template.read_bytes()
    vehicle = _Vehicle()
    calls = []
    controller = ManualRelocalizationController(vehicle, _Scenario(),
        invoke=lambda request, timeout: calls.append(request) or _Response(),
        config_files=LocalizationConfigFiles(template.parent),
        localization_status=_LocalizationStatus(['relocalizing', 'normal'] * 2))
    controller.begin(_settings())
    assert controller.apply(_settings(), {'x': 1, 'y': 2, 'yaw': .7, 'config_path': str(template)})['phase'] == 'switching_to_navigation'
    assert [request['map_path'] for request in calls] == [str(template), str(template)]
    assert all(request['yaw'] == .7 for request in calls)
    assert template.read_bytes() == before
    vehicle.hold, vehicle.source = 'idle', 'navigation'
    controller.status(_settings())
    controller.begin(_settings())
    controller.apply(_settings(), {'x': 1, 'y': 2, 'yaw': .7})
    assert [request['map_path'] for request in calls[2:]] == ['', '']


def test_manual_yaml_allows_requested_map_change_after_initialization(localization_files, monkeypatch):
    template, current = localization_files
    target = current.parent.parent / 'P1' / 'map.yaml'
    target.parent.mkdir()
    target.write_text('image: map.pgm\n')
    template.write_text(f'system: {{map_path: {target.parent}}}')
    active = [current]
    monkeypatch.setattr(ManualRelocalizationController, '_read_current_map', staticmethod(lambda: active[0]))
    calls = []
    def invoke(request, timeout):
        calls.append(request)
        if not request['use_wheel_odom']: active[0] = target
        return _Response()
    vehicle = _Vehicle()
    controller = ManualRelocalizationController(vehicle, _Scenario(), invoke=invoke,
        config_files=LocalizationConfigFiles(template.parent),
        localization_status=_LocalizationStatus(['initializing', 'normal']))
    controller.begin(_settings())
    state = controller.apply(_settings(), {'x': 0, 'y': 0, 'yaw': 0, 'config_path': str(template)})
    assert state['phase'] == 'switching_to_navigation'
    assert [request['map_path'] for request in calls] == [str(template), str(template)]


def test_yaml_changed_after_prepare_is_not_loaded(localization_files):
    template, current = localization_files
    vehicle = _Vehicle()
    calls = []
    def invoke(request, timeout):
        calls.append(request)
        template.write_text(template.read_text() + '\nchanged: true\n')
        return _Response()
    controller = ManualRelocalizationController(vehicle, _Scenario(), invoke=invoke,
        config_files=LocalizationConfigFiles(template.parent))
    controller.begin(_settings())
    assert controller.apply(_settings(), {'x': 0, 'y': 0, 'yaw': 0, 'config_path': str(template)})['phase'] == 'failed'
    assert len(calls) == 1 and calls[0]['use_wheel_odom'] is True
    assert vehicle.hold == 'failed'


def test_loss_of_calibration_hold_disables_editing_and_reports_actual_source():
    vehicle = _Vehicle()
    controller = ManualRelocalizationController(vehicle, _Scenario())
    controller.begin(_settings())
    vehicle.hold, vehicle.source = 'failed', 'navigation'
    state = controller.status(_settings())
    assert state['phase'] == 'failed'
    assert state['can_apply'] is False and state['can_cancel'] is False
    assert state['can_recover_navigation'] is True
    assert state['vehicle_source'] == 'navigation'


def test_map_query_failure_has_a_controlled_actionable_reason(monkeypatch):
    def fail():
        raise manual_relocalization_module.ManualRelocalizationUnavailable('当前地图查询响应超时')
    monkeypatch.setattr(ManualRelocalizationController, '_read_current_map', staticmethod(fail))
    state = ManualRelocalizationController(_Vehicle(), _Scenario()).begin(_settings())
    assert state['phase'] == 'failed'
    assert '地图' in state['detail'] and '超时' in state['detail']
    assert '/opt/' not in state['detail']


@pytest.mark.parametrize('stage', ['prepare', 'initialize', 'confirmation'])
def test_lost_hold_cannot_initialize_or_restore_navigation(stage):
    vehicle = _Vehicle()
    calls = []
    def invoke(request, timeout):
        calls.append(request)
        if stage == 'prepare' or stage == 'confirmation' and not request['use_wheel_odom']:
            vehicle.hold, vehicle.source = 'failed', 'navigation'
        return _Response()
    controller = ManualRelocalizationController(vehicle, _Scenario(), invoke=invoke,
        localization_status=_LocalizationStatus(['initializing', 'normal']))
    controller.begin(_settings())
    if stage == 'initialize':
        original = controller._check_current_runtime
        count = [0]
        def check():
            original()
            count[0] += 1
            if count[0] == 3: vehicle.hold, vehicle.source = 'failed', 'navigation'
        controller._check_current_runtime = check
    state = controller.apply(_settings(), {'x': 0, 'y': 0, 'yaw': 0})
    assert state['phase'] == 'failed'
    assert vehicle.hold == 'failed'
    if stage != 'confirmation': assert len(calls) == 1


def test_manual_map_load_and_initialization_run_concurrently_and_confirm_target(localization_files, monkeypatch):
    template, current = localization_files
    target = current.parent.parent / 'P1' / 'map.yaml'
    target.parent.mkdir(); target.write_text('image: map.pgm\n')
    template.write_text(f'system: {{map_path: {target.parent}}}')
    active = [current]
    monkeypatch.setattr(ManualRelocalizationController, '_read_current_map', staticmethod(lambda: active[0]))
    rendezvous = threading.Barrier(2)
    events = []
    def switch(path, timeout):
        assert path == target
        events.append('switch')
        rendezvous.wait(timeout=2)
        active[0] = target
        return SimpleNamespace(result=0)
    def invoke(request, timeout):
        if request['use_wheel_odom']: events.append('prepare')
        else:
            events.append('initialize')
            rendezvous.wait(timeout=2)
        return _Response()
    controller = ManualRelocalizationController(_Vehicle(), _Scenario(), invoke=invoke,
        switch_map=switch, config_files=LocalizationConfigFiles(template.parent),
        localization_status=_LocalizationStatus(['initializing', 'normal']))
    controller.begin(_settings())
    result = controller.apply(_settings(), {'x': 1, 'y': 2, 'yaw': 0, 'config_path': str(template)})
    assert result['phase'] == 'switching_to_navigation'
    assert events[0] == 'prepare' and set(events[1:]) == {'switch', 'initialize'}
    assert controller._bound_map == target


@pytest.mark.parametrize('failure', ['map_rejected', 'map_timeout', 'old_map', 'localization_rejected'])
def test_manual_map_switch_failure_never_recovers_navigation(localization_files, monkeypatch, failure):
    template, current = localization_files
    target = current.parent.parent / 'P1' / 'map.yaml'
    target.parent.mkdir(); target.write_text('image: map.pgm\n')
    template.write_text(f'system: {{map_path: {target.parent}}}')
    active = [current]
    monkeypatch.setattr(ManualRelocalizationController, '_read_current_map', staticmethod(lambda: active[0]))
    calls = []
    def switch(path, timeout):
        calls.append('switch')
        if failure == 'map_timeout': raise manual_relocalization_module.ManualRelocalizationUnavailable('二维地图切换响应超时')
        if failure != 'old_map': active[0] = target
        return SimpleNamespace(result=1 if failure == 'map_rejected' else 0)
    def invoke(request, timeout):
        return SimpleNamespace(success=not (failure == 'localization_rejected' and not request['use_wheel_odom']))
    vehicle = _Vehicle()
    controller = ManualRelocalizationController(vehicle, _Scenario(), invoke=invoke,
        switch_map=switch, config_files=LocalizationConfigFiles(template.parent),
        localization_status=_LocalizationStatus(['initializing', 'normal']))
    controller.begin(_settings())
    result = controller.apply(_settings(), {'x': 1, 'y': 2, 'yaw': 0, 'config_path': str(template)})
    assert result['phase'] == 'failed' and vehicle.hold == 'failed'
    assert calls == ['switch']

@pytest.mark.parametrize('failure', [None, 'not_ready', 'timeout', 'empty', 'guard'])
def test_map_load_ros_boundary_is_bounded_single_send_and_uses_own_executor(monkeypatch, failure):
    import sys
    events = []
    cancelled = []
    class Client:
        def wait_for_service(self, *, timeout_sec):
            assert timeout_sec == 12
            events.append('discover')
            return failure != 'not_ready'
        def call_async(self, request):
            assert request.map_url == '/opt/ry/data/maps/gk1/P1/map.yaml'
            events.append('send')
            return SimpleNamespace(done=lambda: failure != 'timeout',
                result=lambda: None if failure == 'empty' else SimpleNamespace(result=0),
                cancel=lambda: cancelled.append(True))
    class Node:
        def create_client(self, kind, name):
            assert name == '/map_server/load_map'
            return Client()
        def destroy_node(self): events.append('destroy')
    class Executor:
        def add_node(self, node): events.append('own_executor')
        def spin_until_future_complete(self, future, *, timeout_sec): assert timeout_sec == 12
        def shutdown(self): events.append('shutdown')
    def guard():
        events.append('guard')
        if failure == 'guard':raise manual_relocalization_module.ManualRelocalizationUnavailable('手动重定位停车控制权已失效')
    monkeypatch.setitem(sys.modules, 'rclpy', SimpleNamespace(ok=lambda:True,create_node=lambda name:Node()))
    monkeypatch.setitem(sys.modules, 'rclpy.executors', SimpleNamespace(SingleThreadedExecutor=Executor))
    monkeypatch.setitem(sys.modules, 'nav2_msgs.srv', SimpleNamespace(LoadMap=SimpleNamespace(Request=SimpleNamespace)))
    if failure:
        with pytest.raises(manual_relocalization_module.ManualRelocalizationUnavailable):
            _REAL_MAP_CALL(Path('/opt/ry/data/maps/gk1/P1/map.yaml'),12,before_send=guard)
    else:
        assert _REAL_MAP_CALL(Path('/opt/ry/data/maps/gk1/P1/map.yaml'),12,before_send=guard).result == 0
    assert events[-2:] == ['shutdown','destroy']
    assert events.count('send') == (0 if failure in ['not_ready','guard'] else 1)
    if 'send' in events:assert events.index('guard')<events.index('send')
    assert bool(cancelled) == (failure == 'timeout')
