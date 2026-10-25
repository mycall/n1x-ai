"""Synchronize transfer stages to localize asynchronous CUDA failures."""
import runpy
import os
import torch
from lmcache import device_ops
import lmcache.v1.multiprocess.object_group_transfer as transfer

# Isolate the staged path from newer batched/native transfer fast paths.
transfer._HAS_BATCH_MEMCPY_ASYNC = False
transfer._HAS_NATIVE_OBJECT_GROUP_TRANSFER = False

def checked(name, original):
    def call(*args, **kwargs):
        print(f'PROBE {name} begin', flush=True)
        result = original(*args, **kwargs)
        torch.cuda.current_stream().synchronize()
        print(f'PROBE {name} synchronized', flush=True)
        return result
    return call

if os.environ.get('N1X_PROBE_SYNC') == '1':
    device_ops.multi_layer_block_kv_transfer = checked('block-kernel', device_ops.multi_layer_block_kv_transfer)
    transfer.lmcache_memcpy_async_d2h = checked('host-copy', transfer.lmcache_memcpy_async_d2h)
runpy.run_module('lmcache.v1.multiprocess.http_server', run_name='__main__')
