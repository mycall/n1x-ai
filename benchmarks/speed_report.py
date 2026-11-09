"""Offline context-depth tables from n1x-speed-v1 artifacts; never contacts a server."""
import argparse
from collections import Counter
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def bounds(values):
    return [min(values), max(values)] if values else None


def summarize(run, records):
    s = run['settings']
    cells = []
    for mode in s['modes']:
        for concurrency in s['concurrency']:
            for depth in s['depths']:
                point = [r for r in records if (r['mode'], r['concurrency'], r['depth']) == (mode, concurrency, depth)]
                measured = [r for r in point if r.get('phase') == 'measured']
                valid = [r for r in measured if r['status'] == 'ok']
                expected = s['repeats'] * concurrency
                identities = {(r['repeat'], r['stream']) for r in valid}
                planned = {(repeat, stream) for repeat in range(s['repeats']) for stream in range(concurrency)}
                sources = Counter((r['timing'].get('pp_source'), r['timing'].get('decode_source')) for r in valid)
                skipped = [r.get('reason') for r in point if r['status'] in ('skipped', 'not-applicable')]
                complete = len(valid) == expected and len(measured) == expected and identities == planned and len(sources) == 1
                if complete:
                    source = next(iter(sources))
                    complete = all(source)
                timing_source = list(next(iter(sources))) if len(sources) == 1 else None
                rates = [None, None]
                if complete:
                    rates = [sum(r['read_tokens'] for r in valid)/sum(r['timing']['pp_s'] for r in valid),
                             sum(r['usage']['completion_tokens']-1 for r in valid)/sum(r['timing']['decode_s'] for r in valid)]
                cells.append(dict(mode=mode, concurrency=concurrency, depth=depth,
                    status='complete' if complete else ('not-applicable' if mode == 'cold' and depth == 0 else
                        'skipped' if skipped and not measured else 'incomplete'),
                    expected_requests=expected, recorded_requests=len(measured), valid_requests=len(valid),
                    timing_sources=[dict(pp=k[0], decode=k[1], requests=v) for k,v in sources.items()],
                    timing_source=timing_source, read_write_tks=rates,
                    input_tokens=bounds([r['usage']['prompt_tokens'] for r in valid]),
                    history_tokens=bounds([r['history_tokens'] for r in valid]),
                    read_tokens=bounds([r['read_tokens'] for r in valid]),
                    completion_tokens=bounds([r['usage']['completion_tokens'] for r in valid]),
                    cached_tokens=bounds([(r['usage'].get('prompt_tokens_details') or {})['cached_tokens'] for r in valid]),
                    cached_prompt_fraction=(sum(r['usage']['prompt_tokens_details']['cached_tokens'] for r in valid)
                        /sum(r['usage']['prompt_tokens'] for r in valid)) if valid else None,
                    mean_client_ttft_s=sum(r['client_ttft_s'] for r in valid)/len(valid) if valid else None,
                    mean_e2e_s=sum(r['timing']['e2e_s'] for r in valid)/len(valid) if valid else None,
                    notes=sorted(set(skipped + [e for r in measured for e in r.get('errors', [])]
                                     + [r['error'] for r in measured if 'error' in r]))))
    return dict(schema_version=1, protocol=s['protocol'], run_id=run['run_id'], profile=s['profile'],
                status=run['status'], settings=s, metadata=run, cells=cells)


def load_run(path):
    path = Path(path)
    # Recompute from raw first attempts instead of trusting an editable summary.
    run = read(path/'run.json')
    if run['settings'].get('protocol') != 'n1x-speed-v1':
        raise ValueError(f'{path}: unsupported protocol; historical agent logs are not speed-matrix cells')
    raw = path/'requests.jsonl'
    records = [json.loads(line) for line in raw.read_text(encoding='utf-8-sig').splitlines() if line.strip()] if raw.exists() else []
    result = summarize(run, records)
    result['artifact_directory'] = str(path.resolve())
    return result


def number_range(value):
    if value is None:
        return '—'
    return f'{value[0]:,}' if value[0] == value[1] else f'{value[0]:,}–{value[1]:,}'


def pair(value):
    return '(' + ', '.join('—' if v is None else f'{v:,.2f}' for v in value) + ')'


def escape(value):
    return str(value).replace('|', '\\|').replace('\n', ' ').replace('\r', ' ')


def comparison_key(summary, cell):
    s = summary['settings']
    # Precision/runtime/profile deliberately vary between curves. The workload,
    # sample plan and rate semantics must match, and timing sources split tables.
    return (s['protocol'], cell['mode'], s['extension_tokens'],
            s['output_tokens'], s['thinking'], s.get('reasoning_effort', 'unspecified'),
            s['repeats'], s['tolerance'], s['seed'],
            s['prompt_recipe_sha256'], s['timing_policy'], s.get('generator_sha256'))


