"""Projection session ownership, revision and worker lifecycle regression tests."""
import json
import threading
import time
from pathlib import Path

import pytest

from autodrive_console.deployment import DeploymentStore


def jobs_module():
    from autodrive_console import map_projection_jobs
    return map_projection_jobs


def analyze(source):
    assert source.read_bytes() == b'original PCD bytes'
    return {'finite_points': 4, 'recommended': {'z_min': 0.2, 'z_max': 1.5}}


def project(source, output, parameters):
    assert source.read_bytes() == b'original PCD bytes'
    output.mkdir(parents=True, exist_ok=True)
    (output / 'map.pgm').write_bytes(b'P5\n2 2\n255\n\x00\xff\xcd\x00')
    (output / 'map.yaml').write_text('image: map.pgm\nresolution: 0.1\norigin: [-1, 2, 0]\n')
    return {'width': 2, 'height': 2, 'origin': [-1, 2, 0], 'occupied_cells': 2}


PARAMETERS = {'z_min': 0.2, 'z_max': 1.5, 'resolution': 0.1, 'min_points': 1, 'denoise': False}


@pytest.fixture
def setup(tmp_path):
    store = DeploymentStore(tmp_path / 'deployments')
    first, second = store.create('first')['id'], store.create('second')['id']
    source = tmp_path / 'Original cloud.PCD'
    source.write_bytes(b'original PCD bytes')
    return store, first, second, source


def wait_state(jobs, pid, jid, state):
    # Native file work can take longer under the full integration suite load.
    # This is a test deadline, not a production latency requirement.
    until = time.monotonic() + 15
    while time.monotonic() < until:
        snapshot = jobs.get(pid, jid)
        if snapshot['state'] == state:
            return snapshot
        time.sleep(0.005)
    pytest.fail(f'Expected {state}, got {snapshot}')


def ready(jobs, pid, source):
    job = jobs.create(pid, source)
    wait_state(jobs, pid, job['id'], 'awaiting_parameters')
    jobs.preview(pid, job['id'], PARAMETERS)
    return wait_state(jobs, pid, job['id'], 'ready')


def test_trajectory_is_preview_only_project_owned_and_shares_worker_gate(setup, monkeypatch):
    from autodrive_console import pcd_projection
    module = jobs_module()
    store, pid, other, source = setup
    jobs = module.MapProjectionJobs(store, analyzer=analyze, projector=project)
    before = ready(jobs, pid, source)
    monkeypatch.setattr(pcd_projection, 'trajectory_preview', lambda p: (b'xy', {'point_count': 1}), raising=False)
    body, meta = jobs.trajectory_preview(pid, before['id'], source)
    assert (body, meta) == (b'xy', {'point_count': 1})
    assert jobs.get(pid, before['id']) == before
    with pytest.raises(module.MapProjectionError):
        jobs.trajectory_preview(other, before['id'], source)
    assert module._WORKER_GATE.acquire(blocking=False)
    try:
        with pytest.raises(module.MapProjectionConflict):
            jobs.trajectory_preview(pid, before['id'], source)
    finally:
        module._WORKER_GATE.release()
    jobs.cancel(pid, before['id'])
    with pytest.raises(module.MapProjectionConflict):
        jobs.trajectory_preview(pid, before['id'], source)


def test_native_progress_is_persisted_and_late_cancelled_worker_cannot_update(setup, monkeypatch):
    from autodrive_console import pcd_projection
    module = jobs_module()
    store, pid, _, source = setup
    entered, release = threading.Event(), threading.Event()
    reporters = []
    def native(source, output, parameters, *, on_progress=None):
        assert callable(on_progress)
        reporters.append(on_progress)
        on_progress(45, '正在生成地图栅格。')
        entered.set()
        assert release.wait(5)
        on_progress(90, '正在保存地图预览。')
        return project(source, output, parameters)
    monkeypatch.setattr(pcd_projection, 'project_pcd', native)
    jobs = module.MapProjectionJobs(store, analyzer=analyze)
    job = jobs.create(pid, source)
    wait_state(jobs, pid, job['id'], 'awaiting_parameters')
    jobs.preview(pid, job['id'], PARAMETERS)
    try:
        assert entered.wait(2)
        snapshot = jobs.get(pid, job['id'])
        assert snapshot['state'] == 'processing'
        assert snapshot['progress'] == 45
        assert snapshot['message'] == '正在生成地图栅格。'
        reporters[0](20, '旧进度')
        assert jobs.get(pid, job['id'])['progress'] == 45
        jobs.cancel(pid, job['id'])
    finally:
        release.set()
        wait_worker_idle(module)
    assert jobs.get(pid, job['id'])['state'] == 'cancelled'
    assert jobs.get(pid, job['id'])['progress'] == 0


