"""Sequential candidate runner; waits for an earlier isolated trial to finish."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--directory',type=Path,required=True)
    p.add_argument('--after',required=True)
    p.add_argument('--long',action='store_true')
    p.add_argument('--long-concurrency',nargs='+',choices=['2','4'],default=['2','4'])
    p.add_argument('--restore',action='store_true')
    p.add_argument('variants',nargs='+')
    a=p.parse_args()
    folder=a.directory.resolve()
    while True:
        try:
            state=json.loads((folder/a.after/'status.json').read_text())
            if state.get('stage')=='finished':
                if not state.get('success'):
                    raise SystemExit('Previous control failed; queue stopped')
                break
        except (FileNotFoundError,json.JSONDecodeError):
            pass
        time.sleep(5)
    results=[]
    for name in a.variants:
        if (folder/'STOP').exists():
            break
        cmd=[sys.executable,str(ROOT/'benchmarks/recipe_trial.py'),'--variant',str(folder/(name+'.json')),
             '--out',str(folder/name),'--name',name]
        if a.long:
            cmd+=['--long','--long-concurrency',*a.long_concurrency]
        if a.restore:
            cmd+=['--restore']
        result=subprocess.run(cmd,cwd=ROOT)
        results.append(dict(name=name,returncode=result.returncode))
        (folder/'queue-results.json').write_text(json.dumps(results,indent=2)+'\n')

if __name__=='__main__':
    main()
