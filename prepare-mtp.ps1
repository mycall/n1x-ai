# Optional FlashInfer draft-expert cache; not required by the Triton MTP profile.
# Populate it before loading the large model to keep host-memory use bounded.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$config = Import-PowerShellDataFile (Join-Path $PSScriptRoot 'config.psd1')
$running = & wslc list --quiet --filter 'label=n1x-ai.managed=true'
if ($LASTEXITCODE -ne 0) { throw 'Cannot check project containers' }
if ($running) { throw 'Stop the running project profile before preparing MTP kernels.' }

$code = "from flashinfer.jit.fused_moe import gen_cutlass_fused_moe_sm120_module; gen_cutlass_fused_moe_sm120_module().build_and_load(); print('MTP kernel cache ready', flush=True)"
$arguments = @(
    'run', '--rm', '--name', 'n1x-kernel-build', '--label', 'n1x-ai.managed=true',
    '--gpus', 'all', '--volume', "$($config.CacheVolume):/root/.cache",
    '--env', 'MAX_JOBS=1', '--env', 'FLASHINFER_NVCC_THREADS=1',
    '--entrypoint', 'python', $config.Image, '-c', $code
)
Write-Host 'Preparing optional FlashInfer MTP kernels with one compiler job. The Triton profile does not require this.'
& wslc @arguments
if ($LASTEXITCODE -ne 0) { throw "MTP kernel preparation failed ($LASTEXITCODE)" }