def test_confirm_requires_current_revision_and_imports_original_once(setup):
    module = jobs_module()
    store, pid, _, source = setup
    jobs = module.MapProjectionJobs(store, analyzer=analyze, projector=project)
    job = ready(jobs, pid, source)
    for stale in (0, True, '1', 1.0):
        with pytest.raises(module.MapProjectionError):
            jobs.confirm(pid, job['id'], '大厅', stale)
    asset = jobs.confirm(pid, job['id'], '大厅', job['revision'])
    repeated = jobs.confirm(pid, job['id'], '大厅', job['revision'])
    assert repeated['id'] == asset['id']
    assert len(store.get(pid)['map_assets']) == 1
    assert asset['files']['index'] is None
    assert asset['files']['pcd_count'] == 1
    copied = list((store._project_dir(pid) / 'maps' / asset['id']).glob('*.pcd'))
    assert copied[0].read_bytes() == source.read_bytes() == b'original PCD bytes'
    assert jobs.get(pid, job['id'])['state'] == 'imported'
    assert jobs.preview_path(pid, job['id'], job['revision']).read_bytes().startswith(b'P5')
    with pytest.raises(module.MapProjectionConflict):
        jobs.cancel(pid, job['id'])


def test_ownership_safe_ids_latest_and_private_paths(setup):
    module = jobs_module()
    store, pid, other, source = setup
    jobs = module.MapProjectionJobs(store, analyzer=analyze, projector=project)
    assert jobs.latest(pid) is None
    job = ready(jobs, pid, source)
    assert jobs.latest(pid) == job
    assert jobs.latest(other) is None
    assert str(store.root) not in json.dumps(job)
    for bad in (job['id'], '../escape', 'projection-../../escape'):
        with pytest.raises(module.MapProjectionError):
            jobs.get(other, bad)
    job['analysis']['finite_points'] = 999
    assert jobs.get(pid, job['id'])['analysis']['finite_points'] == 4
    resumed = module.MapProjectionJobs(store, analyzer=analyze, projector=project)
    assert resumed.latest(pid)['state'] == 'ready'


def test_busy_is_global_and_cancelled_analysis_cannot_adopt(setup):
    module = jobs_module()
    store, pid, other, source = setup
    entered, release = threading.Event(), threading.Event()
    def blocked(path):
        entered.set()
        assert release.wait(5)
        return analyze(path)
    jobs = module.MapProjectionJobs(store, analyzer=blocked, projector=project)
    second = module.MapProjectionJobs(DeploymentStore(store.root.parent / 'another'), analyzer=analyze, projector=project)
    second_pid = second.store.create('other')['id']
    job = jobs.create(pid, source)
    assert entered.wait(2)
    try:
        with pytest.raises(module.MapProjectionConflict):
            second.create(second_pid, source)
        assert jobs.cancel(pid, job['id'])['state'] == 'cancelled'
        with pytest.raises(module.MapProjectionConflict):
            second.create(second_pid, source)
    finally:
        release.set()
    wait_worker_idle(module)
    assert jobs.get(pid, job['id'])['state'] == 'cancelled'
    assert jobs.get(pid, job['id'])['analysis'] is None
    assert len(list((store._project_dir(pid) / '.projections').iterdir())) == 1


