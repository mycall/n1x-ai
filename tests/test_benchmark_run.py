import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    'benchmark_runner', Path(__file__).resolve().parents[1] / 'benchmarks/run.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class BenchmarkRunnerTests(unittest.TestCase):
    def run_fixture(self, options):
        with tempfile.TemporaryDirectory() as directory:
            argv = ['run.py', '--out', directory, *options]
            with patch.object(runner.sys, 'argv', argv), patch.object(runner, 'request'), \
                    patch.object(runner, 'command') as command:
                runner.main()
            return [list(map(str, call.args[0])) for call in command.call_args_list
                    if any(str(arg).endswith('/agent_cache_probe.py') for arg in call.args[0])][0]

    def test_default_agent_workload_keeps_thinking_and_concurrency(self):
        command = self.run_fixture(['--suite', 'agents'])
        self.assertIn('--agent-thinking', command)
        at = command.index('--agent-concurrency')
        self.assertEqual(command[at + 1:at + 4], ['1', '2', '4'])
        self.assertEqual(command[command.index('--agent-sessions') + 1], '4')
        self.assertEqual(command[command.index('--agent-turns') + 1], '3')
        self.assertNotIn('--agent-output-tokens', command)

    def test_custom_workload_reaches_probe_without_enabling_thinking(self):
        command = self.run_fixture(['--suite', 'agents', '--no-thinking',
            '--agent-concurrency', '1', '2', '--agent-sessions', '2',
            '--agent-turns', '12', '--agent-output-tokens', '8192'])
        self.assertNotIn('--agent-thinking', command)
        at = command.index('--agent-concurrency')
        self.assertEqual(command[at + 1:at + 3], ['1', '2'])
        for option, expected in [('sessions', '2'), ('turns', '12'), ('output-tokens', '8192')]:
            self.assertEqual(command[command.index('--agent-' + option) + 1], expected)

    def test_restore_workload_does_not_receive_agent_controls(self):
        command = self.run_fixture(['--suite', 'restores'])
        for option in ('concurrency', 'sessions', 'turns', 'output-tokens'):
            self.assertNotIn('--agent-' + option, command)

    def test_invalid_controls_fail_before_network_access(self):
        cases = [
            ['--suite', 'agents', '--agent-output-tokens', '0'],
            ['--suite', 'agents', '--agent-concurrency', '0'],
            ['--suite', 'agents', '--agent-concurrency', '17'],
            ['--suite', 'restores', '--agent-turns', '12'],
        ]
        for options in cases:
            with self.subTest(options=options), patch.object(runner.sys, 'argv', ['run.py', *options]), \
                    patch.object(runner, 'request') as request, patch('sys.stderr', new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as error:
                    runner.main()
                self.assertEqual(error.exception.code, 2)
                request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
