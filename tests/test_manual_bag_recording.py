from __future__ import annotations

from types import SimpleNamespace

import pytest

from autodrive_console.manual_bag_recording import ManualRecordingController, ManualRecordingError, ManualRecordingRequest


class _Timer:
    def __init__(self, _seconds, callback):
        self.callback = callback
        self.started = False
        self.cancelled = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True


class _Recordings:
    def __init__(self):
        self.started = []
        self.stopped = []

    def start_manual(self, request):
        self.started.append(request)
        return SimpleNamespace(archive_id="a" * 32, started_at="2026-10-09T12:00:00+08:00", request=request)

    def stop(self, active):
        self.stopped.append(active)
        return {"archive_id": active.archive_id, "audit": {"status": "passed"}}


def test_manual_request_accepts_only_operator_safe_duration_topics_and_label():
    request = ManualRecordingRequest.from_payload({
        "topics": ["/odom", "/task_status"], "durationMinutes": 15, "label": "窄通道避障",
    })

    assert request == ManualRecordingRequest(("/odom", "/task_status"), 15, "窄通道避障")
    with pytest.raises(ManualRecordingError, match="时长"):
        ManualRecordingRequest.from_payload({"topics": ["/odom"], "durationMinutes": 25})
    with pytest.raises(ManualRecordingError, match="字段"):
        ManualRecordingRequest.from_payload({"topics": ["/odom"], "durationMinutes": 15, "command": "bad"})


def test_manual_recording_duration_is_capped_at_twenty_minutes():
    request = ManualRecordingRequest.from_payload({"topics": ["/odom"], "durationMinutes": 20})

    assert request.duration_minutes == 20
    with pytest.raises(ManualRecordingError, match="时长"):
        ManualRecordingRequest.from_payload({"topics": ["/odom"], "durationMinutes": 30})


def test_manual_recording_survives_page_independent_status_until_operator_stops():
    recordings = _Recordings()
    timers = []
    controller = ManualRecordingController(recordings, timer_factory=lambda seconds, callback: timers.append(_Timer(seconds, callback)) or timers[-1])

    state = controller.start({"topics": ["/odom"], "durationMinutes": 20, "label": "遥控复现"})

    assert state["state"] == "recording"
    assert state["label"] == "遥控复现"
    assert state["topic_count"] == 1
    assert timers[0].started is True
    assert controller.status()["state"] == "recording"

    finished = controller.stop()

    assert finished["state"] == "idle"
    assert timers[0].cancelled is True
    assert len(recordings.stopped) == 1


def test_manual_recording_deadline_stops_exactly_once_when_operator_races_timer():
    recordings = _Recordings()
    timers = []
    controller = ManualRecordingController(recordings, timer_factory=lambda seconds, callback: timers.append(_Timer(seconds, callback)) or timers[-1])
    controller.start({"topics": ["/odom"], "durationMinutes": 5})

    timers[0].callback()

    assert controller.status()["state"] == "idle"
    assert len(recordings.stopped) == 1
    with pytest.raises(ManualRecordingError, match="没有正在录制"):
        controller.stop()


def test_manual_recording_refuses_to_overlap_an_active_test_attempt_recorder():
    recordings = _Recordings()
    controller = ManualRecordingController(recordings, test_recording_active=lambda: True)

    with pytest.raises(ManualRecordingError, match="自动化测试录包"):
        controller.start({"topics": ["/odom"], "durationMinutes": 15})

    assert recordings.started == []
