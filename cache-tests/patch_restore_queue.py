"""Patch the experimental image only, with exact upstream source guards."""
from pathlib import Path
import site

path = Path(site.getsitepackages()[0]) / 'lmcache/v1/distributed/storage_controllers/prefetch_controller.py'
source = path.read_text()
old = '            request_id, spec = self._pending_queue.popleft()'
assert source.count(old) == 1
source = source.replace(old, '''            request_id, spec = self._pending_queue[0]
            from n1x_restore_queue import should_wait
            if should_wait(self, request_id, spec):
                break
''' + old)
old = 'PREFETCH_LOOP_POLL_TIMEOUT_MS = 500'
assert source.count(old) == 1
source = source.replace(old, '''import os as _n1x_os
PREFETCH_LOOP_POLL_TIMEOUT_MS = 50 if int(_n1x_os.environ.get('N1X_RESTORE_WAIT_MS', '0')) > 0 else 500''')
path.write_text(source)
