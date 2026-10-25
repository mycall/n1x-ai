"""Bounded filesystem probes. Run with inference stopped, via system-probe.ps1."""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import random
import shutil
import statistics
import time


def read_probe(path, kind, workers, advise_drop):
    fd = os.open(path, os.O_RDONLY)
    advice = 'not requested'
    try:
        if advise_drop:
            try:
                os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
                advice = 'DONTNEED accepted; host/device caches uncontrolled'
            except OSError as exc:
                advice = repr(exc)
        if kind == 'sequential':
            size = 1024 * 1024
            offsets = list(range(0, min(os.fstat(fd).st_size - size, 512 * size), size))
        else:
            size = 4096
            rng = random.Random(42)
            offsets = [rng.randrange(os.fstat(fd).st_size // size) * size for _ in range(4096)]
        def read(offset):
            start = time.perf_counter()
            data = os.pread(fd, size, offset)
            if len(data) != size:
                raise RuntimeError('Short read')
            return time.perf_counter() - start
        started = time.perf_counter()
        if workers == 1:
            latencies = [read(offset) for offset in offsets]
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                latencies = list(pool.map(read, offsets))
        elapsed = time.perf_counter() - started
        ordered = sorted(latencies)
        return dict(path=str(path), kind=kind, workers=workers, cacheAdvice=advice,
                    blockBytes=size, reads=len(offsets), seconds=elapsed,
                    MiBPerSecond=len(offsets)*size/1024**2/elapsed,
                    medianReadMicroseconds=statistics.median(latencies)*1e6,
                    p95ReadMicroseconds=ordered[int(.95*(len(ordered)-1))]*1e6)
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--scratch', type=Path, required=True)
    args = parser.parse_args()
    args.scratch.mkdir(parents=True, exist_ok=False)
    native = args.scratch / 'storage-fixture.safetensors'
    start = time.perf_counter()
    shutil.copyfile(args.source, native)
    with native.open('rb') as stream:
        os.fsync(stream.fileno())
    copy_seconds = time.perf_counter()-start
    report = dict(source=str(args.source), fixtureBytes=native.stat().st_size,
                  copySeconds=copy_seconds,
                  cpuInfo=Path('/proc/cpuinfo').read_text(),
                  memInfo=Path('/proc/meminfo').read_text(),
                  mounts=Path('/proc/mounts').read_text(),
                  cpuAffinity=sorted(os.sched_getaffinity(0)),
                  limitations='One table file; bounded pread workload, not a full PLE workload or raw SSD benchmark. DONTNEED only advises guest cache eviction; Windows/device caches remain uncontrolled. Python scheduling overhead is included. Copy is a benchmark fixture, not a serving-model replacement.',
                  results=[])
    def save():
        (args.scratch/'results.json').write_text(json.dumps(report,indent=2))
    save()
    # Alternate the paths to reduce a systematic order advantage.
    for kind, workers in [('sequential',1), ('random',1), ('random',8)]:
        for pass_number in (1,2):
            paths = (args.source,native) if pass_number == 1 else (native,args.source)
            for path in paths:
                result = read_probe(path,kind,workers,advise_drop=(pass_number==1))
                result['pass'] = pass_number
                result['location'] = 'windows-bind' if path == args.source else 'linux-volume'
                report['results'].append(result)
                save()
                print(json.dumps(result),flush=True)
    print('Saved '+str(args.scratch/'results.json'),flush=True)


if __name__ == '__main__':
    main()
