"""Recheck exact saved model programs with the corrected bounded validator.

Inference images stay frozen across the matrix. This post-check distinguishes
validator restrictions (such as dict.fromkeys) from actual wrong answers.
Run in the test container with current cache-tests mounted at /probes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from optimization_workloads import CODE_CHECK, CODING_CASES


def validate(directory):
    rows = []
    for concurrency in (1,2,4):
        for name, _, tests in CODING_CASES:
            path = directory/f'lmcache-coding-c{concurrency}-{name}.json'
            if not path.exists():
                rows.append({'case': name, 'concurrency': concurrency, 'correct': False, 'error': 'Missing response'})
                continue
            saved = json.loads(path.read_text(encoding='utf-8-sig'))
            source = saved['message']['content'].strip()
            if source.startswith('```') and source.endswith('```'):
                source = source.split('\n',1)[1].rsplit('```',1)[0].strip()
            try:
                checked = subprocess.run([sys.executable,'-I','-c',CODE_CHECK],
                    input=json.dumps({'source': source, 'tests': tests}), text=True,
                    capture_output=True, timeout=10, cwd='/tmp')
                passed, error = checked.returncode == 0, checked.stderr[-2000:]
            except subprocess.TimeoutExpired:
                passed, error = False, 'Generated function exceeded 10 seconds'
            rows.append({'case': name, 'concurrency': concurrency,
                'responseId': saved['id'], 'sourceSha256': hashlib.sha256(source.encode()).hexdigest(),
                'correct': passed and saved['finishReason'] == 'stop', 'error': error})
    return {'status': 'complete', 'allCorrect': all(row['correct'] for row in rows),
            'validatorSha256': hashlib.sha256(CODE_CHECK.encode()).hexdigest(), 'rows': rows,
            'note': 'Exact saved programs re-executed; model outputs and inference timings unchanged.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    if sys.platform != 'linux':
        raise RuntimeError('Execute generated code only in the test container')
    print(json.dumps(validate(args.directory), indent=2))
