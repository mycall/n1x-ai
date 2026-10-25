"""Model-free IPC path isolation; producer stays alive until receiver exits."""
import multiprocessing as mp
import json
import torch


def receive(pipe, mode):
    try:
        torch.cuda.init()
        payload = pipe.recv()
        if mode == 'event':
            event = torch.cuda.Event.from_ipc_handle(0, payload)
            event.synchronize()
            result = {'passed': True}
        elif mode == 'raw':
            from lmcache.v1.platform.devices.cuda.ipc_wrapper import RawCudaIPCWrapper
            wrapper = RawCudaIPCWrapper.from_wire(payload)
            tensor = wrapper.to_tensor()
            result = {'passed': int(tensor[0].item()) == 37}
        else:
            storage = torch.UntypedStorage._new_shared_cuda(*payload)
            tensor = torch.empty(0, dtype=torch.uint8, device='cuda').set_(storage)
            result = {'passed': int(tensor[0].item()) == 37}
        pipe.send(result)
        pipe.recv()
    except Exception as error:
        pipe.send({'passed': False, 'error': str(error)})


if __name__ == '__main__':
    context = mp.get_context('spawn')
    for mode in ('torch', 'torch-no-event', 'event', 'raw'):
        parent, child = context.Pipe()
        process = context.Process(target=receive, args=(child, mode))
        process.start()
        try:
            tensor = torch.full((1024 * 1024,), 37, dtype=torch.uint8, device='cuda')
            torch.cuda.synchronize()
            if mode == 'event':
                event = torch.cuda.Event(interprocess=True)
                event.record()
                event.synchronize()
                payload = event.ipc_handle()
            elif mode == 'raw':
                from lmcache.v1.platform.devices.cuda.ipc_wrapper import RawCudaIPCWrapper
                wrapper = RawCudaIPCWrapper(tensor)
                payload = wrapper.to_wire()
            else:
                payload = tensor.untyped_storage()._share_cuda_()
                if mode == 'torch-no-event':
                    payload = (*payload[:-1], False)
            parent.send(payload)
            result = parent.recv() if parent.poll(30) else {'passed': False, 'error': 'timeout'}
            print(json.dumps({'mode': mode, **result}), flush=True)
            if result['passed']:
                parent.send('done')
        except Exception as error:
            print(json.dumps({'mode': mode, 'passed': False, 'error': str(error)}), flush=True)
        finally:
            process.join(3)
            if process.is_alive():
                process.kill()
                process.join()
            parent.close()
            child.close()
