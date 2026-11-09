"""Compare serving profiles with identical short prompts, one request at a time."""
import argparse
import json
import time
import urllib.request
import uuid
from pathlib import Path
try:
    from benchmarks.timing import phase_timing
except ModuleNotFoundError:
    from timing import phase_timing
parser = argparse.ArgumentParser(description='Short single-request speculation comparison; run each serving profile separately.')
parser.add_argument('--out', type=Path, required=True)
parser.add_argument('--url', default='http://127.0.0.1:8000')
parser.add_argument('--thinking', action=argparse.BooleanOptionalAction, default=True)
args = parser.parse_args()
arm = uuid.uuid4().hex
out = args.out
out.mkdir(parents=True, exist_ok=True)
http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
tasks = {
    'json': 'Return only a JSON array of objects for integers 1 through 20. Each object must have keys n, square, cube with the integer and its square and cube. No markdown.',
    'code': 'Write a complete Python implementation of a bounded LRU cache using collections.OrderedDict, with get and put methods, type hints, and a small usage example. Explain how eviction works.',
    'explain': 'Explain how a database B-tree index speeds up queries. Cover equality, range scans, composite indexes, and the cost of writes. Use concrete examples in about 300 words.'
}

def metrics(label):
    with http.open(args.url + '/metrics', timeout=15) as r:
        (out / f'{label}.prom').write_bytes(r.read())
metrics('before')
rows = []
for task, prompt in tasks.items():
    for repeat in range(2):
        body = dict(model='qwen/qwen38fn-best', messages=[dict(role='user', content=prompt)], temperature=0, max_tokens=2048 if args.thinking else 512, stream=True, stream_options={'include_usage': True}, chat_template_kwargs={'enable_thinking': args.thinking}, cache_salt=f'compare-{arm}-{task}')
        req = urllib.request.Request(args.url + '/v1/chat/completions', data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
        start = time.perf_counter()
        first = None
        text = ''
        reasoning = ''
        usage = {}
        request_metrics = {}
        finish = None
        with http.open(req, timeout=600) as r:
            for line in r:
                if not line.startswith(b'data: '):
                    continue
                if line.strip() == b'data: [DONE]':
                    break
                chunk = json.loads(line[6:])
                if chunk.get('usage'):
                    usage = chunk['usage']
                if chunk.get('metrics'):
                    request_metrics = chunk['metrics']
                for choice in chunk.get('choices', []):
                    piece = choice.get('delta', {}).get('content') or ''
                    delta = choice.get('delta', {})
                    reasoning += delta.get('reasoning') or delta.get('reasoning_content') or ''
                    if (piece or delta.get('reasoning') or delta.get('reasoning_content')) and first is None:
                        first = time.perf_counter()
                    text += piece
                    if choice.get('finish_reason'):
                        finish = choice['finish_reason']
        end = time.perf_counter()
        timing = phase_timing(usage, request_metrics, end-start, first-start if first else None)
        row = dict(task=task, repeat=repeat, thinking=args.thinking, ttft=first - start if first else None, elapsed=end - start,
                   decode_tps=timing['write_tks'], timing=timing, metrics=request_metrics,
                   usage=usage, finish=finish, text=text, reasoning=reasoning, request=body)
        if task == 'json':
            try:
                row['correct'] = json.loads(text) == [dict(n=n, square=n * n, cube=n ** 3) for n in range(1, 21)]
            except (ValueError, TypeError):
                row['correct'] = False
        rows.append(row)
        (out / 'results.json').write_text(json.dumps(rows, indent=2))
        if row['decode_tps'] is None:
            raise RuntimeError('Missing generated tokens or usage; inspect results.json')
        if task == 'json' and (not row['correct'] or finish != 'stop'):
            raise RuntimeError('JSON correctness check failed; inspect results.json')
        rates=tuple(round(v, 2) if v is not None else None for v in timing['read_write_tks'])
        print(arm, task, repeat, '(read, write) tk/s', rates, timing['pp_source'], finish, row.get('correct', 'manual review'), flush=True)
metrics('after')
