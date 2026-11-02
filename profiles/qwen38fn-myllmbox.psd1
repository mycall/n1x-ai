@{
    Backend = 'native'
    Container = 'n1x-qwen38fn-myllmbox'
    # Relative to this repository; override for another checkout/release location.
    NativeRuntimeRoot = '../../vllm-for-rtx-spark'
    NativeConfig = 'profiles/qwen38fn-myllmbox.yaml'
    NativeModel = 'Qwen3.8-Flash-Next-FP4-Local'
    LanAccess = $false
    Context = 409600
    MaxSequences = 16
    BatchedTokens = 8192
    KvCacheBytes = '12000000000'
    KvCacheDtype = 'fp8'
    Mtp = $true
    DFlash = $false
    UseLMCache = $false
}
