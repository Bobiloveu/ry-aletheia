import hashlib
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
    monkeypatch.setattr(module, 'INSTALL_ROOT', install, raising=False)
    monkeypatch.setattr(module, 'PROC_ROOT', proc, raising=False)
    monkeypatch.setattr(module, 'VERIFIED_BUILDS', {'verified.test': (
        hashlib.sha256(b'verified executable').hexdigest(), hashlib.sha256(b'verified library').hexdigest())}, raising=False)
    return state, process, executable, library


def test_current_config_reuse_requires_a_verified_running_build(runtime):
    result = module.verify_current_config_runtime()
    assert result == (2813, '12345')


def test_binding_an_instance_does_not_require_empty_path_capability(runtime):
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


@pytest.mark.parametrize('failure', ['unknown_version', 'package_failure', 'changed_executable', 'changed_library',
                                    'stale_inode', 'deleted_library', 'wrong_domain', 'multiple_processes', 'no_process'])
def test_current_config_reuse_refuses_unverified_or_stale_runtime(runtime, failure):
    state, process, executable, library = runtime
    if failure == 'unknown_version': state['version'] = 'unknown.future'
    elif failure == 'package_failure': state['returncode'] = 1
    elif failure == 'changed_executable': executable.write_bytes(b'unverified executable')
    elif failure == 'changed_library': library.write_bytes(b'unverified library')
    elif failure == 'stale_inode':
        fields = (process / 'maps').read_text().split()
        fields[4] = str(int(fields[4]) + 1)
        (process / 'maps').write_text(' '.join(fields))
    elif failure == 'deleted_library':
        (process / 'maps').write_text((process / 'maps').read_text().strip() + ' (deleted)\n')
    elif failure == 'wrong_domain': (process / 'environ').write_bytes(b'ROS_DOMAIN_ID=67\0')
    elif failure == 'multiple_processes': shutil.copytree(process, process.parent / '2814', symlinks=True)
    elif failure == 'no_process': shutil.rmtree(process)
    with pytest.raises(module.RelocalizationConfigError): module.verify_current_config_runtime()


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
    with pytest.raises(module.RelocalizationConfigError): module.verify_current_config_runtime()


def test_atomic_package_replacement_cannot_verify_an_unknown_running_binary(runtime, monkeypatch):
    _state, process, executable, library = runtime
    executable.write_bytes(b'unknown running executable')
    library.write_bytes(b'unknown running library')
    pinned = executable.with_name('pinned-running-executable')
    os.link(executable, pinned)
    (process / 'exe').unlink()
    (process / 'exe').symlink_to(pinned)
    original = module._digest
    replaced = [False]
    def replace_then_hash(value):
        if not replaced[0]:
            replaced[0] = True
            for path, data in [(executable, b'verified executable'), (library, b'verified library')]:
                new = path.with_name(path.name + '.new')
                new.write_bytes(data)
                os.replace(new, path)
        return original(value)
    monkeypatch.setattr(module, '_digest', replace_then_hash)
    with pytest.raises(module.RelocalizationConfigError): module.verify_current_config_runtime()
