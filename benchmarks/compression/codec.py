"""Paired copy-free codec timings on identical contiguous SSD-cache samples."""

import ctypes as ct
import json
import time
from pathlib import Path

zstd = ct.CDLL("libzstd.so.1")
P, S = ct.c_void_p, ct.c_size_t
zstd.ZSTD_compress.argtypes = [P, S, P, S, ct.c_int]
zstd.ZSTD_compress.restype = S
zstd.ZSTD_decompress.argtypes = [P, S, P, S]
zstd.ZSTD_decompress.restype = S
lz4 = ct.CDLL("liblz4.so.1")
lz4.LZ4_compress_default.argtypes = [P, P, ct.c_int, ct.c_int]
lz4.LZ4_decompress_safe.argtypes = lz4.LZ4_compress_default.argtypes


def measure(data, codec, chunk, stats):
    # Already allocated fixed buffers, same source bytes for all arms.
    dest = ct.create_string_buffer(chunk + chunk // 16 + 512)
    decoded = ct.create_string_buffer(chunk)
    for offset in range(0, len(data), chunk):
        block = data[offset : offset + chunk]
        start = time.perf_counter_ns()
        if codec == "lz4":
            n = lz4.LZ4_compress_default(block, dest, len(block), len(dest))
        else:
            n = zstd.ZSTD_compress(dest, len(dest), block, len(block), 1)
        middle = time.perf_counter_ns()
        assert 0 < n <= len(dest)
        if n < len(block):
            if codec == "lz4":
                written = lz4.LZ4_decompress_safe(dest, decoded, n, len(block))
            else:
                written = zstd.ZSTD_decompress(decoded, len(block), dest, n)
        else:
            # Verbatim fallback includes copying to a consumer-owned output buffer.
            ct.memmove(decoded, block, len(block))
            written = len(block)
        end = time.perf_counter_ns()
        assert written == len(block) and decoded.raw == block
        stats[0] += len(block)
        stats[1] += min(n, len(block))
        stats[2] += middle - start
        stats[3] += end - middle


arms = {
    (codec, chunk): [0, 0, 0, 0]
    for codec in ["lz4", "zstd1"]
    for chunk in [4096, 65536, 1048576]
}
for file in sorted(Path("/lmcache").rglob("*.data")):
    if not file.is_file():
        continue
    size = file.stat().st_size
    n = max(1, round(size / (8 << 20)))
    with file.open("rb") as f:
        for i in range(n):
            f.seek(((2 * i + 1) * (size >> 20) // (2 * n)) << 20)
            data = f.read(1 << 20)
            if len(data) != (1 << 20):
                continue
            for (codec, chunk), stats in arms.items():
                measure(data, codec, chunk, stats)
if not any(v[0] for v in arms.values()):
    raise SystemExit("No complete object samples under /lmcache")
print(
    json.dumps(
        [
            dict(
                codec=c,
                bytes_per_block=k,
                sample_bytes=v[0],
                stored_bytes=v[1],
                savings=1 - v[1] / v[0],
                encode_MiB_s=v[0] / 2**20 / (v[2] / 1e9),
                restore_MiB_s=v[0] / 2**20 / (v[3] / 1e9),
            )
            for (c, k), v in arms.items()
        ],
        indent=2,
    )
)
