"""Drive installed vllm bench serve; retain response-local timings via a proxy.

Run inside the serving container with its existing tokenizer. No downloads.
The proxy adds independent cache salts and records usage/metrics, forwarding SSE
bytes unchanged. vLLM's benchmark remains responsible for load and client timing.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import random
import sys
import time
import uuid

import aiohttp
from aiohttp import web


def save(path, data):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, indent=2, allow_nan=False) + '\n')
    temp.replace(path)


def utc():
    return datetime.now(timezone.utc).isoformat()


def prepare(tokenizer, target, identity):
    rng = random.Random(identity)
    verbs = ['validates input', 'reads indexed records', 'schedules work',
             'stores responses', 'checks dependencies', 'rebuilds indexes',
             'routes requests', 'tracks latency', 'restores state']
    # Each request differs before the first cache match unit, and throughout.
    lead = f'Reference stream {identity}.\n'
    lines = [f'Record {i}: The service {rng.choice(verbs)} for partition '
             f'{rng.randrange(10000)} with revision {rng.randrange(10000)}.\n'
             for i in range(target // 10 + 100)]
    filler = ''.join(lines)
    tail = '\nContinue with a detailed technical explanation of request handling and data storage.\n'

    def render(n):
        return tokenizer.apply_chat_template([
            {'role': 'system', 'content': 'Read the reference notes. Continue writing detailed reference notes when asked.'},
            {'role': 'user', 'content': lead + filler[:n] + tail}],
            add_generation_prompt=True, tokenize=False,
            enable_thinking=True, reasoning_effort='xhigh')

    lo, hi, best, count = 0, len(filler), None, None
    while lo <= hi:
        mid = (lo + hi) // 2
        text = render(mid)
        size = len(tokenizer.encode(text, add_special_tokens=False))
        if size <= target:
            best, count, lo = text, size, mid + 1
        else:
            hi = mid - 1
    if best is None or target - count > 4:
        raise ValueError(f'Prompt calibration failed: {target}, {count}')
    return {'prompt': best, 'output_tokens': 512}, count


class Recorder:
    def __init__(self, base, out, run_id):
        self.base, self.out, self.run_id = base, out, run_id
        self.wave = None
        self.rows = []

    async def handle(self, request):
        if request.method != 'POST':
            async with self.session.get(self.base + request.path_qs) as response:
                return web.Response(body=await response.read(), status=response.status,
                                    content_type=response.content_type)
        body = await request.json()
        salt = f'{self.run_id}-{self.wave}-{uuid.uuid4().hex}'
        body['cache_salt'] = salt
        row = dict(wave=self.wave, salt=salt, started_utc=utc(), status=None,
                   usage=None, metrics=None, finish_reason=None, done=False,
                   prompt_sha256=hashlib.sha256(body['prompt'].encode()).hexdigest())
        start = time.perf_counter()
        pending = b''
        try:
            async with self.session.post(self.base + request.path_qs, json=body) as response:
                row['status'] = response.status
                downstream = web.StreamResponse(status=response.status,
                                                headers={'Content-Type': response.content_type})
                await downstream.prepare(request)
                async for chunk in response.content.iter_any():
                    pending += chunk
                    while b'\n' in pending:
                        line, pending = pending.split(b'\n', 1)
                        if not line.startswith(b'data:'):
                            continue
                        data = line[5:].strip()
                        if data == b'[DONE]':
                            row['done'] = True
                            continue
                        event = json.loads(data)
                        if event.get('usage'):
                            row['usage'] = event['usage']
                        if event.get('metrics'):
                            row['metrics'] = event['metrics']
                        for choice in event.get('choices', []):
                            row['finish_reason'] = choice.get('finish_reason') or row['finish_reason']
                    await downstream.write(chunk)
                await downstream.write_eof()
                return downstream
        except Exception as exc:
            row['error'] = repr(exc)
            raise
        finally:
            row['elapsed_s'] = time.perf_counter() - start
            self.rows.append(row)
            with (self.out / 'responses.jsonl').open('a') as target:
                target.write(json.dumps(row) + '\n')

    async def snapshot(self, name):
        async with self.session.get(self.base + '/metrics') as response:
            (self.out / name).write_bytes(await response.read())


async def main(args):
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                      VLLM_NO_USAGE_STATS='1', HF_HUB_DISABLE_TELEMETRY='1')
    args.out.mkdir(parents=True, exist_ok=True)
    if (args.out / 'manifest.json').exists():
        manifest = json.loads((args.out / 'manifest.json').read_text())
    else:
        manifest = dict(protocol='n1x-vllm-speed-matrix-v1', run_id=uuid.uuid4().hex,
                        started_utc=utc(), vllm=importlib.metadata.version('vllm'),
                        model=args.model, contexts=args.contexts, concurrency=list(range(1,9)),
                        repeats=args.repeats, output_tokens=512,
                        seed=42, thinking=True, reasoning_effort='xhigh',
                        cold_prefixes=True, finished=[])
        manifest['packages'] = {name: importlib.metadata.version(name) for name in
                                ['vllm', 'torch', 'transformers', 'pandas', 'aiohttp']}
        manifest['source_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        save(args.out / 'manifest.json', manifest)
    timeout = aiohttp.ClientTimeout(total=14400)
    async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
        async with session.get(args.base + '/health') as response:
            response.raise_for_status()
        from transformers import AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(args.tokenizer, local_files_only=True)
        recorder = Recorder(args.base, args.out, manifest['run_id'])
        recorder.session = session
        app = web.Application(client_max_size=16 * 1024**2)
        app.router.add_route('*', '/{path:.*}', recorder.handle)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, '127.0.0.1', args.proxy_port).start()
        cells = [(r, c, n) for r in range(args.repeats)
                 for c in range(1, 9) for n in args.contexts]
        # Counterbalance context/concurrency to reduce systematic thermal drift.
        random.Random(42).shuffle(cells)
        cells = [(-1, 8, 8192), (-1, 1, max(args.contexts))] + cells
        if args.smoke:
            cells = [(0, 1, 4096)]
        for repeat, concurrency, length in cells:
            name = f'r{repeat+1}-c{concurrency}-n{length}'
            if name in manifest['finished']:
                continue
            print(f'{utc()} preparing {name}', flush=True)
            dataset = args.out / f'{name}.jsonl'
            counts = []
            with dataset.open('w') as target:
                for i in range(concurrency):
                    item, count = prepare(tokenizer, length,
                                          f'{manifest["run_id"]}-{name}-{i}')
                    target.write(json.dumps(item) + '\n')
                    counts.append(count)
            recorder.wave, recorder.rows = name, []
            command = ['vllm', 'bench', 'serve', '--backend', 'openai',
                       '--base-url', f'http://127.0.0.1:{args.proxy_port}',
                       '--endpoint', '/v1/completions', '--model', args.model,
                       '--tokenizer', args.tokenizer, '--dataset-name', 'custom',
                       '--dataset-path', str(dataset), '--skip-chat-template',
                       '--custom-output-len', '512',
                       '--num-prompts', str(concurrency), '--max-concurrency', str(concurrency),
                       '--request-rate', 'inf', '--num-warmups', '0',
                       '--ready-check-timeout-sec', '0', '--ignore-eos',
                       '--temperature', '0', '--seed', '42', '--save-result',
                       '--save-detailed', '--result-dir', str(args.out),
                       '--result-filename', f'{name}-vllm.json', '--disable-tqdm']
            save(args.out / f'{name}-command.json', dict(command=command, counts=counts))
            await recorder.snapshot(f'{name}-before.prom')
            started = time.time()
            print(f'{utc()} running {name} input={counts}', flush=True)
            with (args.out / f'{name}.log').open('w') as log:
                process = await asyncio.create_subprocess_exec(*command, stdout=log, stderr=log)
                try:
                    code = await asyncio.wait_for(process.wait(), timeout=14400)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
                    raise
            await recorder.snapshot(f'{name}-after.prom')
            result_path = args.out / f'{name}-vllm.json'
            result = json.loads(result_path.read_text()) if result_path.exists() else {}
            valid = (code == 0 and result.get('completed') == concurrency
                     and result.get('failed') == 0 and len(recorder.rows) == concurrency
                     and all(x['done'] and x['status'] == 200
                             and x['finish_reason'] == 'length'
                             and (x['usage'] or {}).get('completion_tokens') == 512
                             and length - 4 <= (x['usage'] or {}).get('prompt_tokens', 0) <= length
                             and ((x['usage'] or {}).get('prompt_tokens_details') or {}).get('cached_tokens') == 0
                             and (x['metrics'] or {}).get('generation_time_ms', 0) > 0
                             for x in recorder.rows))
            receipt = dict(name=name, repeat=repeat+1, concurrency=concurrency,
                           warmup=repeat < 0,
                           target_input=length, counts=counts, elapsed_s=time.time()-started,
                           valid=valid, exit_code=code, responses=recorder.rows)
            save(args.out / f'{name}-receipt.json', receipt)
            print(f'{utc()} finished {name} valid={valid} seconds={receipt["elapsed_s"]:.1f}', flush=True)
            if not valid:
                raise RuntimeError(f'Invalid benchmark wave: {name}; inspect receipt and log')
            manifest['finished'].append(name)
            manifest['updated_utc'] = utc()
            save(args.out / 'manifest.json', manifest)
            dataset.unlink()  # Receipts retain counts/hashes; deterministic generator retains provenance.
        manifest['completed_utc'] = utc()
        save(args.out / 'manifest.json', manifest)
        await runner.cleanup()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='http://127.0.0.1:8000')
    parser.add_argument('--model', default='qwen/qwen38fn-best')
    parser.add_argument('--tokenizer', default='/model')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--contexts', type=int, nargs='+', default=[4096, 8192, 65536, 261632])
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--proxy-port', type=int, default=18001)
    parser.add_argument('--smoke', action='store_true')
    asyncio.run(main(parser.parse_args()))
