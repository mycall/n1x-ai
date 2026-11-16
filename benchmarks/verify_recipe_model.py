"""Verify downloaded checkpoint shards against a pinned Hugging Face file manifest."""
import argparse
import hashlib
import json
from pathlib import Path
import time

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model',type=Path,required=True)
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--wait',type=int,default=0)
    a=p.parse_args()
    files=json.loads(a.manifest.read_text(encoding='utf-8-sig'))
    deadline=time.monotonic()+a.wait
    while True:
        missing=[f['path'] for f in files if not (a.model/f['path']).is_file() or (a.model/f['path']).stat().st_size!=f['size']]
        if not missing:
            break
        if time.monotonic()>=deadline:
            raise SystemExit(f'Missing or incomplete shards: {missing}')
        time.sleep(10)
    results=[]
    for record in files:
        path=(a.model/record['path']).resolve()
        if not path.is_relative_to(a.model.resolve()):
            raise ValueError('Manifest path outside model directory')
        with path.open('rb') as source:
            digest=hashlib.file_digest(source,'sha256').hexdigest()
        result=dict(path=record['path'],size=path.stat().st_size,sha256=digest,
                    verified=digest==record['lfs']['oid'])
        results.append(result)
        a.out.write_text(json.dumps(dict(complete=False,files=results),indent=2)+'\n')
        print(json.dumps(result),flush=True)
        if not result['verified']:
            raise RuntimeError(f'Checkpoint checksum mismatch: {path.name}')
    index=json.loads((a.model/'model.safetensors.index.json').read_text())
    indexed=set(index['weight_map'].values())
    if indexed!={r['path'] for r in files}:
        raise RuntimeError('Shard inventory differs from checkpoint index')
    a.out.write_text(json.dumps(dict(complete=True,files=results),indent=2)+'\n')

if __name__=='__main__':
    main()
