"""Matched C1/C8 near-maximum-context speed and bounded quality, first scores kept."""
import argparse
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import threading
import time
import uuid

try:
    from benchmarks.speed_probe import Client, thinking_kwargs
except ModuleNotFoundError:
    from speed_probe import Client, thinking_kwargs


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def sample(index, characters):
    """Eight predetermined tasks; long inputs vary only with calibration size."""
    a, b, fee = 7+index, 23+index, 11+index
    codes = [f'CEDAR-{5831+index}', f'MAPLE-{9264+index}', f'BIRCH-{1748+index}']
    line = f'Archive {index:02d}: routine reference record; requests are validated, indexed, processed and stored.\n'
    filler = (line * (characters//len(line)+1))[:characters]
    markers = [f'\nAUTHORITATIVE cedar code: {codes[0]}; units: {a}.\n',
               f'\nAUTHORITATIVE maple code: {codes[1]}; unit_price_cents: {b}.\n',
               f'\nAUTHORITATIVE birch code: {codes[2]}; shipping_cents: {fee}.\n']
    cuts = [characters//10, characters//2, characters*9//10]
    archive = filler[:cuts[0]]+markers[0]+filler[cuts[0]:cuts[1]]+markers[1]+filler[cuts[1]:cuts[2]]+markers[2]+filler[cuts[2]:]
    system = 'Use only the authoritative archive facts and provided tool results. Follow the requested output format exactly.'
    payload = dict(model='qwen/qwen38fn-best', temperature=0, seed=42,
                   chat_template_kwargs=thinking_kwargs(True, 'xhigh'), stream=True,
                   stream_options={'include_usage':True})
    slot = index % 8
    if slot < 2:
        kind = 'needle-retrieval'
        question = 'Return only the cedar, maple and birch codes in that order, separated by a single colon.'
        expected = ':'.join(codes)
    elif slot < 4:
        kind = 'retrieval-arithmetic-json'
        question = 'Return only a JSON object with total_cents = units * unit_price_cents + shipping_cents, and birch = the birch code. No extra keys.'
        expected = dict(total_cents=a*b+fee, birch=codes[2])
    elif slot < 6:
        kind = 'structured-retrieval'
        question = 'Return only a JSON object with keys cedar, maple, birch, units, using their authoritative archive values. No extra keys.'
        expected = dict(cedar=codes[0], maple=codes[1], birch=codes[2], units=a)
    else:
        kind = 'tool-result-continuation'
        question = f'Look up inventory for AX-{index}. After the tool result, return only CASE-{index}:COUNT:BIRCH_CODE using that count and the archive birch code.'
        expected = f'CASE-{index}:{100+index}:{codes[2]}'
    payload['messages'] = [dict(role='system', content=system),
                           dict(role='user', content=archive+'\nQUESTION: '+question)]
    if isinstance(expected, dict):
        payload['response_format'] = {'type':'json_object'}
    if kind == 'tool-result-continuation':
        call_id = f'capacity-inventory-{index}'
        payload['tools'] = [dict(type='function', function=dict(name='lookup_inventory', description='Get inventory count.',
            parameters=dict(type='object', properties=dict(sku=dict(type='string')), required=['sku'], additionalProperties=False)))]
        payload['tool_choice'] = 'auto'
        payload['messages'] += [dict(role='assistant', content=None,
            reasoning_content=f'I need the inventory count for AX-{index} before giving the requested final answer.',
            tool_calls=[dict(id=call_id, type='function', function=dict(name='lookup_inventory', arguments=json.dumps(dict(sku=f'AX-{index}'))))]),
            dict(role='tool', tool_call_id=call_id, content=json.dumps(dict(sku=f'AX-{index}', count=100+index)))]
    return dict(id=f'near-limit-{index}', kind=kind, expected=expected, payload=payload)


def token_count(client, payload):
    fields = {k:deepcopy(payload[k]) for k in ('model','messages','tools','chat_template_kwargs') if k in payload}
    # The pinned ChatCompletionRequest normalizes this deprecated alias before
    # rendering. TokenizeChatRequest does not. Match chat's preprocessing on a
    # copy; preserve the original generation history and canonical precedence.
    for message in fields.get('messages',[]):
        legacy = message.pop('reasoning_content',None)
        if legacy is not None and message.get('reasoning') is None:
            message['reasoning'] = legacy
    result = client.get('/tokenize', dict(**fields, add_generation_prompt=True))
    if type(result.get('count')) is not int:
        raise ValueError('Server tokenizer did not return a rendered token count')
    return result['count']


def calibrate(client, index, limit, output, tolerance=8):
    target = limit-output-tolerance
    low, high = 0, target*12
    best = None
    while low <= high:
        middle = (low+high)//2
        row = sample(index, middle)
        count = token_count(client, row['payload'])
        if best is None or abs(count-target) < abs(best['input_tokens']-target):
            best = dict(**row, input_tokens=count)
        if abs(count-target) <= tolerance and count+output <= limit:
            return dict(**row, input_tokens=count)
        if count < target:
            low = middle+1
        else:
            high = middle-1
    if best is not None and abs(best['input_tokens']-target) <= tolerance and best['input_tokens']+output <= limit:
        return best
    raise ValueError(f'Cannot calibrate task {index} near the context limit')


def score(result, expected):
    if not result.get('stream_done') or result.get('finish_reason') != 'stop':
        return False
    text = (result.get('content') or '').strip()
    if not text:
        return False
    if isinstance(expected, dict):
        try:
            return json.loads(text) == expected
        except (ValueError, TypeError):
            return False
    return text == expected


def metrics(client):
    with client.open('/metrics') as response:
        text = response.read().decode()
    values = {}
    for line in text.splitlines():
        if not line or line.startswith('#'):
            continue
        name = line.split('{',1)[0].split()[0]
        if name not in ('vllm:num_requests_running','vllm:num_requests_waiting','vllm:num_preemptions_total'):
            continue
        try:
            value = float(line.rsplit(None,1)[1])
            if math.isfinite(value):
                values[name] = values.get(name,0)+value
        except ValueError:
            continue
    return values, text


def summarize_group(rows, concurrency, elapsed, before, after, samples, planned=8):
    completed = [r for r in rows if r.get('timing') and isinstance(r.get('usage'),dict)
                 and type(r['usage'].get('prompt_tokens')) is int and type(r['usage'].get('completion_tokens')) is int]
    rates = [None,None]
    # Missing requests/timing/cache evidence cannot silently improve a rate.
    cold_evidence = len(completed) == planned and all(
        (r['usage'].get('prompt_tokens_details') or {}).get('cached_tokens') == 0
        for r in completed)
    timing_valid = cold_evidence and all(
        r.get('rendered_input_matches') and r['timing'].get('pp_s') and r['timing'].get('decode_s') and
        (r['usage'].get('prompt_tokens_details') or {}).get('cached_tokens') == 0
        for r in completed)
    sources = sorted({(r['timing'].get('pp_source'),r['timing'].get('decode_source')) for r in completed}, key=str)
    if timing_valid and len(sources) == 1:
        rates = [sum(r['usage']['prompt_tokens'] for r in completed)/sum(r['timing']['pp_s'] for r in completed),
                 sum(max(r['usage']['completion_tokens']-1,0) for r in completed)/sum(r['timing']['decode_s'] for r in completed)]
    preempt = 'vllm:num_preemptions_total'
    preemptions = after[preempt]-before[preempt] if preempt in before and preempt in after and after[preempt] >= before[preempt] else None
    def maximum(name):
        values = [s['values'][name] for s in samples if name in s.get('values',{})]
        return max(values) if values else None
    lengths = [r['usage']['prompt_tokens'] for r in completed]
    generated = [r['usage']['completion_tokens'] for r in completed]
    return dict(client_concurrency=concurrency, first_attempt_correct=sum(r.get('correct',False) for r in rows),
        planned=planned, completed_streams=sum(r.get('stream_done',False) for r in rows), elapsed_s=elapsed,
        cold_cache_evidence_passed=cold_evidence,
        correct_tasks_s=sum(r.get('correct',False) for r in rows)/elapsed,
        read_write_tks=rates, timing_sources=sources,
        input_tokens_range=[min(lengths),max(lengths)] if lengths else None,
        generated_tokens_range=[min(generated),max(generated)] if generated else None,
        aggregate_input_output_tks=[sum(lengths)/elapsed,sum(generated)/elapsed] if len(completed)==planned else [None,None],
        aggregate_basis='Whole measured batch wall time; distinct from request-phase read/write rates',
        preemptions=preemptions, max_observed_running_requests=maximum('vllm:num_requests_running'),
        max_observed_waiting_requests=maximum('vllm:num_requests_waiting'),
        running_gauge_limit='Scheduled request count does not establish eight fully resident maximum-length KV histories',
        mean_client_ttft_s=sum(r['client_ttft_s'] for r in completed)/len(completed) if completed and all(r.get('client_ttft_s') is not None for r in completed) else None,
        mean_e2e_s=sum(r['timing']['e2e_s'] for r in completed)/len(completed) if completed else None)


def run(args, client=None):
    args.out.mkdir(parents=True, exist_ok=False)
    injected = client is not None
    client = client or Client(args.url, args.timeout)
    observation_client = client if injected else Client(args.url, 5)
    run_id = uuid.uuid4().hex
    settings = dict(protocol='n1x-near-limit-quality-v2', run_id=run_id, profile=args.profile,
        tokenizer_preprocessing='Match pinned chat reasoning_content-to-reasoning normalization; generation history unchanged',
        context_limit=args.context_limit, output_tokens=args.output_tokens, thinking=True, reasoning_effort='xhigh',
        concurrency=args.concurrency, tasks_per_repeat=8, repeats=args.repeats, tasks=8*args.repeats,
        source_hashes={name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                       for name in ('context_capacity_probe.py','speed_probe.py','timing.py')},
        requested_input_target=args.context_limit-args.output_tokens-8,
        first_scores_only=True, no_generation_warmups=True,
        scope='Two needle, two retrieval/arithmetic JSON, two structured retrieval and two provided-tool-result continuation tasks. Not a general reasoning/coding benchmark or full end-to-end tool loop.')
    if args.host_record:
        settings['host'] = json.loads(args.host_record.read_text(encoding='utf-8-sig'))
    settings['models'] = client.get('/v1/models')
    client.get('/health')
    save(args.out/'settings.json', settings)
    if args.prepared_from:
        prior = json.loads((args.prepared_from/'settings.json').read_text(encoding='utf-8-sig'))
        if any(prior.get(k) != settings.get(k) for k in ('protocol','context_limit','output_tokens','repeats','tasks','reasoning_effort')):
            raise ValueError('Prepared comparison uses a different context/output/task/effort plan')
        source = args.prepared_from/'prepared-requests.json'
        prepared = json.loads(source.read_text(encoding='utf-8-sig'))
        if len(prepared) != 8*args.repeats or any(token_count(client,r['payload']) != r['input_tokens'] for r in prepared):
            raise ValueError('Prepared requests do not match the current rendered token counts')
        settings['prepared_source'] = dict(directory=str(args.prepared_from.resolve()),sha256=hashlib.sha256(source.read_bytes()).hexdigest())
        save(args.out/'settings.json',settings)
    else:
        prepared = [calibrate(client,i,args.context_limit,args.output_tokens) for i in range(8*args.repeats)]
    save(args.out/'prepared-requests.json', prepared)
    groups = []
    lock = threading.Lock()
    for concurrency in args.concurrency:
        folder = args.out/f'c{concurrency}'
        folder.mkdir()
        samples = []
        before, raw_before = metrics(observation_client)
        (folder/'before.prom').write_text(raw_before, encoding='utf-8')
        stop = threading.Event()
        def monitor():
            while not stop.is_set():
                try:
                    values, _ = metrics(observation_client)
                    samples.append(dict(utc=datetime.now(timezone.utc).isoformat(), values=values))
                except Exception as error:
                    samples.append(dict(utc=datetime.now(timezone.utc).isoformat(), error=str(error)))
                stop.wait(1)
        observer = threading.Thread(target=monitor, daemon=True)
        observer.start()
        def ask(task):
            payload = dict(task['payload'], max_tokens=args.output_tokens, cache_salt=f'{run_id}-c{concurrency}-{task["id"]}')
            started = time.time()
            try:
                result = client.generate(payload)
                usage = result.get('usage') or {}
                valid_input = usage.get('prompt_tokens') == task['input_tokens']
                row = dict(task_id=task['id'], kind=task['kind'], expected=task['expected'], started_unix_s=started,
                    expected_input_tokens=task['input_tokens'], rendered_input_matches=valid_input,
                    correct=valid_input and score(result, task['expected']), request=payload, **result)
            except Exception as error:
                row = dict(task_id=task['id'],kind=task['kind'],correct=False,error=str(error),request=payload,started_unix_s=started)
            with lock:
                with (folder/'responses.jsonl').open('a',encoding='utf-8') as output:
                    output.write(json.dumps(row,allow_nan=False)+'\n')
            return row
        started = time.perf_counter()
        try:
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                rows = list(pool.map(ask, prepared))
            elapsed = time.perf_counter()-started
        finally:
            stop.set()
            observer.join(6)
            save(folder/'metrics-samples.json', samples)
        after, raw_after = metrics(observation_client)
        (folder/'after.prom').write_text(raw_after,encoding='utf-8')
        summary = summarize_group(rows,concurrency,elapsed,before,after,samples,planned=len(prepared))
        groups.append(summary)
        save(folder/'summary.json',summary)
        save(args.out/'summary.json',dict(settings=settings,groups=groups,complete=len(groups)==len(args.concurrency),
            quality_passed=len(groups)==len(args.concurrency) and all(g['first_attempt_correct']==g['planned'] for g in groups)))
        # Empty finals get one same-history diagnostic replay AFTER first-score
        # timing is closed. A recovered replay never replaces the original score.
        for row in rows:
            if row.get('stream_done') and not (row.get('content') or '').strip():
                try:
                    retry = client.generate(row['request'])
                    diagnostic = dict(task_id=row['task_id'],recovered=score(retry,row['expected']),first_score_unchanged=True,result=retry)
                except Exception as error:
                    diagnostic = dict(task_id=row['task_id'],recovered=False,error=str(error),first_score_unchanged=True)
                with (folder/'empty-final-diagnostics.jsonl').open('a',encoding='utf-8') as output:
                    output.write(json.dumps(diagnostic,allow_nan=False)+'\n')
        print(json.dumps(summary),flush=True)
    labels=' / '.join(f'C{c}' for c in args.concurrency)
    lines = [f'# Near-{args.context_limit:,}-token context at {labels}','',
        f'Thinking enabled, explicit xhigh; {args.output_tokens:,} output tokens reserved within the {args.context_limit:,}-token total context. '
        f'Actual rendered inputs and generated-token ranges are shown. {args.repeats} eight-task sets run at the stated client concurrency points, with fresh cache salts. '
        'This is a bounded synthetic quality check; scheduled requests do not prove eight fully resident maximum contexts.','',
        '| Client C | Input tokens | Generated tokens | First-score quality | Phase (read, write) tk/s | Batch seconds | Preemptions | Peak running / waiting |',
        '| ---: | --- | --- | ---: | --- | ---: | ---: | --- |']
    for g in groups:
        def pair(values):
            return '('+', '.join('—' if v is None else f'{v:.2f}' for v in values)+')'
        lines.append(f"| {g['client_concurrency']} | {g['input_tokens_range']} | {g['generated_tokens_range']} | {g['first_attempt_correct']}/{g['planned']} | {pair(g['read_write_tks'])} | {g['elapsed_s']:.2f} | {g['preemptions']} | {g['max_observed_running_requests']} / {g['max_observed_waiting_requests']} |")
    lines += ['', 'Phase rates sum request token counts and phase durations; batch time includes client waiting and all first attempts. '
        'Timing sources, whole-batch input/output throughput, latencies, raw requests, answers and counter snapshots are retained in JSON. '
        'Output lengths can differ despite identical tasks; this quality workload is separate from fixed-output speed curves.', '']
    (args.out/'comparison.md').write_text('\n'.join(lines),encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--profile',required=True)
    parser.add_argument('--url',default='http://127.0.0.1:8000')
    parser.add_argument('--context-limit',type=int,default=262144)
    parser.add_argument('--output-tokens',type=int,default=8192)
    parser.add_argument('--timeout',type=float,default=1800)
    parser.add_argument('--repeats',type=int,default=3)
    parser.add_argument('--concurrency',type=int,nargs='+',default=[1,8])
    parser.add_argument('--prepared-from',type=Path,help='Reuse the exact earlier task set for a fallback point without rerunning C1')
    parser.add_argument('--host-record',type=Path)
    args = parser.parse_args()
    if (args.context_limit <= args.output_tokens+1024 or args.output_tokens < 128 or args.timeout <= 0 or not 1<=args.repeats<=10
            or any(c not in (1,6,8) for c in args.concurrency) or len(set(args.concurrency))!=len(args.concurrency)):
        parser.error('Invalid context/output allowance or timeout')
    run(args)


if __name__ == '__main__':
    main()
