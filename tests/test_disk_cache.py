import importlib.util
import asyncio
from enum import Enum, auto
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

MODULE = Path(__file__).resolve().parents[1] / 'runtime/lmcache/n1x_disk_cache.py'
spec = importlib.util.spec_from_file_location('disk_budget', MODULE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DiskBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def entry(self, namespace, name, age):
        path = self.root / namespace / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b'x' * 4096)
        os.utime(path, (age, age))
        return path

    def test_global_budget_evicts_oldest_across_namespaces(self):
        old = self.entry('qwen-mtp', 'old.data', 1)
        new = self.entry('qwen-dflash', 'new.data', 2)
        unrelated = self.entry('other', 'keep.data', 0)
        budget = module.DiskBudget(self.root, 8192, 0)
        self.assertTrue(budget.reserve(4096))
        self.assertFalse(old.exists())
        self.assertTrue(new.exists())
        self.assertTrue(unrelated.exists())

    def test_access_protects_recent_entry(self):
        hot = self.entry('qwen-mtp', 'hot.data', 1)
        cold = self.entry('qwen-mtp', 'cold.data', 2)
        budget = module.DiskBudget(self.root, 8192, 0)
        budget.touch([hot])
        self.assertTrue(budget.reserve(4096))
        self.assertTrue(hot.exists())
        self.assertFalse(cold.exists())

    def test_oversized_store_does_not_destroy_existing_cache(self):
        cached = self.entry('qwen-mtp', 'keep.data', 1)
        self.assertFalse(module.DiskBudget(self.root, 8192, 0).reserve(12288))
        self.assertTrue(cached.exists())

    def test_low_disk_space_refuses_store_even_after_eviction(self):
        self.entry('qwen-mtp', 'old.data', 1)
        with patch.object(module.shutil, 'disk_usage', return_value=SimpleNamespace(free=0)):
            self.assertFalse(module.DiskBudget(self.root, 8192, 4096).reserve(4096))


class WriteAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_reclaims_only_completed_unlocked_files(self):
        class Error(Enum):
            SUCCESS = auto()
            OUT_OF_MEMORY = auto()
            KEY_IS_LOCKED = auto()

        delete_started = asyncio.Event()
        finish_delete = asyncio.Event()

        class Adapter:
            async def _execute_store(self, *args):
                pass

            async def _execute_load(self, *args):
                pass

            async def _execute_delete(self, keys):
                delete_started.set()
                await finish_delete.wait()

            def _key_to_path(self, key):
                return root / f'{key}.data'

        deleted = []

        class Manager:
            def delete(self, keys):
                key, = keys
                if key == 'locked':
                    return {key: Error.KEY_IS_LOCKED}
                deleted.append(key)
                return {key: Error.SUCCESS}

            def get_memory_usage(self):
                return 32, 64

        layout = SimpleNamespace(shapes=[(32,)], dtypes=[SimpleNamespace(itemsize=1)])

        def reserve(manager, keys, flags, desc, tag):
            return {key: (Error.SUCCESS if deleted else Error.OUT_OF_MEMORY, None) for key in keys}

        modules = {
            'lmcache.v1.distributed.error': SimpleNamespace(L1Error=Error),
            'lmcache.v1.distributed.internal_api': SimpleNamespace(L2StoreResult=object),
            'lmcache.logging': SimpleNamespace(init_logger=lambda name: module.LOG),
        }
        admission_spec = importlib.util.spec_from_file_location('admission_under_test', MODULE.with_name('n1x_cache_admission.py'))
        admission = importlib.util.module_from_spec(admission_spec)
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules, modules):
            root = Path(directory)
            admission_spec.loader.exec_module(admission)
            module.install(Adapter, lambda name: None)
            adapter = object.__new__(Adapter)
            adapter._n1x_budget = module.DiskBudget(root, 8192, 0)
            manager = Manager()
            for key in ('locked', 'persisted', 'new'):
                (root / f'{key}.data').write_bytes(b'x')
            (root / 'unfinished.tmp').write_bytes(b'x')
            policy = SimpleNamespace(get_eviction_actions=lambda fraction: [
                SimpleNamespace(keys=['new', 'unfinished', 'locked', 'persisted'])
            ])
            admission.register_policy(manager, policy)
            wrapped = admission.demand_admission(reserve)
            args = (manager, ['new'], [False], layout, 'storage_manager')
            self.assertEqual(wrapped(*args)['new'][0], Error.OUT_OF_MEMORY)
            with patch.dict(os.environ, N1X_LMCACHE_RETRY_WRITES='1'):
                admission.register_write_reclaim(manager, {0: adapter})

            task = asyncio.create_task(adapter._execute_delete(['other']))
            await delete_started.wait()
            try:
                self.assertEqual(wrapped(*args)['new'][0], Error.OUT_OF_MEMORY)
                self.assertEqual(deleted, [])
            finally:
                finish_delete.set()
                await task
            self.assertEqual(wrapped(*args)['new'][0], Error.SUCCESS)
            self.assertEqual(deleted, ['persisted'])
            self.assertTrue((root / 'persisted.data').exists())


if __name__ == '__main__':
    unittest.main()
