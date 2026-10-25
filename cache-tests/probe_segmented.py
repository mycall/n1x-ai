"""Eight-GiB segmented IPC: boundary writes, 76 aliases, wire codec and teardown."""
import json
import multiprocessing as mp

import msgspec
import torch
from n1x_vmm import zeros
from lmcache.v1.platform.base.ipc_wire import VmmCudaIPCData
from lmcache.v1.platform.devices.cuda.ipc_wrapper import VmmCudaIPCWrapper

GIB = 1024**3


def receive(pipe):
    wrappers, views = [], []
    try:
        torch.cuda.init()
        for payload in pipe.recv():
            wire = msgspec.msgpack.decode(payload, type=VmmCudaIPCData)
            wrapper = VmmCudaIPCWrapper.from_wire(wire)
            wrappers.append(wrapper)
            view = wrapper.to_tensor()
            assert bool((view == 37).all())
            views.append(view)
        bases = {view.data_ptr() - wrapper._alloc_offset for view, wrapper in zip(views, wrappers)}
        assert len(bases) == 1
        for index, view in enumerate(views):
            view.fill_(11 if index < 76 else 23)
        torch.cuda.synchronize()
        views[0] = None
        wrappers[0].close()
        assert bool((views[75] == 11).all())
        pipe.send({'passed': True, 'aliases': 76, 'boundaryViews': 3, 'mappedPools': len(bases)})
        pipe.recv()
    except Exception as error:
        pipe.send({'passed': False, 'error': repr(error)})
    finally:
        views.clear()
        for wrapper in wrappers:
            wrapper.close()


if __name__ == '__main__':
    base = zeros(8*GIB, 'cuda:0')
    base.fill_(37)
    views = [base[4096+i*1024:].as_strided((4, 1, 16), (2*GIB, 16, 1)) for i in range(76)]
    views += [base[boundary-16:boundary+16] for boundary in (2*GIB, 4*GIB, 6*GIB)]
    wrappers = [VmmCudaIPCWrapper(view) for view in views]
    torch.cuda.synchronize()
    parent, child = mp.get_context('spawn').Pipe()
    process = mp.get_context('spawn').Process(target=receive, args=(child,))
    process.start()
    try:
        parent.send([msgspec.msgpack.encode(wrapper.to_wire()) for wrapper in wrappers])
        if not parent.poll(90):
            raise TimeoutError('Segmented IPC child timed out')
        result = parent.recv()
        if not result['passed']:
            raise RuntimeError(result)
        assert all(bool((view == (11 if index < 76 else 23)).all()) for index, view in enumerate(views))
        assert int(base[-1]) == 37 and int(base[100]) == 37
        parent.send('done')
        process.join(15)
        assert process.exitcode == 0
        print(json.dumps(result), flush=True)
    finally:
        if process.is_alive():
            process.kill()
            process.join()
        for wrapper in wrappers:
            wrapper.close()