def wait_worker_idle(module):
    until = time.monotonic() + 5
    while time.monotonic() < until:
        if module._WORKER_GATE.acquire(blocking=False):
            module._WORKER_GATE.release()
            return
        time.sleep(0.005)
    pytest.fail('Worker did not finish')


def test_new_preview_invalidates_previous_revision_and_cancel_discards_result(setup):
    module = jobs_module()
    store, pid, _, source = setup
    jobs = module.MapProjectionJobs(store, analyzer=analyze, projector=project)
    job = ready(jobs, pid, source)
    entered, release = threading.Event(), threading.Event()
    def blocked(path, output, parameters):
        entered.set()
        assert release.wait(5)
        return project(path, output, parameters)
    jobs._projector = blocked
    pending = jobs.preview(pid, job['id'], {**PARAMETERS, 'z_max': 1.8})
    assert entered.wait(2)
    try:
        assert pending['revision'] == 2
        assert pending['state'] == 'processing'
        assert pending['result'] is None
        with pytest.raises(module.MapProjectionConflict):
            jobs.preview_path(pid, job['id'], 1)
        with pytest.raises(module.MapProjectionConflict):
            jobs.confirm(pid, job['id'], '大厅', 1)
        jobs.cancel(pid, job['id'])
    finally:
        release.set()
    wait_worker_idle(module)
    assert jobs.get(pid, job['id'])['state'] == 'cancelled'
    assert jobs.get(pid, job['id'])['result'] is None
    assert store.get(pid)['map_assets'] == []


def test_restart_interrupts_processing_and_old_worker_cannot_publish(setup):
    module = jobs_module()
    store, pid, _, source = setup
    entered, release = threading.Event(), threading.Event()
    def blocked(path):
        entered.set()
        assert release.wait(5)
        return analyze(path)
    jobs = module.MapProjectionJobs(store, analyzer=blocked, projector=project)
    job = jobs.create(pid, source)
    assert entered.wait(2)
    try:
        restarted = module.MapProjectionJobs(store, analyzer=analyze, projector=project)
        assert restarted.latest(pid)['state'] == 'interrupted'
    finally:
        release.set()
    wait_worker_idle(module)
    assert restarted.get(pid, job['id'])['state'] == 'interrupted'
    assert restarted.get(pid, job['id'])['analysis'] is None


def test_invalid_parameters_do_not_destroy_ready_preview_and_import_failure_is_retryable(setup, monkeypatch):
    module = jobs_module()
    store, pid, _, source = setup
    jobs = module.MapProjectionJobs(store, analyzer=analyze, projector=project)
    job = ready(jobs, pid, source)
    for params in ({}, {**PARAMETERS, 'z_min': 5}, {**PARAMETERS, 'resolution': float('nan')}, {**PARAMETERS, 'min_points': True}, {**PARAMETERS, 'denoise': 'false'}, {**PARAMETERS, 'z_min': 10 ** 400}, {**PARAMETERS, 'min_points': 10_000_001}):
        with pytest.raises(module.MapProjectionError):
            jobs.preview(pid, job['id'], params)
    assert jobs.get(pid, job['id'])['revision'] == 1
    for label in ('', 'x' * 81, None):
        with pytest.raises(module.MapProjectionError):
            jobs.confirm(pid, job['id'], label, 1)
    original = store.import_uploaded_map
    def fails(*args):
        raise OSError('disk failure /private/path')
    monkeypatch.setattr(store, 'import_uploaded_map', fails)
    with pytest.raises(module.MapProjectionError):
        jobs.confirm(pid, job['id'], '大厅', 1)
    assert jobs.get(pid, job['id'])['state'] == 'ready'
    assert '/private/path' not in json.dumps(jobs.get(pid, job['id']))
    monkeypatch.setattr(store, 'import_uploaded_map', original)
    assert jobs.confirm(pid, job['id'], '大厅', 1)['id']


