import json
from pathlib import Path
import tempfile
import unittest

from benchmarks.vllm_speed_matrix_report import summarize


class MatrixReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.write('manifest.json', dict(protocol='test', repeats=2,
                                        contexts=[4096], concurrency=[1]))
        for repeat, pp, decode in [(1, 2, 10), (2, 6, 30)]:
            name = f'r{repeat}-c1-n4096'
            self.write(name+'-receipt.json', dict(name=name, repeat=repeat,
                concurrency=1, target_input=4096, valid=True, responses=[dict(
                    done=True, status=200, finish_reason='length',
                    usage=dict(prompt_tokens=4096, completion_tokens=512,
                               prompt_tokens_details=dict(cached_tokens=0)),
                    metrics=dict(time_to_first_token_ms=pp*1000,
                                 generation_time_ms=decode*1000, queue_time_ms=100))]))
            self.write(name+'-vllm.json', dict(duration=pp+decode, ttfts=[pp],
                        latencies=[pp+decode], mean_tpot_ms=decode/511*1000))

    def write(self, name, data):
        (self.root/name).write_text(json.dumps(data))

    def test_uses_phase_duration_weighting_and_separate_burst_throughput(self):
        result = summarize(self.root)
        cell = result['cells'][0]
        self.assertTrue(result['complete'])
        self.assertEqual(result['measured_requests'], 2)
        self.assertEqual(cell['read_tks'], 8192/8)
        self.assertEqual(cell['write_tks'], 1022/40)
        self.assertEqual(cell['common_output_throughput'], 1024/48)
        self.assertEqual(cell['common_output_wave_range'], [512/36, 512/12])

    def test_refuses_incomplete_matrix(self):
        (self.root/'r2-c1-n4096-receipt.json').unlink()
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            summarize(self.root)
        self.assertFalse(summarize(self.root, incomplete=True)['complete'])

    def test_independently_rejects_cache_hits(self):
        path = self.root/'r1-c1-n4096-receipt.json'
        data = json.loads(path.read_text())
        data['responses'][0]['usage']['prompt_tokens_details']['cached_tokens'] = 4096
        self.write(path.name, data)
        with self.assertRaisesRegex(ValueError, 'Invalid response'):
            summarize(self.root)

    def test_detects_unrelated_server_work(self):
        for repeat in (1, 2):
            name = f'r{repeat}-c1-n4096'
            (self.root/(name+'-before.prom')).write_text('vllm:request_success_total 0\n')
            (self.root/(name+'-after.prom')).write_text('vllm:request_success_total 2\n')
        with self.assertRaisesRegex(ValueError, 'Unexpected server completion count'):
            summarize(self.root)


if __name__ == '__main__':
    unittest.main()
