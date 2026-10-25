"""Bounded FP16 GEMM load, separate from serving performance measurements."""
import argparse
import json
import time

import torch

parser = argparse.ArgumentParser()
parser.add_argument("--seconds", type=int, choices=range(5, 61), default=30)
args = parser.parse_args()
torch.cuda.set_device(0)
free, total = torch.cuda.mem_get_info()
if free < 1024**3:
    raise RuntimeError("Need at least 1 GiB of free CUDA memory for this probe")
n = 8192
torch.manual_seed(42)
a = torch.randn((n, n), device="cuda", dtype=torch.float16) * 0.01
b = torch.randn_like(a) * 0.01
c = torch.empty_like(a)
stream = torch.cuda.Stream()
stream.wait_stream(torch.cuda.current_stream())
with torch.cuda.stream(stream):
    for _ in range(5):
        torch.mm(a, b, out=c)
torch.cuda.current_stream().wait_stream(stream)
torch.cuda.synchronize()
graph = torch.cuda.CUDAGraph()
with torch.cuda.graph(graph):
    for _ in range(8):
        torch.mm(a, b, out=c)
for _ in range(3):
    graph.replay()
torch.cuda.synchronize()
print("Starting bounded dense FP16 compute load", flush=True)
start = time.perf_counter()
iterations = 0
while time.perf_counter() - start < args.seconds:
    graph.replay()
    torch.cuda.synchronize()
    iterations += 8
elapsed = time.perf_counter() - start
finite = bool(torch.isfinite(c).all().item())
print(json.dumps({
    "workload": "8192x8192 FP16 GEMM, CUDA graph of eight operations",
    "device": torch.cuda.get_device_name(0),
    "elapsedSeconds": elapsed,
    "matrixMultiplications": iterations,
    "estimatedDenseTflops": 2 * n**3 * iterations / elapsed / 1e12,
    "peakAllocatedMiB": torch.cuda.max_memory_allocated() / 1024**2,
    "finiteOutput": finite,
    "scope": "Compute-load sanity check; not vLLM throughput or a numerical accuracy qualification",
}), flush=True)
if not finite:
    raise RuntimeError("Non-finite GEMM output")
