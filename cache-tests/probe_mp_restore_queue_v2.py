"""Two actual MP/SSD restores share a 64 MiB L1 without dropping the second.

Use only while no full-model container is running. GPU KV is about 249 MiB.
"""
import os
os.environ.update(LMCACHE_TRACK_USAGE='false', DO_NOT_TRACK='1',
                  VLLM_NO_USAGE_STATS='1', HF_HUB_DISABLE_TELEMETRY='1',
                  N1X_RESTORE_WAIT_MS='2000')
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request

import torch
from n1x_vmm import zeros
from lmcache.utils import EngineType
from lmcache.v1.platform.devices.cuda.ipc_wrapper import VmmCudaIPCWrapper
from lmcache.v1.platform.base.event_ipc import get_event_ipc_backend
from lmcache.v1.multiprocess.custom_types import IPCCacheServerKey
from lmcache.v1.multiprocess.transport.factory import RequestClientFactory


def poll(function, predicate, seconds=30):
    end = time.monotonic()+seconds
    while time.monotonic() < end:
        value = function()
        if predicate(value):
            return value
        time.sleep(.05)
    raise TimeoutError('MP restore-queue probe timed out')


if __name__ == '__main__':
    disk = tempfile.TemporaryDirectory(prefix='n1x-queue-mp-')
    log_path = Path(disk.name)/'server.log'
    log = log_path.open('w')
    server = subprocess.Popen([sys.executable,'-m','lmcache.v1.multiprocess.http_server',
        '--host','127.0.0.1','--port','5555','--http-host','127.0.0.1','--http-port','8080',
        '--l1-size-gb','0.0625','--eviction-policy','LRU','--chunk-size','2048',
        '--separate-object-groups','--l2-prefetch-max-in-flight','1',
        '--eviction-trigger-watermark','0.99','--l2-adapter',
        json.dumps({'type':'fs','base_path':str(Path(disk.name)/'ssd'),'use_odirect':True})],
        stdout=log,stderr=subprocess.STDOUT)
    http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    client, wrappers, events = None, [], []
    try:
        def metrics():
            try:
                with http.open('http://127.0.0.1:8080/metrics',timeout=2) as response:
                    return response.read().decode()
            except OSError:
                if server.poll() is not None:
                    raise RuntimeError(log_path.read_text(errors='replace'))
                return ''
        poll(metrics,bool,60)
        # Block zero is LMCache's null sentinel and cannot hold stored KV.
        base = zeros(9*28966912,'cuda:0')
        base.fill_(37)
        views = [base[i*2048*816:].as_strided((9,2048,1,816),(28966912,816,816,1)) for i in range(12)]
        for view in views:
            view[3:5].fill_(61)
            view[5:9].zero_()
        wrappers = [VmmCudaIPCWrapper(view) for view in views]
        torch.cuda.synchronize()
        client = RequestClientFactory.create('tcp://127.0.0.1:5555')
        instance = os.getpid()
        client.register_kv_cache(instance,wrappers,'probe',1,EngineType.VLLM,{},[]).result(timeout=60)
        backend = get_event_ipc_backend(0)
        def event_handle():
            event = backend.create_event(0)
            backend.record_event(event,None)
            events.append(event)
            return backend.export_event(event,0)
        def key(value,identity):
            # Distinct chunks avoid any accidental equality in the fixture.
            return IPCCacheServerKey.from_token_ids('probe',1,0,[value]*2048+[value+100]*2048,
                start=0,end=4096,request_id=identity)
        keys = [key(7,'queue-A'),key(9,'queue-B')]
        def completed_store_chunks():
            return sum(float(line.split()[-1]) for line in metrics().splitlines()
                       if line.startswith('lmcache_mp_l2_store_completed_objects') and not line.startswith('#'))
        def clear_l1():
            req = urllib.request.Request('http://127.0.0.1:8080/cache/clear',
                data=b'{"tier":"l1","force":false}',headers={'Content-Type':'application/json'})
            with http.open(req,timeout=15) as response:
                response.read()
        for index,cache_key in enumerate(keys):
            assert client.store(cache_key,instance,[[index*2+1,index*2+2]],event_handle()).to_device_future().result(timeout=60)
            poll(completed_store_chunks,lambda value: value >= 2*(index+1))
            time.sleep(.2)
            clear_l1()
        lookup_a,lookup_b = [cache_key.no_worker_id_version() for cache_key in keys]
        client.lookup(lookup_a,1).result(timeout=10)
        poll(lambda:client.query_prefetch_status(lookup_a.request_id).result(timeout=10),lambda value:value is not None and value>0)
        client.lookup(lookup_b,1).result(timeout=10)
        poll(lambda:log_path.read_text(errors='replace'),lambda text:'N1X restore queue waiting version=2' in text,5)
        assert client.query_prefetch_status(lookup_b.request_id).result(timeout=10) is None
        assert client.retrieve(keys[0],instance,[[5,6]],event_handle(),0).to_device_future().result(timeout=60)
        poll(lambda:client.query_prefetch_status(lookup_b.request_id).result(timeout=10),lambda value:value is not None and value>0)
        assert client.retrieve(keys[1],instance,[[7,8]],event_handle(),0).to_device_future().result(timeout=60)
        torch.cuda.synchronize()
        assert all(bool((view[5:7] == 37).all().item()) for view in views)
        assert all(bool((view[7:9] == 61).all().item()) for view in views)
        text = log_path.read_text(errors='replace')
        assert 'N1X restore queue admitted version=2' in text
        assert 'N1X restore queue deadline' not in text
        print(json.dumps({'passed':True,'bothRestoresByteCorrect':True,
            'secondRestoreWaited':True,'admittedAfterFirstRelease':True,'l1MiB':64,'gpuPoolMiB':9*28966912/1024**2}))
        client.unregister_kv_cache(instance).result(timeout=30)
    finally:
        if server.poll() is None:
            print('FINAL METRICS\n'+metrics(),flush=True)
        if client is not None:
            client.close()
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()
        log.close()
        if log_path.exists():
            print(log_path.read_text(errors='replace'),flush=True)
        for wrapper in wrappers:
            wrapper.close()
        disk.cleanup()
