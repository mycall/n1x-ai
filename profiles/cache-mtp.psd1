@{
    Image = 'n1x-ai:lmcache'
    Container = 'n1x-qwen38-cache-mtp'
    Context = 262144
    MaxSequences = 16
    KvCacheBytes = '8589934592'
    KvCacheDtype = 'fp8_e4m3'
    BatchedTokens = 2048
    PleWorkers = 32
    CudaGraphMode = 'FULL_AND_PIECEWISE'
    UseLMCache = $true
    Mtp = $true
}
