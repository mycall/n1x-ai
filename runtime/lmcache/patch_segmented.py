"""Apply source-guarded segmented-pool compatibility changes."""
from n1x_patch import Patch

# VMM removes the validation region where we install initialize_wrapper.
# Check the predecessor before changing any files.
wrapper = Patch('lmcache/v1/platform/devices/cuda/ipc_wrapper.py', 'segmented')
wrapper.require('        self._export_id = export_id_for(int(chunk_base))')
wrapper.require('        return raw.view(self.dtype).as_strided(self.shape, self.stride)')
wrapper.require('from n1x_segmented import', count=0)

allocation = Patch('n1x_vmm.py', 'segmented')
allocation.replace('        owner = Allocation(size, index)',
     '        from n1x_segmented import SegmentedAllocation\n        owner = SegmentedAllocation(size, index) if size >= 4 * 1024**3 else Allocation(size, index)')
allocation.write()
wire = 'lmcache/v1/platform/base/ipc_wire.py'
source = Patch(wire, 'segmented')
source.require('class VmmCudaIPCData(IPCData, tag="cuda_vmm"):')
part = source.section('class VmmCudaIPCData', 'class CpuShmIPCData')
part.require('    segments:', count=0)
part.replace('    nbytes: NonNegative\n', '    nbytes: NonNegative\n    segments: tuple[tuple[bytes, int], ...] = ()\n')
part.replace('    def __post_init__(self) -> None:\n', '''    def __post_init__(self) -> None:
        if self.segments:
            if self.kind != "posix_fd" or sum(size for _, size in self.segments) != self.alloc_size:
                raise ValueError("Invalid segmented allocation")
            if any(len(key) != 16 or size <= 0 for key, size in self.segments):
                raise ValueError("Invalid segment descriptor")
''')
source.replace(part.original, part.text)
source.write()

body = wrapper.section('class VmmCudaIPCWrapper(')

body.replace('        data_ptr = tensor.data_ptr()', '''        from n1x_segmented import initialize_wrapper
        if initialize_wrapper(self, tensor):
            return
        data_ptr = tensor.data_ptr()''')
body.replace('        return VmmCudaIPCData(', '''        from n1x_segmented import publish_segments
        publish_segments(self)
        return VmmCudaIPCData(''')
body.replace('            nbytes=self._nbytes,', '            nbytes=self._nbytes,\n            segments=getattr(self, "_segments", ()),')
body.replace('        obj._fd = None', '        obj._fd = None\n        obj._segments = data.segments\n        obj._segment_fds = []')
body.replace('        fd = getattr(self, "_fd", None)\n        if fd is not None:', '''        from n1x_segmented import close_exports
        close_exports(self)
        fd = getattr(self, "_fd", None)
        if fd is not None:''')
body.replace('            base_ptr, alloc_handle = entry.base_ptr, entry.alloc_handle', '''            base_ptr, alloc_handle = entry.base_ptr, entry.alloc_handle
            if isinstance(alloc_handle, list):
                from n1x_segmented import release_mapping
                release_mapping(base_ptr, self._alloc_size, alloc_handle)
                return''')
body.replace('        driver = _cuda.driver', '''        if getattr(self, "_segments", ()):
            from n1x_segmented import import_segments
            return import_segments(self, device_index, _VmmMapping)
        driver = _cuda.driver''')
body.replace('        state["_fd"] = None', '        state["_fd"] = None\n        state["_segment_fds"] = []')
wrapper.replace(body.original, body.text)
wrapper.write()
