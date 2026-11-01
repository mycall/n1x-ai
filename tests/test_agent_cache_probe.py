import importlib.util
import io
import json
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('agent_probe', Path(__file__).resolve().parents[1] / 'benchmarks/agent_cache_probe.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class AgentProbeTests(unittest.TestCase):
    def test_workload_controls_preserve_reasoning_and_tool_history(self):
        owner = self

        class FakeProbe(module.Probe):
            def snapshot(self, name):
                return {}

            def chat(self, messages, salt, **extra):
                owner.assertTrue(extra['chat_template_kwargs']['enable_thinking'])
                owner.assertEqual(extra['max_tokens'], self.args.agent_output_tokens or 1024)
                last = messages[-1]
                if last['role'] == 'tool':
                    owner.assertEqual(messages[-2][self.args.reasoning_field], 'kept reasoning')
                    owner.assertEqual(last['tool_call_id'], messages[-2]['tool_calls'][0]['id'])
                    code = re.search(r'AGENT-\d{4}', messages[1]['content']).group()
                    content = f"{code}:{json.loads(last['content'])['count']}"
                    return {'finish_reason': 'stop', 'message': {'content': content}}
                if last['content'].endswith('Reply only READY.'):
                    return {'finish_reason': 'stop', 'message': {'content': 'READY'}}
                sku = re.search(r'SKU (AX-\d+-\d+)', last['content']).group(1)
                return {'finish_reason': 'tool_calls', 'message': {'content': None,
                    self.args.reasoning_field: 'kept reasoning', 'tool_calls': [{'id': 'fixture-call',
                    'function': {'name': 'lookup_inventory', 'arguments': json.dumps({'sku': sku})}}]}}

        for points, allowance, field, sessions, turns, planned in [
                (None, None, 'reasoning', 4, 3, 72),
                ([1], 8192, 'reasoning_content', 4, 3, 24),
                ([1], 8192, 'reasoning_content', 1, 12, 24),
                ([2,4], 4096, 'reasoning', 4, 2, 32)]:
            with self.subTest(points=points, field=field, sessions=sessions), tempfile.TemporaryDirectory() as directory:
                args = SimpleNamespace(out=Path(directory), agent_thinking=True,
                    agent_concurrency=points, agent_output_tokens=allowance, reasoning_field=field,
                    agent_sessions=sessions, agent_turns=turns)
                probe = FakeProbe(args)
                with patch('builtins.print'):
                    probe.agents()
                self.assertEqual(sum(row['planned_tasks'] for row in probe.rows), planned)
                self.assertEqual(sum(row['correct_tasks'] for row in probe.rows), planned)
                expected_points = points or [1,2,4]
                self.assertEqual([row['concurrency'] for row in probe.rows], expected_points + list(reversed(expected_points)))
                for row in probe.rows:
                    self.assertEqual(len(row['session_results']), sessions)
                    self.assertEqual(sum(session['correct_tasks'] for session in row['session_results']), row['correct_tasks'])
                    self.assertTrue(all(session['elapsed_s'] >= 0 for session in row['session_results']))
                    self.assertEqual(row['preemptions'], 0)

    def test_raw_request_record_preserves_output_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(out=Path(directory), url='http://fixture')
            probe = module.Probe(args)
            response = {'choices': [{'finish_reason': 'stop', 'message': {'content': 'ok'}}]}
            with patch.object(module, 'request', return_value=json.dumps(response)) as request:
                probe.chat([{'role': 'user', 'content': 'fixture'}], 'salt', max_tokens=8192,
                           chat_template_kwargs={'enable_thinking': True})
            body = request.call_args.args[1]
            self.assertNotIn('reasoning_budget_tokens', body)
            self.assertEqual(body['max_tokens'], 8192)
            saved = json.loads((Path(directory) / 'responses.jsonl').read_text())
            self.assertEqual(saved['request'], body)
            self.assertEqual(saved['response'], response)

    def test_http_failure_keeps_request_and_server_error(self):
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(out=Path(directory), url='http://fixture')
            probe = module.Probe(args)
            error = module.urllib.error.HTTPError('http://fixture', 503, 'Unavailable', {},
                io.BytesIO(b'{"error":"verify batch timed out"}'))
            with patch.object(module, 'request', side_effect=error), self.assertRaises(module.urllib.error.HTTPError):
                probe.chat([{'role': 'user', 'content': 'fixture'}], 'salt')
            saved = json.loads((Path(directory) / 'errors.jsonl').read_text())
            self.assertEqual(saved['status'], 503)
            self.assertIn('verify batch timed out', saved['response_body'])
            self.assertEqual(saved['request']['messages'][0]['content'], 'fixture')
            self.assertFalse((Path(directory) / 'responses.jsonl').exists())
            self.assertTrue(error.closed)


if __name__ == '__main__':
    unittest.main()
