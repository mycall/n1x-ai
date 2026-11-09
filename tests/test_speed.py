"""Offline fixtures only: no running model, network, tokenizer download or GPU."""
import argparse
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from benchmarks import speed_probe as speed
from benchmarks import speed_report as report
from benchmarks.timing import phase_timing


class FakeClient:
    def __init__(self, fail_measured=False, fail_prime=False):
        self.primes = {}
        self.calls = []
        self.lock = threading.Lock()
        self.fail_measured = fail_measured
        self.fail_prime = fail_prime
        self.tokenize_efforts = []

    def get(self, path):
        return None if path == '/health' else {'data': [{'id': 'qwen/qwen38fn-best'}]}

    def tokenize(self, text, thinking, reasoning_effort='xhigh'):
        self.tokenize_efforts.append(reasoning_effort)
        return len(text)//4 + 20

    def generate(self, request):
        with self.lock:
            self.calls.append(request)
            if request['max_tokens'] == 1 and self.fail_prime:
                raise RuntimeError('prime failed fixture')
            count = self.tokenize(request['messages'][-1]['content'], True)
            cached = self.primes.get(request['cache_salt'], 0)
            self.primes[request['cache_salt']] = count
            output = request['max_tokens']
            if self.fail_measured and output > 1:
                output -= 1
            usage = dict(prompt_tokens=count, completion_tokens=output,
                         prompt_tokens_details={'cached_tokens': cached})
            metrics = dict(time_to_first_token_ms=500, generation_time_ms=1000)
            return dict(usage=usage, metrics=metrics, timing=phase_timing(usage, metrics, 2),
                        stream_done=True, finish_reason='length', generated_packets=1,
                        generated_chars=10, client_ttft_s=.5, client_first_to_last_s=1)


def options(out, **updates):
    values = dict(out=out, url='http://unused.invalid', timeout=1, mode='incremental',
                  profile='fixture-profile', depths=[0, 512], concurrency=[1, 2], repeats=2,
                  extension_tokens=128, output_tokens=16, thinking=True, context_limit=2048,
                  tolerance=8, host_record=None, reasoning_effort='xhigh')
    values.update(updates)
    return argparse.Namespace(**values)


