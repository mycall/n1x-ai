"""Matched near-full tool replay after GPU-cache displacement by fresh histories."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import threading
import time
import uuid

from speed_probe import save
from context_capacity_probe import token_count, metrics
from near_full_tools_probe import calibrate, valid_call, assistant, TokenizingClient
from near_full_tools_report import counter


def run(args):
    args.out.mkdir(parents=True, exist_ok=False)
    client = TokenizingClient(args.url)
    client.get('/health')
    run_id = uuid.uuid4().hex
    save(args.out/'run.json', dict(protocol='n1x-displaced-tools-v1', run_id=run_id,
        target=args.target, concurrency=2, targets=2, pressure_histories=4, repeats=args.repeats,
        output_allowance=8192, host=json.loads(args.host.read_text(encoding='utf-8-sig')),
        source_hashes={name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ('displaced_tools_probe.py','near_full_tools_probe.py','speed_probe.py','timing.py')}))
    prepared = [calibrate(client, i, args.target)[0] for i in range(6)]
    lock = threading.Lock()
    def generate(body, phase, repeat, number):
        count = token_count(client, body)
        if count+8192 > 262144:
            raise ValueError('Insufficient output reserve')
        started = time.time()
        result = client.generate(body)
        row = dict(phase=phase, repeat=repeat, session=number, rendered_input=count,
                   started_unix_s=started, request=deepcopy(body), **result)
        with lock, (args.out/'requests.jsonl').open('a',encoding='utf-8') as file:
            file.write(json.dumps(row)+'\n')
        if (result.get('usage') or {}).get('prompt_tokens') != count:
            raise ValueError('Rendered input mismatch')
        print(json.dumps(dict(phase=phase,repeat=repeat,session=number,
            seconds=result['timing']['e2e_s'],cached=result['timing']['cached_tokens'])),flush=True)
        return result
    groups = []
    for repeat in range(args.repeats):
        bodies = [dict(deepcopy(body),cache_salt=f'{run_id}-r{repeat}-s{i}') for i,body in enumerate(prepared)]
        residency=[]
        for number, body in enumerate(bodies):
            phase = 'prime' if number<2 else 'pressure'
            result = generate(body,phase,repeat,number)
            if not valid_call(result,'lookup_inventory',f'AX-{number}-0'):
                raise RuntimeError(f'Invalid {phase} first tool call; raw first score retained')
            if result['timing']['cached_tokens'] != 0:
                raise RuntimeError(f'{phase} was not cold; displacement protocol invalid')
            if number<2:
                prime_label=f'r{repeat}-prime{number}'
                _,raw=metrics(client)
                (args.out/f'{prime_label}-before.prom').write_text(raw,encoding='utf-8')
                warm=generate(body,'prime-residency-check',repeat,number)
                _,raw=metrics(client)
                (args.out/f'{prime_label}-after.prom').write_text(raw,encoding='utf-8')
                a,b=(counter(args.out,prime_label,side,'vllm:prefix_cache_hits_total') for side in ('before','after'))
                resident=bool(a is not None and b is not None and b>a and
                              (warm['timing']['cached_tokens'] or 0)>0)
                residency.append(resident)
                if not valid_call(warm,'lookup_inventory',f'AX-{number}-0'):
                    raise RuntimeError('Prime residency-check tool call failed')
                if args.target>=8192 and not resident:
                    raise RuntimeError('Native residency was not established before displacement')
        # Selection snapshots exclude continuation hits, so native/external
        # cache evidence belongs to the replay wave rather than later requests.
        label=f'r{repeat}-selection'
        _, raw=metrics(client)
        (args.out/f'{label}-before.prom').write_text(raw,encoding='utf-8')
        started=time.monotonic()
        with ThreadPoolExecutor(max_workers=2) as pool:
            selected=list(pool.map(lambda n:generate(bodies[n],'replay-selection',repeat,n),range(2)))
        selection_seconds=time.monotonic()-started
        _, raw=metrics(client)
        (args.out/f'{label}-after.prom').write_text(raw,encoding='utf-8')
        def finish(number):
            result=selected[number]
            if not valid_call(result,'lookup_inventory',f'AX-{number}-0'):
                return dict(session=number,correct=False,error='invalid-replay-tool-call')
            body=deepcopy(bodies[number])
            body['messages'].append(assistant(result))
            value=23+number*7
            body['messages'].append(dict(role='tool',tool_call_id=result['tool_calls'][0]['id'],
                content=json.dumps(dict(sku=f'AX-{number}-0',count=value))))
            final=generate(body,'replay-continuation',repeat,number)
            expected=f'SESSION-{number:04d}:{value}:BIRCH-{1748+number}'
            correct=bool(final.get('stream_done') and final.get('finish_reason')=='stop' and
                not final.get('tool_calls') and (final.get('content') or '').strip()==expected)
            if not (final.get('content') or '').strip() and not final.get('tool_calls'):
                generate(body,'empty-final-diagnostic',repeat,number)
            return dict(session=number,correct=correct,expected=expected,actual=final.get('content'))
        with ThreadPoolExecutor(max_workers=2) as pool:
            tasks=list(pool.map(finish,range(2)))
        elapsed=time.monotonic()-started
        deltas={}
        for name in ('vllm:prefix_cache_hits_total','vllm:external_prefix_cache_hits_total','vllm:num_preemptions_total'):
            a,b=(counter(args.out,label,side,name) for side in ('before','after'))
            deltas[name]=b-a if a is not None and b is not None and b>=a else None
        cached=[r['timing']['cached_tokens'] for r in selected]
        native=deltas['vllm:prefix_cache_hits_total']
        external=deltas['vllm:external_prefix_cache_hits_total']
        group=dict(repeat=repeat,concurrency=2,planned_tasks=2,correct_tasks=sum(t['correct'] for t in tasks),
            elapsed_s=elapsed,selection_elapsed_s=selection_seconds,tasks=tasks,selection_cached_tokens=cached,
            cache_counter_deltas=deltas,prime_native_residency=residency,
            native_displacement_verified=all(residency) and native==0,
            external_restore_verified=bool(all(residency) and native==0 and external is not None and external>0 and
                all(type(n) is int and n>0 for n in cached)),
            selection_results=selected)
        groups.append(group)
        save(args.out/'summary.json',groups)
        print(json.dumps({k:v for k,v in group.items() if k not in ('selection_results','tasks')}),flush=True)
    if not all(g['correct_tasks']==2 for g in groups):
        raise SystemExit('Replay first-attempt correctness failed')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8000')
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--host',type=Path,required=True)
    parser.add_argument('--target',type=int,default=250000)
    parser.add_argument('--repeats',type=int,default=2)
    args=parser.parse_args()
    if not 1024<=args.target<=250000 or not 1<=args.repeats<=10:
        parser.error('Invalid target or repeat count')
    run(args)
