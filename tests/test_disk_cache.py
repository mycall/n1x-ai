import importlib.util
import os
from pathlib import Path
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


if __name__ == '__main__':
    unittest.main()
