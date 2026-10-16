"""Video compatibility regressions; all hardware/process boundaries are mocked."""
import json
import errno
import socket
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from autodrive_console import video

ROOT = Path(__file__).resolve().parents[1]


def manager(tmp_path, **runtime):
    raw = json.loads((ROOT / 'config/video.ros.json').read_text())
    raw['enabled'] = True
    for stream in raw['streams']:
        stream['enabled'] = True
    raw['runtime'].update(runtime)
    path = tmp_path / 'config/video.json'
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(raw))
    return video.VideoManager(path)


def test_private_rtsp_port_keeps_an_available_configured_port():
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    assert video._choose_private_rtsp_port({'rtsp_port': port, 'api_port': 9997, 'whep_port': 8889}) == port
    with socket.socket() as check:
        check.bind(('127.0.0.1', port))  # The availability check releases its socket.


def test_private_rtsp_port_avoids_an_external_listener_and_gateway_ports():
    with socket.socket() as external:
        external.bind(('0.0.0.0', 0))
        external.listen()
        occupied = external.getsockname()[1]
        chosen = video._choose_private_rtsp_port({'rtsp_port': occupied, 'api_port': 18554, 'whep_port': 18555})
        assert chosen not in {occupied, 18554, 18555, 8189}
        with socket.socket() as check:
            check.bind(('127.0.0.1', chosen))
        assert external.fileno() >= 0


def test_private_rtsp_port_does_not_hide_permission_errors():
    with patch('autodrive_console.video.socket.socket') as factory:
        factory.return_value.__enter__.return_value.bind.side_effect = PermissionError(errno.EACCES, 'denied')
        with pytest.raises(PermissionError):
            video._choose_private_rtsp_port({'rtsp_port': 8554, 'api_port': 9997, 'whep_port': 8889})
        assert factory.call_count == 1


def test_private_rtsp_port_exhaustion_is_bounded():
    with patch('autodrive_console.video.socket.socket') as factory:
        factory.return_value.__enter__.return_value.bind.side_effect = OSError(errno.EADDRINUSE, 'occupied')
        with pytest.raises(OSError, match='RTSP'):
            video._choose_private_rtsp_port({'rtsp_port': 8554, 'api_port': 9997, 'whep_port': 8889})
        assert factory.call_count <= 10


def test_rtsp_fallback_matches_gateway_and_reloaded_ingest_without_changing_config(tmp_path):
    m = manager(tmp_path)
    with socket.socket() as external:
        external.bind(('0.0.0.0', 0))
        external.listen()
        occupied = external.getsockname()[1]
        raw = json.loads(m.config_path.read_text())
        raw['gateway']['rtsp_port'] = occupied
        m.config_path.write_text(json.dumps(raw))
        original = m.config_path.read_bytes()
        rt = video.VideoRuntime(m, tmp_path, tmp_path / 'ingest')
        (tmp_path / 'mediamtx').mkdir()
        def restart_an_ingest(ingest, gst):
            reloaded = m.load_config()
            assert reloaded['gateway']['rtsp_port'] == occupied
            rt._start_ingest(reloaded['streams'][1], reloaded, ingest, gst)
            return 0
        with patch.object(rt, '_runtime_root', return_value=tmp_path), \
             patch.object(rt, '_require_executable', side_effect=lambda path, label: path), \
             patch.object(rt, '_install_signal_handlers'), patch.object(rt, '_stop_children'), \
             patch.object(rt.encoder_selector, 'select', return_value=video.EncoderSelection('nvh264enc', None)), \
             patch.object(rt, '_wait_for_gateway', return_value=True), \
             patch.object(rt, '_monitor_children', side_effect=restart_an_ingest), \
             patch('autodrive_console.video.subprocess.Popen') as popen:
            assert rt.run() == 0
        commands = [call.args[0] for call in popen.call_args_list if '--rtsp-url' in call.args[0]]
        assert len(commands) == 2
        urls = [command[command.index('--rtsp-url') + 1] for command in commands]
        ports = {int(url.split(':')[2].split('/')[0]) for url in urls}
        assert len(ports) == 1 and occupied not in ports
        port = ports.pop()
        gateway = (tmp_path / 'mediamtx/ry-aletheia-mediamtx.yml').read_text()
        assert f'rtspAddress: 127.0.0.1:{port}' in gateway
        assert 'apiAddress: 127.0.0.1:9997' in gateway and 'webrtcAddress: :8889' in gateway
        assert m.config_path.read_bytes() == original


