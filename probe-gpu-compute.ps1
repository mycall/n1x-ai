param(
    [string]$Container = 'n1x-qwen38-candidate-fast',
    [ValidateRange(5,60)][int]$Seconds = 30,
    [ValidatePattern('^[a-zA-Z0-9_-]+$')][string]$RunName = 'candidate-compute-power'
)
$ErrorActionPreference = 'Stop'
$config = Import-PowerShellDataFile "$PSScriptRoot/config.psd1"
$base = "http://127.0.0.1:$($config.Port)"
$null = Invoke-WebRequest "$base/health" -UseBasicParsing -TimeoutSec 30
$metrics = (Invoke-WebRequest "$base/metrics" -UseBasicParsing -TimeoutSec 30).Content
foreach ($line in ($metrics -split "`n")) {
    if ($line -match '^vllm:num_requests_(running|waiting)\{[^}]*\}\s+(\S+)' -and [double]$Matches[2] -gt 0) {
        throw 'Run the compute probe only when serving requests are idle.'
    }
}
$dir = Join-Path "$PSScriptRoot/results" $RunName
if (Test-Path $dir) { throw 'Choose a new RunName; existing evidence will not be overwritten.' }
New-Item -ItemType Directory $dir | Out-Null
$stopFile = Join-Path $dir 'telemetry.stop'
$job = Start-Job -FilePath "$PSScriptRoot/capture-memory.ps1" -ArgumentList $Container,(Join-Path $dir 'memory.jsonl'),$stopFile,1
try {
    $source = [Convert]::ToBase64String([IO.File]::ReadAllBytes("$PSScriptRoot/probe-gpu-compute.py"))
    & nvidia-smi --id=0 -q -d POWER,CLOCK,PERFORMANCE,UTILIZATION,TEMPERATURE | Set-Content "$dir/before.txt" -Encoding UTF8
    & wslc exec $Container python -c 'import base64,sys;exec(base64.b64decode(sys.argv.pop(1)))' $source --seconds $Seconds | Tee-Object -FilePath "$dir/compute.log"
    if ($LASTEXITCODE -ne 0) { throw 'Compute probe failed' }
    & nvidia-smi --id=0 -q -d POWER,CLOCK,PERFORMANCE,UTILIZATION,TEMPERATURE | Set-Content "$dir/after.txt" -Encoding UTF8
    $null = Invoke-WebRequest "$base/health" -UseBasicParsing -TimeoutSec 30
} finally {
    Set-Content -LiteralPath $stopFile -Value stop
    $null = Wait-Job $job -Timeout 10
    if ($job.State -eq 'Running') { Stop-Job $job }
    Receive-Job $job
    Remove-Job $job
}
Write-Host "Saved compute probe: $dir"
