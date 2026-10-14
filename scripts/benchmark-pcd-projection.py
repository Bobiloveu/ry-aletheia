#!/usr/bin/env python3
"""Read-only source stress test; all outputs go to a new temporary directory."""
import argparse
import hashlib
import json
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from autodrive_console.pcd_projection import analyze_pcd, project_pcd


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as fp:
        while block := fp.read(1024 * 1024):
            result.update(block)
    return result.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--resolution', type=float, default=.1)
    parser.add_argument('--z-min', type=float)
    parser.add_argument('--z-max', type=float)
    parser.add_argument('--min-points', type=int, default=1)
    parser.add_argument('--denoise', action='store_true')
    parser.add_argument('--iterations', type=int, default=10)
    args = parser.parse_args()
    if not 1 <= args.iterations <= 100:
        parser.error('iterations must be between 1 and 100')
    original = digest(args.source)
    output = Path(tempfile.mkdtemp(prefix='aletheia-pcd-benchmark-'))
    started = time.perf_counter()
    analysis = analyze_pcd(args.source)
    analysis_s = time.perf_counter() - started
    candidate = analysis['candidates'][0] if analysis['candidates'] else None
    low = args.z_min if args.z_min is not None else candidate['z_min'] if candidate else None
    high = args.z_max if args.z_max is not None else candidate['z_max'] if candidate else None
    if low is None or high is None:
        parser.error('no candidate; provide --z-min and --z-max')
    parameters = dict(z_min=low, z_max=high, resolution=args.resolution,
                      min_points=args.min_points, denoise=args.denoise)
    timings, hashes = [], []
    for index in range(args.iterations):
        destination = output / f'round-{index + 1}'
        started = time.perf_counter()
        result = project_pcd(args.source, destination, parameters)
        timings.append(time.perf_counter() - started)
        hashes.append(digest(destination / 'map.pgm'))
        print(json.dumps({'round': index + 1, 'seconds': timings[-1]}, ensure_ascii=False), flush=True)
    report = dict(source=str(args.source.resolve()), source_bytes=args.source.stat().st_size,
                  source_sha256=original, source_unchanged=digest(args.source) == original,
                  points=analysis['point_count'], analysis_seconds=analysis_s, parameters=parameters,
                  width=result['width'], height=result['height'], runs_seconds=timings,
                  median_seconds=statistics.median(timings), pgm_sha256=hashes[0],
                  identical_outputs=len(set(hashes)) == 1, platform=platform.platform(), output=str(output))
    try:
        import resource
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        report['peak_rss_bytes'] = rss if sys.platform == 'darwin' else rss * 1024
    except ImportError:
        pass
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False), flush=True)
    if not report['source_unchanged'] or not report['identical_outputs']:
        raise SystemExit('source changed or output was nondeterministic')


if __name__ == '__main__':
    main()