def test_processing_restart_discards_partial_preview_and_can_retry(setup):
    module = jobs_module()
    store, pid, _, source = setup
    jobs = module.MapProjectionJobs(store, analyzer=analyze, projector=project)
    job = ready(jobs, pid, source)
    entered, release = threading.Event(), threading.Event()
    def blocked(path, output, parameters):
        entered.set()
        assert release.wait(5)
        return project(path, output, parameters)
    jobs._projector = blocked
    jobs.preview(pid, job['id'], PARAMETERS)
    assert entered.wait(2)
    try:
        resumed = module.MapProjectionJobs(store, analyzer=analyze, projector=project)
        assert resumed.latest(pid)['state'] == 'interrupted'
        with pytest.raises(module.MapProjectionConflict):
            resumed.preview_path(pid, job['id'], 2)
    finally:
        release.set()
    wait_worker_idle(module)
    assert resumed.get(pid, job['id'])['state'] == 'interrupted'
    resumed.preview(pid, job['id'], PARAMETERS)
    retry = wait_state(resumed, pid, job['id'], 'ready')
    assert retry['revision'] == 3
    assert resumed.preview_path(pid, job['id'], 3).is_file()


def test_latest_uses_creation_order_and_failed_analysis_preserves_original(setup):
    module = jobs_module()
    store, pid, _, source = setup
    jobs = module.MapProjectionJobs(store, analyzer=analyze, projector=project)
    first = ready(jobs, pid, source)
    def fails(path):
        raise ValueError('点云缺少有效坐标')
    jobs._analyzer = fails
    second = jobs.create(pid, source)
    failed = wait_state(jobs, pid, second['id'], 'failed')
    assert failed['message'] == '点云缺少有效坐标'
    assert jobs.latest(pid)['id'] == second['id']
    assert jobs.get(pid, first['id'])['state'] == 'ready'
    persisted = json.loads((store._project_dir(pid) / '.projections' / second['id'] / 'session.json').read_text())
    original = store._project_dir(pid) / '.projections' / second['id'] / 'source' / persisted['_source_filename']
    assert original.read_bytes() == b'original PCD bytes'
    assert persisted['_source_sha256'] == store._sha256(source)


def test_simultaneous_confirmation_returns_one_map(setup):
    module = jobs_module()
    store, pid, _, source = setup
    jobs = module.MapProjectionJobs(store, analyzer=analyze, projector=project)
    job = ready(jobs, pid, source)
    barrier = threading.Barrier(3)
    assets, errors = [], []
    def confirm():
        barrier.wait()
        try:
            assets.append(jobs.confirm(pid, job['id'], '大厅', 1))
        except Exception as exc:
            errors.append(exc)
    threads = [threading.Thread(target=confirm) for _ in range(2)]
    for worker in threads:
        worker.start()
    barrier.wait()
    for worker in threads:
        worker.join(5)
        assert not worker.is_alive()
    assert not errors
    assert len(assets) == 2
    assert assets[0]['id'] == assets[1]['id']
    assert len(store.get(pid)['map_assets']) == 1


def test_confirmation_recovers_when_session_save_fails_after_map_was_imported(setup, monkeypatch):
    module = jobs_module()
    store, pid, _, source = setup
    jobs = module.MapProjectionJobs(store, analyzer=analyze, projector=project)
    job = ready(jobs, pid, source)
    original_save = jobs._save
    def interrupted_save(record):
        if record['state'] == 'imported':
            raise OSError('simulated process interruption after map import')
        original_save(record)
    monkeypatch.setattr(jobs, '_save', interrupted_save)
    with pytest.raises(OSError):
        jobs.confirm(pid, job['id'], '大厅', 1)
    assert len(store.get(pid)['map_assets']) == 1
    resumed = module.MapProjectionJobs(store, analyzer=analyze, projector=project)
    recovered = resumed.confirm(pid, job['id'], '大厅', 1)
    assert recovered['id'] == store.get(pid)['map_assets'][0]['id']
    assert resumed.get(pid, job['id'])['state'] == 'imported'
    assert len(store.get(pid)['map_assets']) == 1


