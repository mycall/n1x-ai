"""Replace speculative admission with sparse-plan admission in a child image."""
from pathlib import Path
import site

path = Path(site.getsitepackages()[0]) / 'lmcache/v1/distributed/storage_controllers/prefetch_controller.py'
source = path.read_text()
old = 'PREFETCH_LOOP_POLL_TIMEOUT_MS = 500'
assert source.count(old) == 1
source = source.replace(old, '''import os as _n1x_os
PREFETCH_LOOP_POLL_TIMEOUT_MS = 50 if int(_n1x_os.environ.get('N1X_RESTORE_WAIT_MS', '0')) > 0 else 500''')
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
