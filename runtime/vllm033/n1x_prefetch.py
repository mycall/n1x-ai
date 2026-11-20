"""Stream-ordered PLE row gather for eager execution and full decode graphs."""
import ctypes as ct
from pathlib import Path

import torch

from n1x_w4 import ExternalEmbedding


class Gather(ct.Structure):
    _fields_ = [(name, ct.c_void_p) for name in ("shards", "ids", "output", "valid")] + [
        (name, ct.c_int64) for name in ("count", "rows", "rows_per_shard", "width")
    ]


class PrefetchedEmbedding(ExternalEmbedding):
    supports_prefetch = True

    def __init__(self, rows, width, *, max_total_tokens, num_ngram_heads, **kwargs):
        super().__init__(rows, width, **kwargs)
        self.heads = num_ngram_heads
        capacity = max_total_tokens * self.heads
        self.host_ids = torch.empty(capacity, device="cpu", dtype=torch.long, pin_memory=True)
        self.host_rows = torch.empty((capacity, width), device="cpu", dtype=torch.uint8, pin_memory=True)
        self.host_valid = torch.empty((), device="cpu", dtype=torch.int32, pin_memory=True)
        self.device_rows = torch.empty_like(self.host_rows, device="cuda")
        self.valid = torch.empty_like(self.host_valid, device="cuda")
        self.stream = torch.cuda.Stream()
        self.shard_ptrs = (ct.c_void_p * len(self.shards))(*(s.ctypes.data for s in self.shards))
        self.tasks = {}
        self.submit = ct.CDLL(str(Path(__file__).with_name("libn1x_ple.so"))).submit_gather
        self.submit.argtypes = [ct.c_void_p, ct.POINTER(Gather)]
        self.submit.restype = ct.c_int

    def start_prefetch(self, ids):
        count = ids.numel()
        if ids.ndim != 2 or ids.shape[1] != self.heads or count > self.host_ids.numel() or ids.dtype != torch.long:
            raise ValueError(f"Unexpected PLE input {ids.shape} {ids.dtype}")
        if count not in self.tasks:
            self.tasks[count] = Gather(
                ct.addressof(self.shard_ptrs), self.host_ids.data_ptr(), self.host_rows.data_ptr(),
                self.host_valid.data_ptr(), count, self.org_vocab_size, self.rows_per_shard, self.width,
            )
        self.stream.wait_stream(torch.cuda.current_stream())
        with torch.cuda.stream(self.stream):
            self.host_ids[:count].copy_(ids.reshape(-1), non_blocking=True)
            ids.record_stream(self.stream)
            status = self.submit(self.stream.cuda_stream, ct.byref(self.tasks[count]))
            if status:
                raise RuntimeError(f"cudaLaunchHostFunc failed with CUDA status {status}")
            self.device_rows[:count].copy_(self.host_rows[:count], non_blocking=True)
            self.valid.copy_(self.host_valid, non_blocking=True)

    def finalize_prefetch(self, total_tokens):
        torch.cuda.current_stream().wait_stream(self.stream)
        torch._assert_async(self.valid != 0, "Invalid external PLE row")
        return self.device_rows[:total_tokens * self.heads].view(torch.float8_e4m3fn).reshape(
            total_tokens, self.heads * self.width
        )
