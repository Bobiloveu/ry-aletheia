"""Real files and inherited append handles exercise log ownership boundaries."""
import os
import logging
import subprocess
import sys
import time
from pathlib import Path

import pytest

from autodrive_console.tool_logging import ToolLogStore, _ManagedRotatingHandler

MIB = 1024 * 1024


def store_at(tmp_path):
    store = ToolLogStore(tmp_path / 'logs', policy_path=tmp_path / 'config' / 'tool_logging.json')
    store.directory.mkdir()
    return store


def identity(store, name):
    return next(r['file_id'] for r in store.diagnostic_records() if r['name'] == name)


def test_clear_keeps_the_existing_append_descriptor_and_new_events(tmp_path):
    store = store_at(tmp_path)
    target = store.directory / 'video-runtime.log'
    with target.open('ab', buffering=0) as producer:
        producer.write(b'old output\n')
        inode = os.fstat(producer.fileno()).st_ino
        result = store.clear_file(target.name, identity(store, target.name))
        producer.write(b'new output\n')
        assert result['freed_bytes'] == 11
        assert target.stat().st_ino == inode
        assert target.read_bytes() == b'new output\n'


def test_gigabyte_raw_log_retains_only_bounded_tail_without_replacing_inode(tmp_path, monkeypatch):
    store = store_at(tmp_path)
    store.save_policy({'retention_days': 7, 'max_total_mib': 256, 'max_file_mib': 2})
    target = store.directory / 'video-runtime.log'
    with target.open('ab', buffering=0) as producer:
        producer.truncate(1536 * MIB)
        producer.write(b'last diagnostic\n')
        inode = target.stat().st_ino
        # Maintenance must never allocate the complete legacy log.
        with monkeypatch.context() as context:
            context.setattr(Path, 'read_bytes', lambda self: pytest.fail('whole-file read in maintenance'))
            result = store.cleanup()
        producer.write(b'after rotation\n')
        assert target.stat().st_ino == inode
        assert target.read_bytes() == b'after rotation\n'
        archive = store.directory / 'video-runtime.log.1'
        assert archive.stat().st_size <= 2 * MIB
        assert archive.read_bytes().endswith(b'last diagnostic\n')
        assert result['freed_bytes'] > 1530 * MIB


def test_age_and_capacity_cleanup_touch_only_whitelisted_history(tmp_path):
    store = store_at(tmp_path)
    store.save_policy({'retention_days': 7, 'max_total_mib': 128, 'max_file_mib': 16})
    now = time.time()
    for name in ['video-runtime.log.1', 'live_preprocessor_cloud.log.2']:
        path = store.directory / name
        path.write_bytes(b'expired')
        os.utime(path, (now - 8 * 86400, now - 8 * 86400))
    unknown = store.directory / 'customer-notes.log'
    unknown.write_text('keep')
    current = store.directory / 'ry-aletheia-error.log'
    current.write_text('old error still available')
    os.utime(current, (now - 30 * 86400, now - 30 * 86400))
    store.cleanup()
    assert not (store.directory / 'video-runtime.log.1').exists()
    assert not (store.directory / 'live_preprocessor_cloud.log.2').exists()
    assert current.read_text() == 'old error still available'
    assert unknown.read_text() == 'keep'


def test_global_budget_removes_oldest_archives_before_current_logs(tmp_path):
    store = store_at(tmp_path)
    store.save_policy({'retention_days': 7, 'max_total_mib': 128, 'max_file_mib': 16})
    for index, name in enumerate(ToolLogStore.SIDECAR_NAMES):
        for suffix in ['', '.1', '.2']:
            path = store.directory / (name + suffix)
            with path.open('wb') as f:
                f.truncate(16 * MIB)
            stamp = time.time() - (100 + index if suffix else 0)
            os.utime(path, (stamp, stamp))
    store.cleanup()
    assert store.storage_status()['total_size_bytes'] <= 128 * MIB
    assert all((store.directory / name).exists() for name in ToolLogStore.SIDECAR_NAMES)


