#!/usr/bin/env python3
"""Benchmark a disposable project copy, without changing site or robot data.

pixi run --frozen --no-install python scripts/benchmark-task-preview.py deployments/1
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from autodrive_console.deployment import DeploymentStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project_directory', type=Path)
    args = parser.parse_args()
    source = args.project_directory.resolve()
    original = (source/'site-project.json').read_bytes()
    document = json.loads(original)
    with tempfile.TemporaryDirectory(prefix='ry-preview-benchmark-') as temporary:
        root = Path(temporary)
        target = root/document['id']
        shutil.copytree(source, target, ignore=shutil.ignore_patterns('exports'))
        for asset in document['map_assets']:
            asset['source_yaml'] = str(target/Path(asset['source_yaml']).relative_to(source))
        document['task_compiler']['identity']['last_preview_input_sha256'] = None
        (target/'site-project.json').write_text(json.dumps(document), encoding='utf-8')
        store = DeploymentStore(root)
        compiles = 0
        compile_preview = store._compile_task_preview

        def counted(*args):
            nonlocal compiles
            compiles += 1
            return compile_preview(*args)

        store._compile_task_preview = counted
        timings = {}

        def measure(name, operation):
            start = time.perf_counter()
            result = operation()
            timings[name] = round((time.perf_counter()-start)*1000, 3)
            return result

        preview = measure('coldMs', lambda: store.task_compiler_preview(document['id']))
        for index in range(5):
            repeated = measure(f'reopen{index+1}Ms', lambda: store.task_compiler_preview(document['id']))
            assert repeated == preview, 'Unchanged publication differed'
        measure('downloadMs', lambda: store.task_compiler_bundle(document['id']))
        restarted = DeploymentStore(root)

        def unexpected_compile(*args):
            raise AssertionError('Store recreation missed persistent preview cache')

        restarted._compile_task_preview = unexpected_compile
        assert measure('newStoreMs', lambda: restarted.task_compiler_preview(document['id'])) == preview
        assert compiles == 1, f'Compiled unchanged input {compiles} times'
        assert (source/'site-project.json').read_bytes() == original, 'Source project changed'
        print(json.dumps({**timings, 'compiles': compiles,
                          'input_sha256': preview['input_sha256'],
                          'sourceDocumentSha256': hashlib.sha256(original).hexdigest(),
                          'artifactCount': len(preview['artifacts'])}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
