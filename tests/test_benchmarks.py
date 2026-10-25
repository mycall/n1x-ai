import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("benchmark_runner", Path(__file__).parents[1] / "benchmarks/run.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class AgentResultsTests(unittest.TestCase):
    def make_run(self, directory, truncated=False):
        (directory / "artifacts").mkdir()
        (directory / "expected.json").write_text(json.dumps({"session-0": ["ABC"] * 4}))
        records = []
        for turn in range(4):
            packets = [{"name": "data", "value": json.dumps({"choices": [{
                "delta": {"content": piece}, "finish_reason": finish}]})}
                for piece, finish in [("A", None), ("BC", "length" if truncated else "stop")]]
            records.append({"metadata": {"benchmark_phase": "profiling", "conversation_id": "session-0",
                            "turn_index": turn, "request_start_ns": (turn + 1) * 1000000000,
                            "request_end_ns": (turn + 2) * 1000000000},
                            "status": 200, "start_perf_ns": 100,
                            "responses": [{"perf_ns": 500000100, "packets": packets}]})
        (directory / "artifacts/profile_export_raw.jsonl").write_text(
            "".join(json.dumps(record) + "\n" for record in records))

    def test_stream_reconstruction_and_elapsed_time(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.make_run(directory)
            runner.summarize_agent(directory, 4)
            result = json.loads((directory / "accuracy.json").read_text())
            self.assertEqual(result["correct"], 4)
            self.assertEqual(result["correct_turns_per_s"], 1)
            self.assertEqual(result["followup_mean_ttft_s"], 0.5)

    def test_truncated_answers_do_not_count_as_correct(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.make_run(directory, truncated=True)
            runner.summarize_agent(directory, 4)
            self.assertEqual(json.loads((directory / "accuracy.json").read_text())["correct"], 0)

    def test_missing_turns_fail_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.make_run(directory)
            with self.assertRaisesRegex(RuntimeError, "Expected 8 turns"):
                runner.summarize_agent(directory, 8)


if __name__ == "__main__":
    unittest.main()