def test_download_lease_defers_rotation_and_prevents_clear(tmp_path):
    store = store_at(tmp_path)
    store.save_policy({'retention_days': 7, 'max_total_mib': 256, 'max_file_mib': 2})
    target = store.directory / 'video-runtime.log'
    target.write_bytes(b'x' * (3 * MIB))
    with store.open_diagnostic(target.name) as (stream, size):
        assert size == 3 * MIB
        with pytest.raises(ValueError, match='下载'):
            store.clear_file(target.name, identity(store, target.name))
        store.cleanup()
        assert target.stat().st_size == 3 * MIB
        assert stream.read(4) == b'xxxx'
    store.cleanup()
    assert target.stat().st_size == 0


def test_mutation_rejects_replaced_archive_and_active_file_deletion(tmp_path):
    store = store_at(tmp_path)
    target = store.directory / 'video-runtime.log.1'
    target.write_text('original')
    old_id = identity(store, target.name)
    replacement = store.directory / 'replacement'
    replacement.write_text('new archive')
    replacement.replace(target)
    with pytest.raises(ValueError, match='更新'):
        store.delete_file(target.name, old_id)
    assert target.read_text() == 'new archive'
    current = store.directory / 'video-runtime.log'
    current.write_text('active')
    with pytest.raises(ValueError, match='清空'):
        store.delete_file(current.name, identity(store, current.name))
    assert current.read_text() == 'active'


def test_management_never_follows_symlinks_or_unlisted_paths(tmp_path):
    store = store_at(tmp_path)
    outside = tmp_path / 'private.txt'
    outside.write_text('private')
    (store.directory / 'video-runtime.log').symlink_to(outside)
    (store.directory / 'video-runtime.log.1').symlink_to(outside)
    assert store.diagnostic_file('video-runtime.log') is None
    assert store.diagnostic_records() == []
    for name in ['../private.txt', 'video-runtime.log.1', 'video-runtime.log']:
        with pytest.raises(ValueError):
            store.clear_file(name, 'invalid')
        with pytest.raises(ValueError):
            store.delete_file(name, 'invalid')
    store.cleanup(history=True)
    assert outside.read_text() == 'private'


def test_delete_history_does_not_rotate_or_clear_an_oversized_current_file(tmp_path):
    store = store_at(tmp_path)
    store.save_policy({'retention_days': 7, 'max_total_mib': 256, 'max_file_mib': 2})
    current = store.directory / 'video-runtime.log'
    current.write_bytes(b'x' * (3 * MIB))
    archive = store.directory / 'video-runtime.log.1'
    archive.write_text('history')
    store.cleanup(history=True)
    assert current.stat().st_size == 3 * MIB
    assert not archive.exists()


@pytest.mark.parametrize('changes', [
    {'retention_days': 0}, {'retention_days': True}, {'max_file_mib': 33},
    {'max_total_mib': 127}, {'max_file_mib': 32, 'max_total_mib': 128}, {'unknown': 1},
])
def test_bad_policy_does_not_replace_last_valid_policy(tmp_path, changes):
    store = store_at(tmp_path)
    valid = {'retention_days': 7, 'max_total_mib': 256, 'max_file_mib': 16}
    store.save_policy(valid)
    with pytest.raises(ValueError):
        store.save_policy({**valid, **changes})
    assert store.storage_status()['policy'] == valid
    assert ToolLogStore(store.directory, policy_path=store.policy_path).storage_status()['policy'] == valid


def test_background_maintenance_rotates_and_stops_without_process_control(tmp_path):
    store = store_at(tmp_path)
    store.save_policy({'retention_days': 7, 'max_total_mib': 256, 'max_file_mib': 2})
    target = store.directory / 'video-runtime.log'
    target.write_bytes(b'x' * (3 * MIB))
    store.start_maintenance(interval=.01)
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and target.stat().st_size:
            time.sleep(.01)
        assert target.stat().st_size == 0
    finally:
        store.stop_maintenance()
    assert not store._maintenance_thread.is_alive()


def test_second_writer_reopens_current_inode_after_other_writer_rotation(tmp_path):
    first = store_at(tmp_path)
    second = ToolLogStore(first.directory)
    path = first.file()
    a = _ManagedRotatingHandler(first, path, maxBytes=2 * MIB, backupCount=3, encoding='utf-8')
    b = _ManagedRotatingHandler(second, path, maxBytes=2 * MIB, backupCount=3, encoding='utf-8')
    try:
        a.emit(logging.makeLogRecord({'msg': 'first', 'levelno': logging.INFO}))
        b.doRollover()
        a.emit(logging.makeLogRecord({'msg': 'after other writer rotated', 'levelno': logging.INFO}))
        assert 'after other writer rotated' in path.read_text()
        second.cleanup(history=True)
        a.emit(logging.makeLogRecord({'msg': 'still visible', 'levelno': logging.INFO}))
        assert os.fstat(a.stream.fileno()).st_nlink == 1
        assert 'still visible' in path.read_text()
    finally:
        a.close()
        b.close()


