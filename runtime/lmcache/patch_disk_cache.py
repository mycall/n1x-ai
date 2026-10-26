"""Install bounded SSD storage on the pinned LMCache filesystem adapter."""
from n1x_patch import Patch

path = 'lmcache/v1/distributed/l2_adapters/fs_l2_adapter.py'
source = Patch(path, 'disk-cache')
anchor = 'register_l2_adapter_factory("fs", _create_fs_adapter)'
source.require(anchor)
source.require('n1x_disk_cache', count=0)
source.text += '\nfrom n1x_disk_cache import install as _n1x_install_disk_budget\n_n1x_install_disk_budget(FSL2Adapter, _filename_to_object_key)\n'
source.write()
