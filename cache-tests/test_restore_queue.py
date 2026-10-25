import os
import sys
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from n1x_restore_queue import should_wait


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.used = 64
        self.keys = {1: NS(get_physical_size=lambda: 32)}
        self.evictable = set()
        self.manager = NS(get_memory_usage=lambda: (self.used, 64),
            _lock=threading.Lock(), _staging={}, _objects={1: NS(
                memory_obj=self.keys[1], read_lock=NS(is_locked=lambda: 1 not in self.evictable),
                write_lock=NS(is_locked=lambda: False))})
        self.policy = NS(get_eviction_actions=lambda fraction: [NS(keys=list(self.keys))])
        self.controller = NS(_l1_managers={0: self.manager})
        self.spec = NS(key_groups=[NS(keys=[2], layout_desc=NS(shapes=[(32,)], dtypes=[NS(itemsize=1)]))])
        logger = NS(info=lambda *a: None, warning=lambda *a: None)
        self.modules = patch.dict(sys.modules, {
            'lmcache.v1.distributed.error': NS(L1Error=NS(SUCCESS=0)),
            'lmcache.logging': NS(init_logger=lambda name: logger),
            'n1x_cache_admission': NS(state_for=lambda manager: {'policy': self.policy})})
        self.modules.start()
        self.environment = patch.dict(os.environ, N1X_RESTORE_WAIT_MS='500')
        self.environment.start()
        self.addCleanup(self.modules.stop)
        self.addCleanup(self.environment.stop)

    def test_release_admits_without_sleep_or_reserving(self):
        with patch('n1x_restore_queue.time.monotonic', side_effect=[10, 10.1]):
            self.assertTrue(should_wait(self.controller, 1, self.spec))
            self.used = 32
            self.assertFalse(should_wait(self.controller, 1, self.spec))

    def test_deadline_falls_back_instead_of_waiting_forever(self):
        with patch('n1x_restore_queue.time.monotonic', side_effect=[10, 10.6]):
            self.assertTrue(should_wait(self.controller, 1, self.spec))
            self.assertFalse(should_wait(self.controller, 1, self.spec))

    def test_evictable_memory_does_not_delay(self):
        self.evictable.add(1)
        self.assertFalse(should_wait(self.controller, 1, self.spec))

    def test_resident_and_oversized_requests_do_not_wait(self):
        self.spec.key_groups[0].keys = [1]
        self.assertFalse(should_wait(self.controller, 1, self.spec))
        self.spec.key_groups[0].keys = [2, 3, 4]
        self.assertFalse(should_wait(self.controller, 2, self.spec))


if __name__ == '__main__':
    unittest.main()
