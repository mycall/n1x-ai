"""Experimental multi-handle VMM pool with a contiguous virtual address range."""
import os
import uuid
import weakref

import torch
from cuda.bindings import driver as cu
from n1x_vmm import checked
from n1x_vmm_ipc import publish, resolve, withdraw

POOLS = weakref.WeakValueDictionary()
SEGMENT_BYTES = 2 * 1024**3


def identity():
    return os.getpid().to_bytes(4, 'big') + uuid.uuid4().bytes[4:]


def access_range(ptr, size, device):
    access = cu.CUmemAccessDesc()
    access.location.type = cu.CUmemLocationType.CU_MEM_LOCATION_TYPE_DEVICE
    access.location.id = device
    access.flags = cu.CUmemAccess_flags.CU_MEM_ACCESS_FLAGS_PROT_READWRITE
    checked(cu.cuMemSetAccess(ptr, size, [access], 1))


def release_mapping(ptr, size, segments):
    offset = 0
    for length, handle in segments:
        cu.cuMemUnmap(ptr + offset, length)
        cu.cuMemRelease(handle)
        offset += length
    cu.cuMemAddressFree(ptr, size)


class SegmentedAllocation:
    def __init__(self, size, device):
        self.device, self.ptr = device, None
        self.segments = []
        self.export_id = identity()
        prop = cu.CUmemAllocationProp()
        prop.type = cu.CUmemAllocationType.CU_MEM_ALLOCATION_TYPE_PINNED
        prop.location.type = cu.CUmemLocationType.CU_MEM_LOCATION_TYPE_DEVICE
        prop.location.id = device
        prop.requestedHandleTypes = cu.CUmemAllocationHandleType.CU_MEM_HANDLE_TYPE_POSIX_FILE_DESCRIPTOR
        granularity = checked(cu.cuMemGetAllocationGranularity(prop, cu.CUmemAllocationGranularity_flags.CU_MEM_ALLOC_GRANULARITY_MINIMUM))
        self.size = ((size + granularity - 1) // granularity) * granularity
        segment_max = (SEGMENT_BYTES // granularity) * granularity
        self.ptr = int(checked(cu.cuMemAddressReserve(self.size, 0, 0, 0)))
        offset = 0
        try:
            while offset < self.size:
                length = min(segment_max, self.size - offset)
                handle = checked(cu.cuMemCreate(length, prop, 0))
                try:
                    checked(cu.cuMemMap(self.ptr + offset, length, 0, handle, 0))
                except RuntimeError:
                    cu.cuMemRelease(handle)
                    raise
                self.segments.append((length, handle))
                access_range(self.ptr + offset, length, device)
                offset += length
        except RuntimeError:
            self.close()
            raise
        self.segment_ids = [identity() for _ in self.segments]
        POOLS[self.ptr] = self
        print(f'Segmented VMM pool: bytes={self.size} segments={len(self.segments)}', flush=True)

    def close(self):
        if self.ptr is not None:
            POOLS.pop(self.ptr, None)
            release_mapping(self.ptr, self.size, self.segments)
            self.ptr = None
            self.segments = []

    def __del__(self):
        try:
            with torch.cuda.device(self.device):
                self.close()
        except (RuntimeError, AttributeError):
            pass


def initialize_wrapper(wrapper, tensor):
    ptr = tensor.data_ptr()
    pool = next((p for base, p in list(POOLS.items()) if base <= ptr < base + p.size), None)
    if pool is None:
        return False
    span = (1 + sum((n-1)*s for n, s in zip(tensor.shape, tensor.stride()))) * tensor.element_size()
    offset = ptr - pool.ptr
    if offset + span > pool.size:
        raise ValueError('View exceeds segmented pool')
    fds = []
    try:
        with torch.cuda.device(tensor.device):
            for segment_id, (size, handle) in zip(pool.segment_ids, pool.segments):
                fd = int(checked(cu.cuMemExportToShareableHandle(handle, cu.CUmemAllocationHandleType.CU_MEM_HANDLE_TYPE_POSIX_FILE_DESCRIPTOR, 0)))
                fds.append((segment_id, fd))
    except RuntimeError:
        for _, fd in fds:
            os.close(fd)
        raise
    wrapper._segment_fds = fds
    wrapper._segments = tuple((key, size) for key, (size, _) in zip(pool.segment_ids, pool.segments))
    wrapper._export_id = pool.export_id
    wrapper._kind, wrapper._fabric_blob, wrapper._fd = 'posix_fd', None, None
    wrapper._alloc_size, wrapper._alloc_offset, wrapper._nbytes = pool.size, offset, span
    wrapper.handle = (pool.export_id, offset)
    wrapper.dtype, wrapper.shape, wrapper.stride = tensor.dtype, tuple(tensor.shape), tuple(tensor.stride())
    wrapper.storage_offset = 0
    wrapper.device_uuid = wrapper._get_device_uuid(tensor.device.index)
    wrapper._opens = 0
    return True


def publish_segments(wrapper):
    for key, fd in getattr(wrapper, '_segment_fds', []):
        publish(key, fd)


def close_exports(wrapper):
    for key, fd in getattr(wrapper, '_segment_fds', []):
        withdraw(key, fd)
        os.close(fd)
    wrapper._segment_fds = []


def import_segments(wrapper, device, mapping_class):
    ptr = int(checked(cu.cuMemAddressReserve(wrapper._alloc_size, 0, 0, 0)))
    imported = []
    offset = 0
    try:
        for key, size in wrapper._segments:
            fd = resolve(key)
            try:
                handle = checked(cu.cuMemImportFromShareableHandle(fd, cu.CUmemAllocationHandleType.CU_MEM_HANDLE_TYPE_POSIX_FILE_DESCRIPTOR))
            finally:
                os.close(fd)
            try:
                checked(cu.cuMemMap(ptr + offset, size, 0, handle, 0))
            except RuntimeError:
                cu.cuMemRelease(handle)
                raise
            imported.append((size, handle))
            access_range(ptr + offset, size, device)
            offset += size
    except (RuntimeError, OSError):
        release_mapping(ptr, wrapper._alloc_size, imported)
        raise
    return mapping_class(base_ptr=ptr, alloc_handle=imported, refcount=0)
