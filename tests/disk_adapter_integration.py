"""Run in the cache image with an empty /lmcache; uses CPU byte buffers only."""
import os
from pathlib import Path
import time
from types import SimpleNamespace

from lmcache.v1.distributed.api import ObjectKey
from lmcache.v1.distributed.l2_adapters.fs_l2_adapter import FSL2Adapter, FSL2AdapterConfig

os.environ['N1X_LMCACHE_L2_GIB'] = str(16384 / 2**30)
root = Path('/lmcache/qwen-budget-test')
assert not root.exists(), 'Use an empty disposable test filesystem'
adapter = FSL2Adapter(FSL2AdapterConfig(str(root)))


def wait_for(function):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        value = function()
        if value is not None:
            return value
        time.sleep(.01)
    raise TimeoutError('Adapter task did not complete')


try:
    keys = [ObjectKey(chunk_hash=bytes([i])*32, model_name='test', kv_rank=0x01000100,
                      object_group_id=0, cache_salt='budget') for i in range(10)]
    tasks = [adapter.submit_store_task([key], [SimpleNamespace(byte_array=bytearray([i])*4096)])
             for i, key in enumerate(keys)]
    complete = {}
    def finished():
        complete.update(adapter.pop_completed_store_tasks())
        return complete if len(complete) == len(tasks) else None
    wait_for(finished)
    assert sum(p.stat().st_size for p in root.glob('*.data')) <= 16384
    assert not adapter._key_to_path(keys[0]).exists()
    assert adapter._key_to_path(keys[-1]).exists()
    output = SimpleNamespace(byte_array=bytearray(4096))
    task = adapter.submit_load_task([keys[-1]], [output])
    bitmap = wait_for(lambda: adapter.query_load_result(task))
    assert bitmap.get_indices_list() == [0]
    assert output.byte_array == bytearray([9])*4096
    usage = adapter.get_usage().total_bytes_used
    assert usage == sum(p.stat().st_size for p in root.glob('*.data'))
finally:
    adapter.close()

adapter = FSL2Adapter(FSL2AdapterConfig(str(root)))
try:
    assert adapter.get_usage().total_bytes_used == usage
finally:
    adapter.close()
print('Concurrent stores, eviction, load integrity, and restart accounting passed')
