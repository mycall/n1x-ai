"""Check CUDA IPC import before paying the cost of a full model load."""
import multiprocessing as mp
import torch
import json
import sys

def child(conn):
    try:
        torch.cuda.init()
        handle=conn.recv()
        storage=torch.UntypedStorage._new_shared_cuda(*handle)
        view=torch.empty(0, dtype=torch.uint8, device='cuda').set_(storage)
        value=int(view[0].item())
        conn.send({'import':'passed' if value == 0 else 'failed','bytes':storage.nbytes(),'firstByte':value})
        conn.recv()
    except Exception as e:
        conn.send({'import':'failed','error':str(e)})

if __name__=='__main__':
    ctx=mp.get_context('spawn')
    failed=False
    for mib in (1,64):
        parent, peer=ctx.Pipe()
        process=ctx.Process(target=child,args=(peer,))
        process.start()
        tensor=torch.zeros(mib*1024**2,dtype=torch.uint8,device='cuda')
        torch.cuda.synchronize()
        parent.send(tensor.untyped_storage()._share_cuda_())
        if parent.poll(30):
            result=parent.recv()
            print(json.dumps({'mib':mib,**result}),flush=True)
            failed |= result['import'] != 'passed'
            if result['import']=='passed': parent.send('done')
        else:
            print(json.dumps({'mib':mib,'import':'timeout'}),flush=True)
            process.terminate()
            failed=True
        process.join(10)
        if process.is_alive():
            process.kill()
            process.join()
        parent.close()
        peer.close()
    sys.exit(1 if failed else 0)
