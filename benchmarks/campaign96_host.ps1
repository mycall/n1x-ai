param([Parameter(Mandatory)][string]$Out)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$root=Split-Path $PSScriptRoot -Parent
. "$root/scripts/config.ps1"
$trialConfig=Get-N1xConfig -Root $root -Profile qwen38fn-best
$gpu=@(& nvidia-smi --id=0 --query-gpu=memory.total --format=csv,noheader,nounits)
if($LASTEXITCODE -ne 0 -or $gpu.Count -ne 1 -or $gpu[0].Trim() -ne '98304'){
    throw 'This campaign requires the user-selected 96 GiB partition.'
}
$server=& wslc inspect $trialConfig.Container | Out-String | ConvertFrom-Json
if($LASTEXITCODE -ne 0){throw 'Cannot inspect the selected container'}
$os=Get-CimInstance Win32_OperatingSystem
$gpuUsed=@(& nvidia-smi --id=0 --query-gpu=memory.used --format=csv,noheader,nounits)
if($LASTEXITCODE -ne 0 -or $gpuUsed.Count -ne 1){throw 'Cannot verify GPU headroom'}
$gpuFreeMiB=98304-[int]$gpuUsed[0].Trim()
$record=@{config=$trialConfig; git=(& git -C $root rev-parse HEAD);
    dirty=([bool](& git -C $root status --porcelain));
    windowsScheme=(& powercfg /getactivescheme | Out-String).Trim();
    gpu=(& nvidia-smi --id=0 --query-gpu=name,driver_version,memory.total,memory.used --format=csv,noheader | Out-String).Trim();
    server=$server; recordedUtc=[datetime]::UtcNow.ToString('o');
    freePhysicalKiB=$os.FreePhysicalMemory;freeVirtualKiB=$os.FreeVirtualMemory;gpuFreeMiB=$gpuFreeMiB;
    models=(Invoke-RestMethod "http://127.0.0.1:$($trialConfig.Port)/v1/models" -TimeoutSec 15)}
$record | ConvertTo-Json -Depth 35 | Set-Content -LiteralPath $Out -Encoding UTF8
if($os.FreePhysicalMemory -lt 4*1024*1024 -or $os.FreeVirtualMemory -lt 4*1024*1024){
    throw 'Insufficient host memory headroom for the next trial.'
}
if($gpuFreeMiB -lt 2048){throw 'Less than 2 GiB of GPU headroom remains before the next trial.'}