class SpeedTests(unittest.TestCase):
    def test_incremental_calibrates_primes_and_preserves_existing_results(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)/'run'
            client = FakeClient()
            speed.run(options(destination), client)
            summary = report.load_run(destination)
            self.assertEqual(summary['status'], 'completed')
            self.assertEqual(len(summary['cells']), 4)
            self.assertTrue(all(c['status'] == 'complete' for c in summary['cells']))
            rows = [json.loads(line) for line in (destination/'requests.jsonl').read_text().splitlines()]
            primes = [r for r in rows if r['phase'] == 'prime']
            measured = [r for r in rows if r['phase'] == 'measured']
            self.assertEqual(len(primes), 6)
            self.assertEqual(len(measured), 12)
            text = (destination/'comparison.md').read_text(encoding='utf-8')
            self.assertEqual(text.count('## incremental'), 1)
            self.assertIn('**C1**', text)
            self.assertIn('**C2**', text)
            self.assertIn('Server slots', text)
            by_salt = {r['request']['cache_salt']: r for r in primes}
            for row in measured:
                self.assertTrue(abs(row['read_tokens']-128) <= 8)
                if row['depth']:
                    prime = by_salt[row['request']['cache_salt']]
                    self.assertTrue(row['request']['messages'][-1]['content'].startswith(prime['request']['messages'][-1]['content']))
                    self.assertGreater(row['usage']['prompt_tokens_details']['cached_tokens'], 0)
            before = (destination/'requests.jsonl').read_bytes()
            with self.assertRaises(FileExistsError):
                speed.run(options(destination), client)
            self.assertEqual(before, (destination/'requests.jsonl').read_bytes())

    def test_failed_first_scores_do_not_become_completed_cells_or_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)/'run'
            client = FakeClient(fail_measured=True)
            with self.assertRaisesRegex(RuntimeError, 'matrix incomplete'):
                speed.run(options(destination, depths=[0], concurrency=[1]), client)
            self.assertEqual(len(client.calls), 2)  # planned repeats only
            cell = report.load_run(destination)['cells'][0]
            self.assertEqual(cell['status'], 'incomplete')
            self.assertEqual(cell['recorded_requests'], 2)
            self.assertEqual(cell['read_write_tks'], [None, None])
            self.assertIn('fixed-output-not-completed', cell['notes'])

    def test_fast_stream_is_persisted_while_earlier_stream_is_still_blocked(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)/'run'
            client = FakeClient()
            original = client.generate
            release = threading.Event()
            slow_started = threading.Event()
            errors = []
            def generate(request):
                if 'Reference stream 0000.' in request['messages'][-1]['content']:
                    slow_started.set()
                    if not release.wait(5):
                        raise RuntimeError('fixture slow-stream release timed out')
                return original(request)
            def execute():
                try:
                    speed.run(options(destination, depths=[0], concurrency=[2], repeats=1), client)
                except BaseException as error:
                    errors.append(error)
            client.generate = generate
            thread = threading.Thread(target=execute)
            thread.start()
            observed = False
            try:
                self.assertTrue(slow_started.wait(2))
                deadline = time.monotonic()+2
                while time.monotonic() < deadline:
                    path = destination/'requests.jsonl'
                    if path.exists():
                        try:
                            records = [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines()]
                        except json.JSONDecodeError:
                            # The writer may be in the middle of its append.
                            time.sleep(.01)
                            continue
                        if any(r.get('stream') == 1 for r in records):
                            observed = True
                            break
                    time.sleep(.01)
            finally:
                release.set()
                thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertFalse(errors)
            self.assertTrue(observed, 'Completed first attempt was hidden behind the blocked stream')
            self.assertEqual(report.load_run(destination)['cells'][0]['status'], 'complete')

    def test_failed_prime_retained_without_measured_call(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)/'run'
            client = FakeClient(fail_prime=True)
            with self.assertRaisesRegex(RuntimeError, 'prime failed'):
                speed.run(options(destination, depths=[512], concurrency=[1]), client)
            rows = [json.loads(line) for line in (destination/'requests.jsonl').read_text().splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['phase'], 'prime')
            self.assertEqual(rows[0]['status'], 'failed')
            self.assertEqual(report.load_run(destination)['status'], 'failed')

    def test_cold_and_context_capacity_are_explicit(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)/'run'
            client = FakeClient()
            with self.assertRaisesRegex(RuntimeError, 'matrix incomplete'):
                speed.run(options(destination, mode='cold', depths=[0, 512, 2048], concurrency=[1]), client)
            cells = report.load_run(destination)['cells']
            self.assertEqual([c['status'] for c in cells], ['not-applicable', 'complete', 'skipped'])
            self.assertEqual(cells[1]['cached_tokens'], [0, 0])
            self.assertEqual(cells[1]['read_tokens'], cells[1]['input_tokens'])
            self.assertEqual(len(client.calls), 2)

    def test_response_requires_actual_fixed_work_cache_evidence_and_full_stream(self):
        client = FakeClient()
        value = client.generate(speed.body('a'*100, 'salt', 16, True))
        self.assertEqual(speed.validate_response(value, 45, 16, 'cold', 8), [])
        value['usage']['prompt_tokens_details']['cached_tokens'] = 1
        self.assertIn('cold-request-reused-cache', speed.validate_response(value, 45, 16, 'cold', 8))
        value['usage']['prompt_tokens_details'] = {}
        value['stream_done'] = False
        reasons = speed.validate_response(value, 44, 16, 'incremental', 8)
        self.assertIn('rendered-input-mismatch', reasons)
        self.assertIn('cache-coverage-unavailable', reasons)
        self.assertIn('incomplete-generation-stream', reasons)

    def test_stream_counts_reasoning_and_uses_direct_timing(self):
        events = [dict(choices=[{'delta': {'role': 'assistant'}}]),
                  dict(choices=[{'delta': {'reasoning': 'thinking'}}]),
                  dict(choices=[{'delta': {'content': 'answer'}}]),
                  dict(choices=[{'delta': {}, 'finish_reason': 'length'}],
                       usage={'prompt_tokens':100, 'completion_tokens':17, 'prompt_tokens_details':{'cached_tokens':0}},
                       metrics={'time_to_first_token_ms':500, 'generation_time_ms':1000})]
        raw = ''.join('data: '+json.dumps(e)+'\n\n' for e in events)+'data: [DONE]\n\n'
        client = speed.Client('http://unused.invalid')
        with patch.object(client, 'open', return_value=io.BytesIO(raw.encode())), patch.object(speed.time, 'perf_counter', side_effect=[0,1,2,3]):
            result = client.generate({})
        self.assertEqual(result['timing']['read_write_tks'], [200,16])
        self.assertEqual(result['client_ttft_s'], 1)
        self.assertEqual(result['client_first_to_last_s'], 1)
        self.assertTrue(result['stream_done'])

    def test_health_can_have_empty_body(self):
        client = speed.Client('http://unused.invalid')
        with patch.object(client, 'open', return_value=io.BytesIO(b'')):
            self.assertIsNone(client.get('/health'))

    def test_effort_is_sent_to_tokenizer_primes_and_measurements(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)/'run'
            client = FakeClient()
            speed.run(options(destination, depths=[512], concurrency=[1], repeats=1, reasoning_effort='low'), client)
            self.assertEqual(report.load_run(destination)['settings']['reasoning_effort'], 'low')
            self.assertTrue(all(r['chat_template_kwargs'] == {'enable_thinking':True, 'reasoning_effort':'low'} for r in client.calls))
            # Calibration is not allowed to silently use the xhigh template.
            # Fake generate() itself invokes tokenize() with its own default;
            # inspect the actual HTTP tokenizer request separately below.
            api = speed.Client('http://unused.invalid')
            with patch.object(api, 'get', return_value={'count':100}) as get:
                api.tokenize('example', True, 'low')
                self.assertEqual(get.call_args.args[1]['chat_template_kwargs']['reasoning_effort'], 'low')
            calibrated = []
            def tokenize(text, thinking, reasoning_effort):
                calibrated.append(reasoning_effort)
                return len(text)//4 + 20
            with patch.object(client, 'tokenize', side_effect=tokenize):
                speed.calibrate(client, 512, True, 0, reasoning_effort='low')
            self.assertEqual(set(calibrated), {'low'})

    def test_disabled_thinking_omits_effort_and_invalid_effort_is_rejected(self):
        self.assertEqual(speed.thinking_kwargs(False, 'xhigh'), {'enable_thinking':False})
        self.assertEqual(speed.thinking_kwargs(True), {'enable_thinking':True, 'reasoning_effort':'xhigh'})
        with self.assertRaises(ValueError):
            speed.thinking_kwargs(True, 'high')

    def test_effort_groups_and_legacy_unspecified_are_separate(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            speed.run(options(path/'run', depths=[0], concurrency=[1], repeats=1), FakeClient())
            first = report.load_run(path/'run')
            low = deepcopy(first)
            low['settings']['reasoning_effort'] = 'low'
            legacy = deepcopy(first)
            del legacy['settings']['reasoning_effort']
            report.write_report([first, low, legacy], path/'comparison.md', path/'comparison.json')
            text = (path/'comparison.md').read_text(encoding='utf-8')
            self.assertEqual(text.count('## incremental'), 3)
            self.assertIn('Reasoning effort: **xhigh**', text)
            self.assertIn('Reasoning effort: **low**', text)
            self.assertIn('Reasoning effort: **unspecified**', text)

    def test_plan_only_does_not_construct_http_client(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)/'plan'
            argv = ['speed_probe.py', '--plan-only', '--out', str(destination), '--profile', 'fixture',
                    '--context-limit', '2048', '--mode', 'both', '--depths', '0', '512', '2048',
                    '--extension-tokens', '128', '--output-tokens', '16', '--repeats', '2']
            with patch('sys.argv', argv), patch.object(speed, 'Client', side_effect=AssertionError('HTTP must stay offline')):
                speed.main()
            p = report.read(destination/'plan.json')
            self.assertEqual(p['total_measured_requests'], 6)
            self.assertEqual(p['total_prime_requests'], 2)
            self.assertEqual(p['reasoning_effort'], 'xhigh')
            self.assertFalse((destination/'run.json').exists())

    def test_duplicate_samples_and_mixed_timing_do_not_complete_a_point(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'run'
            speed.run(options(path, concurrency=[1], depths=[0]), FakeClient())
            run = report.read(path/'run.json')
            records = [json.loads(line) for line in (path/'requests.jsonl').read_text().splitlines()]
            self.assertEqual(report.summarize(run, [records[0], records[0]])['cells'][0]['status'], 'incomplete')
            records[1]['timing']['pp_source'] = 'derived-e2e-minus-decode-includes-overhead'
            self.assertEqual(report.summarize(run, records)['cells'][0]['read_write_tks'], [None, None])

    def test_reports_separate_protocol_settings_and_do_not_infer_missing_depths(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            speed.run(options(path/'first', concurrency=[1], depths=[0]), FakeClient())
            first = report.load_run(path/'first')
            second = deepcopy(first)
            second['run_id'] = 'second-run'
            second['profile'] = 'other-profile'
            second['settings']['output_tokens'] = 32
            report.write_report([first, second], path/'comparison.md', path/'comparison.json')
            text = (path/'comparison.md').read_text(encoding='utf-8')
            self.assertEqual(text.count('## incremental'), 2)
            self.assertIn('output **16**', text)
            self.assertIn('output **32**', text)
            self.assertEqual(len(report.read(path/'comparison.json')['runs']), 2)
            same = deepcopy(first)
            same['profile'] = 'missing-depth'
            same['cells'][0]['depth'] = 512
            report.write_report([first, same], path/'matched.md', path/'matched.json')
            self.assertIn('— missing', (path/'matched.md').read_text(encoding='utf-8'))

    def test_direct_and_derived_tables_are_separate(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            speed.run(options(path/'first', concurrency=[1], depths=[0]), FakeClient())
            first = report.load_run(path/'first')
            second = deepcopy(first)
            second['cells'][0]['timing_source'][0] = 'derived-e2e-minus-decode-includes-overhead'
            report.write_report([first, second], path/'comparison.md', path/'comparison.json')
            text = (path/'comparison.md').read_text(encoding='utf-8')
            self.assertEqual(text.count('## incremental'), 2)
            self.assertIn('different timing source', text)


if __name__ == '__main__':
    unittest.main()
