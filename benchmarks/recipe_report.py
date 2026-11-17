"""Summarize retained recipe trials without replacing failures or missing points."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def summarize(folder):
    result = {'name': folder.name, 'status': read(folder / 'status.json')}
    for name in ('variant.json', 'config.json', 'failure.json', 'intentional-stop.json',
                 'measurement-plan.json', 'quality-screens.json'):
        path = folder / name
        if path.exists():
            result[name.removesuffix('.json')] = read(path)
    for name in ('recipe.yaml', 'environment.psd1'):
        path = folder / name
        if path.exists():
            result[name] = path.read_text(encoding='utf-8-sig')
    source = folder / 'speed/requests.jsonl'
    if source.exists():
        groups = defaultdict(list)
        for line in source.read_text().splitlines():
            row = json.loads(line)
            groups[(row['concurrency'], row['depth'])].append(row)
        result['speed'] = []
        for (concurrency, depth), rows in sorted(groups.items()):
            valid = [r for r in rows if r['status'] == 'ok']
            item = dict(concurrency=concurrency, depth=depth, recorded=len(rows), valid=len(valid))
            if valid:
                item['read_tokens_s'] = sum(r['read_tokens'] for r in valid) / sum(r['timing']['pp_s'] for r in valid)
                item['write_tokens_s'] = sum(r['usage']['completion_tokens'] - 1 for r in valid) / sum(r['timing']['decode_s'] for r in valid)
                second = [r for r in valid if r['repeat'] == 1]
                if second:
                    item['second_repetition'] = dict(samples=len(second),
                        read_tokens_s=sum(r['read_tokens'] for r in second) / sum(r['timing']['pp_s'] for r in second),
                        write_tokens_s=sum(r['usage']['completion_tokens'] - 1 for r in second) / sum(r['timing']['decode_s'] for r in second))
            result['speed'].append(item)
    for name, relative in [('archive', 'quality/xhigh-t06/quality/summary.json'),
                           ('recovery', 'quality/xhigh-t06/recovery/summary.json'),
                           ('near_full', 'near-full/summary.json'),
                           ('restore', 'restore/summary.json')]:
        path = folder / relative
        if path.exists():
            data = read(path)
            if name == 'near_full':
                compact = []
                for row in data:
                    item = {k: v for k, v in row.items() if k != 'sessions'}
                    phases = defaultdict(list)
                    for session in row['sessions']:
                        for request in session['requests']:
                            if not request.get('diagnostic'):
                                phases[request['phase']].append(request)
                    item['cache_evidence'] = {}
                    for phase, requests in phases.items():
                        counts = [(r.get('usage', {}).get('prompt_tokens_details') or {}).get('cached_tokens', 0) for r in requests]
                        item['cache_evidence'][phase] = dict(requests=len(counts),
                            requests_with_cached_tokens=sum(n > 0 for n in counts), cached_tokens=counts)
                    compact.append(item)
                data = compact
            elif name == 'recovery':
                data = {k: v for k, v in data.items() if k != 'rows'}
            elif name == 'restore':
                responses = folder / 'restore/responses.jsonl'
                if responses.exists():
                    rows = [json.loads(line) for line in responses.read_text().splitlines()]
                    chunk = int(result.get('config', {}).get('LmcacheChunkTokens', 4096))
                    data['verification_requests'] = []
                    for row in rows[-2:]:
                        usage = row['response']['usage']
                        prompt = usage['prompt_tokens']
                        cached = (usage.get('prompt_tokens_details') or {}).get('cached_tokens', 0)
                        eligible = prompt // chunk * chunk
                        data['verification_requests'].append(dict(
                            prompt_tokens=prompt, cached_tokens=cached,
                            complete_chunk_tokens=eligible,
                            prompt_coverage=cached / prompt,
                            complete_chunk_coverage=cached / eligible if eligible else None))
            result[name] = data
    path = folder / 'telemetry.jsonl'
    if path.exists():
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        gpu = [int(row['gpu'].split(',')[0].split()[0]) for row in rows if row.get('gpu')]
        free = [int(row['gpu'].split(',')[1].split()[0]) for row in rows if row.get('gpu')]
        host = [row['host']['availableGiB'] for row in rows if row.get('host')
                and 0 <= row['unix_s'] - row['host'].get('updatedUnixSeconds', 0) <= 15]
        result['resources'] = dict(peak_gpu_used_mib=max(gpu, default=None),
                                   minimum_gpu_free_mib=min(free, default=None),
                                   minimum_host_available_gib=min(host, default=None))
    result['evidence_sha256'] = {}
    for path in sorted(folder.rglob('*.json')):
        if path.name in ('status.json', 'summary.json', 'comparison.json', 'completed.json', 'host.json'):
            result['evidence_sha256'][path.relative_to(folder).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = dict(provenance=read(args.directory / 'provenance.json'),
                  model_verification=read(args.directory / 'az-verification.json'),
                  trials=[summarize(p.parent) for p in sorted(args.directory.glob('*/status.json'))])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n')