def test_height_tuning_keeps_one_generated_revision_and_no_pointcloud_copies(setup):
    module = jobs_module()
    store, pid, _, source = setup
    jobs = module.MapProjectionJobs(store, analyzer=analyze, projector=project)
    job = ready(jobs, pid, source)
    for maximum in (1.6, 1.7, 1.8):
        pending = jobs.preview(pid, job['id'], {**PARAMETERS, 'z_max': maximum})
        job = wait_state(jobs, pid, job['id'], 'ready')
        assert job['revision'] == pending['revision']
    directory = store._project_dir(pid) / '.projections' / job['id']
    assert len(list(directory.glob('revision-*'))) == 1
    assert list(next(directory.glob('revision-*')).glob('*.pcd')) == []
    assert len(list(directory.glob('source/*.pcd'))) == 1


def test_confirmation_recovers_partial_project_import_without_overwriting_assets(setup, monkeypatch):
    module = jobs_module()
    store, pid, _, source = setup
    jobs = module.MapProjectionJobs(store, analyzer=analyze, projector=project)
    job = ready(jobs, pid, source)
    original_write = store._write_json
    def fails_project(path, value):
        if path == store._document_path(pid):
            raise OSError('project metadata write interrupted')
        original_write(path, value)
    monkeypatch.setattr(store, '_write_json', fails_project)
    with pytest.raises(module.MapProjectionError):
        jobs.confirm(pid, job['id'], '大厅', 1)
    assert store.get(pid)['map_assets'] == []
    monkeypatch.setattr(store, '_write_json', original_write)
    asset = jobs.confirm(pid, job['id'], '大厅', 1)
    assert len(store.get(pid)['map_assets']) == 1
    assert asset['id'] == store.get(pid)['map_assets'][0]['id']


def real_source(source):
    import numpy as np
    from pypcd4 import Encoding, PointCloud
    PointCloud.from_points(np.array([[0, 0, 0], [1, 0, 1], [2, 2, 1]], dtype=np.float32),
                           ('x', 'y', 'z'), (np.float32,) * 3).save(source, Encoding.BINARY)


def test_default_analysis_caches_owned_source_sample_across_preview_restart_and_import(setup, monkeypatch):
    import numpy as np
    from autodrive_console import pcd_projection
    module = jobs_module()
    store, pid, other, source = setup
    real_source(source)
    original = source.read_bytes()
    jobs = module.MapProjectionJobs(store)
    pending = jobs.create(pid, source)
    job = wait_state(jobs, pid, pending['id'], 'awaiting_parameters')
    def forbidden_decode(*args, **kwargs):
        raise AssertionError('Source requests must use cached sample, never decode PCD')
    with monkeypatch.context() as scoped:
        scoped.setattr(pcd_projection, '_load', forbidden_decode)
        body, metadata = jobs.source_preview(pid, job['id'])
        assert np.frombuffer(body, dtype='<f4').reshape(-1, 3).tolist() == [
            [-1, -1, -0.5], [0, -1, 0.5], [1, 1, 0.5]]
        assert metadata == job['analysis']['source_preview']
        with pytest.raises(module.MapProjectionError):
            jobs.source_preview(other, job['id'])
    jobs.preview(pid, job['id'], PARAMETERS)
    job = wait_state(jobs, pid, job['id'], 'ready')
    assert jobs.source_preview(pid, job['id'])[0] == body
    resumed = module.MapProjectionJobs(store)
    assert resumed.source_preview(pid, job['id'])[0] == body
    resumed.confirm(pid, job['id'], '三维预览', job['revision'])
    assert resumed.source_preview(pid, job['id'])[0] == body
    assert source.read_bytes() == original
    assert len(list((store._project_dir(pid) / '.projections' / job['id'] / 'source').glob('*.bin'))) == 1


@pytest.mark.parametrize('state', ['analyzing', 'cancelled'])
def test_source_cache_is_not_read_in_ineligible_states(setup, state):
    module = jobs_module()
    store, pid, _, source = setup
    real_source(source)
    jobs = module.MapProjectionJobs(store)
    job = jobs.create(pid, source)
    wait_state(jobs, pid, job['id'], 'awaiting_parameters')
    record = jobs._read(pid, job['id'])
    record['state'] = state
    jobs._save(record)
    with pytest.raises(module.MapProjectionConflict):
        jobs.source_preview(pid, job['id'])


