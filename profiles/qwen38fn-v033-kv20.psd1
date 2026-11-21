@{
    # Exact model, drafter and prepared PLE files: wiki/Model-assets.md and wiki/data/model-assets.json.
    Backend = 'wslc-myllmbox'
    MyllmboxRuntime = 'vllm033'
    Image = 'n1x-ai:v033-serving-lmcache'
    ImageId = 'sha256:00871ef354e6b6f05377931237b69e009f52f567ea250193a69c1b782cbb74cb'
    Container = 'n1x-qwen38fn-v033-kv20'
    MyllmboxConfig = 'profiles/qwen38fn-v033.yaml'
    MyllmboxEnvironment = 'runtime/vllm033/environment.psd1'
    MyllmboxModel = 'Qwen3.8-Flash-Next-W4A16-AutoRound-hybrid'
    MyllmboxDrafter = 'Qwen3.8-Flash-Next-DFlash2'
    MyllmboxWSLCVersion = '3.0.5.0'
    RequiredPartitionMiB = 98304
    CacheVolume = 'n1x-v033-kernel-cache'
    PleVolume = 'n1x-ple-native'
    LanAccess = $false
    Context = 262144
    MaxSequences = 8
    BatchedTokens = 8192
    KvCacheBytes = '21474836480'
    KvCacheDtype = 'fp8'
    CacheBlockTokens = 4096
    LmcacheChunkTokens = 4096
    Mtp = $false
    DFlash = $true
    UseLMCache = $true
    LmcacheL1GiB = 4
    LmcacheL2GiB = 160
    LmcacheVolume = 'n1x-033-compare-kv20-ssd'
    LmcacheNamespace = 'qwen-w4-v033-ple-fp8-{settings}-v1'
    RestoreWaitMs = 0
}
