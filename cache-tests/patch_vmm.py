"""Version-checked experimental patches, confined to the VMM test image."""
from pathlib import Path
import site
root = Path(site.getsitepackages()[0])
path = root / 'vllm/v1/worker/utils.py'
source = path.read_text()
old = '    buf = torch.zeros(buf_size, dtype=torch.int8, device=device)'
assert source.count(old) == 1
source = source.replace(old, '    from n1x_vmm import zeros\n    buf = zeros(buf_size, device)')
path.write_text(source)

path = root / 'lmcache/v1/platform/devices/cuda/ipc_wrapper.py'
source = path.read_text()
start = source.index('class VmmCudaIPCWrapper(')
prefix, body = source[:start], source[start:]
a = body.index('        tensor = attempt_permute_to_contiguous_view(tensor)')
b = body.index('        data_ptr = tensor.data_ptr()', a)
body = body[:a] + '''        tensor = attempt_permute_to_contiguous_view(tensor)

''' + body[b:]
old = '        nbytes = tensor.numel() * tensor.element_size()'
assert body.count(old) == 1
body = body.replace(old, '        nbytes = (1 + sum((n - 1) * s for n, s in zip(tensor.shape, tensor.stride()))) * tensor.element_size()')
old = '        return raw.view(self.dtype).reshape(self.shape)'
assert body.count(old) == 1
body = body.replace(old, '        return raw.view(self.dtype).as_strided(self.shape, self.stride)')
old = '        self._export_id = uuid.uuid4().bytes'
assert body.count(old) == 1
body = body.replace(old, "        from n1x_vmm import export_id_for\n        self._export_id = export_id_for(int(chunk_base))")
# Mapping identity is allocation-wide; wrapper equality must remain view-specific.
old = '        self.handle = self._export_id'
assert body.count(old) == 1
body = body.replace(old, '        self.handle = (self._export_id, self._alloc_offset)')
old = '        obj.handle = data.export_id'
assert body.count(old) == 1
body = body.replace(old, '        obj.handle = (data.export_id, data.alloc_offset)')
old = '        return VmmCudaIPCData('
assert body.count(old) == 1
body = body.replace(old, '''        if self._fd is not None:
            from n1x_vmm_ipc import publish
            publish(self._export_id, self._fd)
        return VmmCudaIPCData(''')
old = '            fd = _resolve_vmm_fd(self._export_id)'
assert body.count(old) == 1
body = body.replace(old, '''            if _VMM_FD_RESOLVER is None:
                from n1x_vmm_ipc import resolve
                fd = resolve(self._export_id)
            else:
                fd = _resolve_vmm_fd(self._export_id)''')
old = '            self._fd = None'
assert body.count(old) == 1
body = body.replace(old, '''            from n1x_vmm_ipc import withdraw
            withdraw(self._export_id, fd)
            self._fd = None''')
path.write_text(prefix + body)

# The native/batched transfer paths fail completion on this WSLC runtime.
# Keep upstream's asynchronous staged kernel/copy path as an opt-in fallback.
path = root / 'lmcache/v1/multiprocess/object_group_transfer.py'
source = path.read_text()
assert '_HAS_BATCH_MEMCPY_ASYNC' in source
assert '_HAS_NATIVE_OBJECT_GROUP_TRANSFER' in source
source += '''
import os as _n1x_os
if _n1x_os.environ.get("N1X_LMCACHE_STAGED_TRANSFER") == "1":
    _HAS_BATCH_MEMCPY_ASYNC = False
    _HAS_NATIVE_OBJECT_GROUP_TRANSFER = False
'''
path.write_text(source)
