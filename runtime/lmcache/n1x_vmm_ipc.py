"""Same-container VMM FD broker. No network listener or serialized code."""
import array
import os
from pathlib import Path
import socket
import struct
import threading

_lock = threading.Lock()
_fds = {}
_server = None
_directory = Path('/tmp/n1x-vmm-fds')

def _path(pid):
    return str(_directory / f'{pid}.sock')

def _serve():
    while True:
        client, _ = _server.accept()
        with client:
            try:
                client.settimeout(10)
                _, uid, _ = struct.unpack('3i', client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                if uid != os.getuid():
                    continue
                key = client.recv(16, socket.MSG_WAITALL)
                with _lock:
                    descriptors = _fds.get(key)
                    if not descriptors:
                        client.sendall(b'!')
                    else:
                        fd = next(iter(descriptors))
                        client.sendmsg([b'F'], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', [fd]))])
            except (OSError, KeyError):
                continue

def publish(key, fd):
    global _server
    with _lock:
        if _server is None:
            _directory.mkdir(mode=0o700, exist_ok=True)
            info = _directory.stat()
            if info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise RuntimeError('Unsafe VMM FD directory ownership or permissions')
            _server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            _server.bind(_path(os.getpid()))
            _server.listen(128)
            threading.Thread(target=_serve, daemon=True, name='n1x-vmm-fd').start()
        _fds.setdefault(key, set()).add(fd)

def withdraw(key, fd):
    with _lock:
        descriptors = _fds.get(key)
        if descriptors is not None:
            descriptors.discard(fd)
            if not descriptors:
                _fds.pop(key, None)

def resolve(key):
    pid = int.from_bytes(key[:4], 'big')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(30)
        client.connect(_path(pid))
        client.sendall(key)
        payload, ancillary, flags, _ = client.recvmsg(1, socket.CMSG_SPACE(4))
        if payload != b'F' or flags & socket.MSG_CTRUNC:
            raise RuntimeError('VMM FD exporter rejected request or truncated descriptor')
        for level, kind, data in ancillary:
            if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                descriptors = array.array('i')
                descriptors.frombytes(data[:4])
                return descriptors[0]
    raise RuntimeError('VMM FD was not delivered')
