"""Small actual L1 allocator test of advisory nonblocking queue decisions."""
import json
import os
from types import SimpleNamespace
import time

import torch
from lmcache.v1.distributed.api import MemoryLayoutDesc, ObjectKey
from lmcache.v1.distributed.config import EvictionConfig, L1ManagerConfig, L1MemoryManagerConfig
from lmcache.v1.distributed.error import L1Error
from lmcache.v1.distributed.eviction import L1EvictionPolicy
from lmcache.v1.distributed.eviction_policy import CreateEvictionPolicy
from lmcache.v1.distributed.l1_manager import L1Manager
from n1x_cache_admission import register_policy
from n1x_restore_queue import should_wait

MIB = 1024 * 1024
manager = L1Manager(L1ManagerConfig(memory_config=L1MemoryManagerConfig(
    size_in_bytes=64*MIB, use_lazy=True, init_size_in_bytes=64*MIB,
    align_bytes=4096, shm_name='')))
policy = CreateEvictionPolicy(EvictionConfig('LRU'))
manager.register_listener(L1EvictionPolicy(policy))
register_policy(manager, policy)
layout = MemoryLayoutDesc(shapes=[torch.Size([32*MIB])], dtypes=[torch.uint8])
def key(i):
    return ObjectKey(chunk_hash=ObjectKey.IntHash2Bytes(i), model_name='restore-queue-probe', kv_rank=0)
resident, incoming = [key(1), key(2)], key(3)
controller = SimpleNamespace(_l1_managers={0: manager})
spec = SimpleNamespace(key_groups=[SimpleNamespace(keys=[incoming], layout_desc=layout)])
os.environ['N1X_RESTORE_WAIT_MS'] = '500'
try:
    reserved = manager.reserve_write(resident, [False, False], layout)
    assert all(error == L1Error.SUCCESS for error, obj in reserved.values())
    manager.finish_write(resident)
    manager.reserve_read(resident)
    start = time.monotonic()
    assert should_wait(controller, 1, spec)
    elapsed = time.monotonic() - start
    assert elapsed < 0.2, 'Queue decision blocked the event loop'
    assert manager.get_memory_usage()[0] == 64*MIB, 'Decision changed allocations'
    manager.finish_read([resident[0]])
    assert not should_wait(controller, 1, spec), 'Unlocked evictable object should permit admission'
    admitted = manager.reserve_write([incoming], [True], layout, tag='prefetch:queue-probe')
    assert admitted[incoming][0] == L1Error.SUCCESS
    assert manager.get_memory_usage()[0] <= 64*MIB
    manager.finish_write([incoming], tag='prefetch:queue-probe')
    manager.reserve_read([incoming])
    manager.finish_read([incoming])
    assert manager.get_memory_usage()[0] == 32*MIB
    print(json.dumps({'passed': True, 'decisionSeconds': elapsed,
                      'waitedWhileLocked': True, 'admittedAfterRelease': True,
                      'temporaryBuffersReleased': True, 'capacityMiB': 64}))
finally:
    manager.close()
