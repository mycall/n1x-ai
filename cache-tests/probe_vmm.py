"""Check exportable CUDA VMM allocations without loading the model."""
import json
import os
import torch
from cuda.bindings import driver as cu

torch.cuda.init()
records = []
for size in (64 * 1024**2, 4 * 1024**3, 10 * 1024**3):
    prop = cu.CUmemAllocationProp()
    prop.type = cu.CUmemAllocationType.CU_MEM_ALLOCATION_TYPE_PINNED
    prop.location.type = cu.CUmemLocationType.CU_MEM_LOCATION_TYPE_DEVICE
    prop.location.id = 0
    prop.requestedHandleTypes = cu.CUmemAllocationHandleType.CU_MEM_HANDLE_TYPE_POSIX_FILE_DESCRIPTOR
    status, handle = cu.cuMemCreate(size, prop, 0)
    row = {'bytes': size, 'create': str(status)}
    if status == cu.CUresult.CUDA_SUCCESS:
        try:
            result = cu.cuMemExportToShareableHandle(handle, prop.requestedHandleTypes, 0)
            row['export'] = str(result[0])
            if result[0] == cu.CUresult.CUDA_SUCCESS:
                os.close(result[1])
        finally:
            row['release'] = str(cu.cuMemRelease(handle)[0])
    records.append(row)
print(json.dumps(records, indent=2))
