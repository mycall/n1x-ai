"""Small CUDA/WSLC compatibility check; does not load model weights."""
import json
import importlib.metadata

print('Importing PyTorch...', flush=True)
import torch

assert torch.cuda.is_available(), 'CUDA is unavailable'
print('CUDA detected; checking BF16 matrix multiplication...', flush=True)
device = torch.cuda.get_device_properties(0)
x = torch.ones((32, 32), device='cuda', dtype=torch.bfloat16)
assert (x @ x).float().mean().item() == 32.0
print('Checking pinned host transfers...', flush=True)
host = torch.arange(16, dtype=torch.float32, pin_memory=True)
assert torch.equal(host.cuda().cpu(), host)
from vllm.utils.torch_utils import get_accelerator_view_from_cpu_tensor

print('Checking mapped host memory used by the PLE adapter...', flush=True)
mapped = get_accelerator_view_from_cpu_tensor(host)
assert torch.equal(mapped.clone().cpu(), host)
torch.cuda.synchronize()
free, total = torch.cuda.mem_get_info()
print(json.dumps({
    'torch': torch.__version__, 'vllm': importlib.metadata.version('vllm'),
    'cuda_runtime': torch.version.cuda, 'gpu': device.name,
    'capability': list(torch.cuda.get_device_capability()),
    'free_gib': round(free / 2**30, 2), 'total_gib': round(total / 2**30, 2),
    'bf16_matmul': 'pass', 'pinned_host_mapping': 'pass',
}, indent=2))