def test_old_session_missing_sample_requires_reupload_without_decoding(setup):
    module = jobs_module()
    store, pid, _, source = setup
    jobs = module.MapProjectionJobs(store, analyzer=analyze, projector=project)
    job = ready(jobs, pid, source)
    with pytest.raises(module.MapProjectionError, match='重新上传'):
        jobs.source_preview(pid, job['id'])


@pytest.mark.parametrize('corruption', ['missing', 'truncated', 'symlink', 'metadata'])
def test_source_cache_path_size_and_metadata_are_validated(setup, corruption):
    module = jobs_module()
    store, pid, _, source = setup
    real_source(source)
    jobs = module.MapProjectionJobs(store)
    job = jobs.create(pid, source)
    wait_state(jobs, pid, job['id'], 'awaiting_parameters')
    cache = store._project_dir(pid) / '.projections' / job['id'] / 'source' / 'source-preview.bin'
    if corruption == 'missing':
        cache.unlink()
    elif corruption == 'truncated':
        cache.write_bytes(b'123')
    elif corruption == 'symlink':
        cache.unlink()
        cache.symlink_to(source)
    else:
        record = jobs._read(pid, job['id'])
        record['analysis']['source_preview']['origin'] = [0, float('nan'), 0]
        jobs._save(record)
    with pytest.raises(module.MapProjectionError):
        jobs.source_preview(pid, job['id'])


def test_adopted_source_cache_is_available_during_projection_and_interruption(setup):
    module = jobs_module()
    store, pid, _, source = setup
    real_source(source)
    entered, release = threading.Event(), threading.Event()
    def blocked(path, output, parameters):
        entered.set()
        assert release.wait(5)
        output.mkdir(parents=True, exist_ok=True)
        (output / 'map.pgm').write_bytes(b'P5\n1 1\n255\n\x00')
        (output / 'map.yaml').write_text('image: map.pgm\nresolution: 1\norigin: [0,0,0]\n')
        return {'width': 1, 'height': 1}
    jobs = module.MapProjectionJobs(store, projector=blocked)
    job = jobs.create(pid, source)
    wait_state(jobs, pid, job['id'], 'awaiting_parameters')
    original = jobs.source_preview(pid, job['id'])
    jobs.preview(pid, job['id'], PARAMETERS)
    assert entered.wait(2)
    try:
        assert jobs.get(pid, job['id'])['state'] == 'processing'
        assert jobs.source_preview(pid, job['id']) == original
        resumed = module.MapProjectionJobs(store)
        assert resumed.get(pid, job['id'])['state'] == 'interrupted'
        assert resumed.source_preview(pid, job['id']) == original
    finally:
        release.set()
    wait_worker_idle(module)


def test_failed_projection_retains_adopted_source_cache_for_height_inspection(setup):
    module = jobs_module()
    store, pid, _, source = setup
    real_source(source)
    jobs = module.MapProjectionJobs(store)
    job = jobs.create(pid, source)
    wait_state(jobs, pid, job['id'], 'awaiting_parameters')
    original = jobs.source_preview(pid, job['id'])
    jobs.preview(pid, job['id'], {**PARAMETERS, 'z_min': 10, 'z_max': 20})
    failed = wait_state(jobs, pid, job['id'], 'failed')
    assert '高度' in failed['message']
    assert jobs.source_preview(pid, job['id']) == original


def test_failed_analysis_without_adopted_cache_requires_reupload(setup):
    module = jobs_module()
    store, pid, _, source = setup
    jobs = module.MapProjectionJobs(store)
    job = jobs.create(pid, source)
    wait_state(jobs, pid, job['id'], 'failed')
    with pytest.raises(module.MapProjectionError, match='重新上传'):
        jobs.source_preview(pid, job['id'])


