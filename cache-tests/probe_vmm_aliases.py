"""Reproduce many layer views sharing one VMM allocation, without model weights."""
import argparse
import json
import multiprocessing as mp
import torch
from n1x_vmm import zeros
from lmcache.v1.platform.devices.cuda.ipc_wrapper import VmmCudaIPCWrapper


def receive(pipe):
    wrappers, views = [], []
    try:
        torch.cuda.init()
        for index, wire in enumerate(pipe.recv()):
            wrapper = VmmCudaIPCWrapper.from_wire(wire)
            wrappers.append(wrapper)
            views.append(wrapper.to_tensor())
            if int(views[-1][0].item()) != 37:
                raise RuntimeError('Imported bytes differ')
            pipe.send({'index': index, 'passed': True})
        bases = {view.data_ptr() - index * 1024 for index, view in enumerate(views)}
        if len(bases) != 1:
            raise RuntimeError(f'Expected one mapping, got {len(bases)}')
        views[0] = None
        wrappers[0].close()
        if int(views[-1][0].item()) != 37:
            raise RuntimeError('Closing one alias invalidated another')
        pipe.send({'done': True, 'sharedMappings': len(bases), 'closeOneAliasPassed': True})
        pipe.recv()
    except Exception as error:
        pipe.send({'passed': False, 'mapped': len(views), 'error': repr(error)})
    finally:
        views.clear()
        for wrapper in wrappers:
            wrapper.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mib', type=int, default=4000)
    parser.add_argument('--aliases', type=int, default=76)
    args = parser.parse_args()
    base = zeros(args.mib * 1024**2, 'cuda:0')
    base.fill_(37)
    wrappers = [VmmCudaIPCWrapper(base[i*1024:(i+1)*1024]) for i in range(args.aliases)]
    if args.aliases > 1 and wrappers[0] == wrappers[1]:
        raise RuntimeError('Different layer offsets compare equal')
    for wrapper in wrappers:
        if wrapper != VmmCudaIPCWrapper.from_wire(wrapper.to_wire()):
            raise RuntimeError('Wire roundtrip changed view identity')
    torch.cuda.synchronize()
    parent, child = mp.get_context('spawn').Pipe()
    process = mp.get_context('spawn').Process(target=receive, args=(child,))
    process.start()
    parent.send([wrapper.to_wire() for wrapper in wrappers])
    passed = False
    while parent.poll(60):
        result = parent.recv()
        print(json.dumps(result), flush=True)
        if result.get('done'):
            passed = True
            parent.send('done')
            break
        if not result.get('passed'):
            break
    process.join(5)
    if process.is_alive():
        process.kill()
        process.join()
    for wrapper in wrappers:
        wrapper.close()
    raise SystemExit(0 if passed else 1)
