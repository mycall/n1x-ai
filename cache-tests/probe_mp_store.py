"""Real MP server store/restore with a synthetic VMM-backed padded KV group."""
import os
import faulthandler
import subprocess
import sys
import time
import urllib.request
import tempfile
import torch
from n1x_vmm import zeros
from lmcache.utils import EngineType
from lmcache.v1.platform.devices.cuda.ipc_wrapper import VmmCudaIPCWrapper
from lmcache.v1.platform.base.event_ipc import get_event_ipc_backend
from lmcache.v1.multiprocess.custom_types import IPCCacheServerKey
from lmcache.v1.multiprocess.transport.factory import RequestClientFactory

if __name__ == '__main__':
    faulthandler.dump_traceback_later(45, repeat=True)
    entry = ['/probes/probe_mp_server.py'] if os.getenv('N1X_PROBE_SYNC') == '1' else ['-m', 'lmcache.v1.multiprocess.http_server']
    pressure = '--pressure' in sys.argv
    segmented = '--segmented' in sys.argv
    disk = tempfile.TemporaryDirectory(prefix='n1x-cache-probe-')
    extra = ['--l2-adapter', '{"type":"fs","base_path":"' + disk.name + '","use_odirect":true}',
             '--eviction-trigger-watermark', '0.99'] if pressure else []
    server = subprocess.Popen([sys.executable, *entry,
        '--host','127.0.0.1','--port','5555','--http-host','127.0.0.1','--http-port','8080',
        '--l1-size-gb','0.0625' if pressure else '0.5','--eviction-policy','LRU','--chunk-size','2048','--separate-object-groups', *extra])
    client = None
    wrappers = []
    try:
        http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(60):
            if server.poll() is not None:
                raise RuntimeError('Server exited')
            try:
                with http.open('http://127.0.0.1:8080/metrics', timeout=2):
                    break
            except OSError:
                time.sleep(1)
        else:
            raise RuntimeError('Server readiness timeout')
        blocks = 288 if segmented else 144
        second_store = 280 if segmented else 3
        second_restore = 281 if segmented else 4
        base = zeros(blocks*28966912, 'cuda:0')
        base.fill_(37)
        views = [base[i*2048*816:].as_strided((blocks,2048,1,816),(28966912,816,816,1)) for i in range(12)]
        wrappers = [VmmCudaIPCWrapper(v) for v in views]
        torch.cuda.synchronize()
        client = RequestClientFactory.create('tcp://127.0.0.1:5555')
        instance = os.getpid()
        client.register_kv_cache(instance, wrappers, 'probe', 1, EngineType.VLLM, {}, []).result(timeout=60)
        backend = get_event_ipc_backend(0)
        events = []
        def event_handle():
            event = backend.create_event(0)
            backend.record_event(event, None)
            events.append(event)
            return backend.export_event(event, 0)
        tokens = 4096 if pressure else 2048
        key = IPCCacheServerKey.from_token_ids('probe',1,0,[7]*tokens,start=0,end=tokens,request_id='probe-store')
        result = client.store(key, instance, [[1, second_store]] if pressure else [[1]], event_handle()).to_device_future().result(timeout=60)
        print(f'STORE result={result}', flush=True)
        assert result
        if pressure:
            # Only this disposable server's L1 is cleared. No force removal.
            time.sleep(3)
            clear = urllib.request.Request('http://127.0.0.1:8080/cache/clear',
                data=b'{"tier":"l1","force":false}', headers={'Content-Type':'application/json'})
            with http.open(clear, timeout=15) as response:
                print('CLEAR', response.read(), flush=True)
            filler = IPCCacheServerKey.from_token_ids('probe',1,0,[9]*4096,start=0,end=4096,request_id='probe-filler')
            assert client.store(filler, instance, [[5, 6]], event_handle()).to_device_future().result(timeout=60)
            time.sleep(3)
        lookup = key.no_worker_id_version()
        client.lookup(lookup, 1).result(timeout=30)
        deadline = time.monotonic()+30
        while time.monotonic() < deadline:
            found = client.query_prefetch_status(lookup.request_id).result(timeout=10)
            if found is not None:
                break
            time.sleep(.1)
        assert found > 0, found
        for view in views:
            view[2].zero_()
            if pressure:
                view[second_restore].zero_()
        result = client.retrieve(key, instance, [[2, second_restore]] if pressure else [[2]], event_handle(), 0).to_device_future().result(timeout=60)
        torch.cuda.synchronize()
        assert result
        assert all(bool((view[2] == 37).all().item()) for view in views)
        if pressure:
            assert all(bool((view[second_restore] == 37).all().item()) for view in views)
        print('MP STORE/RESTORE PASSED', flush=True)
        client.unregister_kv_cache(instance).result(timeout=30)
    finally:
        if client is not None:
            client.close()
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()
        for wrapper in wrappers:
            wrapper.close()
        disk.cleanup()
