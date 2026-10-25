"""Real L1 and native bitmap probe for sparse-plan admission."""
import json
import os
from types import SimpleNamespace as NS
import time

import torch
from lmcache.v1.distributed.api import MemoryLayoutDesc, ObjectKey
from lmcache.v1.distributed.config import EvictionConfig, L1ManagerConfig, L1MemoryManagerConfig
from lmcache.v1.distributed.error import L1Error
from lmcache.v1.distributed.eviction import L1EvictionPolicy
from lmcache.v1.distributed.eviction_policy import CreateEvictionPolicy
from lmcache.v1.distributed.l1_manager import L1Manager
from lmcache.v1.distributed.storage_controllers.prefetch_controller import Bitmap2D
from n1x_cache_admission import register_policy
from n1x_restore_queue_v2 import defer_load

MIB = 1024**2
manager = L1Manager(L1ManagerConfig(memory_config=L1MemoryManagerConfig(
    size_in_bytes=64*MIB, use_lazy=True, init_size_in_bytes=64*MIB,align_bytes=4096,shm_name='')))
policy = CreateEvictionPolicy(EvictionConfig('LRU'))
manager.register_listener(L1EvictionPolicy(policy))
register_policy(manager, policy)
def key(i):
    return ObjectKey(chunk_hash=ObjectKey.IntHash2Bytes(i),model_name='sparse-queue-probe',kv_rank=0)
layout = MemoryLayoutDesc(shapes=[torch.Size([32*MIB])],dtypes=[torch.uint8])
resident = [key(1),key(2)]
groups = [NS(keys=[key(3),key(4),key(5)],layout_desc=layout),
          NS(keys=[key(6),key(7),key(8)],layout_desc=layout)]
request = NS(request_id=1,key_groups=groups)
cells = Bitmap2D.zeros(2,3)
cells[0].set(0)
controller = NS(_l1_managers={0:manager})
os.environ['N1X_RESTORE_WAIT_MS']='500'
try:
    result = manager.reserve_write(resident,[False,False],layout)
    assert all(error == L1Error.SUCCESS for error,obj in result.values())
    manager.finish_write(resident)
    manager.reserve_read(resident)
    start = time.monotonic()
    assert defer_load(controller,request,{0:cells})
    elapsed = time.monotonic()-start
    assert elapsed < .2
    manager.finish_read([resident[0]])
    assert not defer_load(controller,request,{0:cells})
    incoming = groups[0].keys[0]
    result = manager.reserve_write([incoming],[True],layout,tag='prefetch:sparse')
    assert result[incoming][0] == L1Error.SUCCESS
    assert manager.get_memory_usage()[0] <= 64*MIB
    print(json.dumps({'passed':True,'logicalDemandMiB':192,'selectedDemandMiB':32,
                     'capacityMiB':64,'decisionSeconds':elapsed,'admittedAfterRelease':True}))
finally:
    manager.close()
