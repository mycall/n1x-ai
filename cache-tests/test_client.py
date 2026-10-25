"""Protocol checks for the lightweight streaming client; no GPU/model imports."""
import concurrent.futures
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import run_suite

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.end_headers()
        for text in ('RIVER-', '729'):
            self.wfile.write(('data: ' + json.dumps({'choices': [{'delta': {'content': text}}]}) + '\n\n').encode())
            self.wfile.flush()
        self.wfile.write(b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n')
        if body['messages'][0]['content'] != 'omit usage':
            self.wfile.write(b'data: {"choices":[],"usage":{"prompt_tokens":12,"completion_tokens":4}}\n\n')
        self.wfile.write(b'data: [DONE]\n\n')

class ClientTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.original_base = run_suite.BASE
        run_suite.BASE = f'http://127.0.0.1:{self.server.server_port}'
        self.suite = run_suite.Suite(SimpleNamespace(output=self.directory.name, run_id='test'))
        self.suite.phase = 'baseline'
        self.suite.guard = lambda: {'availableGiB': 8, 'powerLineStatus': 'Online'}
        self.suite.metrics = lambda label: {}

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        run_suite.BASE = self.original_base
        self.directory.cleanup()

    def call(self, case='sample', prompt='normal'):
        return self.suite.chat(case, 'cold', [{'role': 'user', 'content': prompt}], 'test', ['RIVER-729'])

    def test_stream_fragments_and_usage(self):
        row = self.call()
        self.assertEqual(row['content'], 'RIVER-729')
        self.assertEqual(row['usage']['completion_tokens'], 4)
        self.assertTrue(row['correct'])
        self.assertIsNotNone(row['ttftSeconds'])

    def test_reset_waits_for_explicit_success(self):
        with patch.object(run_suite, 'request', side_effect=[{'success': False}, {'success': True}]) as call:
            with patch.object(run_suite.time, 'sleep'):
                self.suite.reset()
        self.assertEqual(call.call_count, 2)
        call.assert_called_with('/reset_prefix_cache?reset_external=false', {})

    def test_incomplete_protocol_retains_failed_evidence(self):
        with self.assertRaisesRegex(RuntimeError, 'protocol gate'):
            self.call(prompt='omit usage')
        rows = [json.loads(line) for line in self.suite.journal.read_text().splitlines()]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['usage'], {})

    def test_concurrent_results_are_complete_json_records(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(self.call, ['first', 'second']))
        rows = [json.loads(line) for line in self.suite.journal.read_text().splitlines()]
        self.assertEqual({row['case'] for row in rows}, {'first', 'second'})
        self.assertTrue(all(row['correct'] for row in rows))

if __name__ == '__main__':
    unittest.main()