def test_auto_encoder_accepts_controlled_render_nodes_and_rejects_commands(tmp_path):
    m = manager(tmp_path, encoder='auto', vaapi_device='auto')
    assert m.load_config()['runtime']['encoder'] == 'auto'
    for value in ('/dev/dri/renderD129', '/dev/dri/renderD128'):
        m = manager(tmp_path, encoder='nvh264enc', vaapi_device=value)
        assert m.load_config()['runtime']['vaapi_device'] == value
    for value in ('/tmp/renderD128', '/dev/dri/renderD128;id', '/dev/video0'):
        with pytest.raises(video.VideoConfigurationError):
            manager(tmp_path, vaapi_device=value).load_config()


def test_legacy_intel_migration_preserves_custom_input_and_video_budget(tmp_path):
    m = manager(tmp_path, encoder='vaapih264enc', vaapi_device='/dev/dri/renderD128')
    raw = json.loads(m.config_path.read_text())
    raw['runtime'].pop('hardware_selection_version', None)
    raw['streams'][0].update(source_topic='/custom/image', fps=7, bitrate_kbps=900)
    m.config_path.write_text(json.dumps(raw))
    m.default_config_path = ROOT / 'config/video.shm.json'
    assert m.migrate_config()
    result = m.load_config()
    assert result['runtime']['encoder'] == 'auto'
    assert result['runtime']['vaapi_device'] == 'auto'
    assert result['streams'][0]['input'] == {'kind': 'ros', 'topic': '/custom/image'}
    assert result['streams'][0]['fps'] == 7
    assert result['streams'][0]['bitrate_kbps'] == 900
    assert result['streams'][0]['enabled'] is True


def test_explicit_vaapi_choice_is_not_overwritten_after_legacy_migration(tmp_path):
    m = manager(tmp_path, encoder='vaapih264enc', vaapi_device='/dev/dri/renderD128', hardware_selection_version=1)
    m.default_config_path = ROOT / 'config/video.ros.json'
    assert not m.migrate_config()
    assert m.load_config()['runtime']['encoder'] == 'vaapih264enc'


def test_canonical_default_ros_input_migrates_to_shm_without_custom_topic_guessing(tmp_path):
    m = manager(tmp_path)
    raw = json.loads(m.config_path.read_text())
    for stream in raw['streams'][:4]:
        stream['input'] = {'kind': 'ros', 'topic': stream.pop('source_topic')}
    raw['streams'][0]['input']['topic'] = '/custom/front'
    m.config_path.write_text(json.dumps(raw))
    m.default_config_path = ROOT / 'config/video.shm.json'
    assert m.migrate_config()
    result = m.load_config()
    assert result['streams'][0]['input'] == {'kind': 'ros', 'topic': '/custom/front'}
    assert result['streams'][1]['input'] == {'kind': 'shmsdk', 'channel': 'CamBack'}


def test_encoder_selector_retains_working_intel_without_nvenc_probe(tmp_path):
    selector = video.HardwareEncoderSelector()
    with patch.object(selector, '_render_devices', return_value=['/dev/dri/renderD128']), patch.object(selector, '_probe', return_value=None) as probe:
        result = selector.select(tmp_path / 'gst-launch', 'auto', 'auto')
        again = selector.select(tmp_path / 'gst-launch', 'auto', 'auto')
    assert result.encoder == 'vaapih264enc'
    assert result.device == '/dev/dri/renderD128'
    assert again == result
    assert [call.args[1] for call in probe.call_args_list] == ['vaapih264enc']


def test_encoder_selector_uses_nvenc_when_intel_fails_and_caches_failure(tmp_path):
    selector = video.HardwareEncoderSelector()
    with patch.object(selector, '_render_devices', return_value=['/dev/dri/renderD128']), patch.object(selector, '_probe', side_effect=['Intel 不可用', None]) as probe:
        result = selector.select(tmp_path / 'gst-launch', 'auto', 'auto')
    assert result.encoder == 'nvh264enc'
    assert result.device is None
    assert [call.args[1] for call in probe.call_args_list] == ['vaapih264enc', 'nvh264enc']
    selector = video.HardwareEncoderSelector()
    with patch.object(selector, '_render_devices', return_value=[]), patch.object(selector, '_probe', return_value='NVIDIA 驱动不可用') as probe:
        for _ in range(2):
            with pytest.raises(video.EncoderUnavailable, match='NVIDIA'):
                selector.select(tmp_path / 'gst-launch', 'auto', 'auto')
    assert probe.call_count == 1


