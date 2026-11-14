"""Offline checks for campaign controls; no model or runtime mutation."""
import tempfile
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'benchmarks'))

from campaign96 import Campaign, variant, qualified, comparisons, TransportFailure
from near_full_tools_probe import TokenizingClient, valid_call, assistant


class CampaignTests(unittest.TestCase):
    def setUp(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        (root / 'config.local.psd1').write_text('@{}', encoding='utf-8')
        root_patch = patch('campaign96.ROOT', root)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        shell_patch = patch('campaign96.shutil.which', return_value='fixture-powershell')
        shell_patch.start()
        self.addCleanup(shell_patch.stop)

    def test_transport_failure_recovers_even_when_health_endpoint_works(self):
        with tempfile.TemporaryDirectory() as directory:
            c=Campaign(Path(directory)/'run')
            worker=unittest.mock.Mock(side_effect=[TransportFailure('client timeout'),{'ok':True}])
            with patch('campaign96.healthy',return_value=True),patch.object(c,'guard'),patch.object(c,'command') as command:
                self.assertEqual(c.recoverable(worker,'trial',11,True,8192),{'ok':True})
                self.assertEqual(command.call_count,2)

    def test_probe_failure_is_not_masked_by_missing_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            c=Campaign(Path(directory)/'run')
            with patch.object(c,'configure',return_value=Path(directory)/'host.json'):
                with patch.object(c,'command',side_effect=[1,0]):
                    with self.assertRaisesRegex(RuntimeError,'probe exited 1'):
                        c.tools_once('failed-probe',11,True,8192)

    def test_outage_recovers_in_new_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            c=Campaign(Path(directory)/'run')
            worker=unittest.mock.Mock(side_effect=[RuntimeError('server down'),{'passed':True}])
            with patch('campaign96.healthy',return_value=False), patch.object(c,'guard'), patch.object(c,'command') as commands:
                self.assertEqual(c.recoverable(worker,'trial',11,True,8192),{'passed':True})
            self.assertEqual(worker.call_args_list[0].args[0],'trial-attempt1')
            self.assertEqual(worker.call_args_list[1].args[0],'trial-attempt2')
            self.assertEqual(commands.call_count,2)
            self.assertTrue((c.out/'trial-attempt1-failure.json').exists())

    def test_healthy_server_failure_is_not_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            c=Campaign(Path(directory)/'run')
            worker=unittest.mock.Mock(side_effect=RuntimeError('quality failure'))
            with patch('campaign96.healthy',return_value=True), patch.object(c,'command') as commands:
                with self.assertRaises(RuntimeError):
                    c.recoverable(worker,'trial',11,True,8192)
            self.assertEqual(worker.call_count,1)
            commands.assert_not_called()

    def test_variant_preserves_unrelated_settings_and_original(self):
        original=b"@{\r\n    Image = 'image-id'\r\n    RequiredPartitionMiB = 98304\r\n}\r\n"
        changed=variant(original,15,False,4096).decode()
        self.assertIn("Image = 'image-id'",changed)
        self.assertIn('RequiredPartitionMiB = 98304',changed)
        self.assertIn("KvCacheBytes = '16106127360'",changed)
        self.assertIn('UseLMCache = $false',changed)
        self.assertTrue(original.endswith(b'}\r\n'))

    def test_existing_controls_replaced_once(self):
        original=b"@{\n 'KvCacheBytes' = '1' # old\n UseLMCache = $true\n BatchedTokens = 1\n}\n"
        changed=variant(original,11,False,8192).decode()
        self.assertEqual(changed.count('KvCacheBytes'),1)
        self.assertIn('BatchedTokens = 8192',changed)
        self.assertNotIn('# old',changed)
        with self.assertRaises(ValueError):
            variant(b'@{\n UseLMCache = $true\n UseLMCache = $false\n}\n',11,True,8192)

    def test_restore_preserves_original_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            c=Campaign(Path(directory)/'run')
            c.config=Path(directory)/'config.psd1'
            c.original=b'original\r\n'
            c.expected=b'trial\n'
            c.config.write_bytes(c.expected)
            c.changed=True
            with patch.object(c,'command',return_value=0) as command:
                c.restore()
                self.assertEqual(command.call_count,2)
            self.assertEqual(c.config.read_bytes(),c.original)

    def test_restore_refuses_concurrent_user_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            c=Campaign(Path(directory)/'run')
            c.config=Path(directory)/'config.psd1'
            c.expected=b'trial'
            c.config.write_bytes(b'user edit')
            c.changed=True
            with self.assertRaises(RuntimeError):
                c.restore()
            self.assertEqual(c.config.read_bytes(),b'user edit')

    def test_partial_or_incorrect_run_cannot_qualify(self):
        rows=[dict(concurrency=c,planned_tasks=24,correct_tasks=24,correct_tasks_s=0.02) for c in (2,4)]
        self.assertTrue(qualified(dict(results=rows)))
        self.assertFalse(qualified(dict(results=rows[:1])))
        rows[1]['correct_tasks']=23
        self.assertFalse(qualified(dict(results=rows)))

    def test_ratios_keep_concurrency_separate(self):
        control=dict(results=[dict(concurrency=c,correct_tasks_s=0.02) for c in (2,4)])
        candidate=dict(results=[dict(concurrency=c,correct_tasks_s=rate,correct_tasks=24,planned_tasks=24) for c,rate in ((2,0.04),(4,0.01))])
        self.assertEqual([r['throughput_ratio'] for r in comparisons(control,candidate)],[2,0.5])

    def test_zero_throughput_control_has_no_comparison_ratio(self):
        control=dict(results=[dict(concurrency=2,correct_tasks_s=0)])
        candidate=dict(results=[dict(concurrency=2,correct_tasks_s=0.02,correct_tasks=24,planned_tasks=24)])
        comparison=comparisons(control,candidate)[0]
        self.assertIsNone(comparison['throughput_ratio'])
        self.assertFalse(comparison['comparison_eligible'])

    def test_read_only_tokenization_retry(self):
        client=TokenizingClient('http://unused')
        with patch('near_full_tools_probe.Client.get',side_effect=[urllib.error.URLError('transient'),{'count':10}]) as get:
            with patch('near_full_tools_probe.time.sleep'):
                self.assertEqual(client.get('/tokenize',{}),{'count':10})
            self.assertEqual(get.call_count,2)
        with patch('near_full_tools_probe.Client.get',side_effect=urllib.error.URLError('failed')) as get:
            with self.assertRaises(urllib.error.URLError):
                client.get('/v1/chat/completions',{})
            self.assertEqual(get.call_count,1)

    def test_tool_validation_and_reasoning_preservation(self):
        result=dict(stream_done=True,finish_reason='tool_calls',reasoning='required continuation reasoning',
            tool_calls=[dict(id='call-1',type='function',function=dict(name='lookup_inventory',arguments='{"sku":"AX-0-0"}'))])
        self.assertTrue(valid_call(result,'lookup_inventory','AX-0-0'))
        self.assertFalse(valid_call(result,'lookup_price','AX-0-0'))
        self.assertFalse(valid_call(result,'lookup_inventory','AX-0-1'))
        self.assertFalse(valid_call(dict(result,finish_reason='length'),'lookup_inventory','AX-0-0'))
        self.assertEqual(assistant(result)['reasoning'],result['reasoning'])
        self.assertEqual(assistant(result)['tool_calls'][0]['id'],'call-1')


if __name__=='__main__':
    unittest.main()
