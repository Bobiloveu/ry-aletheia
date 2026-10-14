"""Build and inspect private runtime artifacts without executing media/GPU code."""
import hashlib
import json
import os
import re
import subprocess
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_contains_nvenc_and_closes_dependencies_and_hashes_contents(tmp_path):
    if not all(shutil.which(name) for name in ('dpkg-deb', 'readelf', 'apt-get', 'bash')):
        pytest.skip('私有视频 runtime 构建验证需要 Linux 发布工具链')
    cache = ROOT / '.cache/offline-deps/video-runtime'
    for line in (ROOT / 'tools/video-runtime-packages.lock').read_text().splitlines():
        if not line or line.startswith('#'):
            continue
        package, version, _ = line.split('\t')
        if not (cache / f'{package}_{version}_amd64.deb').is_file():
            pytest.skip('先运行 build_video_runtime.sh 下载锁定发布依赖；普通 Backend 测试不隐式下载')
    runtime = tmp_path / 'runtime'
    subprocess.run([str(ROOT / 'build_video_runtime.sh'), '--output-dir', str(runtime)],
                   cwd=ROOT, check=True, capture_output=True, timeout=180)
    for name in ('libgstnvcodec.so', 'libgstvideoscale.so', 'libgstvideotestsrc.so'):
        assert (runtime / 'plugins' / name).is_file()
    marker = json.loads((runtime / 'ry-aletheia-runtime.json').read_text())
    assert len(marker['content_sha256']) == 64
    assert 'bin/gst-inspect-1.0' in marker['executable_files']
    assert marker['file_sha256']['bin/gst-launch-1.0'] == hashlib.sha256((runtime / 'bin/gst-launch-1.0').read_bytes()).hexdigest()
    host_abi = {'libc.so.6', 'libm.so.6', 'libdl.so.2', 'librt.so.1', 'libpthread.so.0',
                'libresolv.so.2', 'ld-linux-x86-64.so.2', 'libstdc++.so.6', 'libgcc_s.so.1'}
    for directory in ('plugins', 'lib', 'drivers', 'libexec'):
        for path in (runtime / directory).iterdir():
            if not path.is_file() or path.is_symlink():
                continue
            result = subprocess.run(['readelf', '-d', str(path)], check=True, capture_output=True, text=True)
            for soname in re.findall(r'NEEDED.*\[([^]]+)\]', result.stdout):
                assert soname in host_abi or (runtime / 'lib' / soname).is_file(), (path.name, soname)
    # Invoke only the wrapper with a fake executable; never load GST/VAAPI/CUDA.
    binary = runtime / 'bin/gst-launch-1.0.real'
    binary.write_text('#!/bin/sh\nprintf "%s|%s|%s|%s" "$GST_PLUGIN_PATH_1_0" "$GST_PLUGIN_PATH" "$LD_LIBRARY_PATH" "$GST_PLUGIN_SCANNER_1_0"\n')
    binary.chmod(0o755)
    env = dict(os.environ, GST_PLUGIN_PATH_1_0='/foreign/abi', GST_PLUGIN_PATH='/foreign/abi', GST_PLUGIN_SCANNER_1_0='/foreign/scanner')
    output = subprocess.check_output([str(runtime / 'bin/gst-launch-1.0')], env=env, text=True)
    assert output == '||' + str(runtime / 'lib') + '|' + str(runtime / 'libexec/gst-plugin-scanner')
