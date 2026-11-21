"""Experimental bounded L1 reclamation; uses LMCache's existing lock checks."""
from functools import wraps
import math
import os
import threading
import weakref

from lmcache.v1.distributed.error import L1Error
from lmcache.logging import init_logger

LOG = init_logger(__name__)
STATES = weakref.WeakKeyDictionary()
REGISTRY_LOCK = threading.Lock()


def state_for(manager):
    with REGISTRY_LOCK:
        if manager not in STATES:
            STATES[manager] = {'lock': threading.Lock(), 'policy': None}
        return STATES[manager]


def register_policy(manager, policy):
    """Use the same policy and event listener as background eviction."""
    state = state_for(manager)
    with state['lock']:
        state['policy'] = policy


def register_write_reclaim(manager, adapters):
    """Enable store retry only for one bounded filesystem adapter."""
    if os.environ.get('N1X_LMCACHE_RETRY_WRITES') != '1' or len(adapters) != 1:
        return
    reclaim = getattr(next(iter(adapters.values())), 'n1x_reclaim_persisted', None)
    if reclaim is not None:
        state = state_for(manager)
        with state['lock']:
            state['reclaim'] = weakref.WeakMethod(reclaim)


def demand_admission(reserve):
    """Serialize reservations and retry allocation failures after bounded eviction.

    Successful reservations are never repeated. Each candidate is attempted
    once, and deletion rechecks locks atomically inside L1Manager. Readers can
    continue while admissions are serialized. Oversized batches fail normally.
    """
    @wraps(reserve)
    def wrapped(manager, keys, is_temporary, layout_desc, tag=''):
        state = state_for(manager)
        with state['lock']:
            results = reserve(manager, keys, is_temporary, layout_desc, tag)
            policy = state['policy']
            store = tag == 'storage_manager'
            persisted = state.get('reclaim', lambda: None)() if store else None
            if policy is None or (persisted is None and not tag.startswith('prefetch:')):
                return results
            pending = [key for key in keys if results[key][0] == L1Error.OUT_OF_MEMORY]
            if not pending:
                return results
            flags = dict(zip(keys, is_temporary, strict=True))
            object_bytes = sum(math.prod(shape) * dtype.itemsize
                               for shape, dtype in zip(layout_desc.shapes, layout_desc.dtypes, strict=True))
            if object_bytes * len(pending) > manager.get_memory_usage()[1]:
                return results
            # Do not hold the policy lock while entering the manager: its
            # listener callbacks acquire the policy lock in the reverse order.
            actions = policy.get_eviction_actions(1.0)
            requested = set(keys)
            operation = 'write' if store else 'prefetch'
            deleted = 0
            for action in actions:
                for candidate in action.keys:
                    if store and candidate in requested:
                        continue
                    if persisted is None:
                        reclaimed = manager.delete([candidate])[candidate] == L1Error.SUCCESS
                    else:
                        reclaimed = persisted(manager, candidate)
                    if not reclaimed:
                        continue
                    deleted += 1
                    retried = reserve(manager, pending, [flags[key] for key in pending], layout_desc, tag)
                    results.update(retried)
                    pending = [key for key in pending if retried[key][0] == L1Error.OUT_OF_MEMORY]
                    if not pending:
                        LOG.info('N1X %s admission recovered after evicting %d objects', operation, deleted)
                        return results
            LOG.warning('N1X %s admission exhausted eligible objects; evicted=%d pending=%d', operation, deleted, len(pending))
            return results
    return wrapped
