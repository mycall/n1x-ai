"""Experimental FD-exportable allocation for the KV pool only."""
import cupy
import torch
import os
import uuid
from cuda.bindings import driver as cu

_export_ids = {}

def export_id_for(base):
    # Only deduplicate allocations owned here. A fresh allocation at a reused
    # virtual address receives a fresh identity, even if old exports survive.
    return _export_ids.get(base, os.getpid().to_bytes(4, 'big') + uuid.uuid4().bytes[4:])

def checked(result):
    if result[0] != cu.CUresult.CUDA_SUCCESS:
        raise RuntimeError(str(result[0]))
    return result[1] if len(result) == 2 else result[1:]

class Allocation:
    def __init__(self, size, device):
        self.ptr = self.handle = None
        self.device = device
        prop = cu.CUmemAllocationProp()
        prop.type = cu.CUmemAllocationType.CU_MEM_ALLOCATION_TYPE_PINNED
        prop.location.type = cu.CUmemLocationType.CU_MEM_LOCATION_TYPE_DEVICE
        prop.location.id = device
        prop.requestedHandleTypes = cu.CUmemAllocationHandleType.CU_MEM_HANDLE_TYPE_POSIX_FILE_DESCRIPTOR
        granularity = checked(cu.cuMemGetAllocationGranularity(prop, cu.CUmemAllocationGranularity_flags.CU_MEM_ALLOC_GRANULARITY_MINIMUM))
        self.size = ((size + granularity - 1) // granularity) * granularity
        self.handle = checked(cu.cuMemCreate(self.size, prop, 0))
        self.ptr = checked(cu.cuMemAddressReserve(self.size, 0, 0, 0))
        checked(cu.cuMemMap(self.ptr, self.size, 0, self.handle, 0))
        access = cu.CUmemAccessDesc()
        access.location = prop.location
        access.flags = cu.CUmemAccess_flags.CU_MEM_ACCESS_FLAGS_PROT_READWRITE
        checked(cu.cuMemSetAccess(self.ptr, self.size, [access], 1))
        _export_ids[int(self.ptr)] = os.getpid().to_bytes(4, 'big') + uuid.uuid4().bytes[4:]

    def __del__(self):
        try:
            with torch.cuda.device(self.device):
                if self.ptr is not None:
                    _export_ids.pop(int(self.ptr), None)
                    cu.cuMemUnmap(self.ptr, self.size)
                    cu.cuMemAddressFree(self.ptr, self.size)
                if self.handle is not None:
                    cu.cuMemRelease(self.handle)
        except Exception:
            pass  # CUDA may already be shut down at process exit.

def zeros(size, device):
    device = torch.device(device)
    index = device.index if device.index is not None else torch.cuda.current_device()
    with torch.cuda.device(index), cupy.cuda.Device(index):
        # Explicitly bind a CUDA context before driver calls.
        torch.cuda.init()
        cupy.cuda.runtime.setDevice(index)
        # Vision profiling can leave unused blocks in PyTorch's private pool.
        # VMM allocates through the driver and cannot reuse those cached blocks.
        torch.cuda.empty_cache()
        free, total = torch.cuda.mem_get_info(index)
        print(f'VMM KV allocation: requested={size} free={free} total={total}', flush=True)
        owner = Allocation(size, index)
        memory = cupy.cuda.UnownedMemory(int(owner.ptr), owner.size, owner)
        array = cupy.ndarray((size,), dtype=cupy.int8, memptr=cupy.cuda.MemoryPointer(memory, 0))
        tensor = torch.from_dlpack(array)
        tensor.zero_()
        return tensor
