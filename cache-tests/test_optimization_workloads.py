import json
from pathlib import Path
import tempfile
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from optimization_workloads import CODE_CHECK, agent_loops, append_tool_result, run_experiments, timed_request
from run_suite import Suite


class AgentTests(unittest.TestCase):
    def test_seed_zero_reaches_http_body(self):
        with tempfile.TemporaryDirectory() as directory:
            suite=Suite(SimpleNamespace(output=directory,run_id='seed-test'))
            suite.request_seed=0
            suite.guard=lambda: {}
            response={'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':'ok'}}],
                      'usage':{'completion_tokens':1}}
            with patch('optimization_workloads.request',return_value=response) as call:
                timed_request(suite,'seeded',[], 'salt')
            self.assertEqual(call.call_args.args[1]['seed'],0)

    def test_explicit_concurrency_includes_three_and_rejects_duplicates(self):
        with patch('optimization_workloads.agent_loops') as run:
            run_experiments(None, {'agentLoops': True, 'agentConcurrencies': [1,2,3,4]})
            self.assertEqual([call.args[1]['parallelSessions'] for call in run.call_args_list], [1,2,3,4])
            with self.assertRaises(ValueError):
                run_experiments(None, {'agentLoops': True, 'agentConcurrencies': [2,2]})

    def test_common_correct_idioms_are_accepted(self):
        cases = [
            ('def solve(values):\n    return list(dict.fromkeys(values))', [[[3,1,3,2,1],[3,1,2]], [[],[]]]),
            ('def solve(values):\n    return sum(filter(lambda v: v > 0, values))', [[[1,-2,3],4], [[],0]]),
        ]
        for source, fixtures in cases:
            checked = subprocess.run([sys.executable, '-I', '-c', CODE_CHECK],
                input=json.dumps({'source': source, 'tests': fixtures}),
                text=True, capture_output=True, timeout=10)
            self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_generated_code_is_checked_for_behavior_and_imports(self):
        for source, expected_ok in (
            ('def solve(values):\n    return sum(v for v in values if v > 0)', True),
            ('def solve(values):\n    return sum(values)', False),
            ('def solve(values):\n    import os\n    return 4', False),
        ):
            checked = subprocess.run([sys.executable, '-I', '-c', CODE_CHECK],
                input=json.dumps({'source': source, 'tests': [[[1,-2,3],4], [[],0]]}),
                text=True, capture_output=True, timeout=10)
            self.assertEqual(checked.returncode == 0, expected_ok, checked.stderr)

    def test_rejects_wrong_tool_arguments(self):
        response = {'role': 'assistant', 'tool_calls': [{'id': 'call1', 'type': 'function',
            'function': {'name': 'get_inventory', 'arguments': '{"sku":"wrong"}'}}]}
        with self.assertRaisesRegex(RuntimeError, 'Incorrect inventory'):
            append_tool_result([], response, 'expected', 1)

    def test_histories_append_and_restore_preserves_salts(self):
        with tempfile.TemporaryDirectory() as directory:
            suite = Suite(SimpleNamespace(output=directory, run_id='test'))
            suite.phase = 'lmcache'
            suite.synthetic = lambda target, identity: ([{'role': 'user', 'content': identity}], [], 100)
            suite.tokenize = lambda messages: 100
            resets, calls = [], []
            suite.reset = lambda: resets.append(True)
            counter = [0]
            def metrics(label):
                counter[0] += 1
                return {'lmcache_mp_num_chunks_loaded_total': counter[0]}
            suite.metrics = metrics
            def fake(suite, label, messages, salt, **kwargs):
                import copy
                calls.append((label, copy.deepcopy(messages), salt))
                session = int(salt.rsplit(':', 1)[1])
                if label.endswith('-tool'):
                    sku = messages[-1]['content'].split('inventory for ')[1].split('.')[0]
                    message = {'role': 'assistant', 'tool_calls': [{'id': label, 'type': 'function',
                        'function': {'name': 'get_inventory', 'arguments': json.dumps({'sku': sku})}}]}
                else:
                    result = json.loads(messages[-1]['content'])
                    result['codes'] = [f'AGENT{session}-{s}' for s in ('RIVER-729','MAPLE-418','COMET-653')]
                    message = {'role': 'assistant', 'content': json.dumps(result)}
                return {'message': message, 'totalSeconds': 1, 'usage': {'prompt_tokens': 100}}
            with patch('optimization_workloads.timed_request', side_effect=fake), patch('optimization_workloads.time.sleep'):
                agent_loops(suite, {'parallelSessions': 2, 'agentTurns': 4, 'agentContextTokens': 32000})
            self.assertEqual(len(resets), 2)
            for session in range(2):
                rows = [r for r in calls if r[2] == f'test:agent:c2:{session}' and r[0].endswith('-tool')]
                self.assertEqual(len(rows), 4)
                for previous, current in zip(rows, rows[1:]):
                    self.assertEqual(current[1][:len(previous[1])], previous[1])
                    self.assertEqual(len(current[1]), len(previous[1]) + 4)
            self.assertEqual(json.loads((Path(directory)/'agent-loops-c2.json').read_text())['status'], 'complete')


if __name__ == '__main__':
    unittest.main()