def test_hardware_probe_is_bounded_synthetic_and_reaps_timeout_tree(tmp_path):
    selector = video.HardwareEncoderSelector()
    proc = Mock(pid=24680)
    proc.wait.side_effect = [subprocess.TimeoutExpired('probe', 10), 0]
    with patch('autodrive_console.video_encoder.subprocess.Popen', return_value=proc) as popen, patch('autodrive_console.video_encoder.os.killpg') as killpg, patch('autodrive_console.video_encoder.time.monotonic', side_effect=[0, 0, 11]):
        error = selector._probe(tmp_path / 'gst-launch', 'nvh264enc', None)
    command = popen.call_args.args[0]
    assert 'videotestsrc' in command and 'num-buffers=3' in command
    assert 'fakesink' in command and 'nvh264enc' in command
    assert not any('rtsp://' in value or '/dev/video' in value for value in command)
    assert 'preset=low-latency-hq' in command and 'zerolatency=true' in command
    assert popen.call_args.kwargs['start_new_session'] is True
    assert '超时' in error
    killpg.assert_called_once()


def test_status_reads_hardware_error_without_probing_gpu_or_changing_old_fields(tmp_path):
    m = manager(tmp_path)
    status_path = tmp_path / 'runtime/video-status.json'
    status_path.parent.mkdir()
    status_path.write_text(json.dumps({'runtime': {'state': 'error', 'encoder': None, 'device': None,
        'error_code': 'encoder_unavailable', 'detail': '无可用硬件编码器'}, 'streams': {}}))
    with patch.object(m, '_probe_gateway', return_value=video.GatewayHealth(False, 'MediaMTX API 不可用')):
        result = m.status('robot:8087')
    assert result['runtime']['error_code'] == 'encoder_unavailable'
    assert result['runtime']['detail'] == '无可用硬件编码器'
    assert result['streams'][0]['status'] == 'offline'
    assert result['streams'][0]['url'] == 'http://robot:8889/front_camera/whep'


def test_single_stream_crash_retries_with_backoff_without_stopping_peer_or_gateway(tmp_path):
    m = manager(tmp_path)
    rt = video.VideoRuntime(m, tmp_path, tmp_path / 'ingest')
    config = m.load_config()
    failed, peer, media, replacement = Mock(), Mock(), Mock(), Mock()
    failed.poll.return_value, failed.returncode = 2, 2
    peer.poll.return_value = media.poll.return_value = replacement.poll.return_value = None
    rt.ingest_processes = {'front_camera': failed, 'back_camera': peer}
    rt.media_process = media
    config['streams'] = config['streams'][:2]
    with patch('autodrive_console.video.time.monotonic', return_value=100), patch('autodrive_console.video.subprocess.Popen', return_value=replacement):
        assert rt._reconcile_streams(config, tmp_path / 'ingest', tmp_path / 'gst')
        assert 'front_camera' not in rt.ingest_processes
    with patch('autodrive_console.video.time.monotonic', return_value=101.1), patch('autodrive_console.video.subprocess.Popen', return_value=replacement):
        assert rt._reconcile_streams(config, tmp_path / 'ingest', tmp_path / 'gst')
    assert rt.ingest_processes['front_camera'] is replacement
    assert rt.ingest_processes['back_camera'] is peer
    peer.terminate.assert_not_called()
    media.terminate.assert_not_called()
    with patch.object(m, '_probe_gateway', return_value=video.GatewayHealth(False, 'mock gateway')):
        assert m.status()['streams'][0]['retry_count'] == 1


