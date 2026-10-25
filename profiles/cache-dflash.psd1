@{
    Image = 'n1x-ai:lmcache'
    Container = 'n1x-qwen38-cache-dflash'
    Context = 262144
    MaxSequences = 4
    KvCacheBytes = '8589934592'
    KvCacheDtype = 'fp8_e4m3'
    BatchedTokens = 4096
    PleWorkers = 32
    CudaGraphMode = 'FULL_AND_PIECEWISE'
    UseLMCache = $true
    Mtp = $false
    DFlash = $true
    IndexerFP8 = $true
    CacheBlockTokens = 1664
    LmcacheChunkTokens = 1664
}
