"""Compare independent, parallel, and joined compression of co-keyed L2 groups."""

import ctypes as ct
import json
import statistics
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

lib = ct.CDLL("libzstd.so.1")
P, S = ct.c_void_p, ct.c_size_t
lib.ZSTD_compress.argtypes = [P, S, P, S, ct.c_int]
lib.ZSTD_compress.restype = S
lib.ZSTD_decompress.argtypes = [P, S, P, S]
lib.ZSTD_decompress.restype = S
lib.ZSTD_getFrameContentSize.argtypes = [P, S]
lib.ZSTD_getFrameContentSize.restype = ct.c_ulonglong


def pack(x):
    out = ct.create_string_buffer(len(x) * 2)
    n = lib.ZSTD_compress(out, len(out), x, len(x), 1)
    assert n < len(out)
    return out[:n]


groups = defaultdict(dict)
for path in Path("/lmcache").rglob("*.data"):
    stem = path.stem.split("@")
    groups[stem[-1]][int(stem[-2])] = path
results = []


def unpack(x):
    n = lib.ZSTD_getFrameContentSize(x, len(x))
    out = ct.create_string_buffer(n)
    assert lib.ZSTD_decompress(out, n, x, len(x)) == n
    return out.raw


with ThreadPoolExecutor(3) as pool:
    for key, paths in sorted(groups.items()):
        if set(paths) != {0, 1, 2}:
            continue
        # Eight contiguous MiB per object, from the middle, independent of its data content.
        parts = []
        for p in (paths[k] for k in sorted(paths)):
            with p.open("rb") as f:
                f.seek((p.stat().st_size // 2) // 4096 * 4096)
                parts.append(f.read(8 << 20))
        frames = [pack(x) for x in parts]
        raw = b"".join(parts)
        joined = pack(raw)
        times = defaultdict(list)
        cases = dict(
            separate=lambda: [unpack(x) for x in frames],
            parallel=lambda: list(pool.map(unpack, frames)),
            joined=lambda: [unpack(joined)],
            one_separate=lambda: [unpack(frames[1])],
            one_joined=lambda: [
                unpack(joined)[len(parts[0]) : len(parts[0]) + len(parts[1])]
            ],
        )
        for rep in range(6):
            names = list(cases)
            for name in names[rep % len(names) :] + names[: rep % len(names)]:
                start = time.perf_counter()
                result = cases[name]()
                dt = time.perf_counter() - start
                assert b"".join(result) == (
                    parts[1] if name.startswith("one_") else raw
                )
                if rep:
                    times[name].append(dt * 1000)
        results.append(
            dict(
                prefix=key[:12],
                raw_bytes=len(raw),
                separate_bytes=sum(map(len, frames)),
                joined_bytes=len(joined),
                median_ms={k: statistics.median(v) for k, v in times.items()},
            )
        )
print(json.dumps(results, indent=2))
