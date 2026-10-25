import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from run_suite import read_host_status


class HostStatusTests(unittest.TestCase):
    def test_replacement_gap_retries(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'status.json'
            path.write_text(json.dumps({'availableGiB': 3.5}))
            original = Path.open
            attempts = []
            def transient_open(target, *args, **kwargs):
                attempts.append(1)
                if len(attempts) == 1:
                    raise FileNotFoundError()
                return original(target, *args, **kwargs)
            with patch.object(Path, 'open', transient_open), patch('run_suite.time.sleep'):
                self.assertEqual(read_host_status(path)['availableGiB'], 3.5)
            self.assertEqual(len(attempts), 2)

    def test_missing_and_stale_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'status.json'
            with patch('run_suite.time.sleep'), self.assertRaises(RuntimeError):
                read_host_status(path)
            path.write_text('{}')
            os.utime(path, (1, 1))
            with self.assertRaises(RuntimeError):
                read_host_status(path)


if __name__ == '__main__':
    unittest.main()
