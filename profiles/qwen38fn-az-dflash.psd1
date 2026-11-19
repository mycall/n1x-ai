@{
    # FP4-Local-AZ candidate: 8/8 archive + 24/24 recovery tasks at 32K.
    # Long-context and restart restoration qualification pending; not the selected best profile.
    # Model revision: 5d927eabd4e4766a69bf12f7a1387b01d936a78f.
    Backend = 'wslc-myllmbox'
    Image = 'n1x-ai:mbx-setup-1447755d89af469f894bfa8dcb51506d'
    ImageId = 'sha256:819970fd46a90c1e70b7cd06aeb15d5ce3c75b02b62892a8322f42de225566bc'
    Container = 'n1x-qwen38fn-az-dflash'
    MyllmboxConfig = 'profiles/qwen38fn-az-dflash.yaml'
    MyllmboxEnvironment = 'runtime/myllmbox/az-environment.psd1'
    MyllmboxModel = 'Qwen3.8-Flash-Next-FP4-Local-AZ'
    MyllmboxCheckpointPle = $true
    MyllmboxDrafter = 'Qwen3.8-Flash-Next-DFlash2'
    MyllmboxWSLCVersion = '3.0.5.0'
    RequiredPartitionMiB = 98304
    CacheVolume = 'n1x-az-runtime-20261116'
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
    LmcacheVolume = 'n1x-az-dflash-lmc-v1'
    LmcacheNamespace = 'qwen-az-fp4-compute-bf16-ssm-fp32-ple-checkpoint-{settings}-v2'
    RestoreWaitMs = 0
}
