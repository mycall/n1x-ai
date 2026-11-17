"""Local parameter experiment; reuses maintained scoring and preserves first scores."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'benchmarks'))
from agent_cache_probe import Probe, request, save
import tool_recovery_probe as recovery
from context_capacity_probe import calibrate, token_count, score, metrics
from speed_probe import Client, thinking_kwargs

VARIANTS = {'xhigh-t1': ('xhigh', 1.0), 'medium-t1': ('medium', 1.0),
            'xhigh-t06': ('xhigh', 0.6), 'medium-t06': ('medium', 0.6)}


class ParameterProbe(Probe):
    def chat(self, messages, salt, **extra):
        extra.update(temperature=self.args.temperature, top_p=0.95, top_k=20,
                     presence_penalty=0, seed=self.args.seed, max_tokens=8192,
                     chat_template_kwargs=thinking_kwargs(True, self.args.effort))
        return super().chat(messages, salt, **extra)


def diagnostics(folder, url):
    source = folder / 'responses.jsonl'
    if not source.exists():
        return
    for line in source.read_text(encoding='utf-8').splitlines():
        row = json.loads(line)
        choice = row['response']['choices'][0]
        message = choice['message']
        if message.get('tool_calls') or (message.get('content') or '').strip():
            continue
        result = {'first_score_unchanged': True, 'request': row['request']}
        try:
            result['response'] = json.loads(request(url + '/v1/chat/completions', row['request']))
        except Exception as error:
            result['error'] = str(error)
        with (folder / 'empty-final-diagnostics.jsonl').open('a', encoding='utf-8') as output:
            output.write(json.dumps(result) + '\n')


def run_quality(args, prepared, client):
    rows = []
    for concurrency in (1, 2):
        folder = args.out / f'c{concurrency}'
        folder.mkdir(parents=True)
        def ask(task):
            payload = deepcopy(task['payload'])
            payload.update(temperature=args.temperature, top_p=0.95, top_k=20,
                           presence_penalty=0, seed=args.seed, max_tokens=8192,
                           cache_salt=uuid.uuid4().hex,
                           chat_template_kwargs=thinking_kwargs(True, args.effort))
            count = token_count(client, payload)
            if count + 8192 > 262144:
                raise ValueError('Input does not reserve output space')
            start = time.perf_counter()
            try:
                result = client.generate(payload)
                valid = (result.get('usage') or {}).get('prompt_tokens') == count
                record = dict(task_id=task['id'], kind=task['kind'], expected=task['expected'],
                              request=payload, input_tokens=count, rendered_input_matches=valid,
                              correct=valid and score(result, task['expected']), **result)
            except Exception as error:
                record = dict(task_id=task['id'], correct=False, error=str(error), request=payload)
            record['elapsed_s'] = time.perf_counter() - start
            save(folder / (task['id'] + '.json'), record)
            return record
        _, before = metrics(client)
        (folder / 'before.prom').write_text(before, encoding='utf-8')
        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            results = list(pool.map(ask, prepared))
        elapsed = time.perf_counter() - start
        _, after = metrics(client)
        (folder / 'after.prom').write_text(after, encoding='utf-8')
        row = dict(concurrency=concurrency, correct=sum(r['correct'] for r in results),
                   planned=len(prepared), elapsed_s=elapsed, max_output_tokens=8192)
        rows.append(row)
        save(args.out / 'summary.json', rows)
        print(json.dumps(row), flush=True)
        for record in results:
            if record.get('stream_done') and not (record.get('content') or '').strip():
                retry = client.generate(record['request'])
                save(folder / (record['task_id'] + '-diagnostic.json'),
                     dict(first_score_unchanged=True, recovered=score(retry, record['expected']), result=retry))

    if any(row['correct'] != row['planned'] for row in rows):
        raise RuntimeError('Archive quality first-attempt failures')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--url', default='http://127.0.0.1:8000')
    parser.add_argument('--variants', choices=VARIANTS, nargs='+', default=list(VARIANTS))
    parser.add_argument('--phases', choices=['agents', 'recovery', 'quality'], nargs='+', default=['agents', 'recovery'])
    parser.add_argument('--quality-depth', type=int, default=32768)
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    client = Client(args.url)
    client.get('/health')
    meta = dict(utc=datetime.now(timezone.utc).isoformat(), variants={v:VARIANTS[v] for v in args.variants},
                phases=args.phases, quality_depth=args.quality_depth, output_tokens=8192,
                top_p=0.95, top_k=20, seed=args.seed, presence_penalty=0,
                model=client.get('/v1/models'),
                note='Recipe candidate recorded by the parent trial. Fixed seed; scheduler may change reproducibility. '
                     'Agents C1/C2, two sessions/two turns and forward/reverse concurrency sweeps. '
                     'Recovery C4, four sessions/six turns. Quality C1/C2, four archive tasks. '
                     'Recovery summary inherited max_output_tokens=1024 is overridden to 8192; raw requests are authoritative. '
                     'Empty final retries are diagnostic only. No cache flushes, server edits or model downloads.',
                source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in [Path(__file__), *(ROOT/'benchmarks'/n for n in
                                 ['agent_cache_probe.py','tool_recovery_probe.py','context_capacity_probe.py','speed_probe.py','timing.py'])]})
    save(args.out / 'settings.json', meta)
    prepared = None
    if 'quality' in args.phases:
        # Identical user/system/tool messages for every variant; medium changes only template instructions.
        prepared = [calibrate(client, i, args.quality_depth+8192+8, 8192) for i in (0,2,4,6)]
        save(args.out / 'prepared-requests.json', prepared)
    failures = []
    for variant in args.variants:
        effort, temperature = VARIANTS[variant]
        for phase in args.phases:
            folder = args.out / variant / phase
            config = SimpleNamespace(out=folder, url=args.url, no_lmcache_metrics=True,
                effort=effort, temperature=temperature, seed=args.seed, agent_thinking=True,
                agent_output_tokens=8192, agent_sessions=2, agent_turns=2, agent_concurrency=[1,2])
            print(f'START {variant} {phase}', flush=True)
            client.get('/health')
            try:
                if phase == 'agents':
                    ParameterProbe(config).agents()
                elif phase == 'recovery':
                    recovery.Probe = ParameterProbe
                    try:
                        recovery.run(config)
                    finally:
                        if (folder/'summary.json').exists():
                            summary = json.loads((folder/'summary.json').read_text())
                            summary.update(max_output_tokens=8192, reasoning_effort=effort,
                                           temperature=temperature, seed=args.seed)
                            save(folder/'summary.json', summary)
                else:
                    run_quality(config, prepared, client)
            except Exception as error:
                failures.append(dict(variant=variant, phase=phase, error=str(error)))
                save(args.out/'failures.json', failures)
                print(f'FAILED {variant} {phase}: {error}', flush=True)
            diagnostics(folder, args.url)
    save(args.out/'completed.json', dict(utc=datetime.now(timezone.utc).isoformat(), failures=failures))


if __name__ == '__main__':
    main()
