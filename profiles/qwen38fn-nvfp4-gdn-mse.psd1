@{
    # Experimental checkpoint with embedded PLE and the established DFlash2 recipe.
    Backend = 'wslc-myllmbox'
    Image = 'n1x-ai:mbx-setup-1447755d89af469f894bfa8dcb51506d'
    ImageId = 'sha256:819970fd46a90c1e70b7cd06aeb15d5ce3c75b02b62892a8322f42de225566bc'
    Container = 'n1x-qwen38fn-nvfp4-gdn-mse'
    MyllmboxConfig = 'profiles/qwen38fn-az-dflash.yaml'
    MyllmboxEnvironment = 'runtime/myllmbox/az-environment.psd1'
    MyllmboxModel = 'Qwen3.8-Flash-Next-NVFP4-GDN-MSE'
    MyllmboxModelRepository = 'ursuciprian/Qwen3.8-Flash-Next-NVFP4-GDN-MSE'
    MyllmboxModelRevision = '03f4a0570496bbe741189f4a2a7d611679e85406'
    MyllmboxCheckpointPle = $true
    MyllmboxDrafter = 'Qwen3.8-Flash-Next-DFlash2'
    MyllmboxWSLCVersion = '3.0.5.0'
    RequiredPartitionMiB = 98304
    CacheVolume = 'n1x-gdn-mse-03f4a057-runtime'
    PleVolume = 'n1x-ple-native'
    LanAccess = $false
    Context = 262144
    MaxSequences = 8
    BatchedTokens = 8192
    KvCacheBytes = '16106127360'
    KvCacheDtype = 'fp8'
    CacheBlockTokens = 4096
    LmcacheChunkTokens = 4096
    Mtp = $false
    DFlash = $true
    UseLMCache = $true
    LmcacheL1GiB = 4
    LmcacheL2GiB = 160
    LmcacheVolume = 'n1x-gdn-mse-03f4a057-lmc-v1'
    LmcacheNamespace = 'qwen-gdn-mse-03f4a057-compute-bf16-ssm-fp32-ple-checkpoint-{settings}-v2'
    RestoreWaitMs = 0
}
