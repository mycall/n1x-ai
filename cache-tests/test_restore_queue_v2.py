import os
import sys
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from n1x_restore_queue_v2 import defer_load, is_deferred, retry_deferred


class SparseQueueTests(unittest.TestCase):
    def setUp(self):
        self.locked = True
        self.manager = NS(_lock=threading.Lock(), _staging={},
            get_memory_usage=lambda: (64,64), _objects={99: NS(
                read_lock=NS(is_locked=lambda: self.locked),
                write_lock=NS(is_locked=lambda: False), memory_obj=NS(get_physical_size=lambda: 64))})
        policy = NS(get_eviction_actions=lambda fraction: [NS(keys=[99])])
        log = NS(info=lambda *a: None, warning=lambda *a: None, exception=lambda *a: None)
        self.modules = patch.dict(sys.modules, {'lmcache.logging': NS(init_logger=lambda name: log),
            'n1x_cache_admission': NS(state_for=lambda manager: {'policy': policy})})
        self.modules.start()
        self.environment = patch.dict(os.environ, N1X_RESTORE_WAIT_MS='500')
        self.environment.start()
        self.addCleanup(self.modules.stop)
        self.addCleanup(self.environment.stop)
        layout = NS(shapes=[(32,)], dtypes=[NS(itemsize=1)])
        self.request = NS(request_id=1, key_groups=[NS(keys=[1,2,3],layout_desc=layout),
            NS(keys=[4,5,6],layout_desc=layout)], all_loads_done=lambda: True)
        self.cells = {0: [NS(get_indices_list=lambda: [0]), NS(get_indices_list=lambda: [])]}
        self.controller = NS(_l1_managers={0:self.manager}, _in_flight_requests={1:self.request})

    def test_sparse_plan_waits_even_when_all_logical_keys_exceed_capacity(self):
        self.assertTrue(defer_load(self.controller, self.request, self.cells))
        self.assertTrue(is_deferred(self.controller, 1))
        self.locked = False
        self.assertFalse(defer_load(self.controller, self.request, self.cells))
        self.assertFalse(is_deferred(self.controller, 1))

    def test_retry_never_finishes_while_deferred(self):
        completed = []
        self.controller._transition_to_load_phase = lambda request: defer_load(self.controller, request, self.cells)
        self.controller._finish_request = lambda request: completed.append('finish')
        self.controller._retire_request = lambda request: completed.append('retire')
        self.assertTrue(defer_load(self.controller, self.request, self.cells))
        retry_deferred(self.controller)
        self.assertEqual(completed, [])
        self.locked = False
        retry_deferred(self.controller)
        self.assertEqual(completed, ['finish','retire'])

    def test_deadline_and_cancellation_release_queue_entries(self):
        with patch('n1x_restore_queue_v2.time.monotonic', side_effect=[10,10.6]):
            self.assertTrue(defer_load(self.controller, self.request, self.cells))
            self.assertFalse(defer_load(self.controller, self.request, self.cells))
        self.assertTrue(defer_load(self.controller, self.request, self.cells))
        self.controller._in_flight_requests.clear()
        retry_deferred(self.controller)
        self.assertFalse(is_deferred(self.controller, 1))

    def test_truly_oversized_plan_does_not_wait(self):
        cells = {0:[NS(get_indices_list=lambda:[0,1,2]),NS(get_indices_list=lambda:[])]}
        self.assertFalse(defer_load(self.controller, self.request, cells))


if __name__ == '__main__':
    unittest.main()