def test_runtime_refresh_repairs_missing_file_even_when_content_marker_matches(tmp_path):
    m = manager(tmp_path)
    bundle = tmp_path / 'bundle'
    current = tmp_path / 'runtime/video'
    for root in (bundle, current):
        (root / 'bin').mkdir(parents=True)
        (root / 'ry-aletheia-runtime.json').write_text(json.dumps({'schema': 'ry-aletheia-video-runtime/v1',
            'required_files': ['bin/gst-launch-1.0']}))
    (bundle / 'bin/gst-launch-1.0').write_text('new executable')
    rt = video.VideoRuntime(m, tmp_path, tmp_path / 'ingest', bundle)
    rt._refresh_bundled_runtime(current)
    assert (current / 'bin/gst-launch-1.0').read_text() == 'new executable'


def test_runtime_refresh_repairs_lost_executable_bit_with_unchanged_hash(tmp_path):
    m = manager(tmp_path)
    bundle, current = tmp_path / 'bundle', tmp_path / 'runtime/video'
    for root in (bundle, current):
        (root / 'bin').mkdir(parents=True)
        (root / 'ry-aletheia-runtime.json').write_text(json.dumps({'schema': 'ry-aletheia-video-runtime/v1',
            'required_files': ['bin/gst-launch-1.0'], 'executable_files': ['bin/gst-launch-1.0']}))
        (root / 'bin/gst-launch-1.0').write_text('same binary')
    (bundle / 'bin/gst-launch-1.0').chmod(0o755)
    (current / 'bin/gst-launch-1.0').chmod(0o644)
    rt = video.VideoRuntime(m, tmp_path, tmp_path / 'ingest', bundle)
    rt._refresh_bundled_runtime(current)
    assert __import__('os').access(current / 'bin/gst-launch-1.0', __import__('os').X_OK)


def test_selected_encoder_and_real_vaapi_device_reach_native_environment(tmp_path):
    m = manager(tmp_path)
    rt = video.VideoRuntime(m, tmp_path, tmp_path / 'ingest')
    rt.encoder_selection = video.EncoderSelection('vaapih264enc', '/dev/dri/renderD129')
    config = m.load_config()
    with patch('autodrive_console.video.subprocess.Popen', return_value=Mock(pid=24680)) as popen:
        rt._start_ingest(config['streams'][0], config, tmp_path / 'ingest', tmp_path / 'gst')
    command = popen.call_args.args[0]
    environment = popen.call_args.kwargs['env']
    assert command[command.index('--encoder') + 1] == 'vaapih264enc'
    assert environment['GST_VAAPI_DRM_DEVICE'] == '/dev/dri/renderD129'
    assert environment['GST_VAAPI_DISPLAY'] == 'drm'
    assert popen.call_args.kwargs['start_new_session'] is True


def test_ingest_group_stop_reaps_encoder_subtree_after_parent_already_exited():
    parent = Mock(pid=24680)
    parent.poll.return_value = 2
    with patch('autodrive_console.video.os.killpg') as killpg:
        video.VideoRuntime._stop_ingest(parent, process_group=True)
    assert killpg.call_args_list[-1].args[0] == 24680
    assert killpg.call_args_list[-1].args[1] == __import__('signal').SIGKILL


def test_no_hardware_error_is_persisted_before_any_native_media_process_starts(tmp_path):
    m = manager(tmp_path)
    rt = video.VideoRuntime(m, tmp_path, tmp_path / 'ingest')
    with patch.object(rt, '_runtime_root', return_value=tmp_path), patch.object(rt, '_require_executable', side_effect=lambda path, label: path), patch.object(rt, '_write_media_config'), patch.object(rt, '_install_signal_handlers'), patch.object(rt.encoder_selector, 'select', side_effect=video.EncoderUnavailable('无硬件编码器')), patch('autodrive_console.video.subprocess.Popen') as popen:
        assert rt.run() == 2
    popen.assert_not_called()
    assert m._read_runtime_status()['runtime']['error_code'] == 'encoder_unavailable'