@pytest.mark.skipif(os.name == 'nt', reason='production cross-process leases use POSIX flock')
def test_download_lease_is_honoured_by_a_second_real_process(tmp_path):
    store = store_at(tmp_path)
    path = store.directory / 'video-runtime.log'
    path.write_text('download content')
    selected = identity(store, path.name)
    script = '''
import sys
from pathlib import Path
from autodrive_console.tool_logging import ToolLogStore
store=ToolLogStore(Path(sys.argv[1]))
try:
 store.clear_file('video-runtime.log', sys.argv[2])
 print('cleared')
except ValueError as error:
 print(str(error))
'''
    with store.open_diagnostic(path.name) as (source, size):
        child = subprocess.run([sys.executable, '-c', script, str(store.directory), selected], capture_output=True, text=True, timeout=3)
        assert child.returncode == 0, child.stderr
        assert '下载' in child.stdout
        assert source.read(size) == b'download content'


def test_another_store_cannot_rotate_json_log_while_family_is_downloading(tmp_path):
    first = store_at(tmp_path)
    path = first.file()
    handler = _ManagedRotatingHandler(ToolLogStore(first.directory), path, maxBytes=2 * MIB, backupCount=3, encoding='utf-8')
    try:
        handler.emit(logging.makeLogRecord({'msg': 'snapshot', 'levelno': logging.INFO}))
        with first.open_diagnostic(path.name):
            inode = path.stat().st_ino
            handler.doRollover()
            assert path.stat().st_ino == inode
        handler.doRollover()
        assert path.stat().st_ino != inode
    finally:
        handler.close()


def test_listing_and_cleanup_tolerate_an_archive_rotated_between_scan_and_stat(tmp_path, monkeypatch):
    store = store_at(tmp_path)
    archive = store.directory / 'ry-aletheia.log.1'
    archive.write_text('other process can rotate this')
    original = store.diagnostic_files
    def changing_scan():
        files = original()
        archive.unlink(missing_ok=True)
        return files
    monkeypatch.setattr(store, 'diagnostic_files', changing_scan)
    assert store.storage_status()['total_size_bytes'] == 0
    archive.write_text('another archive')
    assert store.cleanup()['removed_count'] == 0


@pytest.mark.skipif(os.name == 'nt', reason='POSIX FIFO protection')
def test_json_handler_rejects_non_regular_files_without_waiting_for_fifo_reader(tmp_path):
    store = store_at(tmp_path)
    os.mkfifo(store.file())
    # Run in a child so a faulty blocking open fails within a bounded timeout.
    script = '''
import sys
from pathlib import Path
from autodrive_console.tool_logging import ToolLogStore, _ManagedRotatingHandler
s=ToolLogStore(Path(sys.argv[1]))
try:
 _ManagedRotatingHandler(s, s.file(), encoding='utf-8')
except (OSError, ValueError):
 print('rejected')
'''
    child = subprocess.run([sys.executable, '-c', script, str(store.directory)], capture_output=True, text=True, timeout=2)
    assert child.returncode == 0, child.stderr
    assert child.stdout.strip() == 'rejected'


def test_corrupt_policy_pauses_automatic_deletion_until_explicitly_resaved(tmp_path):
    store = store_at(tmp_path)
    archive = store.directory / 'video-runtime.log.1'
    archive.write_text('retain evidence while settings are unreadable')
    os.utime(archive, (0, 0))
    store.policy_path.parent.mkdir()
    store.policy_path.write_text('{broken json')
    recovered = ToolLogStore(store.directory, policy_path=store.policy_path)
    assert recovered.storage_status()['last_error']
    with pytest.raises(ValueError, match='暂停'):
        recovered.cleanup()
    assert archive.exists()
    recovered.save_policy(ToolLogStore.DEFAULT_POLICY)
    recovered.cleanup()
    assert not archive.exists()
    assert recovered.storage_status()['last_error'] is None
