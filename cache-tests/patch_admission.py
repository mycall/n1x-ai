"""Patch only the experimental image, with exact-source guards."""
from pathlib import Path
import site

root = Path(site.getsitepackages()[0])
path = root / 'lmcache/v1/distributed/l1_manager.py'
text = path.read_text()
old = '    @l1_mgr_synchronized\n    def reserve_write('
assert text.count(old) == 1
text = text.replace(old, '    @demand_admission\n' + old)
text = text.replace('logger = init_logger(__name__)',
                    'from n1x_cache_admission import demand_admission\n\nlogger = init_logger(__name__)')
path.write_text(text)

path = root / 'lmcache/v1/distributed/storage_controllers/eviction_controller.py'
text = path.read_text()
old = '        self._l1_manager.register_listener(self._listener)'
assert text.count(old) == 1
text = text.replace(old, old + '\n        from n1x_cache_admission import register_policy\n        register_policy(self._l1_manager, self._eviction_policy)')
path.write_text(text)
