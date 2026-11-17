@{
    # Experimental intent copied from qwen38fn-best. These are requested settings,
    # not a claim that TensorFold implements DFlash2, LMCache or the vLLM scheduler.
    # Only setup/status/test are enabled. See wiki/TensorFold-trial.md.
    Backend = 'tensorfold-trial'
    TensorFoldVersion = '1.2.9'
    TensorFoldArchiveSha256 = '91e90c489bef3d217c2d3d51ce34d2a9a160ffc46b36e8b25026016b90f32f04'
    Image = 'n1x-ai:mbx-setup-1447755d89af469f894bfa8dcb51506d'
    ImageId = 'sha256:819970fd46a90c1e70b7cd06aeb15d5ce3c75b02b62892a8322f42de225566bc'
    Container = 'n1x-tensorfold-trial'
    Port = 8001
    MyllmboxModel = 'Qwen3.8-Flash-Next-W4A16-AutoRound-hybrid'
    MyllmboxDrafter = 'Qwen3.8-Flash-Next-DFlash2'
    RequiredPartitionMiB = 98304
    CacheVolume = 'n1x-mbx-w4-dflash-test-cache'
    PleVolume = 'n1x-ple-native'
    LanAccess = $false
    Context = 262144
    MaxOutputTokens = 8192
    MaxSequences = 8
    BatchedTokens = 8192
    KvCacheBytes = '16106127360'
    KvCacheDtype = 'fp8'
    CacheBlockTokens = 4096
    LmcacheChunkTokens = 4096
    Mtp = $false
    DFlash = $true
    DFlashTokens = 3
    UseLMCache = $true
    LmcacheL1GiB = 4
    LmcacheL2GiB = 160
    LmcacheVolume = 'n1x-tensorfold-trial-lmcache'
    LmcacheNamespace = 'qwen-tensorfold-trial'
    RestoreWaitMs = 0
}
