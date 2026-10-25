import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from run_suite import Suite


class ParallelStageTests(unittest.TestCase):
    def test_same_prompts_and_salts_survive_gpu_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / 'dataset.json'
            dataset.write_text(json.dumps({'samples': []}))
            suite = Suite(SimpleNamespace(output=directory, run_id='test',
                          lengths=[], dataset=str(dataset), concurrency=True))
            suite.capacity_check = True
            suite.parallel_context_tokens = 261000
            suite.parallel_sessions = 4
            suite.parallel_restore = True
            suite.phase = 'lmcache'
            resets, calls = [], []
            suite.reset = lambda: resets.append(True)
            suite.synthetic = lambda count, identity: ([identity], [identity], count-12)
            suite.metrics = lambda label: {'preemptions': 0}
            def chat(case, condition, messages, salt, expected):
                calls.append((case, condition, messages, salt))
                return {'id': case + condition, 'correct': True}
            suite.chat = chat
            suite.workload()
            self.assertEqual(len(resets), 2)
            self.assertEqual(len(calls), 12)
            for case in ('parallel-0', 'parallel-1', 'parallel-2', 'parallel-3'):
                rows = [row for row in calls if row[0] == case]
                self.assertEqual([row[1] for row in rows], ['cold', 'gpu-warm', 'gpu-reset'])
                self.assertEqual(len({row[3] for row in rows}), 1)
                self.assertTrue(all(row[2] == rows[0][2] for row in rows))
            evidence = json.loads((Path(directory) / 'lmcache-parallel-config.json').read_text())
            self.assertEqual(evidence['promptTokens'], [260988]*4)
            self.assertEqual(evidence['concurrency'], 4)


if __name__ == '__main__':
    unittest.main()
