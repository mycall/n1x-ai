@{
    Image = 'n1x-ai:magi-v5'
    Container = 'n1x-qwen38'
    ModelRoot = 'C:\Users\michael\models'
    Port = 8000
    Context = 32768
    MaxSequences = 1
    KvCacheBytes = '4g'
    BatchedTokens = 2048
    PleWorkers = 8
    CacheVolume = 'n1x-qwen38-cache'
}
