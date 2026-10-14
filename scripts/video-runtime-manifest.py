#!/usr/bin/env python3
"""Assemble a locked ELF closure and fingerprint it without loading any library."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


# These are the supported Ubuntu 22.04 system ABI. NVIDIA's CUDA/NVENC driver
# libraries are dlopened by nvcodec and deliberately remain vehicle-owned.
SYSTEM_ABI = {'libc.so.6', 'libm.so.6', 'libdl.so.2', 'librt.so.1', 'libpthread.so.0',
              'libresolv.so.2', 'ld-linux-x86-64.so.2', 'libstdc++.so.6', 'libgcc_s.so.1'}


def assemble(extracted: Path, runtime: Path, lockfile: Path, builder: Path) -> None:
    libraries: dict[str, Path] = {}
    for directory in (extracted / 'usr/lib/x86_64-linux-gnu', extracted / 'lib/x86_64-linux-gnu'):
        if directory.is_dir():
            libraries.update({path.name: path for path in directory.glob('*.so*') if path.is_file()})
    pending = [path for directory in ('plugins', 'drivers', 'libexec', 'bin')
               for path in (runtime / directory).iterdir() if path.is_file() and path.read_bytes()[:4] == b'\x7fELF']
    seen: set[str] = set()
    while pending:
        path = pending.pop()
        if path.name in seen:
            continue
        seen.add(path.name)
        dynamic = subprocess.check_output(['readelf', '-d', str(path)], text=True)
        for soname in re.findall(r'NEEDED.*\[([^]]+)\]', dynamic):
            if soname in SYSTEM_ABI or soname in seen:
                continue
            source = libraries.get(soname)
            if source is None:
                raise RuntimeError(f'Locked video runtime has an unresolved ELF dependency: {path.name} -> {soname}')
            actual = source.resolve()
            if not actual.is_relative_to(extracted.resolve()):
                raise RuntimeError(f'Archive library escapes extracted runtime: {source}')
            destination = runtime / 'lib' / actual.name
            if not destination.exists():
                shutil.copy2(actual, destination)
            link = runtime / 'lib' / soname
            if soname != actual.name and not link.exists():
                link.symlink_to(actual.name)
            pending.append(link)
    files = {str(path.relative_to(runtime)): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in sorted(runtime.rglob('*')) if path.is_file() and path.name != 'ry-aletheia-runtime.json'}
    fingerprint = hashlib.sha256(lockfile.read_bytes() + builder.read_bytes() + Path(__file__).read_bytes() +
                                 json.dumps(files, sort_keys=True).encode()).hexdigest()
    marker = {'schema': 'ry-aletheia-video-runtime/v1', 'mediamtx_version': '1.19.2',
              'plugins': ['coreelements', 'rawparse', 'videoconvert', 'videoscale', 'videotestsrc',
                          'videoparsersbad', 'rtspclientsink', 'vaapi', 'nvcodec', 'app', 'tcp', 'udp', 'rtp', 'rtpmanager'],
              'content_sha256': fingerprint, 'required_files': sorted(files), 'file_sha256': files,
              'executable_files': sorted(name for name in files if name.startswith(('bin/', 'libexec/')) or name == 'mediamtx/mediamtx'),
              'system_abi': sorted(SYSTEM_ABI),
              'vehicle_driver_libraries': ['libcuda.so.1', 'libnvidia-encode.so.1']}
    (runtime / 'ry-aletheia-runtime.json').write_text(json.dumps(marker, indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    assemble(*(Path(value) for value in sys.argv[1:]))
