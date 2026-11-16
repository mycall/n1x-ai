"""Run one isolated recipe contender without editing the selected configuration."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import traceback

from speed_probe import Client, save

ROOT = Path(__file__).resolve().parents[1]
CONTAINER = 'n1x-recipe-trial'


def run(args):
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    variant = args.variant.resolve()
    original = (ROOT/'config.local.psd1').read_bytes()
    save(out/'variant.json',json.loads(variant.read_text(encoding='utf-8-sig')))
    sources=[Path(__file__),ROOT/'benchmarks/recipe_trial_host.ps1',ROOT/'benchmarks/recipe_quality_probe.py',
             ROOT/'benchmarks/speed_probe.py',ROOT/'benchmarks/near_full_tools_probe.py']
    save(out/'source-hashes.json',{str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest() for path in sources})
    stop = threading.Event()
    state = {}

    def status(stage, **extra):
        state.update(stage=stage, unix_s=time.time(), **extra)
        save(out/'status.json', state)
        print(json.dumps(state), flush=True)

    def command(argv, name, timeout=3600, required=True):
        status(name)
        with (out/(name+'.log')).open('w', encoding='utf-8') as log:
            result = subprocess.run([str(x) for x in argv], cwd=ROOT, stdout=log,
                                    stderr=subprocess.STDOUT, timeout=timeout,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if required and result.returncode:
            raise RuntimeError(f'{name} failed ({result.returncode})')
        return result.returncode

    def host(action):
        return ['pwsh','-NoProfile','-File',ROOT/'benchmarks/recipe_trial_host.ps1',
                '-Variant',variant,'-Out',out,'-Action',action]

    def wait_ready():
        client=Client('http://127.0.0.1:8000',timeout=5)
        status('waiting-ready')
        deadline=time.monotonic()+2400
        stopped_observations=0
        while True:
            try:
                client.get('/health')
                return
            except Exception:
                if time.monotonic()>deadline:
                    raise TimeoutError('Readiness exceeded 40 minutes')
                result=subprocess.run(['wslc','inspect',CONTAINER],capture_output=True,text=True)
                try:
                    inspected=json.loads(result.stdout) if result.returncode==0 else []
                except ValueError:
                    inspected=[]
                if isinstance(inspected,dict):
                    inspected=[inspected]
                if not inspected:
                    save(out/'inspection-transient.json',dict(unix_s=time.time(),returncode=result.returncode,
                        stdout=result.stdout,stderr=result.stderr))
                    stopped_observations=0
                elif not inspected[0]['State']['Running']:
                    stopped_observations+=1
                    save(out/'inspection-stopped.json',inspected)
                    if stopped_observations>=2:
                        raise RuntimeError('Trial container exited before readiness (confirmed twice)')
                else:
                    stopped_observations=0
                time.sleep(5)

    def monitor():
        with (out/'telemetry.jsonl').open('w',encoding='utf-8') as log:
            while not stop.is_set():
                result=subprocess.run(['nvidia-smi','--id=0','--query-gpu=memory.used,memory.free,clocks.sm,power.draw,temperature.gpu',
                    '--format=csv,noheader'],capture_output=True,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                try:
                    memory=json.loads((ROOT/'.state'/CONTAINER/'host.json').read_text(encoding='utf-8-sig'))
                except (OSError,ValueError):
                    memory=None
                log.write(json.dumps(dict(unix_s=time.time(),stage=state.get('stage'),gpu=result.stdout.strip(),host=memory))+'\n')
                log.flush()
                stop.wait(5)

    watcher=threading.Thread(target=monitor,daemon=True)
    watcher.start()
    failure=None
    launched=False
    try:
        command(host('launch'),'launch',timeout=180)
        launched=True
        wait_ready()
        command(host('capture'),'capture',timeout=90)
        # Warm each candidate before measuring. Preserve any first-attempt failure.
        status('warmup')
        warm=Client('http://127.0.0.1:8000',timeout=180).get('/v1/chat/completions',dict(
            model='qwen/qwen38fn-best',messages=[dict(role='user',content='What is 17 plus 25? Reply with the number.')],
            max_tokens=8192,temperature=0,chat_template_kwargs=dict(enable_thinking=True)))
        save(out/'warmup.json',warm)
        if not (warm['choices'][0]['message'].get('content') or '').strip():
            save(out/'warmup-retry.json',Client('http://127.0.0.1:8000',timeout=180).get('/v1/chat/completions',dict(
                model='qwen/qwen38fn-best',messages=[dict(role='user',content='What is 17 plus 25? Reply with the number.')],
                max_tokens=8192,temperature=0,chat_template_kwargs=dict(enable_thinking=True))))
            raise RuntimeError('Empty first warmup answer')
        if not args.skip_screen:
            command([sys.executable,ROOT/'benchmarks/speed_probe.py','--out',out/'speed','--profile',args.name,
                '--host-record',out/'host.json','--depths',*args.depths,'--concurrency','1','2','--repeats','2',
                '--output-tokens','512','--context-limit','262144','--mode','cold','--timeout','900'],'speed',timeout=5400)
            quality=ROOT/'benchmarks/recipe_quality_probe.py'
            command([sys.executable,quality,'--out',out/'quality','--variants','xhigh-t06','--phases','quality','recovery',
                     '--quality-depth','32768'],'quality',timeout=2400)
            completed=json.loads((out/'quality/completed.json').read_text())
            if completed['failures']:
                raise RuntimeError('Quality screen failed; retained first scores')
            scores=json.loads((out/'quality/xhigh-t06/quality/summary.json').read_text())
            if len(scores)!=2 or any(row['correct']!=row['planned'] for row in scores):
                raise RuntimeError('Archive quality screen did not pass every first attempt')
        if args.long:
            command([sys.executable,ROOT/'benchmarks/near_full_tools_probe.py','--out',out/'near-full',
                '--host',out/'host.json','--target','250000','--concurrency',*args.long_concurrency,'--sessions','4',
                '--turns','3','--repeats','1'],'near-full',timeout=3600)
        if args.restore:
            config=json.loads((out/'config.json').read_text(encoding='utf-8-sig'))
            if not config['UseLMCache']:
                raise RuntimeError('SSD restore qualification requires an LMCache candidate')
            restore=out/'restore'
            restore.mkdir()
            for stage in ('seed','verify'):
                if stage=='verify':
                    command(host('restart'),'restart',timeout=180)
                    wait_ready()
                command(['wslc','run','--rm','--network',f'container:{CONTAINER}',
                    '--volume',f'{ROOT}/benchmarks:/benchmarks:ro','--volume',f'{restore}:/results',
                    '--entrypoint','python3',config['ImageId'],'/benchmarks/restart_restore_probe.py',stage],
                    'restore-'+stage,timeout=1800)
    except BaseException as error:
        failure=repr(error)
        save(out/'failure.json',dict(error=failure,traceback=traceback.format_exc()))
    finally:
        if launched:
            command(['wslc','logs',CONTAINER],'server',timeout=90,required=False)
            command(host('stop'),'stop',timeout=180,required=False)
            command(['wslc','logs',CONTAINER],'server-final',timeout=90,required=False)
        stop.set()
        watcher.join(10)
        if (ROOT/'config.local.psd1').read_bytes()!=original:
            failure=(failure or '')+' Selected configuration changed externally; not overwritten.'
        status('finished',success=failure is None,error=failure)
    if failure:
        raise SystemExit(failure)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--variant',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--name',required=True)
    parser.add_argument('--depths',nargs='+',default=['4096','32768'])
    parser.add_argument('--long',action='store_true')
    parser.add_argument('--restore',action='store_true')
    parser.add_argument('--skip-screen',action='store_true',help='Run only explicitly requested long/restore qualification')
    parser.add_argument('--long-concurrency',nargs='+',choices=['2','4'],default=['2','4'])
    args=parser.parse_args()
    if args.skip_screen and not (args.long or args.restore):
        parser.error('--skip-screen requires --long or --restore')
    run(args)
