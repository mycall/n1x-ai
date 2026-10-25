@{
    DefaultProfile = 'baseline'
    Image = 'n1x-ai:magi-v5'
    Container = 'n1x-qwen38'
    ModelRoot = ''
    Port = 8000
    Context = 32768
    MaxSequences = 1
    KvCacheBytes = '4g'
    KvCacheDtype = 'auto'
    BatchedTokens = 2048
    PleWorkers = 8
    CacheVolume = 'n1x-qwen38-cache'
    PleVolume = 'n1x-ple-native'
    Mtp = $false
    DFlash = $false
    UseLMCache = $false
    LmcacheL1GiB = 8
    LmcacheL2GiB = 16
    CacheBlockTokens = 2048
    LmcacheChunkTokens = 2048
    LmcacheVolume = 'n1x-qwen38-lmcache'
    RestoreWaitMs = 0
    WindowsMinimumGiB = 4
}
