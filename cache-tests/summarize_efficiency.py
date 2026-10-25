"""Score checked warm turns; keep cold and forced restore out of throughput."""
import argparse
import json
import math
from pathlib import Path
from summarize_optimizations import summarize, read


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values)*fraction)-1)]


def score(root, protocol):
    record = summarize(root)
    rows = []
    for agents in record['agents']:
        turns = {turn['turn']: turn for turn in agents['turns']}
        cohorts = []
        for indices in protocol['warmCohorts']:
            selected = [turns[index] for index in indices if index in turns]
            if len(selected) != len(indices):
                continue
            elapsed = sum(turn['requestWallSeconds'] for turn in selected)
            correct = sum(sum(row['correct'] for row in read(root/agents['file'])['turns'][turn['turn']]['sessions']) for turn in selected)
            latencies = [value for turn in selected for value in turn['sessionSeconds']]
            gpu_hits=sum(turn['metrics']['gpuHitTokens'] for turn in selected)
            external_hits=sum(turn['metrics']['externalHitTokens'] for turn in selected)
            cache_path=('gpu-and-external' if gpu_hits and external_hits else
                        'gpu' if gpu_hits else 'external' if external_hits else 'no-measured-reuse')
            cohorts.append({'turns': indices, 'correctTurns': correct, 'httpWallSeconds': elapsed,
                'correctTurnsPerSecond': correct/elapsed, 'latencyP50Seconds': percentile(latencies,.5),
                'latencyP95Seconds': percentile(latencies,.95), 'allCorrect': all(turn['allCorrect'] for turn in selected),
                'cachePath':cache_path,'gpuHitTokens':gpu_hits,'externalHitTokens':external_hits,
                'loadedChunks':sum(turn['metrics']['loadedChunks'] for turn in selected)})
        rows.append({'concurrency': len(agents['turns'][0]['sessionSeconds']), 'cohorts': cohorts,
            'complete': agents['status']=='complete' and len(turns)==protocol['agentTurns'] and len(cohorts)==2,
            'allCorrect': all(turn['allCorrect'] for turn in agents['turns']),
            'restore': [turn for turn in agents['turns'] if turn['gpuReset']],
            'cold': turns.get(0), 'metrics': agents['metrics']})
    power = [json.loads(line) for line in (root/'windows-memory.jsonl').read_text(encoding='utf-8-sig').splitlines() if line] if (root/'windows-memory.jsonl').exists() else []
    return {'directory': str(root), 'status': record['status'], 'config':record['config'],
        'image': read(root/'test-image.json'), 'memory':record['memory'],
        'powerCondition':record['power'], 'powerSamples':len(power),
        'powerStates':sorted({str(row.get('powerLineStatus')) for row in power}),
        'agents':rows, 'parallel':record['parallel'],
        'featuresPassed':len(read(root/'lmcache-features.json'))==6 and all(row['passed'] for row in read(root/'lmcache-features.json')) if (root/'lmcache-features.json').exists() else False}


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('runs',type=Path,nargs='+')
    parser.add_argument('--protocol',type=Path,default=Path('efficiency-protocol.json'))
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    protocol=read(args.protocol)
    runs=[score(root,protocol) for root in args.runs]
    errors=[]
    warnings=[]
    for run,profile in zip(runs,protocol['profiles']):
        name=run['directory']
        def require(passed,message):
            if not passed:
                errors.append(name+': '+message)
        require(run['status']=='complete','suite incomplete')
        require(run['config'].get('requestSeed')==protocol['requestSeed'],'seed mismatch')
        require(run['config'].get('agentTurns')==protocol['agentTurns'],'turn count mismatch')
        require(run['config'].get('prefillBatchTokens')==profile['batch'],'batch mismatch')
        require(run['config'].get('disableMtp')==(not profile['mtp']),'MTP setting mismatch')
        require(run['powerStates']==['Online'] and run['powerSamples']>0,'external power not verified throughout')
        require(run['featuresPassed'],'feature checks incomplete')
        require(run['memory'].get('gpuReportedCapacityGiB')==88,'GPU partition mismatch')
        minimum=run['memory'].get('lowestWindowsSample',{}).get('availableGiB',0)
        require(minimum>=protocol['constraints']['windowsTargetGiB'],'Windows headroom below target')
        require(sorted(row['concurrency'] for row in run['agents'])==sorted(profile['concurrencies']),'concurrency coverage incomplete')
        for row in run['agents']:
            require(row['complete'] and row['allCorrect'],'agent turns incomplete or incorrect')
            if row['metrics']['preemptions']:
                warnings.append(f"{name}: concurrency {row['concurrency']} had {row['metrics']['preemptions']} KV preemptions; include their cost in throughput")
            if row['metrics']['prefetchFailureChunks']:
                warnings.append(f"{name}: concurrency {row['concurrency']} declined {row['metrics']['prefetchFailureChunks']} cache prefetch chunks; check fallback costs")
            require(len(row['restore'])==1 and row['restore'][0]['metrics']['loadedChunks']>0,'no verified external restore')
        if profile.get('twoNear262K'):
            require(len(run['parallel'])>=3 and all(row['allCorrect'] for row in run['parallel']),'two near-262K session qualification incomplete')
    if len(runs)!=len(protocol['profiles']):
        errors.append('Protocol profile coverage incomplete')
    if len({run['image'].get('id') for run in runs})!=1:
        errors.append('Comparison images differ')
    result={'protocol':protocol,'qualified':not errors,'errors':errors,'warnings':warnings,'runs':runs}
    args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('Saved',args.output)
    raise SystemExit(1 if errors else 0)
