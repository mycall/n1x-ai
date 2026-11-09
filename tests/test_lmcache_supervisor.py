import os
import unittest
from unittest.mock import MagicMock, Mock, patch

from runtime.lmcache import serve


class CacheControlSupervisorTests(unittest.TestCase):
    def run_supervisor(self, enabled):
        cache = Mock()
        model = Mock()
        cache.poll.return_value = model.poll.return_value = None
        stop = Mock()
        stop.is_set.return_value = False
        stop.wait.side_effect = [False, True]
        processes = [cache, model] if enabled else [model]
        with patch.dict(os.environ, {'N1X_LMCACHE_ENABLED': str(int(enabled))}), \
             patch.object(serve, 'STOP', stop), \
             patch.object(serve.signal, 'signal'), \
             patch.object(serve, 'check_headroom') as guard, \
             patch.object(serve.HTTP, 'open', return_value=MagicMock()), \
             patch.object(serve.subprocess, 'Popen', side_effect=processes) as launch, \
             patch.object(serve, 'stop_process') as cleanup:
            serve.main(['--model', '/models/existing'])
        self.assertEqual(guard.call_count, 3 if enabled else 2)
        self.assertEqual([c.args[0] for c in cleanup.call_args_list], processes[::-1])
        return [c.args[0] for c in launch.call_args_list]

    def test_cache_off_keeps_guard_and_model_arguments_without_cache_service(self):
        off = self.run_supervisor(False)
        on = self.run_supervisor(True)
        self.assertEqual(len(off), 1)
        self.assertEqual(len(on), 2)
        self.assertIn('lmcache.v1.multiprocess.http_server', on[0])
        self.assertNotIn('--kv-transfer-config', off[0])
        self.assertEqual(off[0], on[1][:-2])
        self.assertEqual(on[1][-2], '--kv-transfer-config')

    def test_cache_off_refuses_to_start_without_windows_headroom(self):
        with patch.dict(os.environ, {'N1X_LMCACHE_ENABLED': '0'}), \
             patch.object(serve.signal, 'signal'), \
             patch.object(serve, 'check_headroom', side_effect=RuntimeError('low memory')), \
             patch.object(serve.subprocess, 'Popen') as launch:
            with self.assertRaisesRegex(RuntimeError, 'low memory'):
                serve.main([])
        launch.assert_not_called()

    def test_child_exit_is_detected_and_cleaned_up_in_cache_off_mode(self):
        model = Mock()
        model.poll.return_value = 1
        stop = Mock()
        stop.wait.return_value = False
        with patch.dict(os.environ, {'N1X_LMCACHE_ENABLED': '0'}), \
             patch.object(serve, 'STOP', stop), \
             patch.object(serve.signal, 'signal'), \
             patch.object(serve, 'check_headroom') as guard, \
             patch.object(serve.subprocess, 'Popen', return_value=model), \
             patch.object(serve, 'stop_process') as cleanup:
            with self.assertRaisesRegex(RuntimeError, 'serving process exited'):
                serve.main([])
        self.assertEqual(guard.call_count, 2)
        cleanup.assert_called_once_with(model)

    def test_invalid_mode_cannot_silently_enable_a_cache_control(self):
        with patch.dict(os.environ, {'N1X_LMCACHE_ENABLED': 'false'}), \
             patch.object(serve.subprocess, 'Popen') as launch:
            with self.assertRaisesRegex(ValueError, 'must be 0 or 1'):
                serve.main([])
        launch.assert_not_called()


class WindowsCommitHeadroomTests(unittest.TestCase):
    def snapshot(self, **values):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        import json
        import time
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / 'host.json'
        data = dict(availableGiB=12, availableCommitGiB=6, updatedUnixSeconds=time.time())
        data.update(values)
        path.write_text(json.dumps(data), encoding='utf-8')
        return path

    def test_valid_snapshot_accepts_both_reserves_at_the_limit(self):
        serve.check_headroom(self.snapshot(availableGiB=4, availableCommitGiB=4), minimum=4)

    def test_commit_exhaustion_rejected_despite_free_physical_ram(self):
        with self.assertRaisesRegex(RuntimeError, 'commit headroom below 4 GiB'):
            serve.check_headroom(self.snapshot(availableCommitGiB=.5), minimum=4)

    def test_missing_commit_snapshot_requires_updated_host_monitor(self):
        path = self.snapshot()
        import json
        data = json.loads(path.read_text(encoding='utf-8'))
        del data['availableCommitGiB']
        path.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'commit headroom is missing'):
            serve.check_headroom(path, minimum=4)

    def test_physical_limit_still_enforced_with_ample_commit(self):
        with self.assertRaisesRegex(RuntimeError, 'available memory below 4 GiB'):
            serve.check_headroom(self.snapshot(availableGiB=3, availableCommitGiB=100), minimum=4)