def test_retry_exhaustion_stops_spawning_only_failed_stream_and_toggle_resets_it(tmp_path):
    m = manager(tmp_path)
    rt = video.VideoRuntime(m, tmp_path, tmp_path / 'ingest')
    config = m.load_config()
    config['streams'] = config['streams'][:1]
    with patch('autodrive_console.video.subprocess.Popen', side_effect=OSError('cannot spawn')) as popen:
        for now in (0, 1, 3, 7, 15, 31, 100, 1000):
            with patch('autodrive_console.video.time.monotonic', return_value=now):
                assert rt._reconcile_streams(config, tmp_path / 'ingest', tmp_path / 'gst')
        assert popen.call_count == 6  # initial start plus five retries
        assert m._read_runtime_status()['streams']['front_camera']['error_code'] == 'ingest_retry_exhausted'
        config['streams'][0]['enabled'] = False
        rt._reconcile_streams(config, tmp_path / 'ingest', tmp_path / 'gst')
        config['streams'][0]['enabled'] = True
        rt._reconcile_streams(config, tmp_path / 'ingest', tmp_path / 'gst')
        assert popen.call_count == 7


def test_nvenc_streams_start_in_order_until_published_or_startup_deadline(tmp_path):
    m = manager(tmp_path)
    rt = video.VideoRuntime(m,tmp_path,tmp_path/'ingest')
    rt.encoder_selection = video.EncoderSelection('nvh264enc',None)
    config=m.load_config()
    config['streams']=config['streams'][:3]
    processes=[]
    def launch(*args,**kwargs):
        child=Mock(pid=12345+len(processes));child.poll.return_value=None
        processes.append(child);return child
    with patch('autodrive_console.video.subprocess.Popen',side_effect=launch), patch.object(m,'_probe_gateway',return_value=video.GatewayHealth(True,'ready',frozenset())) as health:
        with patch('autodrive_console.video.time.monotonic',return_value=0):
            rt._reconcile_streams(config,tmp_path/'ingest',tmp_path/'gst')
        assert list(rt.ingest_processes)==['front_camera']
        with patch('autodrive_console.video.time.monotonic',return_value=1):
            rt._reconcile_streams(config,tmp_path/'ingest',tmp_path/'gst')
        assert list(rt.ingest_processes)==['front_camera']
        health.return_value=video.GatewayHealth(True,'ready',frozenset({'front_camera'}))
        with patch('autodrive_console.video.time.monotonic',return_value=2):
            rt._reconcile_streams(config,tmp_path/'ingest',tmp_path/'gst')
        assert list(rt.ingest_processes)==['front_camera','back_camera']
        with patch('autodrive_console.video.time.monotonic',return_value=15):
            rt._reconcile_streams(config,tmp_path/'ingest',tmp_path/'gst')
        assert list(rt.ingest_processes)==['front_camera','back_camera','left_camera']
        for child in processes:child.terminate.assert_not_called()


@pytest.mark.parametrize('reason',['disabled','crashed'])
def test_disabled_or_failed_starting_stream_does_not_hold_up_other_nvenc_streams(tmp_path,reason):
    m=manager(tmp_path)
    rt=video.VideoRuntime(m,tmp_path,tmp_path/'ingest')
    rt.encoder_selection=video.EncoderSelection('nvh264enc',None)
    config=m.load_config();config['streams']=config['streams'][:2]
    child=Mock(pid=12345);child.poll.return_value=None
    with patch('autodrive_console.video.subprocess.Popen',return_value=child),patch.object(m,'_probe_gateway',return_value=video.GatewayHealth(False,'unavailable')),patch.object(rt,'_stop_ingest'):
        rt._reconcile_streams(config,tmp_path/'ingest',tmp_path/'gst')
        assert list(rt.ingest_processes)==['front_camera']
        if reason=='disabled':
            config['streams'][0]['enabled']=False
        else:
            child.poll.return_value=3
            child.returncode=3
        rt._reconcile_streams(config,tmp_path/'ingest',tmp_path/'gst')
        assert list(rt.ingest_processes)==['back_camera']


def test_cancel_during_hardware_preflight_does_not_start_any_media_process(tmp_path):
    m = manager(tmp_path)
    rt = video.VideoRuntime(m, tmp_path, tmp_path / 'ingest')
    def finish_probe(*args, **kwargs):
        rt.stopping = True
        return video.EncoderSelection('nvh264enc', None)
    with patch.object(rt, '_runtime_root', return_value=tmp_path), patch.object(rt, '_require_executable', side_effect=lambda path, label: path), patch.object(rt, '_write_media_config'), patch.object(rt, '_install_signal_handlers'), patch.object(rt.encoder_selector, 'select', side_effect=finish_probe), patch('autodrive_console.video.subprocess.Popen') as popen:
        assert rt.run() == 0
    popen.assert_not_called()
    assert m._read_runtime_status()['runtime']['state'] == 'disabled'


