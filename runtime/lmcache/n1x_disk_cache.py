"""Bound the project's FS cache across namespaces; one serving profile at a time."""
import asyncio
import logging
import os
from pathlib import Path
import shutil

LOG = logging.getLogger(__name__)


class DiskBudget:
    def __init__(self, root, capacity, minimum_free=20 * 2**30):
        self.root = Path(root).resolve()
        self.capacity = capacity
        self.minimum_free = minimum_free
        if capacity <= 0 or minimum_free < 0:
            raise ValueError('Invalid disk cache budget')

    def entries(self):
        entries = []
        for namespace in self.root.iterdir():
            if namespace.is_symlink() or not namespace.is_dir() or not namespace.name.startswith('qwen-'):
                continue
            for path in namespace.iterdir():
                if path.is_symlink() or path.suffix not in ('.data', '.tmp') or not path.is_file():
                    continue
                stat = path.stat()
                entries.append((stat.st_mtime_ns, path, max(stat.st_size, getattr(stat, 'st_blocks', 0) * 512)))
        return sorted(entries)

    def reserve(self, incoming, on_delete=lambda path, size: None):
        if incoming > self.capacity:
            return False
        entries = self.entries()
        used = sum(size for _, _, size in entries)
        free = shutil.disk_usage(self.root).free
        for _, path, size in entries:
            if used + incoming <= self.capacity and free >= self.minimum_free + incoming:
                break
            logical_size = path.stat().st_size
            path.unlink(missing_ok=True)
            used -= size
            on_delete(path, logical_size)
            free = shutil.disk_usage(self.root).free
        return used + incoming <= self.capacity and free >= self.minimum_free + incoming

    @staticmethod
    def touch(paths):
        for path in paths:
            try:
                os.utime(path, None)
            except FileNotFoundError:
                pass


def install(adapter_class, filename_to_key):
    """Wrap pinned LMCache FS operations without changing its transfer protocol."""
    from lmcache.v1.distributed.internal_api import L2StoreResult

    original_init = adapter_class.__init__
    original_store = adapter_class._execute_store
    original_load = adapter_class._execute_load

    def initialize(self, config):
        original_init(self, config)
        base = self._base_path.resolve()
        if base.parent != Path('/lmcache') or not base.name.startswith('qwen-'):
            raise ValueError('Bounded FS cache requires a project namespace under /lmcache')
        self._n1x_budget = DiskBudget(base.parent, int(float(os.environ.get('N1X_LMCACHE_L2_GIB', '16')) * 2**30))
        self._n1x_store_lock = asyncio.Lock()
        if not self._n1x_budget.reserve(0):
            raise OSError('LMCache requires 20 GiB available on its Linux filesystem')
        retained = [(filename_to_key(path.name), path.stat().st_size)
                    for _, path, _ in self._n1x_budget.entries() if path.parent == base]
        retained = [(key, size) for key, size in retained if key is not None]
        if retained:
            self._notify_keys_stored([key for key, _ in retained], [size for _, size in retained])
        LOG.info('N1X SSD cache budget: %.1f GiB across project namespaces', self._n1x_budget.capacity / 2**30)

    async def store(self, keys, objects, task_id):
        # Serialize reservations and writes so concurrent stores cannot overbook.
        async with self._n1x_store_lock:
            # Reserve every object: eviction may remove an existing key in this task.
            incoming = sum(((len(obj.byte_array) + 4095) // 4096) * 4096 for obj in objects)

            def deleted(path, size):
                if path.parent == self._base_path.resolve():
                    key = filename_to_key(path.name)
                    if key is not None:
                        self._notify_keys_deleted([key], [size])

            if not self._n1x_budget.reserve(incoming, deleted):
                with self._lock:
                    self._completed_store_tasks[task_id] = L2StoreResult(False, 0)
                self._store_efd.notify()
                LOG.warning('SSD store skipped: capacity or free-space budget exhausted')
                return
            await original_store(self, keys, objects, task_id)

    async def load(self, keys, objects, task_id):
        self._n1x_budget.touch(self._key_to_path(key) for key in keys)
        await original_load(self, keys, objects, task_id)

    adapter_class.__init__ = initialize
    adapter_class._execute_store = store
    adapter_class._execute_load = load
