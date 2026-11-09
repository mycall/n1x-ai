@{
    # Exact model, drafter and prepared PLE files: wiki/Model-assets.md and wiki/data/model-assets.json.
    # Default prioritizes common low-concurrency use; C1 measured, C2 unmeasured. See wiki/Benchmarks.md#matched-prefill-comparison.
    Backend = 'wslc-myllmbox'
    Image = 'n1x-ai:mbx-cache-test'
    ImageId = 'sha256:de420cb63cedf084f8838e1e11a7db611e43418c04b3cebc756bc4a5955571aa'
    Container = 'n1x-qwen38fn-best'
    MyllmboxConfig = 'profiles/qwen38fn-best.yaml'
    MyllmboxEnvironment = 'runtime/myllmbox/environment.psd1'
    MyllmboxModel = 'Qwen3.8-Flash-Next-W4A16-AutoRound-hybrid'
    MyllmboxDrafter = 'Qwen3.8-Flash-Next-DFlash2'
    MyllmboxWSLCVersion = '3.0.5.0'
    RequiredPartitionMiB = 90112
    CacheVolume = 'n1x-mbx-w4-dflash-test-cache'
    PleVolume = 'n1x-ple-native'
    LanAccess = $false
    Context = 262144
    MaxSequences = 8
    BatchedTokens = 8192
    KvCacheBytes = '11811160064'
    KvCacheDtype = 'fp8'
    CacheBlockTokens = 4096
    LmcacheChunkTokens = 4096
    Mtp = $false
    DFlash = $true
    UseLMCache = $true
    LmcacheL1GiB = 4
    LmcacheL2GiB = 160
    LmcacheVolume = 'n1x-c8-lmc4-ssd160-v1'
    LmcacheNamespace = 'qwen-c8-w4-std-fp32-idxbf16-kv11-b4k-v1'
    RestoreWaitMs = 0
}
