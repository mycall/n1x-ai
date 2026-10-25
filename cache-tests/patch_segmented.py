"""Exact-source guarded changes for the segmented-pool test image only."""
from pathlib import Path
import site

root = Path(site.getsitepackages()[0])


def edit(relative, old, new):
    path = root / relative
    source = path.read_text()
    if source.count(old) != 1:
        raise RuntimeError(f'Unexpected patch target: {relative}: {old[:70]}')
    path.write_text(source.replace(old, new))


edit('n1x_vmm.py', '        owner = Allocation(size, index)',
     '        from n1x_segmented import SegmentedAllocation\n        owner = SegmentedAllocation(size, index) if size >= 4 * 1024**3 else Allocation(size, index)')
wire = 'lmcache/v1/platform/base/ipc_wire.py'
edit(wire, 'class VmmCudaIPCData(IPCData, tag="cuda_vmm"):', 'class VmmCudaIPCData(IPCData, tag="cuda_vmm"):')
path = root / wire
source = path.read_text()
start, end = source.index('class VmmCudaIPCData'), source.index('class CpuShmIPCData')
part = source[start:end]
part = part.replace('    nbytes: NonNegative\n', '    nbytes: NonNegative\n    segments: tuple[tuple[bytes, int], ...] = ()\n')
part = part.replace('    def __post_init__(self) -> None:\n', '''    def __post_init__(self) -> None:
        if self.segments:
            if self.kind != "posix_fd" or sum(size for _, size in self.segments) != self.alloc_size:
                raise ValueError("Invalid segmented allocation")
            if any(len(key) != 16 or size <= 0 for key, size in self.segments):
                raise ValueError("Invalid segment descriptor")
''')
path.write_text(source[:start] + part + source[end:])

relative = 'lmcache/v1/platform/devices/cuda/ipc_wrapper.py'
path = root / relative
source = path.read_text()
start = source.index('class VmmCudaIPCWrapper(')
prefix, body = source[:start], source[start:]


def replace(old, new):
    global body
    if body.count(old) != 1:
        raise RuntimeError(f'Unexpected wrapper target: {old[:80]}')
    body = body.replace(old, new)


replace('        data_ptr = tensor.data_ptr()', '''        from n1x_segmented import initialize_wrapper
        if initialize_wrapper(self, tensor):
            return
        data_ptr = tensor.data_ptr()''')
replace('        return VmmCudaIPCData(', '''        from n1x_segmented import publish_segments
        publish_segments(self)
        return VmmCudaIPCData(''')
replace('            nbytes=self._nbytes,', '            nbytes=self._nbytes,\n            segments=getattr(self, "_segments", ()),')
replace('        obj._fd = None', '        obj._fd = None\n        obj._segments = data.segments\n        obj._segment_fds = []')
replace('        fd = getattr(self, "_fd", None)\n        if fd is not None:', '''        from n1x_segmented import close_exports
        close_exports(self)
        fd = getattr(self, "_fd", None)
        if fd is not None:''')
replace('            base_ptr, alloc_handle = entry.base_ptr, entry.alloc_handle', '''            base_ptr, alloc_handle = entry.base_ptr, entry.alloc_handle
            if isinstance(alloc_handle, list):
                from n1x_segmented import release_mapping
                release_mapping(base_ptr, self._alloc_size, alloc_handle)
                return''')
replace('        driver = _cuda.driver', '''        if getattr(self, "_segments", ()):
            from n1x_segmented import import_segments
            return import_segments(self, device_index, _VmmMapping)
        driver = _cuda.driver''')
replace('        state["_fd"] = None', '        state["_fd"] = None\n        state["_segment_fds"] = []')
path.write_text(prefix + body)
