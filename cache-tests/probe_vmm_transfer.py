"""Exercise LMCache's block kernel with the observed shared-pool geometry."""
import argparse
import json
import multiprocessing as mp
import torch
import lmcache.cuda_ops as ops
import lmcache.lmcache_native as native
from n1x_vmm import zeros
from lmcache.v1.platform.devices.cuda.ipc_wrapper import VmmCudaIPCWrapper

device = torch.device('cuda:0')
nb, nl, bs, hs, stride = 144, 12, 2048, 816, 28966912
nh, element_size = 1, 1
dtype = torch.uint8

def configure(layout):
    global nl, bs, hs, nh, element_size, dtype
    nl, bs, nh, hs, element_size = {
        'state': (12,2048,1,816,1), 'draft': (1,2048,1,112,1),
        'index': (13,512,1,128,2), 'kv': (13,2048,2,512,1),
    }[layout]
    dtype = torch.bfloat16 if element_size == 2 else torch.uint8

def transfer(pointers, block):
    ptrs = torch.tensor(pointers, dtype=torch.int64, device=device)
    ids = torch.tensor([block], dtype=torch.int64, device=device)
    staging = torch.zeros(nl*bs*nh*hs*element_size, dtype=torch.uint8, device=device)
    desc = native.PageBufferShapeDesc()
    for name, value in dict(kv_size=1, nl=nl, nb=nb, bs=bs, nh=nh, hs=hs,
                        element_size=element_size, block_stride_elems=stride//element_size).items():
        setattr(desc, name, value)
    torch.cuda.synchronize()
    ops.multi_layer_block_kv_transfer(ptrs, [staging.data_ptr()], ids, device,
        native.TransferDirection.D2H, desc, bs, native.EngineKVFormat.NL_X_NB_BS_NH_CS, 0)
    torch.cuda.synchronize()
    assert bool((staging == 37).all().item())

def receiver(pipe, block, layout):
    wrappers, views = [], []
    try:
        torch.cuda.init()
        configure(layout)
        wrappers = [VmmCudaIPCWrapper.from_wire(w) for w in pipe.recv()]
        views = [w.to_tensor() for w in wrappers]
        transfer([v.data_ptr() for v in views], block)
        pipe.send({'block': block, 'imported': True, 'passed': True})
        pipe.recv()
    except Exception as error:
        pipe.send({'passed': False, 'error': repr(error)})
    finally:
        views.clear()
        for wrapper in wrappers:
            wrapper.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--block', type=int, default=143)
    parser.add_argument('--imported', action='store_true')
    parser.add_argument('--layout', choices=['state','draft','index','kv'], default='state')
    args = parser.parse_args()
    configure(args.layout)
    base = zeros(nb * stride, device)
    base.fill_(37)
    if not args.imported:
        transfer([base.data_ptr() + i*bs*nh*hs*element_size for i in range(nl)], args.block)
        print(json.dumps({'block': args.block, 'passed': True}), flush=True)
    else:
        wrappers = [VmmCudaIPCWrapper(base[i*bs*nh*hs*element_size:].view(dtype).as_strided(
            (nb,bs,nh,hs),(stride//element_size,nh*hs,hs,1))) for i in range(nl)]
        torch.cuda.synchronize()
        parent, child = mp.get_context('spawn').Pipe()
        process = mp.get_context('spawn').Process(target=receiver, args=(child,args.block,args.layout))
        process.start()
        parent.send([w.to_wire() for w in wrappers])
        result = parent.recv() if parent.poll(60) else {'passed':False,'error':'timeout'}
        print(json.dumps(result), flush=True)
        if result['passed']:
            parent.send('done')
        process.join(5)
        if process.is_alive():
            process.kill()
            process.join()
        for wrapper in wrappers:
            wrapper.close()
        raise SystemExit(0 if result['passed'] else 1)
