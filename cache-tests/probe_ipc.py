"""Small CUDA IPC qualification; no model load."""
import json
import traceback
import torch
import argparse

parser = argparse.ArgumentParser()
parser.add_argument('--many', action='store_true')
parser.add_argument('--ballast-gib', type=int, default=0)
parser.add_argument('--sizes-mib', type=int, nargs='+')
args = parser.parse_args()
ballast = torch.empty(args.ballast_gib * 1024**3, dtype=torch.uint8, device='cuda')
retained = []

results = {'torch': torch.__version__, 'device': torch.cuda.get_device_name(0), 'tests': []}
sizes = [value * 1024**2 for value in args.sizes_mib] if args.sizes_mib else ([128 * 1024 * 1024] * 76 if args.many else (1024, 1024 * 1024, 64 * 1024 * 1024))
for size in sizes:
    try:
        tensor = torch.zeros(size, dtype=torch.uint8, device='cuda')
        torch.cuda.synchronize()
        handle = tensor.untyped_storage()._share_cuda_()
        results['tests'].append({'bytes': size, 'shareCuda': 'passed', 'handleFields': len(handle), 'freeBytes': torch.cuda.mem_get_info()[0]})
        retained.append((tensor, handle))
    except Exception as error:
        results['tests'].append({'bytes': size, 'shareCuda': 'failed', 'error': str(error), 'traceback': traceback.format_exc()})
        break
try:
    event = torch.cuda.Event(interprocess=True)
    event.record()
    event.synchronize()
    event.ipc_handle()
    results['eventIpc'] = 'passed'
except Exception as error:
    results['eventIpc'] = str(error)
print(json.dumps(results, indent=2), flush=True)
