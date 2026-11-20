import ctypes as c
import json
import mmap
import os
import struct
from pathlib import Path

import numpy as np

lib = c.CDLL("/trial/hot.so")
raw = c.CDLL("/opt/mbx/lib/libmbx_ple_nvme.so")
for x in (lib, raw):
    x.mbx_t_read.argtypes = [
        c.c_int,
        c.c_void_p,
        c.c_int64,
        c.c_void_p,
        c.c_void_p,
        c.c_int,
        c.c_int,
        c.c_int,
    ]
fd = raw.mbx_t_fd(str(next(Path("/cache/ple-nvme-fp8").glob("map-*"))).encode())
assert fd >= 0
threads = 0 if raw.mbx_t_open(256) == 0 else 32


def fetch(reader, ids):
    out = np.empty((len(ids), 160), "u1")
    rc = reader.mbx_t_read(
        fd, ids.ctypes.data, len(ids), out.ctypes.data, out.ctypes.data, 160, 0, threads
    )
    assert rc == 0, rc
    return out


rng = np.random.default_rng(1120)
seed = rng.integers(320001536, size=64, dtype="i8")
assert np.array_equal(fetch(raw, seed), fetch(lib, seed))
with (
    open("/tmp/ple-trial-%d.stats" % os.getpid(), "r+b") as f,
    mmap.mmap(f.fileno(), 0) as mapped,
):
    struct.pack_into("=QQ", mapped, 0, 1, 1)
    for ids in [
        seed,
        seed[::-1].copy(),
        np.repeat(seed, 2),
        *np.arange(115000, dtype="i8").reshape(23, -1),
        seed,
    ]:
        assert np.array_equal(fetch(raw, ids), fetch(lib, ids))
    epoch, enabled, calls, rows, hits, issued, ns, resident = struct.unpack_from(
        "=8Q", mapped
    )
    assert resident == (16 << 20) // 160 and hits >= 192 and calls > issued
    struct.pack_into("=QQ", mapped, 0, 2, 1)
    assert np.array_equal(fetch(raw, seed), fetch(lib, seed))
    assert struct.unpack_from("=8Q", mapped)[7] == len(set(seed))
    print(
        json.dumps(
            dict(
                byte_parity=True,
                eviction_checked=True,
                reset_checked=True,
                rows=rows,
                hits=hits,
                capacity_rows=resident,
                capacity_payload_bytes=resident * 160,
            )
        )
    )