def test_cancel_after_failed_intel_does_not_start_detached_nvenc_probe(tmp_path):
    selector = video.HardwareEncoderSelector()
    stopped = False
    def failure(*args, **kwargs):
        nonlocal stopped
        stopped = True
        return 'driver unavailable'
    with patch.object(selector, '_render_devices', return_value=['/dev/dri/renderD128']), patch.object(selector, '_probe', side_effect=failure) as probe:
        with pytest.raises(video.EncoderProbeCancelled):
            selector.select(tmp_path / 'gst', 'auto', 'auto', cancelled=lambda: stopped)
    assert probe.call_count == 1


def test_output_dimensions_are_validated_before_hardware_or_process_start(tmp_path):
    m = manager(tmp_path)
    raw = json.loads(m.config_path.read_text())
    for resolution in ('641x480', '640x481', '9000x480', '8192x8192'):
        raw['streams'][0]['resolution'] = resolution
        m.config_path.write_text(json.dumps(raw))
        with pytest.raises(video.VideoConfigurationError, match='分辨率|resolution'):
            m.load_config()


def test_console_stop_signals_only_owned_descendant_groups_and_rejects_reused_pid(tmp_path, monkeypatch):
    import signal
    proc_root = tmp_path / 'proc'
    def process(pid, parent, group, birth, children=''):
        root = proc_root / str(pid)
        (root / 'task' / str(pid)).mkdir(parents=True, exist_ok=True)
        (root / 'task' / str(pid) / 'children').write_text(children)
        # Fields 3..22: state, ppid, pgrp, session, then padding, starttime.
        fields = ['S', str(parent), str(group), str(group)] + ['0'] * 15 + [str(birth)]
        (root / 'stat').write_text(f'{pid} (native helper) ' + ' '.join(fields))
        (root / 'cmdline').write_bytes(b'/private/aletheia_video_ingest\0--node-name\0ry_aletheia_video_front_camera\0')
    process(11111, 99, 11111, 10, '22222 33333')
    process(22222, 11111, 22222, 20, '22223')
    process(22223, 22222, 22222, 21)
    process(33333, 11111, 11111, 30)  # MediaMTX shares runner group.
    monkeypatch.setattr(video, '_PROC_ROOT', proc_root)
    groups = video._owned_subgroups(11111)
    assert groups == [(22222, 20)]
    with patch('autodrive_console.video.os.killpg') as killpg:
        video._signal_owned_subgroups(groups, signal.SIGTERM)
        assert killpg.call_args.args == (22222, signal.SIGTERM)
        process(22222, 777, 22222, 999)  # PID reused after the snapshot.
        video._signal_owned_subgroups(groups, signal.SIGKILL)
        assert killpg.call_count == 1


def test_runner_owns_bandwidth_worker_and_stops_it_even_when_monitor_fails(tmp_path):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    m = manager(tmp_path)
    raw = json.loads(m.config_path.read_text())
    request_started, release = threading.Event(), threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            request_started.set()
            release.wait(2)
            body = b'{"items":[],"pageCount":1}'
            self.send_response(200); self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            try: self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError): pass
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval':.01}, daemon=True)
    thread.start()
    raw['gateway']['api_url'] = f'http://127.0.0.1:{server.server_port}/v3/paths/list'
    m.config_path.write_text(json.dumps(raw))
    rt = video.VideoRuntime(m, tmp_path, tmp_path/'ingest')
    (tmp_path/'mediamtx').mkdir()
    def fail_after_start(*args):
        assert request_started.wait(1)
        assert not release.is_set()  # Media lifecycle progressed while statistics HTTP was blocked.
        assert rt.bandwidth_monitor.thread.is_alive()
        raise RuntimeError('test monitor failure')
    try:
        with patch.object(rt, '_runtime_root', return_value=tmp_path), \
             patch.object(rt, '_require_executable', side_effect=lambda path,label:path), \
             patch.object(rt, '_install_signal_handlers'), patch.object(rt, '_stop_children'), \
             patch.object(rt.encoder_selector, 'select', return_value=video.EncoderSelection('nvh264enc',None)), \
             patch.object(rt, '_wait_for_gateway', return_value=True), \
             patch.object(rt, '_reconcile_streams'), \
             patch.object(rt, '_monitor_children', side_effect=fail_after_start), \
             patch('autodrive_console.video.subprocess.Popen'):
            with pytest.raises(RuntimeError, match='test monitor failure'):
                rt.run()
        assert not rt.bandwidth_monitor.thread.is_alive()
    finally:
        release.set()
        server.shutdown(); thread.join(2); server.server_close()


