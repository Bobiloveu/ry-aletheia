"""Persisted, project-owned offline point-cloud projection sessions.

Only one analysis/projection may run in the backend process. Busy requests are
rejected instead of accumulating uploads in an unbounded executor queue.
Cancellation prevents adoption; it does not start another CPU-heavy operation
until the current operation has actually returned.
"""
from __future__ import annotations

import copy
import json
import logging
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import time
import uuid

from .deployment import DeploymentError, DeploymentStore

LOGGER = logging.getLogger('ry_aletheia.map_projection_jobs')


class MapProjectionError(ValueError):
    pass


class MapProjectionConflict(MapProjectionError):
    pass


_WORKER_GATE = threading.BoundedSemaphore(1)
_STATE_LOCK = threading.RLock()
_JOB_ID = re.compile(r'projection-[a-f0-9]{32}\Z')
_PUBLIC_FIELDS = (
    'id', 'project_id', 'state', 'progress', 'message', 'revision',
    'analysis', 'parameters', 'result', 'map_asset_id',
)


def _analyze(source, preview_output):
    from .pcd_projection import analyze_pcd
    return analyze_pcd(source, preview_output=preview_output)


def _project(source, output, parameters, *, on_progress=None):
    from .pcd_projection import project_pcd
    return project_pcd(source, output, parameters, on_progress=on_progress)


