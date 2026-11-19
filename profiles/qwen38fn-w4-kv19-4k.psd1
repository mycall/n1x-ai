@{
    # Restore-qualified W4 + DFlash2 K3 + BF16 SSM + KV19, prefill batch4K.
    # 32/32 short + 12/12 near-full tasks; C4 545.43 s, 20/20 follow-up cache hits.
    # Restart: 2/2 correct in 5.71 s, 126976/126976 complete-chunk tokens each.
    # Strict restore check passed; partial prompt tail still recomputed (97.02% total coverage).
    # See wiki/FP4-Local-AZ-trial.md for the throughput/restore tradeoff.
    Backend = 'wslc-myllmbox'
    Image = 'n1x-ai:mbx-setup-1447755d89af469f894bfa8dcb51506d'
    ImageId = 'sha256:819970fd46a90c1e70b7cd06aeb15d5ce3c75b02b62892a8322f42de225566bc'
    Container = 'n1x-qwen38fn-w4-kv19-4k'
    MyllmboxConfig = 'profiles/qwen38fn-w4-kv19-4k.yaml'
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
    BatchedTokens = 4096
    KvCacheBytes = '20401094656'
    KvCacheDtype = 'fp8'
    CacheBlockTokens = 4096
    LmcacheChunkTokens = 4096
    Mtp = $false
    DFlash = $true
    UseLMCache = $true
    LmcacheL1GiB = 4
    LmcacheL2GiB = 160
    LmcacheVolume = 'n1x-w4-kv19-4k-lmc-v1'
    LmcacheNamespace = 'qwen-w4a16-compute-bf16-ssm-bf16-index-bf16-ple-fp8-{settings}-v2'
    RestoreWaitMs = 0
}
