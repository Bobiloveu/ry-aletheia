import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

import autodrive_console.relocalization_config as module


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    install = tmp_path / 'lightning'
    executable = install / 'lib/lightning/run_loc_online'
    library = install / 'lib/liblightning.libs.so'
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b'verified executable')
    library.write_bytes(b'verified library')
    proc = tmp_path / 'proc'
    process = proc / '2813'
    process.mkdir(parents=True)
    (process / 'exe').symlink_to(executable)
    (process / 'cmdline').write_bytes(str(executable).encode() + b'\0--config\0/private/startup.yaml\0')
    (process / 'environ').write_bytes(b'ROS_DOMAIN_ID=66\0')
    (process / 'stat').write_text('2813 (run_loc_online) ' + ' '.join(['S'] + ['0'] * 18 + ['12345']))
    stat = library.stat()
    (process / 'maps').write_text(f'1000-2000 r-xp 0000 {os.major(stat.st_dev):x}:{os.minor(stat.st_dev):x} {stat.st_ino} {library}\n')
    state = {'version': 'verified.test', 'returncode': 0}
    def package(args, **kwargs):
        assert args[0] == 'dpkg-query' and args[-1] == 'ry-lightning'
        assert 0 < kwargs['timeout'] <= 5
        return SimpleNamespace(returncode=state['returncode'], stdout=state['version'], stderr='')
    monkeypatch.setattr(subprocess, 'run', package)
    monkeypatch.setenv('ROS_DOMAIN_ID', '66')
    monkeypatch.setattr(module, 'PROC_ROOT', proc, raising=False)
    return state, process, executable, library


@pytest.mark.parametrize('version', ['1.6.5+compatible.5', '1.6.5+compatible.7', 'unknown.future'])
def test_current_config_identity_is_independent_of_package_version(runtime, monkeypatch, version):
    state, _process, _executable, _library = runtime
    state['version'] = version
    def no_package_query(*args, **kwargs):
        pytest.fail('manual relocalization must not query or whitelist package versions')
    monkeypatch.setattr(subprocess, 'run', no_package_query)
    assert module.localizer_runtime_identity() == (2813, '12345')


def test_binding_an_instance_accepts_an_unknown_package_version(runtime):
    state, _process, _executable, _library = runtime
    state['version'] = 'unknown.future'
    assert module.localizer_runtime_identity() == (2813, '12345')


@pytest.mark.parametrize('failure', ['wrong_domain', 'multiple_processes', 'no_process'])
def test_instance_binding_still_requires_a_unique_localizer_in_the_ros_domain(runtime, failure):
    _state, process, _executable, _library = runtime
    if failure == 'wrong_domain': (process / 'environ').write_bytes(b'ROS_DOMAIN_ID=67\0')
    elif failure == 'multiple_processes': shutil.copytree(process, process.parent / '2814', symlinks=True)
    else: shutil.rmtree(process)
    with pytest.raises(module.RelocalizationConfigError): module.localizer_runtime_identity()


@pytest.mark.parametrize('change', ['unknown_version', 'package_failure', 'changed_executable', 'changed_library',
                                  'stale_inode', 'deleted_library', 'no_install_tree'])
def test_runtime_binding_does_not_inspect_installed_binary_fingerprints(runtime, change):
    state, process, executable, library = runtime
    if change == 'unknown_version': state['version'] = 'unknown.future'
    elif change == 'package_failure': state['returncode'] = 1
    elif change == 'changed_executable': executable.write_bytes(b'upgraded executable')
    elif change == 'changed_library': library.write_bytes(b'upgraded library')
    elif change == 'stale_inode':
        fields = (process / 'maps').read_text().split()
        fields[4] = str(int(fields[4]) + 1)
        (process / 'maps').write_text(' '.join(fields))
    elif change == 'deleted_library':
        (process / 'maps').write_text((process / 'maps').read_text().strip() + ' (deleted)\n')
    elif change == 'no_install_tree': shutil.rmtree(executable.parents[2])
    assert module.localizer_runtime_identity() == (2813, '12345')


@pytest.mark.parametrize('failure', ['unreadable', 'malformed', 'invalid_domain'])
def test_unreadable_candidate_localizer_cannot_be_ignored_when_proving_uniqueness(runtime, monkeypatch, failure):
    _state, process, _executable, _library = runtime
    second = process.parent / '2814'
    shutil.copytree(process, second, symlinks=True)
    if failure == 'unreadable':
        original = Path.read_bytes
        def read(path):
            if path == second / 'environ': raise PermissionError('private process environment')
            return original(path)
        monkeypatch.setattr(Path, 'read_bytes', read)
    elif failure == 'malformed': (second / 'environ').write_bytes(b'ROS_DOMAIN_ID\0')
    else: (second / 'environ').write_bytes(b'ROS_DOMAIN_ID=invalid\0')
    with pytest.raises(module.RelocalizationConfigError): module.localizer_runtime_identity()


def test_runtime_identity_changes_when_localizer_restarts_even_if_pid_is_reused(runtime):
    _state, process, _executable, _library = runtime
    before = module.localizer_runtime_identity()
    (process / 'stat').write_text('2813 (run_loc_online) ' + ' '.join(['S'] + ['0'] * 18 + ['12346']))
    assert module.localizer_runtime_identity() != before


@pytest.mark.parametrize('change', ['command', 'domain', 'restart', 'second_process'])
def test_runtime_identity_rechecks_evidence_that_changes_during_one_read(runtime, monkeypatch, change):
    _state, process, _executable, _library = runtime
    original = Path.read_bytes
    changed = False
    def read(path):
        nonlocal changed
        value = original(path)
        if path == process / 'environ' and not changed:
            changed = True
            if change == 'command': (process / 'cmdline').write_bytes(b'/usr/bin/other_process\0')
            elif change == 'domain': (process / 'environ').write_bytes(b'ROS_DOMAIN_ID=67\0')
            elif change == 'restart':
                (process / 'stat').write_text('2813 (run_loc_online) ' + ' '.join(['S'] + ['0'] * 18 + ['12346']))
            else: shutil.copytree(process, process.parent / '2814', symlinks=True)
        return value
    monkeypatch.setattr(Path, 'read_bytes', read)
    with pytest.raises(module.RelocalizationConfigError): module.localizer_runtime_identity()


def test_restarting_localizer_in_another_ros_domain_does_not_block_target_instance(runtime, monkeypatch):
    _state, process, _executable, _library = runtime
    other = process.parent / '2814'
    shutil.copytree(process, other, symlinks=True)
    (other / 'environ').write_bytes(b'ROS_DOMAIN_ID=67\0')
    original = Path.read_bytes
    changed = False
    def read(path):
        nonlocal changed
        value = original(path)
        if path == other / 'environ' and not changed:
            changed = True
            (other / 'stat').write_text('2814 (run_loc_online) ' + ' '.join(['S'] + ['0'] * 18 + ['12346']))
        return value
    monkeypatch.setattr(Path, 'read_bytes', read)
    assert module.localizer_runtime_identity() == (2813, '12345')
