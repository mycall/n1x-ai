"""Near-full appended tool histories; first scores and cache evidence retained.

Run against an already verified server. No restart, cache flush, or model loading.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import threading
import time
import urllib.error
import uuid

from speed_probe import Client, save, thinking_kwargs
from context_capacity_probe import token_count, metrics


class TokenizingClient(Client):
    """Retry only read-only tokenization transport failures, never generation."""
    def get(self, path, body=None):
        for attempt in range(3):
            try:
                return super().get(path, body)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
                if path != '/tokenize' or isinstance(error, urllib.error.HTTPError) or attempt == 2:
                    raise
                print(f'Tokenization transport retry {attempt+1}: {error}', flush=True)
                time.sleep(attempt+1)


TOOLS = [dict(type='function', function=dict(name=name, description=description,
    parameters=dict(type='object', properties=dict(sku=dict(type='string')),
                    required=['sku'], additionalProperties=False))) for name, description in (
    ('lookup_inventory', 'Return current inventory count for a SKU.'),
    ('lookup_price', 'Return current price in cents for a SKU.'))]


def question(number, turn):
    kind = 'inventory' if turn % 2 == 0 else 'price'
    return (f'Look up {kind} for SKU AX-{number}-{turn}. Use the appropriate tool. '
            'After its result return only SESSION_CODE:VALUE:BIRCH_CODE, using the '
            'archive codes and the returned count or price_cents. No other text.')


def payload(number, characters):
    unit = 'Archive reference: routine warehouse records are indexed and stored for later review.\n'
    filler = (unit * (characters // len(unit) + 1))[:characters]
    a, b = characters // 10, characters * 9 // 10
    archive = (filler[:a] + f'\nAUTHORITATIVE session code: SESSION-{number:04d}.\n' +
               filler[a:b] + f'\nAUTHORITATIVE birch code: BIRCH-{1748+number}.\n' + filler[b:])
    return dict(model='qwen/qwen38fn-best', temperature=0, seed=42, max_tokens=8192,
        stream=True, stream_options={'include_usage': True}, tools=deepcopy(TOOLS), tool_choice='auto',
        chat_template_kwargs=thinking_kwargs(True, 'xhigh'), messages=[
            dict(role='system', content='Use the requested lookup tool; never guess its result. '
                 'Preserve the requested SKU exactly. Use authoritative archive codes and tool results. '
                 'Follow the requested output format exactly.'),
            dict(role='user', content=archive+'\n'+question(number, 0))])


def calibrate(client, number, target):
    low, high = 0, target * 12
    while low <= high:
        middle = (low + high) // 2
        body = payload(number, middle)
        count = token_count(client, body)
        if abs(count-target) <= 8:
            return body, count
        if count < target:
            low = middle + 1
        else:
            high = middle - 1
    raise ValueError('Cannot calibrate initial tool prompt')


def valid_call(result, name, sku):
    calls = result.get('tool_calls') or []
    if not result.get('stream_done') or result.get('finish_reason') != 'tool_calls' or len(calls) != 1:
        return False
    call = calls[0]
    try:
        return bool(call.get('id') and call.get('type') == 'function' and
                    call['function']['name'] == name and
                    json.loads(call['function']['arguments']) == {'sku': sku})
    except (KeyError, TypeError, ValueError):
        return False


def assistant(result):
    message = dict(role='assistant', content=result.get('content') or None)
    if result.get('reasoning'):
        message['reasoning'] = result['reasoning']
    if result.get('tool_calls'):
        message['tool_calls'] = deepcopy(result['tool_calls'])
    return message


def run(args):
    args.out.mkdir(parents=True, exist_ok=False)
    client = TokenizingClient(args.url)
    client.get('/health')
    run_id = uuid.uuid4().hex
    metadata = dict(protocol='n1x-near-full-tools-v1', started_utc=datetime.now(timezone.utc).isoformat(),
        run_id=run_id, target=args.target, context_limit=262144, output_allowance=8192,
        concurrency=args.concurrency, sessions=args.sessions, turns=args.turns, repeats=args.repeats,
        thinking=True, reasoning_effort='xhigh', temperature=0, seed=42,
        models=client.get('/v1/models'), host=json.loads(args.host.read_text(encoding='utf-8-sig')),
        source_hashes={name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ('near_full_tools_probe.py', 'speed_probe.py', 'context_capacity_probe.py', 'timing.py')})
    save(args.out/'run.json', metadata)
    lock = threading.Lock()
    def record(filename, row):
        with lock, (args.out/filename).open('a', encoding='utf-8') as file:
            file.write(json.dumps(row)+'\n')
    prepared = [calibrate(client, i, args.target) for i in range(args.sessions)]
    save(args.out/'calibration.json', [dict(session=i, tokens=n) for i, (_, n) in enumerate(prepared)])
    print('Calibrated initial inputs: '+str([n for _, n in prepared]), flush=True)
    groups = []
    for repeat in range(args.repeats):
        order = args.concurrency if repeat % 2 == 0 else list(reversed(args.concurrency))
        for concurrency in order:
            label = f'r{repeat}-c{concurrency}'
            before, raw = metrics(client)
            (args.out/f'{label}-before.prom').write_text(raw, encoding='utf-8')
            def session(number):
                body = deepcopy(prepared[number][0])
                body['cache_salt'] = f'{run_id}-{label}-s{number}'
                correct = 0
                requests = []
                def generate(turn, phase, diagnostic=False):
                    count = token_count(client, body)
                    if count + body['max_tokens'] > 262144:
                        raise ValueError(f'History exceeds reserved context: {count}+8192')
                    started_unix_s = time.time()
                    result = client.generate(body)
                    usage = result.get('usage') or {}
                    result['rendered_input_matches'] = usage.get('prompt_tokens') == count
                    row = dict(group=label, session=number, turn=turn, phase=phase, diagnostic=diagnostic,
                               rendered_input=count, started_unix_s=started_unix_s,
                               request=deepcopy(body), **result)
                    record('requests.jsonl', row)
                    if not diagnostic:
                        requests.append({k:v for k,v in row.items() if k != 'request'})
                    print(json.dumps(dict(group=label, session=number, turn=turn, phase=phase,
                        diagnostic=diagnostic, input=count, cached=(usage.get('prompt_tokens_details') or {}).get('cached_tokens'),
                        output=usage.get('completion_tokens'), finish=result.get('finish_reason'),
                        seconds=result['timing']['e2e_s'])), flush=True)
                    if not result['rendered_input_matches']:
                        raise ValueError('Rendered input differs from response usage')
                    return result
                try:
                    for turn in range(args.turns):
                        start = time.monotonic()
                        if turn:
                            body['messages'].append(dict(role='user', content=question(number, turn)))
                        name = 'lookup_inventory' if turn % 2 == 0 else 'lookup_price'
                        sku = f'AX-{number}-{turn}'
                        selected = generate(turn, 'cold-selection' if turn == 0 else 'appended-selection')
                        if not valid_call(selected, name, sku):
                            record('tasks.jsonl', dict(group=label, session=number, turn=turn, correct=False, error='invalid-tool-call'))
                            break
                        body['messages'].append(assistant(selected))
                        value = 23 + number * 7 + turn
                        field = 'count' if name == 'lookup_inventory' else 'price_cents'
                        body['messages'].append(dict(role='tool', tool_call_id=selected['tool_calls'][0]['id'],
                            content=json.dumps(dict(sku=sku, **{field:value}))))
                        final = generate(turn, 'tool-continuation')
                        expected = f'SESSION-{number:04d}:{value}:BIRCH-{1748+number}'
                        passed = bool(final.get('stream_done') and final.get('finish_reason') == 'stop' and
                                      not final.get('tool_calls') and (final.get('content') or '').strip() == expected)
                        correct += int(passed)
                        record('tasks.jsonl', dict(group=label, session=number, turn=turn, correct=passed,
                            expected=expected, actual=final.get('content'), elapsed_s=time.monotonic()-start))
                        if not (final.get('content') or '').strip() and not final.get('tool_calls'):
                            generate(turn, 'empty-final-retry', diagnostic=True)
                        if not passed:
                            break
                        body['messages'].append(assistant(final))
                except Exception as error:
                    record('errors.jsonl', dict(group=label, session=number, error=repr(error)))
                return dict(session=number, correct_tasks=correct, planned_tasks=args.turns, requests=requests)
            start = time.monotonic()
            stop = threading.Event()
            def monitor():
                observer = Client(args.url, timeout=5)
                while not stop.is_set():
                    try:
                        values, _ = metrics(observer)
                        host_path=Path(__file__).resolve().parents[1]/'.state/n1x-qwen38fn-best/host.json'
                        try:
                            host_memory=json.loads(host_path.read_text(encoding='utf-8-sig'))
                        except (OSError, ValueError):
                            host_memory=None
                        record('scheduler.jsonl', dict(group=label, unix_s=time.time(), values=values,host_memory=host_memory))
                    except Exception as error:
                        record('scheduler.jsonl', dict(group=label, unix_s=time.time(), error=str(error)))
                    stop.wait(2)
            watcher = threading.Thread(target=monitor, daemon=True)
            watcher.start()
            try:
                with ThreadPoolExecutor(max_workers=concurrency) as pool:
                    results = list(pool.map(session, range(args.sessions)))
            finally:
                stop.set()
                watcher.join(6)
            elapsed = time.monotonic()-start
            # Persist completed first attempts before querying a possibly dead
            # server. Missing final telemetry must not erase the group evidence.
            partial=dict(group=label,concurrency=concurrency,repeat=repeat,elapsed_s=elapsed,
                correct_tasks=sum(r['correct_tasks'] for r in results),
                planned_tasks=args.sessions*args.turns,sessions=results,telemetry_complete=False)
            save(args.out/'partial-group.json',partial)
            after, raw = metrics(client)
            (args.out/f'{label}-after.prom').write_text(raw, encoding='utf-8')
            correct = sum(r['correct_tasks'] for r in results)
            group = dict(group=label, concurrency=concurrency, repeat=repeat, elapsed_s=elapsed,
                correct_tasks=correct, planned_tasks=args.sessions*args.turns, correct_tasks_s=correct/elapsed,
                preemptions=after.get('vllm:num_preemptions_total',0)-before.get('vllm:num_preemptions_total',0),
                sessions=results)
            groups.append(group)
            save(args.out/'summary.json', groups)
            print(json.dumps({k:v for k,v in group.items() if k != 'sessions'}), flush=True)
    if sum(g['correct_tasks'] for g in groups) != len(groups)*args.sessions*args.turns:
        raise SystemExit('Incomplete qualification: inspect first scores and errors')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8000')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--host', type=Path, required=True)
    parser.add_argument('--target', type=int, default=250000)
    parser.add_argument('--concurrency', nargs='+', type=int, choices=(1,2,4), default=[1,2])
    parser.add_argument('--sessions', type=int, default=2)
    parser.add_argument('--turns', type=int, default=3)
    parser.add_argument('--repeats', type=int, default=2)
    args = parser.parse_args()
    if (not 1024 <= args.target <= 250000 or min(args.sessions,args.turns,args.repeats) < 1
            or args.sessions < max(args.concurrency) or len(set(args.concurrency)) != len(args.concurrency)):
        parser.error('Target must be 1024..250000 and counts positive')
    run(args)
