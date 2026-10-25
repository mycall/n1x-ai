#Requires -Version 5.1
param(
    [ValidateSet('all','vllm','aiperf','ruler','scheduler','speculation')][string]$Suite='all',
    [string]$Profile='',
    [string]$PowerMode='Not recorded',
    [ValidateRange(1,16)][int]$SchedulerConcurrency=4,
    [ValidateRange(1,4096)][int]$SchedulerOutputTokens=256,
    [switch]$Build,
    [switch]$Smoke
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
. "$PSScriptRoot/scripts/config.ps1"
$config=Get-N1xConfig -Root $PSScriptRoot -Profile $Profile
if(-not $Smoke -and $Suite -in @('all','ruler') -and $config.Context -lt 262144){
    throw 'The full RULER sweep needs a 262144-token profile. Use -Profile cache-mtp, or -Smoke for a small check.'
}
$model=Join-Path $config.ModelRoot 'Qwen3.8-Flash-Next-W4A16-AutoRound-hybrid'
if(-not(Test-Path -LiteralPath "$model/tokenizer_config.json")){throw "Tokenizer not found at $model"}
if($Build){
    $buildArgs=@('build','--progress','plain','-t','n1x-ai:benchmarks')
    foreach($entry in @(@('https_proxy','HTTPS_PROXY'),@('http_proxy','HTTP_PROXY'))){
        if([Environment]::GetEnvironmentVariable($entry[1])){$buildArgs+=@('--secret',"id=$($entry[0]),env=$($entry[1])")}
    }
    $buildArgs+="$PSScriptRoot/benchmarks"
    & wslc @buildArgs
    if($LASTEXITCODE -ne 0){throw 'Benchmark image build failed'}
}
$health=Invoke-WebRequest "http://127.0.0.1:$($config.Port)/health" -UseBasicParsing -TimeoutSec 15
if($health.StatusCode -ne 200){throw 'Start the model service before benchmarking'}
$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$destination=Join-Path $PSScriptRoot "results/benchmarks/$stamp-$Suite"
New-Item -ItemType Directory -Force $destination | Out-Null
$os=Get-CimInstance Win32_OperatingSystem
Add-Type -AssemblyName System.Windows.Forms
$power=[System.Windows.Forms.SystemInformation]::PowerStatus
$record=@{
    started=(Get-Date).ToUniversalTime().ToString('o'); powerMode=$PowerMode
    windowsScheme=(& powercfg /getactivescheme | Out-String).Trim()
    availableGiB=[math]::Round($os.FreePhysicalMemory/1MB,2)
    config=$config; git=(& git -C $PSScriptRoot rev-parse HEAD)
    battery=@(Get-CimInstance Win32_Battery | Select-Object BatteryStatus,EstimatedChargeRemaining)
    powerSource=$power.PowerLineStatus.ToString()
    server=(& wslc inspect $config.Container | Out-String | ConvertFrom-Json)
    clientImage=(& wslc image inspect n1x-ai:benchmarks | Out-String | ConvertFrom-Json)
}
$record | ConvertTo-Json -Depth 30 | Set-Content "$destination/host.json" -Encoding UTF8
$runArgs=@('run','--rm','--name','n1x-benchmark-client','--network',"container:$($config.Container)",
    '-v',"${model}:/model:ro",'-v',"${destination}:/results",'n1x-ai:benchmarks','--suite',$Suite)
if($Suite -eq 'scheduler'){$runArgs+=@('--scheduler-concurrency',[string]$SchedulerConcurrency,
    '--scheduler-output-tokens',[string]$SchedulerOutputTokens)}
if($Smoke){$runArgs+=@('--concurrency','1','--input-lengths','512','--requests','2','--output-tokens','16',
    '--agent-concurrency','1','--conversations','1','--context-lengths','4096','--samples','1')}
Write-Host "Results: $destination"
& wslc @runArgs
if($LASTEXITCODE -ne 0){throw "Benchmark failed; inspect $destination"}
Write-Host "Completed. Raw results: $destination"
