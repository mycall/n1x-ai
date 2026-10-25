"""Exercise demand-driven reclamation using the installed LMCache allocator.

This is an isolated admission experiment, not a serving-path patch. Objects
eligible for reclamation represent copies already persisted to SSD.
"""
import json
import sys
import concurrent.futures
import threading
import time

import torch
from lmcache.v1.distributed.api import MemoryLayoutDesc, ObjectKey
from lmcache.v1.distributed.config import EvictionConfig, L1ManagerConfig, L1MemoryManagerConfig
from lmcache.v1.distributed.error import L1Error
from lmcache.v1.distributed.eviction import L1EvictionPolicy
from lmcache.v1.distributed.eviction_policy import CreateEvictionPolicy
from lmcache.v1.distributed.l1_manager import L1Manager

MIB = 1024 * 1024


def key(value):
    return ObjectKey(chunk_hash=ObjectKey.IntHash2Bytes(value), model_name='pressure-probe', kv_rank=0)


def reclaim(manager, policy, required_bytes):
    """Reclaim eligible objects in policy order until the batch fits.

    The caller must serialize admission against competing writers. Deletion
    still checks locks, so a newly locked candidate is skipped safely.
    """
    used, capacity = manager.get_memory_usage()
    if required_bytes > capacity:
        return False, 0
    deleted = 0
    if capacity - used >= required_bytes:
        return True, deleted
    actions = policy.get_eviction_actions(1.0, key_eligible_filter=manager.is_key_evictable)
    for action in actions:
        for candidate in action.keys:
            result = manager.delete([candidate])
            if result[candidate] == L1Error.SUCCESS:
                deleted += 1
            used, capacity = manager.get_memory_usage()
            if capacity - used >= required_bytes:
                return True, deleted
    return False, deleted


def run(policy_name, integrated=False):
    manager = L1Manager(L1ManagerConfig(memory_config=L1MemoryManagerConfig(
        size_in_bytes=64*MIB, use_lazy=True, init_size_in_bytes=64*MIB,
        align_bytes=4096, shm_name='')))
    policy = CreateEvictionPolicy(EvictionConfig(policy_name))
    manager.register_listener(L1EvictionPolicy(policy))
    if integrated:
        from n1x_cache_admission import register_policy
        register_policy(manager, policy)
    layout = MemoryLayoutDesc(shapes=[torch.Size([8*MIB])], dtypes=[torch.uint8])
    resident = [key(i) for i in range(6)]
    incoming = [key(i) for i in range(10, 14)]
    try:
        initial = manager.reserve_write(resident, [False]*6, layout)
        assert all(error == L1Error.SUCCESS for error, _ in initial.values())
        for _, obj in initial.values():
            obj.tensor.fill_(37)
        manager.finish_write(resident)
        # Six of eight slots are occupied: below the default 80% threshold.
        assert manager.get_memory_usage()[0] == 48*MIB
        baseline = manager.reserve_write(incoming, [True]*4, layout)
        assert all(error == L1Error.OUT_OF_MEMORY for error, _ in baseline.values())
        assert manager.get_memory_usage()[0] == 48*MIB, 'Failed batch leaked memory'
        manager.reserve_read([resident[0]])
        assert not manager.is_key_evictable(resident[0])
        if integrated:
            restored = manager.reserve_write(incoming, [True]*4, layout, tag='prefetch:probe')
        else:
            admitted, deleted = reclaim(manager, policy, 32*MIB)
            assert admitted and deleted == 2
            restored = manager.reserve_write(incoming, [True]*4, layout)
        assert all(error == L1Error.SUCCESS for error, _ in restored.values())
        assert manager.get_memory_usage()[0] == 64*MIB
        protected = manager.unsafe_read([resident[0]])[resident[0]]
        assert protected[0] == L1Error.SUCCESS
        assert bool((protected[1].tensor == 37).all())
        # In-flight writes are protected too. Lock all remaining residents;
        # another request must decline without forcing removal or growing L1.
        for candidate in resident[1:]:
            manager.reserve_read([candidate])
        blocked, removed = reclaim(manager, policy, 8*MIB)
        assert not blocked and removed == 0
        if integrated:
            denied = manager.reserve_write([key(99)], [True], layout, tag='prefetch:blocked')
            assert denied[key(99)][0] == L1Error.OUT_OF_MEMORY
        oversized, removed = reclaim(manager, policy, 72*MIB)
        assert not oversized and removed == 0
        manager.finish_write(incoming, tag='prefetch:probe' if integrated else '')
        manager.reserve_read(incoming)
        manager.finish_read(incoming)
        assert manager.get_memory_usage()[0] == 32*MIB, 'Temporary buffers not released'
        return {'policy': policy_name, 'integrated': integrated, 'passed': True, 'capacityMiB': 64,
                'baseline': '32 MiB batch fails at 75% occupancy',
                'reclaimedMiB': 16, 'protectedReadIntact': True,
                'lockedWritesPreserved': True, 'oversizedBatchDeclined': True,
                'temporaryRestoreBuffersReleased': True}
    finally:
        manager.close()


def concurrent_admission():
    from n1x_cache_admission import register_policy
    manager = L1Manager(L1ManagerConfig(memory_config=L1MemoryManagerConfig(
        size_in_bytes=64*MIB, use_lazy=True, init_size_in_bytes=64*MIB,
        align_bytes=4096, shm_name='')))
    policy = CreateEvictionPolicy(EvictionConfig('LRU'))
    manager.register_listener(L1EvictionPolicy(policy))
    register_policy(manager, policy)
    layout = MemoryLayoutDesc(shapes=[torch.Size([8*MIB])], dtypes=[torch.uint8])
    barrier = threading.Barrier(2)
    def reserve_batch(offset):
        barrier.wait(timeout=10)
        return manager.reserve_write([key(offset+i) for i in range(6)], [True]*6,
                                     layout, tag=f'prefetch:{offset}')
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(reserve_batch, offset) for offset in (100, 200)]
            results = [future.result(timeout=20) for future in futures]
        counts = sorted(sum(error == L1Error.SUCCESS for error, _ in row.values()) for row in results)
        assert counts == [0, 6], counts
        assert manager.get_memory_usage()[0] == 48*MIB
        return {'concurrentAdmission': 'passed', 'successfulBatches': 1,
                'declinedBatches': 1, 'capacityExceeded': False}
    finally:
        manager.close()


if __name__ == '__main__':
    integrated = '--integrated' in sys.argv
    print(json.dumps({'timestamp': time.time(), 'tests': [run('LRU', integrated), run('ARC', integrated)]}, indent=2))
    if integrated:
        print(json.dumps(concurrent_admission()))
