@{
    # Exact model, drafter and prepared PLE files: wiki/Model-assets.md and wiki/data/model-assets.json.
    # Selected 96 GiB deployment: 48/48 C2/C4 tool tasks. No matched 88 GiB control.
    # See wiki/96GiB-comparison-campaign.md and wiki/Profile-review.md.
    Backend = 'wslc-myllmbox'
    Image = 'n1x-ai:mbx-setup-1447755d89af469f894bfa8dcb51506d'
    ImageId = 'sha256:819970fd46a90c1e70b7cd06aeb15d5ce3c75b02b62892a8322f42de225566bc'
    Container = 'n1x-qwen38fn-best'
    MyllmboxConfig = 'profiles/qwen38fn-best.yaml'
    MyllmboxEnvironment = 'runtime/myllmbox/environment.psd1'
    MyllmboxModel = 'Qwen3.8-Flash-Next-W4A16-AutoRound-hybrid'
    MyllmboxDrafter = 'Qwen3.8-Flash-Next-DFlash2'
    MyllmboxWSLCVersion = '3.0.5.0'
    RequiredPartitionMiB = 98304
    CacheVolume = 'n1x-mbx-w4-dflash-test-cache'
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
    LmcacheVolume = 'n1x-c8-lmc4-ssd160-v1'
    LmcacheNamespace = 'qwen-c8-w4-std-fp32-idxbf16-kv11-b4k-v1'
    RestoreWaitMs = 0
}
