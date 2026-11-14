"""Run the authorized 96 GiB comparison campaign, recording and restoring settings.

This owns the model API for the duration. Create STOP in the output directory
to stop after the current command. Configuration is restored in finally.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import traceback

from near_full_tools_report import report
from speed_probe import Client

ROOT = Path(__file__).resolve().parents[1]
CREATE_FLAGS = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


class TransportFailure(RuntimeError):
    pass


def healthy():
    try:
        Client('http://127.0.0.1:8000',timeout=3).get('/health')
        return True
    except Exception:
        return False


def write(path, value):
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    temporary.replace(path)


def variant(original, kv, cache, batch):
    text = original.decode('utf-8-sig')
    values = {'KvCacheBytes': f"'{kv*1024**3}'", 'UseLMCache': '$true' if cache else '$false',
              'BatchedTokens': str(batch)}
    for key, value in values.items():
        pattern = rf"(?m)^[ \t]*['\"]?{key}['\"]?\s*=[^\r\n]*"
        if len(re.findall(pattern,text)) > 1:
            raise ValueError(f'Ambiguous local setting: {key}')
        line = f'    {key} = {value}'
        if re.search(pattern,text):
            text = re.sub(pattern,lambda _:line,text)
        else:
            text, count = re.subn(r'\}\s*$',lambda _:line+'\n}\n',text)
            if count != 1:
                raise ValueError('Cannot safely append a local setting')
    return text.encode('utf-8')


def qualified(summary):
    return (len(summary['results'])==2 and {r['concurrency'] for r in summary['results']}=={2,4}
            and all(r['planned_tasks']==24 and r['correct_tasks']==24 for r in summary['results']))


def comparisons(control, candidate):
    a={r['concurrency']:r for r in control['results']}
    return [dict(concurrency=b['concurrency'],control_tasks_s=a[b['concurrency']]['correct_tasks_s'],
                 candidate_tasks_s=b['correct_tasks_s'],
                 throughput_ratio=(b['correct_tasks_s']/a[b['concurrency']]['correct_tasks_s']
                     if a[b['concurrency']]['correct_tasks_s'] > 0 else None),
                 comparison_eligible=control.get('qualified',False) and candidate.get('qualified',False),
                 candidate_correct=b['correct_tasks'],candidate_planned=b['planned_tasks'])
            for b in candidate['results']]


class Campaign:
    def __init__(self, out, baseline_from=None, resume_from=None, finish_from=None):
        self.finish_from=finish_from
        self.resume_from=resume_from
        self.baseline_from=baseline_from
        self.out=out.resolve()
        self.out.mkdir(parents=True,exist_ok=True)
        if (self.out/'status.json').exists():
            raise RuntimeError('Campaign directory already contains a run')
        self.config=ROOT/'config.local.psd1'
        self.original=self.config.read_bytes()
        self.expected=self.original
        self.ps=shutil.which('pwsh') or shutil.which('powershell')
        if not self.ps:
            raise RuntimeError('PowerShell is required')
        self.state={}
        self.current=None
        self.base_config=None
        self.summaries={}
        self.decisions={}
        self.changed=False

    def status(self, state, stage, **extra):
        self.state=dict(state=state,stage=stage,pid=os.getpid(),updated_utc=datetime.now(timezone.utc).isoformat(),**extra)
        write(self.out/'status.json',self.state)
        print(json.dumps(self.state),flush=True)

    def command(self, command, name, timeout=21600, allow_failure=False, restoring=False):
        if not restoring and (self.out/'STOP').exists():
            raise RuntimeError('STOP requested; restoring original configuration')
        with (self.out/(name+'.log')).open('w',encoding='utf-8') as output:
            process=subprocess.Popen([str(a) for a in command],cwd=ROOT,stdout=output,
                stderr=subprocess.STDOUT,creationflags=CREATE_FLAGS,env={**os.environ,'N1X_CLIENT_CONFIG':'off'})
            self.status('restoring' if restoring else 'running',name,child_pid=process.pid)
            start=time.monotonic()
            probe=any(Path(str(arg)).name in ('near_full_tools_probe.py','displaced_tools_probe.py') for arg in command)
            unhealthy=0
            while process.poll() is None:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
                write(self.out/'heartbeat.json',dict(stage=name,child_pid=process.pid,
                    utc=datetime.now(timezone.utc).isoformat(),elapsed_s=time.monotonic()-start))
                if probe and process.poll() is None:
                    unhealthy=0 if healthy() else unhealthy+1
                    if unhealthy>=3:
                        write(self.out/(name+'-watchdog.json'),dict(reason='Three consecutive health failures',elapsed_s=time.monotonic()-start))
                        process.terminate()
                        process.wait(30)
                if time.monotonic()-start > timeout:
                    process.terminate()
                    process.wait(30)
                    raise TimeoutError(f'{name} exceeded {timeout} seconds')
            if process.returncode and not allow_failure:
                raise RuntimeError(f'{name} exited {process.returncode}; see its log')
            return process.returncode

    def psfile(self, path, *args):
        return [self.ps,'-NoProfile','-File',ROOT/path,*args]

    def guard(self):
        if self.config.read_bytes()!=self.expected:
            raise RuntimeError('Local configuration changed outside the campaign; refusing to overwrite it')

    def capture(self, name):
        path=self.out/(name+'-host.json')
        self.command(self.psfile('benchmarks/campaign96_host.ps1','-Out',path),name+'-host',timeout=60)
        config=json.loads(path.read_text(encoding='utf-8-sig'))['config']
        if self.base_config is None:
            self.base_config=config
        else:
            differences={key for key in set(config)|set(self.base_config) if config.get(key)!=self.base_config.get(key)}
            if differences-{'KvCacheBytes','UseLMCache','BatchedTokens'}:
                raise RuntimeError(f'Unexpected configuration differences: {sorted(differences)}')
        return path,config

    def configure(self, name, kv, cache, batch):
        desired=(kv,cache,batch)
        self.guard()
        if self.current is None:
            self.command(self.psfile('n1x.ps1','start','-Profile','qwen38fn-best'),name+'-start',timeout=180)
            self.command(self.psfile('n1x.ps1','wait','-Profile','qwen38fn-best','-TimeoutSeconds','1200'),name+'-ready',timeout=1250)
            _,effective=self.capture('initial')
            self.current=(int(effective['KvCacheBytes'])//1024**3,effective['UseLMCache'],effective['BatchedTokens'])
        if self.current!=desired:
            data=variant(self.original,*desired)
            self.config.write_bytes(data)
            self.expected=data
            self.changed=True
            self.command(self.psfile('n1x.ps1','recreate','-Profile','qwen38fn-best'),name+'-recreate',timeout=180)
            self.command(self.psfile('n1x.ps1','wait','-Profile','qwen38fn-best','-TimeoutSeconds','1200'),name+'-ready',timeout=1250)
            self.current=desired
        host,effective=self.capture(name)
        actual=(int(effective['KvCacheBytes'])//1024**3,effective['UseLMCache'],effective['BatchedTokens'])
        if actual!=desired:
            raise RuntimeError(f'Configuration mismatch: {actual} != {desired}')
        self.guard()
        return host

    def recoverable(self, method, name, *settings):
        for attempt in range(1,4):
            attempt_name=f'{name}-attempt{attempt}'
            try:
                return method(attempt_name,*settings)
            except Exception as exc:
                write(self.out/(attempt_name+'-failure.json'),dict(error=repr(exc),traceback=traceback.format_exc(),attempt=attempt,excluded_from_speed_comparison=True))
                if (self.out/'STOP').exists() or (healthy() and not isinstance(exc,TransportFailure)) or attempt==3:
                    raise
                self.guard()
                self.status('recovering',name,failed_attempt=attempt,error=repr(exc))
                self.command(self.psfile('n1x.ps1','recreate','-Profile','qwen38fn-best'),attempt_name+'-recover',timeout=180)
                self.command(self.psfile('n1x.ps1','wait','-Profile','qwen38fn-best','-TimeoutSeconds','1200'),attempt_name+'-recover-ready',timeout=1250)

    def tools(self, name, kv, cache, batch):
        if self.resume_from:
            source=self.resume_from/f'{name}-attempt1'
            if (source/'summary.json').exists():
                summary=report(source)
                complete=(self.resume_from/f'{name}-attempt1-report.json').exists()
                summary.update(qualified=complete and qualified(summary),imported_from=str(source.resolve()),interrupted=not complete)
                self.summaries[name]=summary
                write(self.out/(name+'-retained.json'),summary)
                return summary
        try:
            return self.recoverable(self.tools_once,name,kv,cache,batch)
        except TransportFailure:
            folder=self.out/f'{name}-attempt3'
            if (self.out/'STOP').exists() or not (folder/'summary.json').exists():
                raise
            summary=report(folder)
            summary.update(qualified=False,recovery_exhausted=True)
            self.summaries[name]=summary
            write(self.out/(name+'-unqualified.json'),summary)
            return summary

    def tools_once(self, name, kv, cache, batch):
        host=self.configure(name,kv,cache,batch)
        code=self.command([sys.executable,ROOT/'benchmarks/near_full_tools_probe.py',
            '--out',self.out/name,'--host',host,'--sessions','4','--concurrency','2','4','--repeats','2'],
            name,allow_failure=True)
        self.command(['wslc','logs','n1x-qwen38fn-best'],name+'-server',timeout=60)
        summary_path=self.out/name/'summary.json'
        errors_path=self.out/name/'errors.jsonl'
        if code and errors_path.exists() and any(word in errors_path.read_text(encoding='utf-8') for word in ('URLError','TimeoutError','ConnectionAbortedError','ConnectionResetError')):
            raise TransportFailure(f'{name}: client transport failure; first scores preserved')
        if code and not summary_path.exists():
            raise RuntimeError(f'{name} probe exited {code}; inspect {name}.log and {name}-server.log. Partial first attempts retained.')
        summary=report(self.out/name)
        summary['process_exit_code']=code
        summary['qualified']=qualified(summary) and code==0
        self.summaries[name]=summary
        write(self.out/(name+'-report.json'),summary)
        self.capture(name+'-after')
        self.guard()
        return summary

    def replay(self,name,kv,cache):
        return self.recoverable(self.replay_once,name,kv,cache)

    def replay_once(self,name,kv,cache):
        host=self.configure(name,kv,cache,8192)
        code=self.command([sys.executable,ROOT/'benchmarks/displaced_tools_probe.py','--out',self.out/name,
            '--host',host,'--repeats','2'],name,allow_failure=True)
        self.command(['wslc','logs','n1x-qwen38fn-best'],name+'-server',timeout=60)
        if code:
            raise RuntimeError(f'{name} replay exited {code}; first attempts preserved')
        groups=json.loads((self.out/name/'summary.json').read_text(encoding='utf-8'))
        self.summaries[name]=dict(groups=groups,complete=len(groups)==2,
            correctness_passed=len(groups)==2 and all(g['correct_tasks']==g['planned_tasks'] for g in groups),
            native_displacement_verified=len(groups)==2 and all(g['native_displacement_verified'] for g in groups),
            external_restore_verified=len(groups)==2 and all(g['external_restore_verified'] for g in groups))
        self.capture(name+'-after')
        self.guard()

    def restore(self):
        self.guard()
        if self.changed:
            self.config.write_bytes(self.original)
            self.expected=self.original
            self.command(self.psfile('n1x.ps1','recreate','-Profile','qwen38fn-best'),
                'restore-original-recreate',timeout=180,restoring=True)
            self.command(self.psfile('n1x.ps1','wait','-Profile','qwen38fn-best','-TimeoutSeconds','1200'),
                'restore-original-ready',timeout=1250,restoring=True)

    def markdown(self, error, restored):
        lines=['# 96 GiB comparison campaign','',
            'Status: '+('failed: '+error if error else 'complete')+'.',
            f'Original configuration restored: {restored}.','',
            '| Configuration | C | Correct tasks | Batch seconds | Correct tasks/s | Warm task seconds |',
            '| --- | ---: | ---: | ---: | ---: | ---: |']
        for name,summary in self.summaries.items():
            for row in summary.get('results',[]):
                warm=row['appended_task_mean_s']
                warm_text=f'{warm:.2f}' if warm is not None else 'unavailable'
                lines.append(f"| {name} | {row['concurrency']} | {row['correct_tasks']}/{row['planned_tasks']} | "
                    f"{row['elapsed_s']:.2f} | {row['correct_tasks_s']:.5f} | {warm_text} |")
        lines+=['','## Displaced replay','',
            '| Configuration | Repeat | Correct tasks | Replay seconds | Native displacement verified | External restore verified |',
            '| --- | ---: | ---: | ---: | --- | --- |']
        for name,summary in self.summaries.items():
            for row in summary.get('groups',[]):
                lines.append(f"| {name} | {row['repeat']} | {row['correct_tasks']}/{row['planned_tasks']} | "
                    f"{row['elapsed_s']:.2f} | {row['native_displacement_verified']} | {row['external_restore_verified']} |")
        lines+=['','Configuration order was not counterbalanced. These are screening results; '
            'no matched 88 GiB control was run. Inspect first scores, cache counters and raw logs before promoting a setting.',
            'The provisional KV choice only controls follow-up tests; the campaign restores the original settings.','']
        (self.out/'comparison.md').write_text('\n'.join(lines),encoding='utf-8')

    def run(self):
        lock=ROOT/'.state/campaign96.lock'
        lock.parent.mkdir(exist_ok=True)
        with lock.open('x',encoding='utf-8') as file:
            json.dump(dict(pid=os.getpid(),out=str(self.out)),file)
        error=None
        restored=False
        try:
            (self.out/'config.local.original.psd1').write_bytes(self.original)
            write(self.out/'plan.json',dict(protocol='n1x-campaign96-v1',partition_mib=98304,
                input_target=250000,output_allowance=8192,sessions=4,turns=3,repeats=2,
                concurrency=[2,4],concurrency_order='2,4 then 4,2',
                stages=['KV11 on batch8K','KV15 on batch8K','chosen KV cache off batch8K',
                        'cache-off displaced C2 replay','cache-on displaced C2 replay','chosen KV cache on batch4K'],
                selection='For follow-up tests only: choose KV15 if all tasks pass and combined correct-work throughput improves at least 5%; otherwise KV11.',
                limits='Configuration order is not counterbalanced. Results are screening evidence, not statistical proof or a matched 88/96 GiB comparison.',
                restore_original=True,started_utc=datetime.now(timezone.utc).isoformat(),
                recovery_policy='Three health-check failures abort an interrupted probe; up to two same-configuration server recreations and fresh whole-stage attempts. Failed attempts retained separately; successful retry does not establish failure-free reliability.',
                source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (
                    Path(__file__),ROOT/'benchmarks/campaign96_host.ps1',ROOT/'benchmarks/near_full_tools_probe.py',
                    ROOT/'benchmarks/near_full_tools_report.py',ROOT/'benchmarks/displaced_tools_probe.py')}))
            if self.finish_from:
                for source in self.finish_from.glob('*-retained.json'):
                    self.summaries[source.stem]=json.loads(source.read_text(encoding='utf-8'))
                off=self.finish_from/'kv11-off-replay-attempt1/summary.json'
                groups=json.loads(off.read_text(encoding='utf-8'))
                if len(groups)!=2:
                    raise RuntimeError('Expected two completed cache-off replay groups')
                self.summaries['retained-off-replay']=dict(groups=groups,imported_from=str(off.resolve()))
                self.replay('kv11-on-replay',11,True)
                self.tools('kv11-on-4k',11,True,4096)
            else:
                if self.baseline_from:
                    a=report(self.baseline_from)
                    a.update(qualified=False,imported_from=str(self.baseline_from.resolve()),reason='Retained failed baseline; not eligible for promotion comparisons')
                    self.summaries['retained-kv11-baseline']=a
                    write(self.out/'retained-baseline.json',a)
                else:
                    a=self.tools('kv11-on-8k',11,True,8192)
                b=self.tools('kv15-on-8k',15,True,8192)
                def rate(summary):
                    return sum(r['correct_tasks'] for r in summary['results'])/sum(r['elapsed_s'] for r in summary['results'])
                control_rate=rate(a)
                ratio=rate(b)/control_rate if control_rate > 0 else None
                chosen=15 if a['qualified'] and b['qualified'] and ratio is not None and ratio>=1.05 else 11
                chosen_summary=b if chosen==15 else a
                self.decisions['kv']=dict(chosen_for_followups=chosen,kv15_over_kv11=ratio,
                    kv15_qualified=b['qualified'],comparison_eligible=a['qualified'] and b['qualified'],by_concurrency=comparisons(a,b))
                write(self.out/'decisions.json',self.decisions)
                off=self.tools(f'kv{chosen}-off-8k',chosen,False,8192)
                self.decisions['cache_off_vs_on']=comparisons(chosen_summary,off)
                self.replay(f'kv{chosen}-off-replay',chosen,False)
                self.replay(f'kv{chosen}-on-replay',chosen,True)
                small=self.tools(f'kv{chosen}-on-4k',chosen,True,4096)
                self.decisions['batch4k_vs_8k']=comparisons(chosen_summary,small)
                write(self.out/'decisions.json',self.decisions)
        except BaseException as exc:
            error=repr(exc)
            (self.out/'failure-traceback.txt').write_text(traceback.format_exc(),encoding='utf-8')
            write(self.out/'failure.json',dict(error=error,stage=self.state,utc=datetime.now(timezone.utc).isoformat()))
        finally:
            try:
                self.restore()
                restored=True
            except BaseException as exc:
                error=(error+'; ' if error else '')+'RESTORE: '+repr(exc)
            write(self.out/'summary.json',dict(status='failed' if error else 'complete',error=error,
                original_configuration_restored=restored,decisions=self.decisions,results=self.summaries,
                failed_attempt_files=[p.name for p in self.out.glob('*-attempt*-failure.json')]))
            self.markdown(error,restored)
            self.status('failed' if error else 'complete','finished',error=error,original_configuration_restored=restored)
            lock.unlink()
        if error:
            raise SystemExit(error)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--baseline-from',type=Path)
    parser.add_argument('--resume-from',type=Path)
    parser.add_argument('--finish-from',type=Path)
    args=parser.parse_args()
    Campaign(args.out,args.baseline_from,args.resume_from,args.finish_from).run()
