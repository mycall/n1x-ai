param([int]$Port = 18133, [switch]$TargetOnly)
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
    '--env', 'VLLM_USE_V2_MODEL_RUNNER=1', '--env', "N1X_QWEN4_DFLASH=$([int](-not $TargetOnly))",
    'n1x-ai:vllm033-dflash-candidate',
    '/model', '--served-model-name', 'qwen/qwen38fn-best', '--gpu-memory-utilization', '0.01',
    '--enforce-eager', '--max-model-len', '2048', '--max-num-seqs', '1', '--max-num-batched-tokens', '256',
    '--kv-cache-memory-bytes', '4294967296', '--dtype', 'bfloat16', '--moe-backend', 'marlin'
)
if (-not $TargetOnly) {
    $args033 += @('--speculative-config', '{"method":"dflash","model":"/drafter","num_speculative_tokens":3,"attention_backend":"TRITON_ATTN","draft_load_config":{"load_format":"safetensors"}}')
}
& wslc @args033
if ($LASTEXITCODE) { throw "Could not start the 0.33 trial ($LASTEXITCODE)" }
