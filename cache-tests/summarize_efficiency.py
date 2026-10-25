"""Score checked warm turns; keep cold and forced restore out of throughput."""
import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from summarize_optimizations import summarize, read


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values)*fraction)-1)]


def score(root, protocol):
    record = summarize(root)
    rows = []
    for agents in record['agents']:
        raw=read(root/agents['file'])['turns']
        count=len(raw[0]['sessions'])
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
        histories={str(index):[next((row.get('promptTokens',0) for row in turn['sessions'] if row['session']==index),0) for turn in raw] for index in range(count)}
        rows.append({'concurrency': count, 'cohorts': cohorts,
            'complete': agents['status']=='complete' and [turn['turn'] for turn in raw]==list(range(protocol['agentTurns'])) and len(cohorts)==2
                        and all(sorted(row['session'] for row in turn['sessions'])==list(range(count)) for turn in raw),
            'historyPromptTokens':histories,
            'allCorrect': all(turn['allCorrect'] for turn in agents['turns']),
            'restore': [turn for turn in agents['turns'] if turn['gpuReset']],
            'cold': turns.get(0), 'metrics': agents['metrics']})
    power = [json.loads(line) for line in (root/'windows-memory.jsonl').read_text(encoding='utf-8-sig').splitlines() if line] if (root/'windows-memory.jsonl').exists() else []
    image=read(root/'test-image.json')
    wrapper=root/'collect_rejected_reference.py'
    wrapper_source=Path(__file__).with_name('collect_rejected_reference.py')
    wrapper_verified=wrapper.exists() and image.get('clientWrapperSha256')==hashlib.sha256(wrapper.read_bytes()).hexdigest()==hashlib.sha256(wrapper_source.read_bytes()).hexdigest()
    return {'directory': str(root), 'status': record['status'], 'config':record['config'],
        'image': image, 'memory':record['memory'],
        'referenceFeatureRejection':read(root/'reference-feature-rejection.json'),
        'referenceWrapperVerified':wrapper_verified,
        'powerCondition':record['power'], 'powerSamples':len(power),
        'powerStates':sorted({str(row.get('powerLineStatus')) for row in power}),
        'allWindowsMinimumGiB':min((row['availableGiB'] for row in power),default=0),
        'agents':rows, 'parallel':record['parallel'],
        'featuresPassed':len(read(root/'lmcache-features.json'))==6 and all(row['passed'] for row in read(root/'lmcache-features.json')) if (root/'lmcache-features.json').exists() else False}


