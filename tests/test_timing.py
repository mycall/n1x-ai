import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('timing', Path(__file__).resolve().parents[1] / 'benchmarks/timing.py')
timing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(timing)


class TimingTests(unittest.TestCase):
    def test_direct_excludes_queue_and_uses_generated_interval(self):
        r = timing.phase_timing({'prompt_tokens': 100, 'completion_tokens': 21},
            {'time_to_first_token_ms': 500, 'generation_time_ms': 1000, 'tokens_per_second': 999}, 3)
        self.assertEqual(r['read_write_tks'], [200, 20])
        self.assertEqual(r['pp_s'], .5)

    def test_fallback_subtracts_durations_only(self):
        r = timing.phase_timing({'prompt_tokens': 100, 'completion_tokens': 21}, {}, 3, 1)
        self.assertEqual(r['read_write_tks'], [100, 10])
        self.assertIn('derived', r['pp_source'])

    def test_missing_or_invalid_is_not_zero_speed(self):
        r = timing.phase_timing({'completion_tokens': 1}, {'generation_time_ms': float('nan')}, 2)
        self.assertEqual(r['read_write_tks'], [None, None])


if __name__ == '__main__':
    unittest.main()
