"""Test FD-based CUDA VMM sharing independently of legacy IPC."""
import ctypes
import json
import multiprocessing as mp
from multiprocessing.reduction import send_handle, recv_handle
import os
from cuda.bindings import driver as cu

SIZE = 64 * 1024**2
KIND = cu.CUmemAllocationHandleType.CU_MEM_HANDLE_TYPE_POSIX_FILE_DESCRIPTOR

def checked(result):
    if result[0] != cu.CUresult.CUDA_SUCCESS:
        raise RuntimeError(str(result[0]))
    return result[1] if len(result) == 2 else result[1:]

def init():
    checked(cu.cuInit(0))
    context = checked(cu.cuDevicePrimaryCtxRetain(0))
    checked(cu.cuCtxSetCurrent(context))

def mapping(handle):
    ptr = checked(cu.cuMemAddressReserve(SIZE, 0, 0, 0))
    checked(cu.cuMemMap(ptr, SIZE, 0, handle, 0))
    access = cu.CUmemAccessDesc()
    access.location.type = cu.CUmemLocationType.CU_MEM_LOCATION_TYPE_DEVICE
    access.location.id = 0
    access.flags = cu.CUmemAccess_flags.CU_MEM_ACCESS_FLAGS_PROT_READWRITE
    checked(cu.cuMemSetAccess(ptr, SIZE, [access], 1))
    return ptr

def receive(pipe):
    try:
        init()
        fd = recv_handle(pipe)
        handle = checked(cu.cuMemImportFromShareableHandle(fd, KIND))
        ptr = mapping(handle)
        value = ctypes.c_ubyte()
        checked(cu.cuMemcpyDtoH(ctypes.addressof(value), ptr, 1))
        pipe.send({'passed': value.value == 37, 'value': value.value})
        checked(cu.cuMemUnmap(ptr, SIZE))
        checked(cu.cuMemAddressFree(ptr, SIZE))
        checked(cu.cuMemRelease(handle))
        os.close(fd)
    except Exception as error:
        pipe.send({'passed': False, 'error': str(error)})

if __name__ == '__main__':
    ctx = mp.get_context('spawn')
    parent, child = ctx.Pipe()
    process = ctx.Process(target=receive, args=(child,))
    process.start()
    try:
        init()
        prop = cu.CUmemAllocationProp()
        prop.type = cu.CUmemAllocationType.CU_MEM_ALLOCATION_TYPE_PINNED
        prop.location.type = cu.CUmemLocationType.CU_MEM_LOCATION_TYPE_DEVICE
        prop.location.id = 0
        prop.requestedHandleTypes = KIND
        handle = checked(cu.cuMemCreate(SIZE, prop, 0))
        ptr = mapping(handle)
        checked(cu.cuMemsetD8(ptr, 37, SIZE))
        checked(cu.cuCtxSynchronize())
        fd = checked(cu.cuMemExportToShareableHandle(handle, KIND, 0))
        send_handle(parent, fd, process.pid)
        result = parent.recv() if parent.poll(30) else {'passed': False, 'error': 'timeout'}
        print(json.dumps(result), flush=True)
        os.close(fd)
    except Exception as error:
        print(json.dumps({'passed': False, 'error': str(error)}), flush=True)
    finally:
        process.join(3)
        if process.is_alive():
            process.kill()
            process.join()
