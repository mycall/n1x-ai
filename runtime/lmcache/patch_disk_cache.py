"""Install bounded SSD storage on the pinned LMCache filesystem adapter."""
from pathlib import Path
import site

path = Path(site.getsitepackages()[0]) / 'lmcache/v1/distributed/l2_adapters/fs_l2_adapter.py'
source = path.read_text()
anchor = 'register_l2_adapter_factory("fs", _create_fs_adapter)'
assert source.count(anchor) == 1
assert 'n1x_disk_cache' not in source
source += '\nfrom n1x_disk_cache import install as _n1x_install_disk_budget\n_n1x_install_disk_budget(FSL2Adapter, _filename_to_object_key)\n'
path.write_text(source)
