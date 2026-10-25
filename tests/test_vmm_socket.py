import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime' / 'lmcache'))
from n1x_vmm_ipc import _bind_server


@unittest.skipUnless(os.name == 'posix', 'Linux VMM broker socket tests')
class BrokerSocketTests(unittest.TestCase):
    def test_stale_socket_is_rebound(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'broker.sock')
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as old:
                old.bind(path)
                old.listen(1)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as new:
                _bind_server(new, path)
                new.listen(1)
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.connect(path)

    def test_live_socket_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'broker.sock')
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as live:
                live.bind(path)
                live.listen(2)
                inode = os.stat(path).st_ino
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as new:
                    with self.assertRaisesRegex(RuntimeError, 'live broker'):
                        _bind_server(new, path)
                self.assertEqual(os.stat(path).st_ino, inode)

    def test_regular_file_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'broker.sock'
            path.write_text('keep')
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as new:
                with self.assertRaisesRegex(RuntimeError, 'Unsafe'):
                    _bind_server(new, str(path))
            self.assertEqual(path.read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()
