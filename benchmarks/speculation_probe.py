"""Compare serving profiles with identical short prompts, one request at a time."""
import argparse
import json
import time
import urllib.request
import uuid
from pathlib import Path
parser = argparse.ArgumentParser(description='Short single-request speculation comparison; run each serving profile separately.')
parser.add_argument('--out', type=Path, required=True)
parser.add_argument('--url', default='http://127.0.0.1:8000')
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
        body = dict(model='qwen', messages=[dict(role='user', content=prompt)], temperature=0, max_tokens=512, stream=True, stream_options={'include_usage': True}, chat_template_kwargs={'enable_thinking': False}, cache_salt=f'compare-{arm}-{task}')
        req = urllib.request.Request(args.url + '/v1/chat/completions', data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
        start = time.perf_counter()
        first = None
        text = ''
        usage = {}
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
                for choice in chunk.get('choices', []):
                    piece = choice.get('delta', {}).get('content') or ''
                    if piece and first is None:
                        first = time.perf_counter()
                    text += piece
                    if choice.get('finish_reason'):
                        finish = choice['finish_reason']
        end = time.perf_counter()
        row = dict(task=task, repeat=repeat, ttft=first - start, elapsed=end - start, decode_tps=(usage['completion_tokens'] - 1) / (end - first), usage=usage, finish=finish, text=text)
        if task == 'json':
            row['correct'] = json.loads(text) == [dict(n=n, square=n * n, cube=n ** 3) for n in range(1, 21)]
        rows.append(row)
        (out / 'results.json').write_text(json.dumps(rows, indent=2))
        if task == 'json' and (not row['correct'] or finish != 'stop'):
            raise RuntimeError('JSON correctness check failed; inspect results.json')
        print(arm, task, repeat, round(row['decode_tps'], 2), finish, row.get('correct', 'manual review'), flush=True)
metrics('after')
