"""Replace speculative admission with sparse-plan admission in a child image."""
from pathlib import Path
import site

path = Path(site.getsitepackages()[0]) / 'lmcache/v1/distributed/storage_controllers/prefetch_controller.py'
source = path.read_text()
old = '''            request_id, spec = self._pending_queue[0]
            from n1x_restore_queue import should_wait
            if should_wait(self, request_id, spec):
                break
            request_id, spec = self._pending_queue.popleft()'''
assert source.count(old) == 1
source = source.replace(old, '            request_id, spec = self._pending_queue.popleft()')
old = '        cells_by_l1, retain = self._build_l1_allocation_plans(request)'
assert source.count(old) == 1
source = source.replace(old, old + '''
        from n1x_restore_queue_v2 import defer_load
        if defer_load(self, request, cells_by_l1):
            return''')
old = '        if request.phase == PrefetchPhase.PLAN_AND_LOAD and request.all_loads_done():'
assert source.count(old) == 1
source = source.replace(old, '''        from n1x_restore_queue_v2 import is_deferred
        if (request.phase == PrefetchPhase.PLAN_AND_LOAD and request.all_loads_done()
                and not is_deferred(self, request.request_id)):''')
old = '                self._start_pending_requests()'
assert source.count(old) == 1
source = source.replace(old, old + '''
                from n1x_restore_queue_v2 import retry_deferred
                retry_deferred(self)''')
path.write_text(source)