def test_detail_cache_upgrades_existing_source_in_background_without_changing_ready_map(setup):
    module = jobs_module()
    store, pid, other, source = setup
    real_source(source)
    jobs = module.MapProjectionJobs(store)
    job = jobs.create(pid, source)
    wait_state(jobs, pid, job['id'], 'awaiting_parameters')
    jobs.preview(pid, job['id'], PARAMETERS)
    ready = wait_state(jobs, pid, job['id'], 'ready')
    assert jobs.source_detail(pid, job['id']) is None
    wait_worker_idle(module)
    body, metadata = jobs.source_detail(pid, job['id'])
    assert len(body) == metadata['point_count'] * 20
    assert metadata['format'] == 'xyz-rgba-intensity-v1'
    current = jobs.get(pid, job['id'])
    assert current['state'] == ready['state'] and current['revision'] == ready['revision']
    assert current['result'] == ready['result']
    assert jobs.source_detail(pid, job['id']) == (body, metadata)
    with pytest.raises(module.MapProjectionError):
        jobs.source_detail(other, job['id'])
    jobs.cancel(pid, job['id'])
    with pytest.raises(module.MapProjectionConflict):
        jobs.source_detail(pid, job['id'])


def test_detail_upgrade_respects_worker_gate_and_does_not_decode_on_cached_reads(setup, monkeypatch):
    from autodrive_console import pcd_projection
    module=jobs_module()
    store,pid,_,source=setup
    real_source(source);jobs=module.MapProjectionJobs(store)
    job=jobs.create(pid,source);wait_state(jobs,pid,job['id'],'awaiting_parameters')
    assert module._WORKER_GATE.acquire(blocking=False)
    try:
        assert jobs.source_detail(pid,job['id']) is None
        assert not jobs._pending_details
    finally:
        module._WORKER_GATE.release()
    assert jobs.source_detail(pid,job['id']) is None
    wait_worker_idle(module)
    before=jobs.source_detail(pid,job['id'])
    monkeypatch.setattr(pcd_projection,'build_source_detail',lambda *args: (_ for _ in ()).throw(AssertionError('cached reads must not decode')))
    assert jobs.source_detail(pid,job['id'])==before


@pytest.mark.parametrize('field,value', [
    ('origin', None), ('bounds', [[0, 1]]), ('source_point_count', None),
    ('finite_point_count', 0), ('attributes', None),
])
def test_detail_cache_rejects_incomplete_metadata_before_http_headers(setup, field, value):
    module = jobs_module()
    store, pid, _, source = setup
    real_source(source)
    jobs = module.MapProjectionJobs(store)
    job = jobs.create(pid, source)
    wait_state(jobs, pid, job['id'], 'awaiting_parameters')
    jobs.source_detail(pid, job['id'])
    wait_worker_idle(module)
    record = jobs._read(pid, job['id'])
    record['analysis']['source_detail'][field] = value
    jobs._save(record)
    with pytest.raises(module.MapProjectionError):
        jobs.source_detail(pid, job['id'])


def test_sampled_detail_cache_rebuilds_full_source_without_reupload(setup):
    from autodrive_console import pcd_projection
    module = jobs_module()
    store, pid, _, source = setup
    real_source(source)
    jobs = module.MapProjectionJobs(store)
    job = jobs.create(pid, source)
    wait_state(jobs, pid, job['id'], 'awaiting_parameters')
    record = jobs._read(pid, job['id'])
    cache = jobs._directory(pid, job['id'])/'source'/'source-detail.bin'
    metadata = pcd_projection.build_source_detail(source, cache)
    metadata['point_count'] = 1
    cache.write_bytes(cache.read_bytes()[:20])
    record['analysis']['source_detail'] = metadata
    jobs._save(record)
    assert jobs.source_detail(pid, job['id']) is None, 'old sampled caches must not be served as full source'
    wait_worker_idle(module)
    body, metadata = jobs.source_detail(pid, job['id'])
    assert metadata['point_count'] == metadata['finite_point_count'] == 3
    assert len(body) == 60
    assert source.read_bytes() == jobs._source(jobs._read(pid, job['id'])).read_bytes()
