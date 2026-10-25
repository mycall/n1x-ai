"""Summarize measured optimization runs without declaring a speed winner."""
import argparse
from datetime import datetime
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}


def cache_metrics(metrics):
    drafts = metrics.get('vllm:spec_decode_num_draft_tokens_total', 0)
    accepted = metrics.get('vllm:spec_decode_num_accepted_tokens_total', 0)
    return {'loadedChunks': metrics.get('lmcache_mp_num_chunks_loaded_total', 0),
            'gpuHitTokens': metrics.get('vllm:prefix_cache_hits_total', 0),
            'gpuQueriedTokens': metrics.get('vllm:prefix_cache_queries_total', 0),
            'prefetchFailureChunks': metrics.get('lmcache_mp_l2_prefetch_failure_chunks_total', 0),
            'externalHitTokens': metrics.get('vllm:external_prefix_cache_hits_total', 0),
            'preemptions': metrics.get('vllm:num_preemptions_total', 0),
            'draftTokens': drafts, 'acceptedDraftTokens': accepted,
            'draftAcceptance': accepted/drafts if drafts else None}


def agent_turn(root, turn):
    count = len(turn['sessions'])
    responses = [read(root/f"lmcache-agents-c{count}-turn-{turn['turn']}-session-{row['session']}-{kind}.json")
                 for row in turn['sessions'] for kind in ('tool','answer')]
    tokens = sum(response.get('usage', {}).get('completion_tokens', 0) for response in responses)
    timed = [response for response in responses if response.get('timestamp') and response.get('totalSeconds') is not None]
    # Reconstruct the HTTP span, excluding the deliberate metrics-publication
    # sleep after the agent pool has completed. Preserve original harness time.
    request_span = (max(datetime.fromisoformat(row['timestamp']).timestamp() for row in timed)
                    - min(datetime.fromisoformat(row['timestamp']).timestamp()-row['totalSeconds'] for row in timed)) if len(timed) == len(responses) and timed else None
    return {'turn': turn['turn'], 'gpuReset': turn['gpuReset'],
        'wallSeconds': turn['wallSeconds'],
        'allCorrect': all(row['correct'] for row in turn['sessions']),
        'completionTokens': tokens,
        'requestWallSeconds': request_span,
        'outputTokensPerRequestWallSecond': tokens/request_span if request_span and request_span > 0 else None,
        'outputTokensPerWallSecond': tokens/turn['wallSeconds'],
        'sessionSeconds': [row['toolSeconds']+row['answerSeconds'] for row in turn['sessions']],
        'metrics': cache_metrics(turn['metricsDelta'])}


def summarize(root):
    summary = read(root/'summary.json')
    record = {'directory': str(root), 'status': summary.get('status', 'incomplete'),
              'error': summary.get('error'), 'config': read(root/'run-config.json'),
              'power': read(root/'power-condition.json'), 'memory': read(root/'memory-balance.json'),
              'agents': [], 'coding': [], 'parallel': [], 'prefix': read(root/'prefix-experiment.json')}
    journal = root/'requests.jsonl'
    requests = {row['id']: row for row in
        (json.loads(line) for line in journal.read_text(encoding='utf-8-sig').splitlines() if line)} if journal.exists() else {}
    for variant in record['prefix'].get('results', []):
        variant['gpuHitTokens'] = [requests.get(identifier, {}).get('metricsDelta', {}).get('vllm:prefix_cache_hits_total', 0)
                                  for identifier in variant['requests']]
    for path in sorted(root.glob('agent-loops-c*.json')):
        data = read(path)
        record['agents'].append({'file': path.name, 'status': data['status'],
            'metrics': cache_metrics(data.get('metricsDelta', {})),
            'turns': [agent_turn(root, turn) for turn in data['turns']]})
    for group in read(root/'coding-workload.json').get('groups', []):
        tokens = sum(row['usage']['completion_tokens'] for row in group['rows'])
        verified = [row for row in read(root/'coding-validation.json').get('rows', [])
                    if row['concurrency'] == group['concurrency']]
        record['coding'].append({'concurrency': group['concurrency'],
            'originalAllCorrect': group['allCorrect'],
            'allCorrect': all(row['correct'] for row in verified) if len(verified) == 4 else group['allCorrect'],
            'validation': 'saved-program recheck' if len(verified) == 4 else 'during inference run',
            'wallSeconds': group['wallSeconds'], 'completionTokens': tokens,
            'outputTokensPerWallSecond': tokens/group['wallSeconds'],
            'metrics': cache_metrics(group['metricsDelta'])})
    for stage in ('cold','gpu-warm','gpu-reset'):
        data = read(root/f'lmcache-parallel-{stage}.json')
        if data:
            record['parallel'].append({'stage': stage, 'allCorrect': data['allCorrect'],
                                      'metrics': cache_metrics(data['metricsDelta'])})
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('runs', nargs='+', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    evidence = {'runs': [summarize(root) for root in args.runs],
        'limitations': ['Power was not controlled unless the run record says otherwise.',
                        'Small fixtures and periodic memory samples do not prove sustained production behavior.',
                        'Per-turn speculative counters can publish late; use overall agent counters for acceptance.',
                        'Agent harness wall time includes a one-second metrics pause. Request wall spans are reconstructed from per-call timestamps and exclude that pause.',
                        'Output tokens per wall second includes prompt processing and validation overhead; it is not pure decode speed.']}
    args.output.write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    print(f'Saved {len(evidence["runs"])} runs to {args.output}')
