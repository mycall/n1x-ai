"""Seed two long prefixes, then verify concurrent SSD restores after restart."""
import argparse
import sys,json,time
from pathlib import Path
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,'/benchmarks')
from agent_cache_probe import Probe,save
p=Probe(SimpleNamespace(out=Path('/results'),url='http://127.0.0.1:8000'))
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('stage',choices=('seed','verify'))
args=parser.parse_args()
if args.stage=='seed':
    messages,tokens=p.archive(131000)
    salts=[p.salt+'-pair-'+str(i) for i in range(2)]
    save(p.out/'manifest.json',dict(messages=messages,tokens=tokens,salts=salts))
    for salt in salts:
        p.retrieve(messages,salt)
        print('Seed passed: '+salt,flush=True)
    deadline=time.monotonic()+60
    previous=None
    stable=0
    while time.monotonic()<deadline:
        counters=p.snapshot('seed-after')
        submitted=counters.get('lmcache_mp_l2_store_submitted_requests_total',0)
        completed=counters.get('lmcache_mp_l2_store_completed_requests_total',0)
        stable=stable+1 if submitted>0 and completed>=submitted and submitted==previous else 0
        if stable>=2:
            break
        previous=submitted
        time.sleep(1)
    else:
        raise RuntimeError('SSD stores did not settle before restart')
else:
    m=json.loads((p.out/'manifest.json').read_text())
    before=p.snapshot('before')
    start=time.monotonic()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda salt:p.retrieve(m['messages'],salt),m['salts']))
    elapsed=time.monotonic()-start
    after=p.snapshot('after')
    names=['vllm:prefix_cache_hits_total','vllm:external_prefix_cache_hits_total','vllm:num_preemptions_total','lmcache_mp_num_finished_retrieves_total','lmcache_mp_l2_prefetch_load_completed_chunks_total']
    delta={k:after.get(k,0)-before.get(k,0) for k in names}
    qualified=all(results) and delta[names[0]]==0 and delta[names[1]]>2*(m['tokens']-4096) and delta[names[3]]>=2 and delta[names[4]]>0
    result=dict(tokens_each=m['tokens'],correct=sum(results),elapsed_s=elapsed,qualified=qualified,delta=delta)
    save(p.out/'summary.json',result)
    print(json.dumps(result),flush=True)
    if not qualified: raise RuntimeError('Answers passed but full simultaneous external restores not established')
