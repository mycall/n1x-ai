"""Paired KV20/K5 batch comparison; retains failures and retires only its trial caches."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import statistics
import subprocess
import sys

from recipe_report import summarize

ROOT = Path(__file__).resolve().parents[1]


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def stats(values):
    return dict(n=len(values), mean=statistics.mean(values) if values else None,
                median=statistics.median(values) if values else None,
                minimum=min(values) if values else None, maximum=max(values) if values else None,
                sample_sd=statistics.stdev(values) if len(values)>1 else None)


def report(folder, plan, output):
    trials=[]
    for item in plan['runs']:
        directory=folder/item['name']
        if (directory/'status.json').exists():
            trials.append(dict(pair=item['pair'], batch=item['batch'], seed=item['seed'], **summarize(directory)))
    groups={}
    for batch in (4096,8192):
        rows=[r for r in trials if r['batch']==batch]
        long=[g for r in rows for g in r.get('near_full',[]) if g['concurrency']==4]
        screens=[s for r in rows for s in r.get('quality-screens',[])]
        restores=[r['restore'] for r in rows if 'restore' in r]
        speeds={}
        for c,d in ((1,4096),(1,32768),(2,4096),(2,32768)):
            points=[p for r in rows for p in r.get('speed',[]) if p['concurrency']==c and p['depth']==d
                    and p['valid']==p['recorded']==2*c and p.get('write_tokens_s') is not None]
            speeds[f'c{c}-d{d}']={key:stats([p[key] for p in points]) for key in ('read_tokens_s','write_tokens_s')}
        groups[str(batch)]=dict(planned_trials=3, recorded_trials=len(rows),
            finished_trials=sum(r['status']['stage']=='finished' for r in rows),
            long_elapsed_s=stats([g['elapsed_s'] for g in long]),
            long_correct=sum(g['correct_tasks'] for g in long), long_planned=sum(g['planned_tasks'] for g in long),
            followup_hits=sum(v['requests_with_cached_tokens'] for g in long for k,v in g['cache_evidence'].items() if k!='cold-selection'),
            followup_requests=sum(v['requests'] for g in long for k,v in g['cache_evidence'].items() if k!='cold-selection'),
            short_screens=len(screens), short_planned=32*len(screens),
            short_correct=sum(sum(a['correct'] for a in s['archive'])+s['recovery'].get('correct',0) for s in screens),
            restore_elapsed_s=stats([r['elapsed_s'] for r in restores]),
            restore_correct=sum(r['correct'] for r in restores), restore_requests=2*len(restores),
            strict_restore_passes=sum(r['qualified'] for r in restores),
            restore_chunk_coverage=stats([q['complete_chunk_coverage'] for r in restores for q in r.get('verification_requests',[])]),
            minimum_gpu_free_mib=min((r['resources']['minimum_gpu_free_mib'] for r in rows
                if r.get('resources',{}).get('minimum_gpu_free_mib') is not None),default=None), speed=speeds)
    pairs=[]
    for pair in range(1,4):
        values={r['batch']:r['near_full'][0]['elapsed_s'] for r in trials if r['pair']==pair and r.get('near_full')}
        if len(values)==2:
            pairs.append(dict(pair=pair,batch4k_s=values[4096],batch8k_s=values[8192],
                              batch8k_elapsed_reduction_pct=100*(1-values[8192]/values[4096])))
    save(output,dict(plan=plan,groups=groups,paired_results=pairs,trials=trials))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--directory',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--tag',default='20261117-averages')
    p.add_argument('--report-only',action='store_true')
    a=p.parse_args()
    folder=a.directory.resolve()
    plan_path=folder/(a.tag+'-plan.json')
    if plan_path.exists():
        plan=json.loads(plan_path.read_text())
    else:
        plan=dict(created_utc=datetime.now(timezone.utc).isoformat(),
            scope='Three new paired full trials per batch; prior exploratory results excluded from primary averages.',
            order='4K/8K, 8K/4K, 4K/8K', quality_seeds=[45,46,47],
            failure_policy='Retain all first scores; continue long/restore after short failures; average all completed workloads, not only passes.',runs=[])
        for pair,order in enumerate(((4096,8192),(8192,4096),(4096,8192)),1):
            for batch in order:
                name=f'w4-kv20-batch{batch//1024}k-k5-{a.tag}-r{pair}'
                variant=dict(flags={'mamba-ssm-cache-dtype':'bfloat16'},config=dict(
                    Container='n1x-recipe-trial',LmcacheNamespace='qwen-recipe-'+name,
                    LmcacheVolume='n1x-recipe-'+name,KvCacheBytes='21474836480',BatchedTokens=batch,DFlashTokens=5))
                save(folder/(name+'.json'),variant)
                plan['runs'].append(dict(name=name,pair=pair,batch=batch,seed=44+pair,volume=variant['config']['LmcacheVolume']))
        save(plan_path,plan)
    a.out.parent.mkdir(parents=True,exist_ok=True)
    if a.report_only:
        report(folder,plan,a.out)
        return
    for item in plan['runs']:
        directory=folder/item['name']
        if (folder/'STOP').exists():
            break
        if not directory.exists():
            if shutil.disk_usage(folder).free<80*1024**3:
                raise RuntimeError('Less than 80 GiB disk headroom; no new trial started')
            cmd=[sys.executable,str(ROOT/'benchmarks/recipe_trial.py'),'--variant',str(folder/(item['name']+'.json')),
                '--out',str(directory),'--name',item['name'],'--quality-seeds',str(item['seed']),
                '--continue-after-quality-failure','--long','--long-concurrency','4','--restore']
            print('TRIAL '+item['name'],flush=True)
            result=subprocess.run(cmd,cwd=ROOT)
            save(directory/'runner-returncode.json',dict(returncode=result.returncode))
        state=json.loads((directory/'status.json').read_text())
        if state['stage']!='finished':
            raise RuntimeError('Existing unfinished trial requires inspection: '+item['name'])
        report(folder,plan,a.out)
        if not (directory/'cleanup.json').exists():
            inspected=json.loads(subprocess.check_output(['wslc','inspect','n1x-recipe-trial'],text=True))
            container=inspected[0] if isinstance(inspected,list) else inspected
            if container['State']['Running']:
                raise RuntimeError('Refusing to remove a running trial')
            if not any(m.get('Name')==item['volume'] for m in container.get('Mounts',[])):
                raise RuntimeError('Trial volume does not match the stopped container')
            subprocess.run(['wslc','rm','n1x-recipe-trial'],check=True)
            subprocess.run(['wslc','volume','rm',item['volume']],check=True)
            trim=subprocess.run(['wslc','system','session','run','/usr/sbin/fstrim','-av'],capture_output=True,text=True)
            save(directory/'cleanup.json',dict(volume=item['volume'],removed=True,trim_returncode=trim.returncode,
                trim_stdout=trim.stdout,trim_stderr=trim.stderr,raw_evidence_preserved=True))
    report(folder,plan,a.out)


if __name__=='__main__':
    main()
