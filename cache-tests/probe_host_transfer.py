"""Check LMCache's registered-host-memory transfer path independently."""
import torch
from lmcache.v1.memory_allocators.lazy_memory_allocator import LazyMemoryAllocator
from lmcache.v1.gpu_connector.gpu_ops import lmcache_memcpy_async_d2h, lmcache_memcpy_async_h2d

torch.cuda.init()
allocator = LazyMemoryAllocator(init_size=64*1024**2, final_size=64*1024**2)
obj = allocator.allocate(torch.Size([20*1024**2]), torch.uint8)
assert obj is not None
gpu = torch.full((obj.get_size(),), 37, dtype=torch.uint8, device='cuda')
lmcache_memcpy_async_d2h(gpu, obj)
torch.cuda.synchronize()
assert bool((obj.raw_tensor[:obj.get_size()] == 37).all().item())
gpu.zero_()
lmcache_memcpy_async_h2d(obj, gpu)
torch.cuda.synchronize()
assert bool((gpu == 37).all().item())
allocator.free(obj)
allocator.close()
print('LMCache registered host-memory roundtrip passed', flush=True)
