"""Measure cache-related host RSS above a matched stock-reader pass."""

import ctypes as c
import json
import mmap
import os
import struct
from pathlib import Path

import numpy as np

lib = c.CDLL("/trial/hot.so")
lib.mbx_t_read.argtypes = [
    c.c_int,
    c.c_void_p,
    c.c_int64,
    c.c_void_p,
    c.c_void_p,
    c.c_int,
    c.c_int,
    c.c_int,
]
fd = lib.mbx_t_fd(str(next(Path("/cache/ple-nvme-fp8").glob("map-*"))).encode())
assert fd >= 0
nt = 0 if lib.mbx_t_open(256) == 0 else 32
ids = np.arange(140000, dtype="i8")
buf = np.empty((4096, 160), "u1")


def run():
    for i in range(0, len(ids), len(buf)):
        chunk = ids[i : i + len(buf)]
        rc = lib.mbx_t_read(
            fd,
            chunk.ctypes.data,
            len(chunk),
            buf.ctypes.data,
            buf.ctypes.data,
            160,
            0,
            nt,
        )
        assert rc == 0, rc


def rss():
    c.CDLL(None).malloc_trim(0)
    return (
        int(Path("/proc/self/status").read_text().split("VmRSS:")[1].split()[0]) * 1024
    )


run()
before = rss()
with (
    open("/tmp/ple-trial-%d.stats" % os.getpid(), "r+b") as f,
    mmap.mmap(f.fileno(), 0) as m,
):
    struct.pack_into("=QQ", m, 0, 1, 1)
    run()
    resident = struct.unpack_from("=8Q", m)[7]
after = rss()
print(
    json.dumps(
        dict(
            off_rss_bytes=before,
            on_rss_bytes=after,
            delta_bytes=after - before,
            payload_bytes=resident * 160,
        )
    )
)
