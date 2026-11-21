"""Apply bounded cache admission with exact-source guards."""
from n1x_patch import Patch

path = 'lmcache/v1/distributed/l1_manager.py'
text = Patch(path, 'admission')
text.require('from n1x_cache_admission import', count=0)
old = '    @l1_mgr_synchronized\n    def reserve_write('
text.replace(old, '    @demand_admission\n' + old)
text.replace('logger = init_logger(__name__)',
                    'from n1x_cache_admission import demand_admission\n\nlogger = init_logger(__name__)')
text.write()

path = 'lmcache/v1/distributed/storage_manager.py'
text = Patch(path, 'write-admission')
text.require('register_write_reclaim', count=0)
text.require('_L1_WRITE_TAG = "storage_manager"')
old = '            PeriodicEventNotifier.create('
text.replace(old, '''            from n1x_cache_admission import register_write_reclaim
            if len(self._l1_managers_by_id) == 1:
                register_write_reclaim(self._l1_manager, self._l2_adapters)

''' + old)
text.write()

path = 'lmcache/v1/distributed/storage_controllers/eviction_controller.py'
text = Patch(path, 'admission')
text.require('from n1x_cache_admission import', count=0)
old = '        self._l1_manager.register_listener(self._listener)'
text.replace(old, old + '\n        from n1x_cache_admission import register_policy\n        register_policy(self._l1_manager, self._eviction_policy)')
text.write()
