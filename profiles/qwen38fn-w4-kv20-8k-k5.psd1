@{
    # Measured long-context throughput winner: W4 + DFlash2 K5 + BF16 SSM + KV20/batch8K.
    # Three new paired runs: 384.60 s mean C4, SD 0.74 s; 36/36 long tasks, 60/60 hits.
    # Seeds 45/46/47: 96/96 short tasks; earlier seed 42/43/44 results remain in the wiki.
    # Restore: 6/6 correct, 7.57 s mean pair; 30/31 chunks; strict check fails.
    # New trials' minimum GPU headroom: 1,986 MiB at 96 GiB.
    # See wiki/FP4-Local-AZ-trial.md for variability, earlier failures, and tradeoffs.
    Backend = 'wslc-myllmbox'
    Image = 'n1x-ai:mbx-setup-1447755d89af469f894bfa8dcb51506d'
    ImageId = 'sha256:819970fd46a90c1e70b7cd06aeb15d5ce3c75b02b62892a8322f42de225566bc'
    Container = 'n1x-qwen38fn-w4-kv20-8k-k5'
    MyllmboxConfig = 'profiles/qwen38fn-w4-kv20-8k-k5.yaml'
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
    KvCacheBytes = '21474836480'
    KvCacheDtype = 'fp8'
    CacheBlockTokens = 4096
    LmcacheChunkTokens = 4096
    Mtp = $false
    DFlash = $true
    DFlashTokens = 5
    UseLMCache = $true
    LmcacheL1GiB = 4
    LmcacheL2GiB = 160
    LmcacheVolume = 'n1x-w4-kv20-8k-k5-lmc-v1'
    LmcacheNamespace = 'qwen-w4-dflash-k5-bf16-kv20-batch8k-v1'
    RestoreWaitMs = 0
}
