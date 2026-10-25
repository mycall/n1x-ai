import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

path=Path(__file__).resolve().parents[1]/'runtime/lmcache/serve.py'
spec=importlib.util.spec_from_file_location('serve',path)
serve=importlib.util.module_from_spec(spec)
spec.loader.exec_module(serve)


class MemoryGuardTests(unittest.TestCase):
    def test_snapshot_refresh_can_be_read_during_a_partial_write(self):
        fresh=json.dumps({'availableGiB':8,'updatedUnixSeconds':time.time()})
        path=Mock()
        path.read_text.side_effect=['{',fresh]
        with patch.object(serve.time,'sleep'):
            serve.check_headroom(path,4)
        self.assertEqual(path.read_text.call_count,2)

    def test_fresh_headroom_is_accepted_and_low_or_stale_state_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'host.json'
            for available,age,expected in ((8,0,None),(3.9,0,'below'),(8,100,'stale')):
                path.write_text(json.dumps({'availableGiB':available,'updatedUnixSeconds':time.time()-age}))
                if expected:
                    with self.assertRaisesRegex(RuntimeError,expected):
                        serve.check_headroom(path,4)
                else:
                    serve.check_headroom(path,4)


if __name__=='__main__':
    unittest.main()