def test_statistics_start_failure_does_not_stop_video_or_skip_children_cleanup(tmp_path):
    m=manager(tmp_path);rt=video.VideoRuntime(m,tmp_path,tmp_path/'ingest')
    (tmp_path/'mediamtx').mkdir()
    with patch.object(rt,'_runtime_root',return_value=tmp_path), \
         patch.object(rt,'_require_executable',side_effect=lambda path,label:path), \
         patch.object(rt,'_install_signal_handlers'), patch.object(rt,'_stop_children') as cleanup, \
         patch.object(rt.encoder_selector,'select',return_value=video.EncoderSelection('nvh264enc',None)), \
         patch.object(rt,'_wait_for_gateway',return_value=True), \
         patch.object(rt,'_reconcile_streams'), \
         patch.object(rt,'_monitor_children',return_value=0) as playback, \
         patch('autodrive_console.video.subprocess.Popen'), \
         patch('autodrive_console.video_bandwidth.threading.Thread.start',side_effect=RuntimeError('cannot start thread')):
        assert rt.run()==0
    assert playback.call_count==1
    assert cleanup.call_count==1


def test_nvenc_candidate_is_explicit_and_does_not_change_default_or_vaapi(tmp_path):
    m=manager(tmp_path)
    assert m.load_config()['runtime']['nvenc_rate_control']=='cbr'
    m=manager(tmp_path,nvenc_rate_control='vbr')
    assert m.load_config()['runtime']['nvenc_rate_control']=='vbr'
    for value in ('auto','vbr;id',True,[],None):
        with pytest.raises(video.VideoConfigurationError,match='nvenc_rate_control'):
            manager(tmp_path,nvenc_rate_control=value).load_config()


def test_nvenc_candidate_selection_cache_and_probe_use_same_mode(tmp_path):
    selector=video.HardwareEncoderSelector()
    with patch.object(selector,'_probe',return_value=None) as probe:
        cbr=selector.select(tmp_path/'gst','nvh264enc','auto')
        vbr=selector.select(tmp_path/'gst','nvh264enc','auto',nvenc_rate_control='vbr')
        assert selector.select(tmp_path/'gst','nvh264enc','auto',nvenc_rate_control='vbr')==vbr
    assert probe.call_count==2
    assert cbr.nvenc_rate_control=='cbr' and vbr.nvenc_rate_control=='vbr'
    assert probe.call_args_list[-1].kwargs['nvenc_rate_control']=='vbr'
    proc=Mock();proc.wait.return_value=0
    with patch('autodrive_console.video_encoder.subprocess.Popen',return_value=proc) as popen:
        assert selector._probe(tmp_path/'gst','nvh264enc',None,nvenc_rate_control='vbr') is None
    args=popen.call_args.args[0]
    assert 'rc-mode=vbr' in args and 'max-bitrate=1200' in args and 'const-quality=23' in args
    assert 'rc-mode=cbr' not in args
    assert 'bframes=0' in args and 'zerolatency=true' in args and 'gop-size=15' in args


def test_selected_nvenc_policy_reaches_ingest_even_if_file_changes_mid_run(tmp_path):
    m=manager(tmp_path,nvenc_rate_control='vbr')
    rt=video.VideoRuntime(m,tmp_path,tmp_path/'ingest')
    rt.encoder_selection=video.EncoderSelection('nvh264enc',None,'vbr')
    config=m.load_config()
    config['runtime']['nvenc_rate_control']='cbr'
    with patch('autodrive_console.video.subprocess.Popen') as popen:
        rt._start_ingest(config['streams'][0],config,tmp_path/'ingest',tmp_path/'gst')
    args=popen.call_args.args[0]
    assert args[args.index('--nvenc-rate-control')+1]=='vbr'
    assert args[args.index('--fps')+1]=='15'
    assert args[args.index('--bitrate-kbps')+1]=='1200'
