"""Supervise vLLM and the local cache service with a Windows memory guard."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

os.environ.update(LMCACHE_TRACK_USAGE='false',DO_NOT_TRACK='1',VLLM_NO_USAGE_STATS='1',HF_HUB_DISABLE_TELEMETRY='1')
STOP=threading.Event()
HTTP=urllib.request.build_opener(urllib.request.ProxyHandler({}))


def check_headroom(path=Path('/state/host.json'),minimum=None):
    minimum=float(os.environ.get('N1X_WINDOWS_MINIMUM_GIB','4')) if minimum is None else minimum
    for attempt in range(10):
        try:
            data=json.loads(path.read_text(encoding='utf-8-sig'))
            break
        except (FileNotFoundError,json.JSONDecodeError):
            if attempt==9:
                raise RuntimeError('Windows memory monitor is unavailable')
            time.sleep(.2)
    if time.time()-data['updatedUnixSeconds']>90:
        raise RuntimeError('Windows memory monitor is stale; restart the profile')
    if data['availableGiB']<minimum:
        raise RuntimeError(f"Windows available memory below {minimum:g} GiB; stopping services")


def stop_process(process):
    if process.poll() is None:
        os.killpg(process.pid,signal.SIGTERM)
        try:
            process.wait(timeout=45)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGKILL)
            process.wait(timeout=15)


def main(arguments):
    processes=[]
    for event in (signal.SIGTERM,signal.SIGINT):
        signal.signal(event,lambda *_:STOP.set())
    try:
        check_headroom()
        namespace=os.environ.get('N1X_CACHE_NAMESPACE','qwen-v032-fp8-mtp')
        server=subprocess.Popen([sys.executable,'-m','lmcache.v1.multiprocess.http_server',
            '--host','127.0.0.1','--port','5555','--http-host','127.0.0.1','--http-port','8080',
            '--l1-size-gb',os.environ.get('N1X_LMCACHE_L1_GIB','8'),
            '--eviction-policy','LRU','--chunk-size','2048','--separate-object-groups',
            '--l2-prefetch-max-in-flight','1','--l2-adapter',json.dumps({
                'type':'fs','base_path':'/lmcache/'+namespace,'use_odirect':True})],start_new_session=True)
        processes.append(server)
        deadline=time.monotonic()+180
        while not STOP.is_set():
            check_headroom()
            if server.poll() is not None:
                raise RuntimeError('LMCache exited during startup')
            try:
                with HTTP.open('http://127.0.0.1:8080/metrics',timeout=5):
                    break
            except (OSError,urllib.error.URLError):
                if time.monotonic()>deadline:
                    raise RuntimeError('LMCache did not become ready')
                STOP.wait(1)
        if STOP.is_set():
            return
        connector={'kv_connector':'LMCacheMPConnector','kv_role':'kv_both',
            'kv_connector_module_path':'lmcache.integration.vllm.lmcache_mp_connector',
            'kv_connector_extra_config':{'lmcache.mp.host':'127.0.0.1','lmcache.mp.port':5555,'lmcache.mp.use_vmm_api':True}}
        model=subprocess.Popen([sys.executable,'-m','vllm.entrypoints.openai.api_server',*arguments,
            '--block-size','2048','--mamba-cache-mode','align','--kv-transfer-config',json.dumps(connector)],start_new_session=True)
        processes.append(model)
        while not STOP.wait(2):
            check_headroom()
            if any(process.poll() is not None for process in processes):
                raise RuntimeError('A serving process exited; inspect container logs')
    finally:
        for process in reversed(processes):
            stop_process(process)


if __name__=='__main__':
    main(sys.argv[1:])
