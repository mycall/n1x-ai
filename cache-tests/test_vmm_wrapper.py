"""Cross-process data, stride, offset, writeback and padding checks."""
import json
import argparse
import multiprocessing as mp
from multiprocessing.reduction import send_handle, recv_handle
import sys
import torch
from n1x_vmm import zeros
from lmcache.v1.platform.devices.cuda.ipc_wrapper import VmmCudaIPCWrapper, set_vmm_fd_resolver

def receiver(pipe):
    try:
        torch.cuda.init()
        wire = pipe.recv()
        # Use the same FD broker as the real LMCache worker/server path.
        wrapper = VmmCudaIPCWrapper.from_wire(wire)
        view = wrapper.to_tensor()
        assert tuple(view.stride()) == (1024, 16, 1)
        assert bool((view == 37).all().item())
        view.fill_(11)
        torch.cuda.synchronize()
        pipe.send({'passed': True})
        pipe.recv()
        del view
        wrapper.close()
    except Exception as error:
        pipe.send({'passed': False, 'error': repr(error)})

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mib', type=int, nargs='+', default=[64, 4000])
    parser.add_argument('--retain-allocations', action='store_true')
    args = parser.parse_args()
    if any(mib <= 0 for mib in args.mib):
        parser.error('--mib values must be positive')
    retained = []
    for mib in args.mib:
        base = zeros(mib * 1024**2, 'cuda:0')
        base.fill_(37)
        view = base[8:8 + 64*1024].view(64, 1024)[:, :512].view(64, 32, 16)
        wrapper = VmmCudaIPCWrapper(view)
        torch.cuda.synchronize()
        ctx = mp.get_context('spawn')
        parent, child = ctx.Pipe()
        process = ctx.Process(target=receiver, args=(child,))
        process.start()
        parent.send(wrapper.to_wire())
        result = parent.recv() if parent.poll(60) else {'passed': False, 'error': 'timeout'}
        if result['passed']:
            assert bool((view == 11).all().item())
            assert bool((base[8:8+64*1024].view(64,1024)[:,512:] == 37).all().item())
            assert int(base[0].item()) == 37 and int(base[-1].item()) == 37
            parent.send('done')
        print(json.dumps({'mib': mib, **result}), flush=True)
        process.join(5)
        if process.is_alive():
            process.kill()
            process.join()
        wrapper.close()
        if args.retain_allocations:
            retained.append(base)
        del wrapper, view, base
        if not result['passed']:
            sys.exit(1)
    if retained:
        print(json.dumps({'retainedTotalMiB': sum(args.mib), 'allocations': len(retained), 'passed': True}), flush=True)
