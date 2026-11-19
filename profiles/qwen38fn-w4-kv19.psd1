@{
    # W4 + BF16 SSM + KV19: 32/32 short and 12/12 near-full C4 tasks.
    # Near-full C4: 462.53 s, all 20 follow-ups reused the prefix.
    # Restart: 2/2 correct with ~94% external prefix coverage; strict full-restore check failed.
    # Separate experimental profile; see wiki/FP4-Local-AZ-trial.md.
    Backend = 'wslc-myllmbox'
    Image = 'n1x-ai:mbx-setup-1447755d89af469f894bfa8dcb51506d'
    ImageId = 'sha256:819970fd46a90c1e70b7cd06aeb15d5ce3c75b02b62892a8322f42de225566bc'
    Container = 'n1x-qwen38fn-w4-kv19'
    MyllmboxConfig = 'profiles/qwen38fn-w4-kv19.yaml'
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
    KvCacheBytes = '20401094656'
    KvCacheDtype = 'fp8'
    CacheBlockTokens = 4096
    LmcacheChunkTokens = 4096
    Mtp = $false
    DFlash = $true
    UseLMCache = $true
    LmcacheL1GiB = 4
    LmcacheL2GiB = 160
    LmcacheVolume = 'n1x-w4-kv19-lmc-v1'
    LmcacheNamespace = 'qwen-w4a16-compute-bf16-ssm-bf16-index-bf16-ple-fp8-{settings}-v2'
    RestoreWaitMs = 0
}
