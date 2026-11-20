"""Warm-device O_DIRECT read versus O_DIRECT plus Zstd-1 at one MiB per frame."""

import ctypes as ct
import hashlib
import json
import mmap
import os
import tempfile
import time
from pathlib import Path

lib = ct.CDLL("libzstd.so.1")
P, S = ct.c_void_p, ct.c_size_t
lib.ZSTD_compress.argtypes = [P, S, P, S, ct.c_int]
lib.ZSTD_compress.restype = S
lib.ZSTD_decompress.argtypes = [P, S, P, S]
lib.ZSTD_decompress.restype = S
unit = 1 << 20
files = sorted(
    p
    for p in Path("/lmcache").rglob("*.data")
    if p.is_file() and p.stat().st_size >= unit
)
if not files:
    raise SystemExit("No complete LMCache objects under /lmcache")
with tempfile.TemporaryDirectory(dir="/scratch") as temp:
    base = Path(temp)
    entries = []
    encoded = ct.create_string_buffer(2 * unit)
    expected = hashlib.sha256()
    with (base / "raw").open("wb") as plain, (base / "framed").open("wb") as framed:
        for p in files:
            size = p.stat().st_size
            n = max(1, round(size / (8 * unit)))
            with p.open("rb") as f:
                for i in range(n):
                    f.seek(((2 * i + 1) * (size // unit) // (2 * n)) * unit)
                    buf = f.read(unit)
                    if len(buf) != unit:
                        continue
                    expected.update(buf)
                    plain.write(buf)
                    length = lib.ZSTD_compress(encoded, len(encoded), buf, unit, 1)
                    assert 0 < length < len(encoded)
                    payload = encoded.raw[:length] if length < unit else buf
                    pad = (-len(payload)) % 4096
                    entries.append((framed.tell(), len(payload), len(payload) + pad))
                    framed.write(payload)
                    framed.write(bytes(pad))
        for handle in (plain, framed):
            handle.flush()
            os.fsync(handle.fileno())
    out = ct.create_string_buffer(unit)
    results = []
    for compressed in [False, True, True, False]:
        digest = hashlib.sha256()
        fd = os.open(
            base / ("framed" if compressed else "raw"), os.O_RDONLY | os.O_DIRECT
        )
        aligned = mmap.mmap(-1, unit)
        ptr = ct.addressof(ct.c_char.from_buffer(aligned))
        elapsed = 0
        for i, (offset, length, padded) in enumerate(entries):
            begin = time.perf_counter_ns()
            if compressed:
                read = os.preadv(fd, [memoryview(aligned)[:padded]], offset)
                assert read == padded
                if length < unit:
                    assert lib.ZSTD_decompress(out, unit, ptr, length) == unit
                else:
                    ct.memmove(out, ptr, unit)
            else:
                read = os.preadv(fd, [aligned], i * unit)
                assert read == unit
            elapsed += time.perf_counter_ns() - begin
            digest.update(out if compressed else aligned)
        assert digest.hexdigest() == expected.hexdigest()
        aligned.close()
        os.close(fd)
        results.append(dict(zstd=compressed, ms=elapsed / 1e6))
    print(
        json.dumps(
            dict(
                logical_bytes=len(entries) * unit,
                stored_bytes=(base / "framed").stat().st_size,
                direct_read_runs=results,
            ),
            indent=2,
        )
    )
