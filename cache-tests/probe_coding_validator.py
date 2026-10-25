"""Check saved-program validation in the actual Linux/Python test environment."""
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_coding_results import validate

programs = {
    'positive_sum': 'def solve(values):\n    return sum(filter(lambda x: x > 0, values))',
    'deduplicate': 'def solve(values):\n    return list(dict.fromkeys(values))',
    'runs': 'def solve(values):\n    result = []\n    for value in values:\n        if result and result[-1][0] == value:\n            result[-1][1] += 1\n        else:\n            result.append([value, 1])\n    return result',
    'prefix_sums': 'def solve(values):\n    result = []\n    total = 0\n    for value in values:\n        total += value\n        result.append(total)\n    return result',
}
with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    for concurrency in (1,2,4):
        for name, source in programs.items():
            (root/f'lmcache-coding-c{concurrency}-{name}.json').write_text(json.dumps({
                'id': f'fixture-c{concurrency}-{name}', 'finishReason': 'stop',
                'message': {'content': source}}))
    checked = validate(root)
    assert checked['allCorrect'] and len(checked['rows']) == 12
    target = root/'lmcache-coding-c1-positive_sum.json'
    bad = json.loads(target.read_text())
    bad['message']['content'] = 'def solve(values):\n    return 0'
    target.write_text(json.dumps(bad))
    checked = validate(root)
    assert not checked['allCorrect'] and not checked['rows'][0]['correct']
    print(json.dumps({'passed': True, 'correctPrograms': 12, 'wrongProgramRejected': True,
                      'validatorSha256': checked['validatorSha256']}))
