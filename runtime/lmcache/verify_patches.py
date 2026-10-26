"""Check the final installed patch set without allocating GPU memory."""
import importlib

from n1x_patch import Patch, installed_root


# These are final-state checks: later patches must preserve earlier hooks.
REQUIRED = {
    'vllm/v1/worker/utils.py': (
        '    from n1x_vmm import zeros\n    buf = zeros(buf_size, device)',
    ),
    'n1x_vmm.py': (
        'from n1x_segmented import SegmentedAllocation',
        'owner = SegmentedAllocation(size, index) if size >= 4 * 1024**3 else Allocation(size, index)',
    ),
    'lmcache/v1/platform/base/ipc_wire.py': (
        '    segments: tuple[tuple[bytes, int], ...] = ()',
        'sum(size for _, size in self.segments) != self.alloc_size',
        'any(len(key) != 16 or size <= 0 for key, size in self.segments)',
    ),
    'lmcache/v1/platform/devices/cuda/ipc_wrapper.py': (
        '        if initialize_wrapper(self, tensor):\n            return\n        data_ptr = tensor.data_ptr()',
        'nbytes = (1 + sum((n - 1) * s for n, s in zip(tensor.shape, tensor.stride()))) * tensor.element_size()',
        'return raw.view(self.dtype).as_strided(self.shape, self.stride)',
        'self._export_id = export_id_for(int(chunk_base))',
        'self.handle = (self._export_id, self._alloc_offset)',
        'obj.handle = (data.export_id, data.alloc_offset)',
        'publish(self._export_id, self._fd)',
        'fd = resolve(self._export_id)',
        'withdraw(self._export_id, fd)',
        'publish_segments(self)',
        'segments=getattr(self, "_segments", ())',
        'obj._segments = data.segments',
        'obj._segment_fds = []',
        'close_exports(self)',
        'release_mapping(base_ptr, self._alloc_size, alloc_handle)\n                return',
        'return import_segments(self, device_index, _VmmMapping)',
        'state["_segment_fds"] = []',
    ),
    'lmcache/v1/multiprocess/object_group_transfer.py': (
        'if _n1x_os.environ.get("N1X_LMCACHE_STAGED_TRANSFER") == "1":\n'
        '    _HAS_BATCH_MEMCPY_ASYNC = False\n    _HAS_NATIVE_OBJECT_GROUP_TRANSFER = False',
    ),
    'lmcache/v1/distributed/l1_manager.py': (
        'from n1x_cache_admission import demand_admission',
        '    @demand_admission\n    @l1_mgr_synchronized\n    def reserve_write(',
    ),
    'lmcache/v1/distributed/storage_controllers/eviction_controller.py': (
        'register_policy(self._l1_manager, self._eviction_policy)',
    ),
    'lmcache/v1/distributed/storage_controllers/prefetch_controller.py': (
        "PREFETCH_LOOP_POLL_TIMEOUT_MS = 50 if int(_n1x_os.environ.get('N1X_RESTORE_WAIT_MS', '0')) > 0 else 500",
        'if defer_load(self, request, cells_by_l1):\n            return',
        'and not is_deferred(self, request.request_id)',
        'retry_deferred(self)',
    ),
    'lmcache/v1/distributed/l2_adapters/fs_l2_adapter.py': (
        '_n1x_install_disk_budget(FSL2Adapter, _filename_to_object_key)',
    ),
}


def verify_sources(root=None):
    root = installed_root() if root is None else root
    for relative, needles in REQUIRED.items():
        source = Patch(relative, 'verify', root=root)
        source.compile()
        for needle in needles:
            source.require(needle)
    for path in root.glob('n1x_*.py'):
        Patch(path, 'verify').compile()


def smoke_imports():
    # Import definitions only; do not construct allocators, wrappers or services.
    for module in (
        'lmcache.v1.platform.base.ipc_wire',
        'lmcache.v1.platform.devices.cuda.ipc_wrapper',
        'n1x_vmm', 'n1x_segmented', 'n1x_vmm_ipc',
        'n1x_cache_admission', 'n1x_restore_queue_v2', 'n1x_disk_cache',
    ):
        importlib.import_module(module)
    from lmcache.v1.platform.base.ipc_wire import VmmCudaIPCData
    from n1x_vmm import zeros

    if 'segments' not in VmmCudaIPCData.__struct_fields__ or not callable(zeros):
        raise RuntimeError('Unexpected patch target: verify: missing IPC/allocation definitions')


if __name__ == '__main__':
    verify_sources()
    smoke_imports()
    print('Patch source, compilation and import checks passed; GPU integration is separate.')
