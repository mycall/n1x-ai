"""Bounded nonblocking wait using the actual sparse L2-to-L1 load plan."""
import math
import os
import time


def is_deferred(controller, request_id):
    return request_id in getattr(controller, '_n1x_deferred_loads', {})


def defer_load(controller, request, cells_by_l1):
    from lmcache.logging import init_logger
    from n1x_cache_admission import state_for
    log = init_logger(__name__)
    wait_ms = int(os.environ.get('N1X_RESTORE_WAIT_MS', '0'))
    records = getattr(controller, '_n1x_deferred_loads', None)
    if records is None:
        records = controller._n1x_deferred_loads = {}
    identity = request.request_id
    if wait_ms <= 0 or len(controller._l1_managers) != 1:
        records.pop(identity, None)
        return False
    blocked, details = False, []
    protected = {key for group in request.key_groups for key in group.keys}
    for index, cells in cells_by_l1.items():
        manager = controller._l1_managers[index]
        policy = state_for(manager)['policy']
        if policy is None:
            continue
        # Count selected cells only. Sliding/recurrent groups need not have
        # a stored object at every historical attention chunk boundary.
        needed = sum(len(row.get_indices_list()) * sum(math.prod(shape) * dtype.itemsize
                     for shape, dtype in zip(group.layout_desc.shapes, group.layout_desc.dtypes, strict=True))
                     for group, row in zip(request.key_groups, cells, strict=True))
        used, capacity = manager.get_memory_usage()
        candidates = {key for action in policy.get_eviction_actions(1.0) for key in action.keys} - protected
        with manager._lock:
            reclaimable = sum(entry.memory_obj.get_physical_size()
                for key, entry in manager._objects.items()
                if key in candidates and not entry.read_lock.is_locked()
                and not entry.write_lock.is_locked() and key not in manager._staging)
        available = capacity - used + reclaimable
        details.append((index, needed, available, capacity))
        if available < needed <= capacity:
            blocked = True
    previous = records.get(identity)
    if not blocked:
        records.pop(identity, None)
        if previous:
            log.info('N1X restore queue admitted version=2 request=%s after %.3fs',
                     identity, time.monotonic() - previous['started'])
        return False
    now = time.monotonic()
    if previous is None:
        previous = records[identity] = {'request': request, 'started': now}
        log.info('N1X restore queue waiting version=2 request=%s plan=%s deadline_ms=%d',
                 identity, details, wait_ms)
    if now - previous['started'] >= wait_ms / 1000:
        records.pop(identity, None)
        log.warning('N1X restore queue deadline version=2 request=%s; using normal bounded admission', identity)
        return False
    return True


def retry_deferred(controller):
    from lmcache.logging import init_logger
    records = getattr(controller, '_n1x_deferred_loads', {})
    for identity, entry in list(records.items()):
        if identity not in controller._in_flight_requests:
            records.pop(identity, None)
            continue
        request = entry['request']
        try:
            controller._transition_to_load_phase(request)
            if not is_deferred(controller, identity) and request.all_loads_done():
                controller._finish_request(request)
                controller._retire_request(request)
        except Exception:
            init_logger(__name__).exception('N1X deferred restore failed request=%s', identity)
            records.pop(identity, None)
            controller._abort_request(request)
