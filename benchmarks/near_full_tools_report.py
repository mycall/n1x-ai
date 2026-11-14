"""Summarize saved near-full tool first attempts without contacting the server."""
import argparse
import json
from pathlib import Path
import statistics


def counter(folder, label, side, name):
    values = []
    for line in (folder/f'{label}-{side}.prom').read_text(encoding='utf-8').splitlines():
        if line.startswith(name+'{') or line.startswith(name+' '):
            values.append(float(line.rsplit(None,1)[1]))
    return sum(values) if values else None


def report(folder):
    groups = json.loads((folder/'summary.json').read_text(encoding='utf-8'))
    tasks = [json.loads(line) for line in (folder/'tasks.jsonl').read_text(encoding='utf-8').splitlines()]
    output = []
    for concurrency in sorted({g['concurrency'] for g in groups}):
        selected = [g for g in groups if g['concurrency'] == concurrency]
        rows = [r for g in selected for session in g['sessions'] for r in session['requests']]
        elapsed = sum(g['elapsed_s'] for g in selected)
        correct = sum(g['correct_tasks'] for g in selected)
        entry = dict(concurrency=concurrency, correct_tasks=correct,
            planned_tasks=sum(g['planned_tasks'] for g in selected), elapsed_s=elapsed,
            correct_tasks_s=correct/elapsed, preemptions=sum(g['preemptions'] for g in selected),
            input_range=[min(r['rendered_input'] for r in rows),max(r['rendered_input'] for r in rows)] if rows else None,
            phases={})
        group_names = {g['group'] for g in selected}
        warm_tasks = [t for t in tasks if t['group'] in group_names and t['turn'] > 0 and 'elapsed_s' in t]
        entry['appended_task_mean_s'] = statistics.mean(t['elapsed_s'] for t in warm_tasks) if warm_tasks else None
        entry['appended_task_timing_basis'] = 'Selection plus continuation, including harness tokenization; first cold task excluded'
        entry['cache_counter_deltas'] = {}
        for name in ('vllm:prefix_cache_hits_total','vllm:external_prefix_cache_hits_total'):
            pairs = [(counter(folder,g['group'],'before',name),counter(folder,g['group'],'after',name)) for g in selected]
            entry['cache_counter_deltas'][name] = (sum(b-a for a,b in pairs)
                if all(a is not None and b is not None and b >= a for a,b in pairs) else None)
        for phase in ('cold-selection','appended-selection','tool-continuation'):
            samples = [r for r in rows if r['phase'] == phase]
            if not samples:
                continue
            cached = [(r.get('usage',{}).get('prompt_tokens_details') or {}).get('cached_tokens') for r in samples]
            known = all(type(n) is int for n in cached)
            prompts = sum(r['usage']['prompt_tokens'] for r in samples)
            outputs = [r['usage']['completion_tokens'] for r in samples]
            pp = [r['timing'].get('pp_s') for r in samples]
            decode = [r['timing'].get('decode_s') for r in samples]
            ttft = [r.get('client_ttft_s') for r in samples]
            entry['phases'][phase] = dict(requests=len(samples),
                mean_e2e_s=statistics.mean(r['timing']['e2e_s'] for r in samples),
                mean_client_ttft_s=statistics.mean(ttft) if all(n is not None for n in ttft) else None,
                mean_pp_s=statistics.mean(pp) if all(n is not None for n in pp) else None,
                generated_range=[min(outputs),max(outputs)],
                cached_tokens=sum(cached) if known else None,
                cached_fraction=sum(cached)/prompts if known else None,
                requests_with_cache=sum(n>0 for n in cached) if known else None,
                write_tks=sum(max(n-1,0) for n in outputs)/sum(decode) if all(n and n>0 for n in decode) else None,
                timing_sources=sorted({(r['timing']['pp_source'],r['timing']['decode_source']) for r in samples},key=str))
        output.append(entry)
    return dict(protocol='n1x-near-full-tools-v1', results=output,
        limits='Synthetic tool selection and append-only continuations. Cold selection and warm phases '
               'have different generated work; their latency ratio is not a matched cache speedup. '
               'No cache-off comparison, displaced replay, or SSD restart qualification.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder',type=Path)
    args = parser.parse_args()
    print(json.dumps(report(args.folder),indent=2))