def write_report(summaries, markdown_path, json_path):
    groups = {}
    for index, summary in enumerate(summaries):
        for cell in summary['cells']:
            key = comparison_key(summary, cell)
            groups.setdefault(key, {}).setdefault(index, []).append(cell)
    lines = ['# Speed by context depth', '',
        'Each cell is **(read, write) tk/s**. Rows are recorded profile runs; columns are requested context depths. '
        'The detail table gives actual rendered lengths, cache coverage, timing sources and sample counts. '
        'Missing or incomplete points are never interpolated, replaced by a retry or copied from a different workload.', '',
        'Incremental depth is the rendered history primed immediately before an added prompt of approximately 2,048 tokens '
        '(or the configured extension). Its read numerator is the **actual added rendered tokens**, even if the engine '
        'recomputes/evicts history. Cold depth is the full rendered prompt and requires zero recorded cache hits. '
        'Generation uses a fixed token count with EOS ignored, including reasoning. This is a speed workload, not an accuracy score.', '',
        'Read = summed workload tokens / summed PP durations. Write = summed (completion tokens − 1) / summed decode durations. '
        'Direct per-request server PP is preferred; only absent PP is derived as e2e − decode. Derived PP includes queue/transport '
        'overhead. Tables with different direct/derived sources are separated. Rates are weighted request-phase rates, '
        'not whole-run throughput; concurrent request intervals overlap.', '']
    for key, entries in groups.items():
        protocol, mode, extension, output, thinking, effort, repeats, tolerance, seed, recipe, policy, generator = key
        sources = {tuple(cell['timing_source']) for cells in entries.values() for cell in cells
                   if cell['status'] == 'complete' and cell['timing_source']}
        if not sources:
            sources = {('unavailable', 'unavailable')}
        for source in sorted(sources):
            lines += [f'## {mode} · thinking {"on" if thinking else "off"}', '',
                f'Reasoning effort: **{escape(effort) if thinking else "disabled"}**. '
                'An unspecified effort in an older run is not relabelled as xhigh.', '',
                f'Protocol `{protocol}`; output **{output}**; repeats **{repeats}**; '
                f'extension **{extension}** (incremental only); token calibration tolerance ±{tolerance}.', '',
                f'PP source: `{source[0]}`. Decode source: `{source[1]}`.', '']
            depths = sorted({cell['depth'] for cells in entries.values() for cell in cells})
            concurrencies = sorted({cell['concurrency'] for cells in entries.values() for cell in cells})
            lines += ['| Client concurrency | Profile / run | Server slots | ' + ' | '.join(f'{d:,}' for d in depths) + ' |',
                      '| --- | --- | ---: | ' + ' | '.join('---:' for _ in depths) + ' |']
            for concurrency in concurrencies:
                lines.append(f'| **C{concurrency}** | ' + ' | '.join('' for _ in range(len(depths)+2)) + ' |')
                for index, cells in entries.items():
                    summary = summaries[index]
                    values = []
                    for depth in depths:
                        c = next((c for c in cells if c['depth'] == depth and c['concurrency'] == concurrency), None)
                        if c is None:
                            values.append('— missing')
                        elif c['status'] == 'complete' and tuple(c['timing_source']) == source:
                            values.append(pair(c['read_write_tks']))
                        elif c['status'] == 'complete':
                            values.append('— different timing source')
                        else:
                            values.append('— ' + c['status'])
                    label = f"{escape(summary['profile'])} / `{summary['run_id'][:8]}`"
                    slots = summary['metadata'].get('host', {}).get('config', {}).get('MaxSequences', '—')
                    lines.append('| | ' + label + f' | {slots} | ' + ' | '.join(values) + ' |')
            lines += ['', '| Client concurrency | Profile / run | Depth | Actual history | Actual input | Read numerator | Generated | Cached tokens | Valid / planned | Mean client TTFT / e2e (s) | Status |',
                      '| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |']
            for index, cells in entries.items():
                summary = summaries[index]
                for c in sorted(cells, key=lambda c:(c['concurrency'], c['depth'])):
                    if c['status'] == 'complete' and tuple(c['timing_source']) != source:
                        continue
                    latency = '—' if c['mean_client_ttft_s'] is None else f"{c['mean_client_ttft_s']:.3f} / {c['mean_e2e_s']:.3f}"
                    lines.append(f"| {c['concurrency']} | {escape(summary['profile'])} / `{summary['run_id'][:8]}` | {c['depth']:,} | "
                        f"{number_range(c['history_tokens'])} | {number_range(c['input_tokens'])} | "
                        f"{number_range(c['read_tokens'])} | {number_range(c['completion_tokens'])} | "
                        f"{number_range(c['cached_tokens'])} | {c['valid_requests']}/{c['expected_requests']} | "
                        f"{latency} | {escape(c['status'] + (': ' + '; '.join(c['notes']) if c['notes'] else ''))} |")
            lines.append('')
    lines += ['## Run metadata', '',
              'Run metadata and the comparison JSON retain effective profile settings, host/server image identity when '
              'recorded by benchmark.ps1, source hashes, prompt hashes in raw requests, budgets and completion status. '
              'A completed speed matrix does not qualify tools, accuracy, restoration or public deployment. '
              'Compare power state, hardware partition and runtime pins before attributing differences to a single component.', '',
              '| Profile | Run | Status | Context limit | Artifacts |', '| --- | --- | --- | ---: | --- |']
    for s in summaries:
        lines.append(f"| {escape(s['profile'])} | `{s['run_id']}` | {s['status']} | {s['settings']['context_limit']:,} | {escape(s.get('artifact_directory', 'this run'))} |")
    markdown_path, json_path = Path(markdown_path), Path(json_path)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text('\n'.join(lines)+'\n', encoding='utf-8')
    json_path.write_text(json.dumps(dict(schema_version=1, runs=summaries), indent=2, allow_nan=False)+'\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', type=Path, nargs='+', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('Output directory already exists; choose a fresh path to preserve reports')
    summaries = [load_run(p) for p in args.runs]
    # Atomic creation closes the race with another report using the same path.
    args.out.mkdir(parents=True, exist_ok=False)
    write_report(summaries, args.out/'comparison.md', args.out/'comparison.json')
    print(args.out/'comparison.md')


if __name__ == '__main__':
    main()
