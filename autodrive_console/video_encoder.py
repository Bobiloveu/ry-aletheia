"""Bounded hardware-only preflight, invoked once by an explicitly enabled runner.

No camera, ROS or ShmSDK input is opened here. Failed probes are cached for the
lifetime of that runner; HTTP status requests never instantiate this selector.
"""
from __future__ import annotations

import os
import logging
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

LOGGER = logging.getLogger('ry_aletheia.video')


class EncoderUnavailable(RuntimeError):
    pass


class EncoderProbeCancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class EncoderSelection:
    encoder: str
    device: str | None


class HardwareEncoderSelector:
    def __init__(self) -> None:
        self._cache: dict[tuple[str, str, str], EncoderSelection | str] = {}

    @staticmethod
    def _render_devices() -> list[str]:
        # Limit the startup budget even on machines exposing many adapters.
        return sorted(str(path) for path in Path('/dev/dri').glob('renderD[0-9]*'))[:2]

    def select(self, gst_launch: Path, requested: str, vaapi_device: str,
               cancelled: Callable[[], bool] | None = None) -> EncoderSelection:
        key = (str(gst_launch), requested, vaapi_device)
        cached = self._cache.get(key)
        if isinstance(cached, EncoderSelection):
            return cached
        if isinstance(cached, str):
            raise EncoderUnavailable(cached)
        errors: list[str] = []
        candidates: list[EncoderSelection] = []
        if requested in {'auto', 'vaapih264enc'}:
            devices = self._render_devices() if vaapi_device == 'auto' else [vaapi_device]
            candidates.extend(EncoderSelection('vaapih264enc', device) for device in devices)
            if not devices:
                errors.append('Intel VAAPI：没有可用的 DRM render 节点')
        if requested in {'auto', 'nvh264enc'}:
            candidates.append(EncoderSelection('nvh264enc', None))
        for candidate in candidates:
            if cancelled and cancelled():
                raise EncoderProbeCancelled('硬件编码预检已取消')
            LOGGER.info('视频硬件编码预检：encoder=%s device=%s synthetic_frames=3 timeout_s=%s', candidate.encoder, candidate.device,10 if candidate.encoder=='nvh264enc' else 4)
            error = self._probe(gst_launch, candidate.encoder, candidate.device, cancelled)
            if cancelled and cancelled():
                raise EncoderProbeCancelled('硬件编码预检已取消')
            if error is None:
                self._cache[key] = candidate
                LOGGER.info('视频硬件编码选择完成：encoder=%s device=%s', candidate.encoder, candidate.device)
                return candidate
            LOGGER.warning('视频硬件编码预检失败：encoder=%s device=%s detail=%s', candidate.encoder, candidate.device, error[-2048:])
            errors.append(f'{candidate.encoder} {candidate.device or "NVIDIA"}：{error}')
        detail = '没有可用的硬件 H.264 编码器；请核对 Intel VAAPI 或 NVIDIA NVENC 及车端驱动/权限。' + '；'.join(errors)
        self._cache[key] = detail
        raise EncoderUnavailable(detail)

    @staticmethod
    def _probe(gst_launch: Path, encoder: str, device: str | None,
               cancelled: Callable[[], bool] | None = None) -> str | None:
        command = [str(gst_launch), '-q', 'videotestsrc', 'num-buffers=3', '!',
                   'video/x-raw,width=640,height=480,framerate=15/1', '!', 'videoconvert', '!',
                   'video/x-raw,format=NV12', '!', encoder, 'bitrate=1200']
        if encoder == 'nvh264enc':
            # Properties verified against the locked GStreamer 1.20.3 source.
            command += ['preset=low-latency-hq', 'rc-mode=cbr', 'zerolatency=true', 'bframes=0', 'gop-size=15']
            command += ['!', 'video/x-h264,profile=constrained-baseline']
        else:
            command += ['keyframe-period=15']
        command += ['!', 'h264parse', '!', 'fakesink', 'sync=false']
        environment = os.environ.copy()
        if device:
            environment['GST_VAAPI_DRM_DEVICE'] = device
            environment['GST_VAAPI_DISPLAY'] = 'drm'
        # Keep driver/scanner diagnostics bounded in RAM, including failures.
        with tempfile.TemporaryFile() as diagnostic:
            try:
                process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=diagnostic,
                                           env=environment, start_new_session=True, close_fds=True)
                timeout_s = 10 if encoder == 'nvh264enc' else 4
                deadline = time.monotonic() + timeout_s
                error = None
                while True:
                    if cancelled and cancelled():
                        error = '合成帧硬件编码预检已取消'
                        break
                    try:
                        code = process.wait(timeout=min(0.1, max(0.001, deadline - time.monotonic())))
                        break
                    except subprocess.TimeoutExpired:
                        if time.monotonic() >= deadline:
                            error = f'合成帧硬件编码预检超时（{timeout_s} 秒）'
                            break
                if error:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
                    return error
            except OSError as exc:
                return str(exc)
            if code == 0:
                return None
            diagnostic.seek(0, os.SEEK_END)
            diagnostic.seek(max(0, diagnostic.tell() - 2048))
            return diagnostic.read().decode('utf-8', errors='replace').strip() or f'合成帧编码失败（exit={code}）'