def qualify(runs,protocol):
    errors=[]
    warnings=[]
    for run,profile in zip(runs,protocol['profiles']):
        error_start=len(errors)
        name=run['directory']
        def require(passed,message):
            if not passed:
                errors.append(name+': '+message)
        require(run['status']=='complete','suite incomplete')
        require(run['config'].get('requestSeed')==protocol['requestSeed'],'seed mismatch')
        require(run['config'].get('agentTurns')==protocol['agentTurns'],'turn count mismatch')
        require(run['config'].get('prefillBatchTokens')==profile['batch'],'batch mismatch')
        require(run['config'].get('disableMtp')==(not profile['mtp']),'MTP setting mismatch')
        fixed=protocol['fixed']
        require(run['config'].get('lmcacheL1GiB')==fixed['lmcacheL1GiB'],'host cache budget mismatch')
        arguments=run['config'].get('modelArgs',[])
        def option(name):
            return arguments[arguments.index(name)+1] if arguments.count(name)==1 and arguments.index(name)+1<len(arguments) else None
        for flag,expected in {'--max-num-batched-tokens':profile['batch'],
                              '--max-model-len':262144,'--max-num-seqs':16,
                              '--kv-cache-memory-bytes':fixed['gpuKvGiB']*1024**3,
                              '--kv-cache-dtype':'fp8_e4m3','--mamba-ssm-cache-dtype':'bfloat16'}.items():
            require(option(flag)==str(expected),'actual launch argument mismatch: '+flag)
        require(bool(re.fullmatch(r'sha256:[0-9a-f]{64}',run['image'].get('id',''))),'missing image identity')
        require(run['powerStates']==['Online'] and run['powerSamples']>0,'external power not verified throughout')
        rejected=(not run['featuresPassed'] and profile.get('name')=='batch8192-mtp'
                  and run['config'].get('collectRejectedReference') is True
                  and run.get('referenceWrapperVerified') is True
                  and run.get('referenceFeatureRejection',{}).get('qualified') is False
                  and run['referenceFeatureRejection'].get('error')=='Feature check failed: vision_ocr')
        require(run['featuresPassed'] or rejected,'feature checks incomplete')
        if rejected:
            warnings.append(name+': rejected OCR reference; text timing only, excluded from recommendation')
        require(run['allWindowsMinimumGiB']>=protocol['constraints']['windowsGuardGiB'],'Windows headroom below guard')
        require(run['memory'].get('gpuReportedCapacityGiB')==88,'GPU partition mismatch')
        minimum=run['memory'].get('lowestWindowsSample',{}).get('availableGiB',0)
        require(minimum>=protocol['constraints']['windowsTargetGiB'],'Windows headroom below target')
        require(sorted(row['concurrency'] for row in run['agents'])==sorted(profile['concurrencies']),'concurrency coverage incomplete')
        for row in run['agents']:
            require(row['complete'] and row['allCorrect'],'agent turns incomplete or incorrect')
            require(all(values and values[0]>=fixed['agentContextTarget'] and
                        all(b>a for a,b in zip(values,values[1:])) for values in row['historyPromptTokens'].values()),
                    'long growing histories not verified')
            drafts=row['metrics']['draftTokens']
            require(drafts>0 if profile['mtp'] else drafts==0,'runtime draft counters mismatch')
            if row['metrics']['preemptions']:
                warnings.append(f"{name}: concurrency {row['concurrency']} had {row['metrics']['preemptions']} KV preemptions; include their cost in throughput")
            if row['metrics']['prefetchFailureChunks']:
                warnings.append(f"{name}: concurrency {row['concurrency']} declined {row['metrics']['prefetchFailureChunks']} cache prefetch chunks; check fallback costs")
            require(len(row['restore'])==1 and row['restore'][0]['turn']==protocol['agentTurns']//2
                    and row['restore'][0]['metrics']['loadedChunks']>0,'no verified external restore at the required turn')
        if profile.get('twoNear262K'):
            require(run['config'].get('parallelSessions')==2 and run['config'].get('parallelContextTokens')==261000,'two near-262K configuration mismatch')
            stages={row['stage']:row for row in run['parallel']}
            require(set(stages)=={'cold','gpu-warm','gpu-reset'},'two near-262K stages incomplete')
            for stage in stages.values():
                require(stage['allCorrect'] and stage['allResponsesCorrect'] and stage['requestCount']==2
                        and len(stage['promptTokens'])==2 and all(260000<=count<262144 for count in stage['promptTokens']),
                        'two near-262K direct response evidence incomplete')
            restored=stages.get('gpu-reset',{}).get('metrics',{})
            require(restored.get('externalHitTokens',0)>=516096 and restored.get('loadedChunks',0)>=254,
                    'two full external prefixes not verified')
        run['profileName']=profile.get('name')
        run['qualificationErrors']=errors[error_start:]+(['OCR rejected; remaining feature checks did not run'] if rejected else [])
        run['qualified']=not run['qualificationErrors']
    if len(runs)!=len(protocol['profiles']):
        errors.append('Protocol profile coverage incomplete')
    if len({run['image'].get('id') for run in runs})!=1:
        errors.append('Comparison images differ')
    return errors,warnings


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('runs',type=Path,nargs='+')
    parser.add_argument('--protocol',type=Path,default=Path('efficiency-protocol.json'))
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    protocol=read(args.protocol)
    runs=[score(root,protocol) for root in args.runs]
    errors,warnings=qualify(runs,protocol)
    result={'protocol':protocol,'experimentsComplete':not errors,
            'qualified':not errors and all(run['qualified'] for run in runs),
            'eligibleProfiles':[run['profileName'] for run in runs if run['qualified']],
            'errors':errors,'warnings':warnings,'runs':runs}
    args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('Saved',args.output)
    raise SystemExit(1 if errors else 0)
