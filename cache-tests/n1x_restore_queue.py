"""Optional, bounded prefetch admission wait without blocking the event loop.

The estimate is advisory. Existing allocator and eviction lock checks remain
authoritative. Restrict to the single-L1 topology qualified on this machine.
"""
import math
import os
import time


def should_wait(controller, request_id, spec):
    wait_ms = int(os.environ.get('N1X_RESTORE_WAIT_MS', '0'))
    if wait_ms <= 0 or len(controller._l1_managers) != 1:
        return False
    from lmcache.logging import init_logger
    from n1x_cache_admission import state_for
    logger = init_logger(__name__)
    manager = next(iter(controller._l1_managers.values()))
    policy = state_for(manager)['policy']
    if policy is None:
        return False
    used, capacity = manager.get_memory_usage()
    needed = 0
    requested = {key for group in spec.key_groups for key in group.keys}
    # unsafe_read requires an existing read lock and is not a residency query.
    # Snapshot metadata under the real manager lock; never take temporary read
    # locks here (finishing one could delete a temporary restore object).
    actions = policy.get_eviction_actions(1.0)
    candidates = {key for action in actions for key in action.keys} - requested
    with manager._lock:
        resident = set(manager._objects)
        reclaimable = sum(entry.memory_obj.get_physical_size()
            for key, entry in manager._objects.items()
            if key in candidates and not entry.read_lock.is_locked()
            and not entry.write_lock.is_locked() and key not in manager._staging)
    for group in spec.key_groups:
        size = sum(math.prod(shape) * dtype.itemsize for shape, dtype in
                   zip(group.layout_desc.shapes, group.layout_desc.dtypes, strict=True))
        needed += size * sum(key not in resident for key in group.keys)
    available = capacity - used
    if available < needed <= capacity:
        available += reclaimable
    previous = getattr(controller, '_n1x_admission_wait', None)
    if available >= needed or needed > capacity:
        if previous and previous[0] == request_id:
            logger.info('N1X restore queue admitted request=%s after %.3fs',
                        request_id, time.monotonic() - previous[1])
        controller._n1x_admission_wait = None
        return False
    now = time.monotonic()
    if previous is None or previous[0] != request_id:
        previous = (request_id, now)
        controller._n1x_admission_wait = previous
        logger.info('N1X restore queue waiting request=%s needed=%d available=%d deadline_ms=%d',
                    request_id, needed, available, wait_ms)
    if now - previous[1] >= wait_ms / 1000:
        logger.warning('N1X restore queue deadline request=%s; using normal bounded admission', request_id)
        controller._n1x_admission_wait = None
        return False
    return True
