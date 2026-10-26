"""Apply source-guarded VMM compatibility patches to the cache image."""
from n1x_patch import Patch

# Running VMM after segmented would erase its initialization hook.
wrapper = Patch('lmcache/v1/platform/devices/cuda/ipc_wrapper.py', 'vmm')
wrapper.require('from n1x_segmented import', count=0)
source = Patch('vllm/v1/worker/utils.py', 'vmm')
old = '    buf = torch.zeros(buf_size, dtype=torch.int8, device=device)'
source.replace(old, '    from n1x_vmm import zeros\n    buf = zeros(buf_size, device)')
source.write()

body = wrapper.section('class VmmCudaIPCWrapper(')
validation = body.section('        tensor = attempt_permute_to_contiguous_view(tensor)',
                          '        data_ptr = tensor.data_ptr()')
body.replace(validation.original, '        tensor = attempt_permute_to_contiguous_view(tensor)\n\n')
old = '        nbytes = tensor.numel() * tensor.element_size()'
body.replace(old, '        nbytes = (1 + sum((n - 1) * s for n, s in zip(tensor.shape, tensor.stride()))) * tensor.element_size()')
old = '        return raw.view(self.dtype).reshape(self.shape)'
body.replace(old, '        return raw.view(self.dtype).as_strided(self.shape, self.stride)')
old = '        self._export_id = uuid.uuid4().bytes'
body.replace(old, "        from n1x_vmm import export_id_for\n        self._export_id = export_id_for(int(chunk_base))")
# Mapping identity is allocation-wide; wrapper equality must remain view-specific.
old = '        self.handle = self._export_id'
body.replace(old, '        self.handle = (self._export_id, self._alloc_offset)')
old = '        obj.handle = data.export_id'
body.replace(old, '        obj.handle = (data.export_id, data.alloc_offset)')
old = '        return VmmCudaIPCData('
body.replace(old, '''        if self._fd is not None:
            from n1x_vmm_ipc import publish
            publish(self._export_id, self._fd)
        return VmmCudaIPCData(''')
old = '            fd = _resolve_vmm_fd(self._export_id)'
body.replace(old, '''            if _VMM_FD_RESOLVER is None:
                from n1x_vmm_ipc import resolve
                fd = resolve(self._export_id)
            else:
                fd = _resolve_vmm_fd(self._export_id)''')
old = '            self._fd = None'
body.replace(old, '''            from n1x_vmm_ipc import withdraw
            withdraw(self._export_id, fd)
            self._fd = None''')
wrapper.replace(body.original, body.text)
wrapper.write()

# The native/batched transfer paths fail completion on this WSLC runtime.
# Keep upstream's asynchronous staged kernel/copy path as an opt-in fallback.
source = Patch('lmcache/v1/multiprocess/object_group_transfer.py', 'vmm')
source.require('_HAS_BATCH_MEMCPY_ASYNC', count=None)
source.require('_HAS_NATIVE_OBJECT_GROUP_TRANSFER', count=None)
source.require('N1X_LMCACHE_STAGED_TRANSFER', count=0)
source.text += '''
import os as _n1x_os
if _n1x_os.environ.get("N1X_LMCACHE_STAGED_TRANSFER") == "1":
    _HAS_BATCH_MEMCPY_ASYNC = False
    _HAS_NATIVE_OBJECT_GROUP_TRANSFER = False
'''
source.write()
