"""Audit required artifacts from the complete optimization comparison matrix."""
import argparse
import hashlib
import json
from pathlib import Path

from summarize_optimizations import read
from optimization_workloads import CODE_CHECK, CODING_CASES

CASES = ('agents', 'eager', 'pressure-immediate', 'pressure-wait',
         'prefill-8192', 'prefill-2048', 'prefill-4096', 'mtp-on', 'mtp-off')


def audit(root, prefix):
    errors, details, images = [], {}, set()
    overrides = read(root/f'{prefix}-overrides.json')
    def require(condition, message):
        if not condition:
            errors.append(message)
    for case in CASES:
        directory = root / overrides.get(case, f'{prefix}-{case}')
        summary = read(directory/'summary.json')
        config = read(directory/'run-config.json')
        details[case] = {'directory': str(directory), 'status': summary.get('status', 'missing'),
                         'error': summary.get('error')}
        require(summary.get('status') == 'complete', f'{case}: suite incomplete')
        image_record = read(directory/'test-image.json')
        image = image_record.get('id')
        require(bool(image), f'{case}: missing image identity')
        if case == 'pressure-wait' and config.get('restoreQueueVersion') == 2:
            require(bool(image_record.get('baseImageId')), f'{case}: missing queue-child parent provenance')
            images.add(image_record.get('baseImageId'))
            details[case]['queueImage'] = image
            details[case]['queueVersion'] = 2
        elif image:
            images.add(image)
        memory = read(directory/'memory-balance.json')
        require(memory.get('gpuReportedCapacityGiB') == 88, f'{case}: GPU partition not verified')
        windows_path = directory/'windows-memory.jsonl'
        samples = [json.loads(line) for line in windows_path.read_text(encoding='utf-8-sig').splitlines()
                   if line] if windows_path.exists() else []
        minimum = min((row['availableGiB'] for row in samples), default=0)
        details[case]['windowsMinimumGiB'] = minimum
        require(minimum >= 4, f'{case}: Windows headroom missing/below floor')
        features = read(directory/'lmcache-features.json')
        require(isinstance(features, list) and len(features) == 6
                and all(row.get('passed') for row in features), f'{case}: feature checks incomplete/failed')
        require(config.get('lmcacheL1GiB') == (4 if case.startswith('pressure-') else 8),
                f'{case}: unexpected host cache size')
        if case.startswith('pressure-'):
            for stage in ('cold', 'gpu-warm', 'gpu-reset'):
                group = read(directory/f'lmcache-parallel-{stage}.json')
                require(group.get('allCorrect') is True and len(group.get('requests', [])) == 2,
                        f'{case}: missing/correctness failure in {stage}')
            require(config.get('restoreWaitMs') == (2000 if case == 'pressure-wait' else 0),
                    f'{case}: wrong wait configuration')
            if case == 'pressure-wait':
                log_path = directory/'lmcache-server.log'
                log = log_path.read_text(errors='replace') if log_path.exists() else ''
                require('N1X restore queue waiting' in log, f'{case}: queue was not exercised')
        else:
            counts = (1,2,4) if case.startswith('prefill-') else ((2,) if case.startswith('mtp-') else (4,))
            for count in counts:
                data = read(directory/f'agent-loops-c{count}.json')
                turns = data.get('turns', [])
                require(data.get('status') == 'complete' and len(turns) == 4,
                        f'{case}: {count}-client agent turns incomplete')
                require(all(len(turn.get('sessions', [])) == count
                            and all(row.get('correct') for row in turn['sessions']) for turn in turns),
                        f'{case}: {count}-client agent correctness failed')
                resumed = [turn for turn in turns if turn.get('gpuReset')]
                require(len(resumed) == 1 and resumed[0]['metricsDelta'].get('lmcache_mp_num_chunks_loaded_total', 0) > 0,
                        f'{case}: {count}-client agent restore not measured')
                if len(turns) == 4:
                    for session in range(count):
                        token_counts = [next((row.get('promptTokens', 0) for row in turn['sessions']
                                              if row['session'] == session), 0) for turn in turns]
                        require(all(b > a > 0 for a,b in zip(token_counts, token_counts[1:])),
                                f'{case}: session {session} growing history not verified')
            if case.startswith('prefill-'):
                require(config.get('prefillBatchTokens') == int(case.split('-')[1]),
                        f'{case}: unexpected prefill batch setting')
            if case.startswith('mtp-'):
                coding = read(directory/'coding-workload.json')
                require(coding.get('status') == 'complete'
                        and [group['concurrency'] for group in coding.get('groups', [])] == [1,2,4],
                        f'{case}: coding comparison incomplete')
                details[case]['codingAllCorrect'] = coding.get('allCorrect')
                validated = read(directory/'coding-validation.json')
                details[case]['codingVerifiedAllCorrect'] = validated.get('allCorrect')
                require(validated.get('status') == 'complete' and len(validated.get('rows', [])) == 12,
                        f'{case}: saved-program validation incomplete')
                require(validated.get('validatorSha256') == hashlib.sha256(CODE_CHECK.encode()).hexdigest(),
                        f'{case}: corrected validator identity missing/mismatched')
                expected_programs = {(c, name) for c in (1,2,4) for name, _, _ in CODING_CASES}
                require({(row['concurrency'], row['case']) for row in validated.get('rows', [])} == expected_programs,
                        f'{case}: saved-program validation coverage incomplete')
                for row in validated.get('rows', []):
                    saved = read(directory/f"lmcache-coding-c{row['concurrency']}-{row['case']}.json")
                    source = saved.get('message', {}).get('content', '').strip()
                    if source.startswith('```') and source.endswith('```'):
                        source = source.split('\n',1)[1].rsplit('```',1)[0].strip()
                    require(row.get('sourceSha256') == hashlib.sha256(source.encode()).hexdigest(),
                            f"{case}: saved program changed for {row['case']}")
                drafts = sum(group['metricsDelta'].get('vllm:spec_decode_num_draft_tokens_total', 0)
                             for group in coding.get('groups', []))
                require(drafts > 0 if case == 'mtp-on' else drafts == 0,
                        f'{case}: draft counters contradict MTP setting')
                require(config.get('disableMtp') == (case == 'mtp-off'), f'{case}: incorrect MTP configuration')
        require(config.get('eagerPrefetch') == (case == 'eager'), f'{case}: incorrect eager prefetch configuration')
    prefix_data = read(root/overrides.get('agents', f'{prefix}-agents')/'prefix-experiment.json')
    require(prefix_data.get('status') == 'complete'
            and {row['placement'] for row in prefix_data.get('results', [])} == {'early','late'},
            'Stable-prefix experiment incomplete')
    require(len(images) == 1, 'Comparison core image identities differ')
    capacity = read(root/'two-262k-gpu88-verification.json')
    require(capacity.get('status') == 'complete', 'Two near-262K capacity check incomplete')
    capacity_dir = root.parent / capacity.get('run', 'missing')
    capacity_summary = read(capacity_dir/'summary.json')
    restored = read(capacity_dir/'lmcache-parallel-gpu-reset.json')
    require(capacity_summary.get('status') == 'complete' and restored.get('allCorrect') is True
            and len(restored.get('requests', [])) == 2
            and restored.get('metricsDelta', {}).get('lmcache_mp_num_chunks_loaded_total', 0) >= 254
            and restored.get('metricsDelta', {}).get('vllm:external_prefix_cache_hits_total', 0) >= 516096,
            'Two near-262K external restores lack direct runtime evidence')
    return {'complete': not errors, 'errors': errors, 'cases': details,
            'note': 'Completion means comparisons executed and evidence exists. Accuracy regressions and power limits still require interpretation.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--results', type=Path, default=Path('results'))
    parser.add_argument('--prefix', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    record = audit(args.results, args.prefix)
    args.output.write_text(json.dumps(record, indent=2), encoding='utf-8')
    print(json.dumps({'complete': record['complete'], 'missingOrFailedChecks': len(record['errors'])}))
    raise SystemExit(0 if record['complete'] else 1)
