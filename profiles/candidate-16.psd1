@{
    Container = 'n1x-qwen38-candidate-16'
    Context = 262144
    KvCacheBytes = '10g'
    MaxSequences = 16
    BatchedTokens = 8192
    PleWorkers = 32
    CudaGraphMode = 'FULL_AND_PIECEWISE'
    PleVolume = 'n1x-ple-native'
}
