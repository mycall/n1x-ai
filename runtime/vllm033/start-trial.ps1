param(
    [int]$Port = 18133,
    [switch]$TargetOnly,
    [switch]$Serving,
    [string]$CacheVolume,
    [ValidateRange(0.5, 16)][double]$CacheL1GiB = 1
)
$ErrorActionPreference = 'Stop'
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
. "$root/scripts/config.ps1"
$config = Get-N1xConfig -Root $root -Profile 'qwen38fn-best'
$target = Join-Path $config.ModelRoot $config.MyllmboxModel
$draft = Join-Path $config.ModelRoot $config.MyllmboxDrafter
$args033 = @(
    'run', '-d', '--name', 'n1x-trial-v033', '--pull', 'never', '--gpus', 'all', '--shm-size', '2g',
    '--publish', "127.0.0.1:${Port}:8000", '--volume', "${target}:/model:ro",
    '--volume', "${draft}:/drafter:ro", '--volume', "$($config.PleVolume):/ple:ro",
    '--env', 'N1X_W4_PLE_DIR=/ple', '--env', 'HF_HUB_OFFLINE=1', '--env', 'TRANSFORMERS_OFFLINE=1',
    '--env', 'VLLM_NO_USAGE_STATS=1', '--env', 'MAX_JOBS=1', '--env', 'VLLM_USE_DEEP_GEMM=0',
    '--env', 'VLLM_USE_V2_MODEL_RUNNER=1', '--env', "N1X_QWEN4_DFLASH=$([int](-not $TargetOnly))"
)
if ($CacheVolume -and (-not $Serving -or $CacheVolume -notmatch '^n1x-033-[a-z0-9-]+$')) {
    throw 'Select -Serving and a separate n1x-033-* cache volume for the 0.33 trial'
}
$image = 'n1x-ai:vllm033-dflash-candidate'
if ($Serving) {
    $image = 'n1x-ai:v033-serving'
    $args033 += @('--env','N1X_PLE_PREFETCH=1')
}
if ($CacheVolume) {
    $l1Budget = $CacheL1GiB.ToString([Globalization.CultureInfo]::InvariantCulture)
    . "$root/scripts/native.ps1"
    . "$root/scripts/myllmbox.ps1"
    $config.Container = 'n1x-trial-v033'
    Start-N1xMyllmboxMonitor $root $config
    $state = (Get-N1xMyllmboxPaths $root $config).State
    $cacheMode = if ($TargetOnly) { 'target' } else { 'dflash2-k3' }
    $args033 += @('--volume', "${CacheVolume}:/lmcache", '--volume', "${state}:/state:ro",
        '--env','N1X_LMCACHE_STAGED_TRANSFER=1','--env',"N1X_CACHE_NAMESPACE=qwen-w4-$cacheMode-fp8-033-v1",
        '--env',"N1X_LMCACHE_L1_GIB=$l1Budget",'--env','N1X_LMCACHE_L2_GIB=16',
        '--env','N1X_CACHE_BLOCK_TOKENS=4096','--env','N1X_LMCACHE_CHUNK_TOKENS=4096',
        '--entrypoint','python3')
    $image = 'n1x-ai:v033-serving-lmcache'
}
$args033 += $image
if ($CacheVolume) {$args033 += @('-u','/opt/n1x/serve.py','--model')}
$args033 += @('/model', '--served-model-name', 'qwen/qwen38fn-best', '--gpu-memory-utilization', '0.01',
    '--dtype', 'bfloat16', '--moe-backend', 'marlin')
if ($Serving) {
    # LMCache requires each hybrid prefill step to advance a full cache block.
    $batchTokens = if ($CacheVolume) { '4096' } else { '2048' }
    $args033 += @('--max-model-len','262144','--max-num-seqs','2','--max-num-batched-tokens',$batchTokens,
        '--kv-cache-memory-bytes','16106127360','--kv-cache-dtype','fp8','--kv-cache-dtype-skip-layers','sliding_window',
        '--enable-auto-tool-choice','--tool-call-parser','qwen3_xml',
        '--reasoning-parser','qwen3','--enable-prompt-tokens-details',
        '--compilation-config','{"mode":0,"cudagraph_mode":"FULL_DECODE_ONLY","cudagraph_capture_sizes":[1,2,4,8]}')
    # The LMCache supervisor supplies the cache block size itself.
    if ($CacheVolume) {
        # The 4096-token FlashInfer tuning sweep exhausted host memory headroom.
        $args033 += @('--kernel-config','{"enable_flashinfer_autotune":false}')
    } else {
        $args033 += @('--block-size','4096','--mamba-cache-mode','align')
    }
} else {
    $args033 += @('--enforce-eager','--max-model-len','2048','--max-num-seqs','1',
        '--max-num-batched-tokens','256','--kv-cache-memory-bytes','4294967296')
}
if (-not $TargetOnly) {
    $args033 += @('--speculative-config', '{"method":"dflash","model":"/drafter","num_speculative_tokens":3,"attention_backend":"TRITON_ATTN","draft_load_config":{"load_format":"safetensors"}}')
}
& wslc @args033
if ($LASTEXITCODE) { throw "Could not start the 0.33 trial ($LASTEXITCODE)" }