class MapProjectionJobs:
    def __init__(self, store: DeploymentStore, *, analyzer=None, projector=None):
        self.store = store
        self._analyzer = analyzer or _analyze
        self._projector = projector or _project
        self._pending_details = set()
        # An unfinished record belongs to an earlier process. Reading the disk
        # on adoption also prevents an earlier worker from reviving that record.
        with _STATE_LOCK:
            for project in self.store.list_projects():
                for job in self._records(project['id']):
                    if job['state'] in {'analyzing', 'processing'}:
                        job.update(state='interrupted', progress=0,
                                   message='处理已中断，请重新生成预览。', result=None)
                        self._save(job)
                        LOGGER.warning('Projection interrupted project=%s job=%s revision=%s',
                                       job['project_id'], job['id'], job['revision'])
                    self._prune_outputs(job)

    def _root(self, project_id):
        if not isinstance(project_id, str):
            raise MapProjectionError('部署项目标识无效')
        try:
            self.store.get(project_id)
            project = self.store._project_dir(project_id).resolve()
        except (DeploymentError, OSError) as exc:
            raise MapProjectionError('部署项目不存在或标识无效') from exc
        if not project.is_relative_to(self.store.root.resolve()):
            raise MapProjectionError('部署项目路径无效')
        root = project / '.projections'
        if not root.resolve().is_relative_to(project):
            raise MapProjectionError('投影会话路径无效')
        return root

    def _directory(self, project_id, job_id):
        if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
            raise MapProjectionError('投影会话标识无效')
        root = self._root(project_id)
        directory = root / job_id
        if not directory.resolve().is_relative_to(root.resolve()):
            raise MapProjectionError('投影会话路径无效')
        return directory

    def _read(self, project_id, job_id):
        directory = self._directory(project_id, job_id)
        path = directory / 'session.json'
        if not path.resolve().is_relative_to(directory.resolve()):
            raise MapProjectionError('投影会话路径无效')
        try:
            job = json.loads(path.read_text(encoding='utf-8'))
            if (not isinstance(job, dict) or job.get('id') != job_id
                    or job.get('project_id') != project_id
                    or any(field not in job for field in _PUBLIC_FIELDS)):
                raise ValueError('invalid session')
            return job
        except (OSError, ValueError) as exc:
            raise MapProjectionError('投影会话不存在或已损坏') from exc

    def _save(self, job):
        self.store._write_json(
            self._directory(job['project_id'], job['id']) / 'session.json', job)

    def _prune_outputs(self, job):
        """Discard only regenerable previews; original PCDs are never pruned."""
        directory = self._directory(job['project_id'], job['id'])
        keep = f"revision-{job['revision']}" if job['state'] in {'ready', 'imported'} else None
        for child in directory.iterdir():
            if child.name == keep or child.is_symlink():
                continue
            if re.fullmatch(r'revision-[0-9]+', child.name) or child.name.startswith('.preview-'):
                if child.is_dir() and child.resolve().is_relative_to(directory.resolve()):
                    shutil.rmtree(child, ignore_errors=True)

    def _records(self, project_id):
        root = self._root(project_id)
        if not root.is_dir():
            return []
        records = []
        for directory in root.iterdir():
            if _JOB_ID.fullmatch(directory.name) and directory.is_dir():
                try:
                    records.append(self._read(project_id, directory.name))
                except MapProjectionError:
                    continue
        return records

    @staticmethod
    def _snapshot(job):
        return copy.deepcopy({key: job[key] for key in _PUBLIC_FIELDS})

    def get(self, project_id, job_id):
        with _STATE_LOCK:
            return self._snapshot(self._read(project_id, job_id))

    def latest(self, project_id):
        with _STATE_LOCK:
            records = self._records(project_id)
            return self._snapshot(max(records, key=lambda job: job['_created_ns'])) if records else None

    @staticmethod
    def _reserve():
        if not _WORKER_GATE.acquire(blocking=False):
            raise MapProjectionConflict('已有点云正在处理，请稍后重试。')

    def create(self, project_id, source: Path):
        with _STATE_LOCK:
            self._root(project_id)
            source = Path(source)
            if source.suffix.lower() != '.pcd' or not source.is_file():
                raise MapProjectionError('请选择有效的 PCD 文件。')
            self._reserve()
            directory = None
            try:
                job_id = f'projection-{uuid.uuid4().hex}'
                directory = self._directory(project_id, job_id)
                source_dir = directory / 'source'
                source_dir.mkdir(parents=True)
                stem = re.sub(r'[^\w.-]', '_', source.stem).strip('.')[:150] or 'cloud'
                filename = stem + '.pcd'
                saved_source = source_dir / filename
                shutil.copyfile(source, saved_source)
                job = dict(id=job_id, project_id=project_id, state='analyzing',
                           progress=0, message='正在分析点云高度分布。', revision=0,
                           analysis=None, parameters=None, result=None, map_asset_id=None,
                           _created_ns=time.time_ns(), _source_filename=filename,
                           _source_sha256=self.store._sha256(saved_source),
                           _source_bytes=saved_source.stat().st_size)
                self._save(job)
                snapshot = self._snapshot(job)
                self._start(job)
                return snapshot
            except Exception:
                if directory is not None:
                    shutil.rmtree(directory, ignore_errors=True)
                _WORKER_GATE.release()
                raise

    @staticmethod
    def _parameters(parameters):
        expected = {'z_min', 'z_max', 'resolution', 'min_points', 'denoise'}
        if not isinstance(parameters, dict) or set(parameters) != expected:
            raise MapProjectionError('请填写完整的高度、分辨率和去噪参数。')
        result = dict(parameters)
        for key in ('z_min', 'z_max', 'resolution'):
            value = result[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise MapProjectionError('高度和分辨率必须为有限数值。')
            try:
                result[key] = float(value)
            except OverflowError as exc:
                raise MapProjectionError('高度和分辨率必须为有限数值。') from exc
            if not math.isfinite(result[key]):
                raise MapProjectionError('高度和分辨率必须为有限数值。')
        if result['z_min'] >= result['z_max'] or result['resolution'] <= 0:
            raise MapProjectionError('高度下限必须小于上限，分辨率必须大于零。')
        if type(result['min_points']) is not int or not 1 <= result['min_points'] <= 10_000_000 or type(result['denoise']) is not bool:
            raise MapProjectionError('去噪参数无效。')
        return result

    def preview(self, project_id, job_id, parameters):
        parameters = self._parameters(parameters)
        with _STATE_LOCK:
            job = self._read(project_id, job_id)
            if job['state'] in {'analyzing', 'processing', 'cancelled', 'imported'}:
                raise MapProjectionConflict('当前会话无法生成预览。')
            self._reserve()
            try:
                job.update(state='processing', progress=0, message='正在生成二维地图预览。',
                           revision=job['revision'] + 1, parameters=parameters, result=None)
                job.pop('_import_intent', None)
                self._save(job)
                self._prune_outputs(job)
                snapshot = self._snapshot(job)
                self._start(job)
                return snapshot
            except Exception:
                _WORKER_GATE.release()
                raise

    def trajectory_preview(self, project_id, job_id, source):
        """Parse a temporary overlay under the existing bound; never mutate a map."""
        from .pcd_projection import trajectory_preview
        with _STATE_LOCK:
            job = self._read(project_id, job_id)
            if not job['analysis'] or job['state'] in {'cancelled', 'imported'}:
                raise MapProjectionConflict('当前会话无法读取轨迹预览。')
            self._reserve()
        try:
            result = trajectory_preview(Path(source))
            with _STATE_LOCK:
                current = self._read(project_id, job_id)
                if current['state'] in {'cancelled', 'imported'}:
                    raise MapProjectionConflict('当前会话已结束，轨迹预览未采用。')
            return result
        finally:
            _WORKER_GATE.release()

    def _source(self, job):
        filename = job.get('_source_filename')
        if not isinstance(filename, str) or Path(filename).name != filename or not filename.endswith('.pcd'):
            raise MapProjectionError('原始点云文件记录无效。')
        directory = self._directory(job['project_id'], job['id'])
        source = directory / 'source' / filename
        if not source.resolve().is_relative_to(directory.resolve()) or not source.is_file():
            raise MapProjectionError('原始点云文件不存在。')
        return source

    def _start(self, job):
        threading.Thread(target=self._run, args=(copy.deepcopy(job),),
                         name='map-projection', daemon=True).start()

    def _current(self, original):
        current = self._read(original['project_id'], original['id'])
        return current if (current['state'] == original['state']
                           and current['revision'] == original['revision']) else None

    def _progress(self, original, value, message):
        # Use the same revision/state fence as result adoption. Cancelled work
        # may still finish computing but can never revive its status or output.
        with _STATE_LOCK:
            job = self._current(original)
            if job is not None and job['progress'] < value < 100:
                job.update(progress=value, message=message)
                self._save(job)

    def _run(self, original):
        LOGGER.info('Projection started project=%s job=%s revision=%s phase=%s',
                    original['project_id'], original['id'], original['revision'], original['state'])
        temporary = None
        result = None
        failure = None
        try:
            source = self._source(original)
            if original['state'] == 'analyzing':
                # Existing injected analyzers intentionally retain their one-arg
                # interface; only the native analyzer creates the display cache.
                result = (self._analyzer(source, source.parent / 'source-preview.bin')
                          if self._analyzer is _analyze else self._analyzer(source))
            else:
                directory = self._directory(original['project_id'], original['id'])
                temporary = Path(tempfile.mkdtemp(prefix='.preview-', dir=directory))
                result = (self._projector(source, temporary, original['parameters'],
                          on_progress=lambda value, message: self._progress(original, value, message))
                          if self._projector is _project else
                          self._projector(source, temporary, original['parameters']))
                for name in ('map.yaml', 'map.pgm'):
                    path = temporary / name
                    if not path.is_file() or not path.resolve().is_relative_to(temporary.resolve()):
                        raise MapProjectionError('预览输出不完整。')
        except Exception as exc:
            failure = exc
        # Release the worker gate under the same lock that exposes the terminal
        # snapshot, so observing "ready" always permits the next operation.
        with _STATE_LOCK:
            try:
                job = self._current(original)
                if job is not None:
                    try:
                        if failure is not None:
                            raise failure
                        if original['state'] == 'analyzing':
                            job.update(state='awaiting_parameters', analysis=result, progress=100,
                                       message='高度分析完成，请检查并调整投影范围。')
                        else:
                            destination = self._directory(job['project_id'], job['id']) / f"revision-{job['revision']}"
                            os.replace(temporary, destination)
                            temporary = None
                            job.update(state='ready', result=result, progress=100,
                                       message='预览已生成，请检查门洞与通道后确认导入。')
                        self._save(job)
                        self._prune_outputs(job)
                        LOGGER.info('Projection succeeded project=%s job=%s revision=%s state=%s',
                                    job['project_id'], job['id'], job['revision'], job['state'])
                    except Exception as exc:
                        LOGGER.exception('Projection failed project=%s job=%s revision=%s phase=%s',
                                         original['project_id'], original['id'], original['revision'], original['state'])
                        # Unexpected filesystem/parser errors can contain absolute
                        # server paths. Only plain domain validation reaches UI.
                        message = str(exc) if isinstance(exc, ValueError) else ''
                        if not message or '/' in message or chr(92) in message:
                            message = '点云处理失败，请检查文件与参数后重试。'
                        job.update(state='failed', progress=0, message=message[:240], result=None)
                        self._save(job)
                else:
                    LOGGER.info('Projection result discarded project=%s job=%s revision=%s',
                                original['project_id'], original['id'], original['revision'])
            except (MapProjectionError, OSError):
                LOGGER.warning('Projection result unavailable project=%s job=%s revision=%s',
                               original['project_id'], original['id'], original['revision'], exc_info=True)
                pass  # The project may have been deleted while processing.
            finally:
                if temporary is not None:
                    shutil.rmtree(temporary, ignore_errors=True)
                _WORKER_GATE.release()

    @staticmethod
    def _revision(job, revision):
        if type(revision) is not int or revision < 1:
            raise MapProjectionError('预览版本无效。')
        if revision != job['revision']:
            raise MapProjectionConflict('参数或预览已更新，请使用当前预览。')

    def preview_path(self, project_id, job_id, revision):
        with _STATE_LOCK:
            job = self._read(project_id, job_id)
            self._revision(job, revision)
            if job['state'] not in {'ready', 'imported'}:
                raise MapProjectionConflict('当前预览尚未完成或已失效。')
            directory = self._directory(project_id, job_id)
            path = directory / f'revision-{revision}' / 'map.pgm'
            if not path.is_file() or not path.resolve().is_relative_to(directory.resolve()):
                raise MapProjectionError('预览文件不存在。')
            return path

    def source_detail(self, project_id, job_id):
        """Read a full finite cloud cache, upgrading legacy sampled caches in the background."""
        with _STATE_LOCK:
            job = self._read(project_id, job_id)
            if job['state'] in {'analyzing', 'cancelled'}:
                raise MapProjectionConflict('当前点云分析尚未完成或已失效。')
            if not isinstance(job.get('analysis'), dict):
                raise MapProjectionError('点云分析未完成，请重新上传 PCD。')
            metadata = job['analysis'].get('source_detail')
            sampled = (isinstance(metadata, dict)
                       and type(metadata.get('point_count')) is int
                       and type(metadata.get('finite_point_count')) is int
                       and 1 <= metadata['point_count'] < metadata['finite_point_count'] <= 10_000_000)
            if metadata is None or sampled:
                if job.get('_source_detail_error'):
                    raise MapProjectionError(job['_source_detail_error'])
                key = (project_id, job_id)
                if key not in self._pending_details and _WORKER_GATE.acquire(blocking=False):
                    try:
                        source = self._source(job)
                        self._pending_details.add(key)
                        threading.Thread(target=self._build_detail, args=(key, source),
                                         name='point-cloud-detail', daemon=True).start()
                    except Exception:
                        self._pending_details.discard(key)
                        _WORKER_GATE.release()
                        raise
                return None
            if (not isinstance(metadata, dict) or metadata.get('format') != 'xyz-rgba-intensity-v1'
                    or type(metadata.get('point_count')) is not int
                    or not 1 <= metadata['point_count'] <= 10_000_000):
                raise MapProjectionError('精细点云缓存无效，请重新上传 PCD。')
            count, total, finite = (metadata.get(key) for key in
                                   ('point_count', 'source_point_count', 'finite_point_count'))
            def finite_number(value):
                try:
                    return type(value) in (int, float) and math.isfinite(value)
                except OverflowError:
                    return False
            def valid_bounds(value):
                return (isinstance(value, list) and len(value) == 3
                        and all(isinstance(pair, list) and len(pair) == 2
                                and all(map(finite_number, pair)) and pair[0] <= pair[1]
                                for pair in value))
            origin, bounds, attributes = (metadata.get(key) for key in ('origin', 'bounds', 'attributes'))
            if (any(type(value) is not int for value in (total, finite))
                    or not count == finite <= total <= 10_000_000
                    or not isinstance(origin, list) or len(origin) != 3
                    or not all(map(finite_number, origin)) or not valid_bounds(bounds)
                    or not isinstance(attributes, dict)):
                raise MapProjectionError('精细点云缓存无效，请重新上传 PCD。')
            display = attributes.get('display_bounds')
            intensity = attributes.get('intensity_range')
            if (type(attributes.get('rgb')) is not bool or type(attributes.get('intensity')) is not bool
                    or not valid_bounds(display)
                    or any(a[0] < b[0] or a[1] > b[1] for a, b in zip(display, bounds))
                    or (intensity is not None and (not isinstance(intensity, list) or len(intensity) != 2
                        or not all(map(finite_number, intensity)) or intensity[0] > intensity[1]))):
                raise MapProjectionError('精细点云缓存无效，请重新上传 PCD。')
            directory = self._directory(project_id, job_id)
            path = directory / 'source' / 'source-detail.bin'
            if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()):
                raise MapProjectionError('精细点云缓存路径无效。')
            try:
                if path.stat().st_size != metadata['point_count'] * 20:
                    raise MapProjectionError('精细点云缓存不完整，请重新上传 PCD。')
                with path.open('rb') as fp:
                    body = fp.read(200_000_001)
                if len(body) != metadata['point_count'] * 20:
                    raise MapProjectionError('精细点云缓存不完整，请重新上传 PCD。')
                json.dumps(metadata, allow_nan=False)
            except (OSError, ValueError) as exc:
                raise MapProjectionError('精细点云缓存无法读取，请重新上传 PCD。') from exc
            return body, copy.deepcopy(metadata)

    def _build_detail(self, key, source):
        LOGGER.info('Projection detail started project=%s job=%s', *key)
        result, error = None, None
        try:
            from .pcd_projection import build_source_detail
            result = build_source_detail(source, source.parent / 'source-detail.bin')
        except Exception:
            LOGGER.exception('Projection detail failed project=%s job=%s', *key)
            error = '精细点云生成失败，请检查原始 PCD 后重新上传。'
        with _STATE_LOCK:
            try:
                job = self._read(*key)
                if job['state'] != 'cancelled':
                    if error:
                        job['_source_detail_error'] = error
                    else:
                        job['analysis']['source_detail'] = result
                    self._save(job)
                    if error is None:
                        LOGGER.info('Projection detail succeeded project=%s job=%s', *key)
                else:
                    LOGGER.info('Projection detail discarded project=%s job=%s', *key)
            except (MapProjectionError, OSError):
                LOGGER.warning('Projection detail result unavailable project=%s job=%s', *key, exc_info=True)
                pass
            finally:
                self._pending_details.discard(key)
                _WORKER_GATE.release()

    def source_preview(self, project_id, job_id):
        """Return a bounded adopted display cache; never decode PCD on reads."""
        with _STATE_LOCK:
            job = self._read(project_id, job_id)
            if job['state'] not in {'awaiting_parameters', 'processing', 'ready', 'imported', 'interrupted', 'failed'}:
                raise MapProjectionConflict('当前会话的点云分析尚未完成或已失效。')
            unavailable = '三维点云样本不可用，请重新上传 PCD。'
            analysis = job.get('analysis')
            metadata = analysis.get('source_preview') if isinstance(analysis, dict) else None
            if not isinstance(metadata, dict):
                raise MapProjectionError(unavailable)
            count, total, finite = (metadata.get(key) for key in
                                    ('point_count', 'source_point_count', 'finite_point_count'))
            if (any(type(value) is not int for value in (count, total, finite))
                    or not 1 <= count <= 100_000 or not count == finite <= total <= 10_000_000):
                raise MapProjectionError(unavailable)
            origin, bounds = metadata.get('origin'), metadata.get('bounds')
            def finite_number(value):
                try:
                    return type(value) in (int, float) and math.isfinite(value)
                except OverflowError:
                    return False
            if (not isinstance(origin, list) or len(origin) != 3 or not all(map(finite_number, origin))
                    or not isinstance(bounds, list) or len(bounds) != 3
                    or any(not isinstance(pair, list) or len(pair) != 2
                           or not all(map(finite_number, pair)) or pair[0] > pair[1] for pair in bounds)):
                raise MapProjectionError(unavailable)
            directory = self._directory(project_id, job_id)
            source_dir = directory / 'source'
            path = source_dir / 'source-preview.bin'
            if (not source_dir.resolve().is_relative_to(directory.resolve())
                    or path.is_symlink() or not path.is_file()
                    or not path.resolve().is_relative_to(source_dir.resolve())):
                raise MapProjectionError(unavailable)
            try:
                with path.open('rb') as fp:
                    body = fp.read(100_000 * 12 + 1)
            except OSError as exc:
                raise MapProjectionError(unavailable) from exc
            if len(body) != count * 12:
                raise MapProjectionError(unavailable)
            return body, copy.deepcopy(metadata)

    def confirm(self, project_id, job_id, label, revision):
        if not isinstance(label, str) or not 1 <= len(label.strip()) <= 80:
            raise MapProjectionError('地图名称应为 1 至 80 个字符。')
        with _STATE_LOCK:
            job = self._read(project_id, job_id)
            self._revision(job, revision)
            if job['state'] == 'imported':
                asset = next((asset for asset in self.store.get(project_id)['map_assets']
                              if asset['id'] == job['map_asset_id']), None)
                if asset is None:
                    raise MapProjectionError('已导入地图不存在。')
                return asset
            self.preview_path(project_id, job_id, revision)
            directory = self._directory(project_id, job_id)
            generated = directory / f'revision-{revision}'
            source = self._source(job)
            pointcloud = generated / source.name
            if not pointcloud.exists():
                # The immutable input lives on the same filesystem. Avoid one
                # full PCD copy per preview; the importer makes the final copy.
                os.link(source, pointcloud)
            expected = f"map-{self.store._sha256(generated / 'map.yaml')[:12]}"
            asset = None
            orphan_backup = None
            if job.get('_import_intent') == expected:
                existing = next((item for item in self.store.get(project_id)['map_assets']
                                 if item['id'] == expected), None)
                if existing is not None:
                    snapshot = self.store._project_dir(project_id) / 'maps' / expected
                    for name in ('map.yaml', 'map.pgm', source.name):
                        stored = snapshot / name
                        if (not stored.is_file() or stored.is_symlink()
                                or self.store._sha256(stored) != self.store._sha256(generated / name)):
                            raise MapProjectionConflict('已保存地图与当前预览不一致，请重新生成预览。')
                    asset = existing
                else:
                    # Recover a copied snapshot left before project metadata
                    # was committed, retaining it until the retry succeeds.
                    orphan = self.store._project_dir(project_id) / 'maps' / expected
                    if orphan.exists():
                        if orphan.is_symlink() or not orphan.is_dir():
                            raise MapProjectionConflict('地图快照路径异常，请检查后重试。')
                        orphan_backup = directory / f'.import-recovery-{uuid.uuid4().hex}'
                        os.replace(orphan, orphan_backup)
            if asset is None:
                # Persist intent BEFORE changing the project document. A retry
                # can then reconcile an import that survived a process crash.
                job['_import_intent'] = expected
                self._save(job)
            try:
                if asset is None:
                    asset = self.store.import_uploaded_map(
                        project_id, generated / 'map.yaml', label.strip(), 'custom', directory)
            except (ValueError, OSError) as exc:
                LOGGER.warning('Projection import failed project=%s job=%s revision=%s',
                               project_id, job_id, revision, exc_info=True)
                job['message'] = '地图导入失败，预览已保留，请重试。'
                self._save(job)
                raise MapProjectionError(job['message']) from exc
            job.update(state='imported', map_asset_id=asset['id'], progress=100,
                       message='地图已导入，可以继续配置部署。')
            self._save(job)
            if orphan_backup is not None:
                shutil.rmtree(orphan_backup, ignore_errors=True)
            LOGGER.info('Projection imported project=%s job=%s revision=%s asset=%s',
                        project_id, job_id, revision, asset['id'])
            return asset

    def cancel(self, project_id, job_id):
        with _STATE_LOCK:
            job = self._read(project_id, job_id)
            if job['state'] == 'imported':
                raise MapProjectionConflict('已导入的地图无法取消。')
            job.update(state='cancelled', progress=0, message='已取消处理，原始点云已保留。', result=None)
            self._save(job)
            LOGGER.info('Projection cancelled project=%s job=%s revision=%s',
                        project_id, job_id, job['revision'])
            # A running worker removes its own temporary directory when it
            # notices cancellation; do not delete beneath its open files here.
            for child in self._directory(project_id, job_id).glob('revision-*'):
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child, ignore_errors=True)
            return self._snapshot(job)
