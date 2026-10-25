$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = Split-Path -Parent $PSScriptRoot
$directory = Join-Path $root '.build/memory-summary-regression'
New-Item -ItemType Directory -Force $directory | Out-Null
# Startup/shutdown samples omit server; a valid serving sample may omit guest.
$samples = @(
    @{timestamp='startup';windows=@{availableGiB=20};gpu=@{usedMiB=100;totalMiB=90112};serverError='not ready'},
    @{timestamp='serving-a';windows=@{availableGiB=8};gpu=@{usedMiB=88064;totalMiB=90112};server=@{};
      guest=@{MemAvailable=3;Cached=2;SwapTotal=0;SwapFree=0}},
    @{timestamp='serving-b';windows=@{availableGiB=5};gpu=@{usedMiB=87040;totalMiB=90112};server=@{}},
    @{timestamp='shutdown';windows=@{availableGiB=22};serverError='stopped'}
)
$lines = @($samples | ForEach-Object { $_ | ConvertTo-Json -Depth 5 -Compress })
$lines | Set-Content (Join-Path $directory 'memory.jsonl') -Encoding UTF8
@{modelArgs=@('--kv-cache-memory-bytes','8589934592');lmcacheL1GiB=8} |
    ConvertTo-Json | Set-Content (Join-Path $directory 'run-config.json') -Encoding UTF8
& (Join-Path $root 'summarize-memory.ps1') -RunDirectory $directory | Out-Null
$report = Get-Content (Join-Path $directory 'memory-balance.json') -Raw | ConvertFrom-Json
if ($report.pairedServingSamples -ne 2 -or $report.gpuPeakUsedGiB -ne 86 -or
    $report.lowestWindowsSample.availableGiB -ne 5 -or $null -ne $report.lowestWindowsSample.guestAvailableGiB) {
    throw 'Memory summary mishandled absent server/guest properties under strict mode'
}
Write-Output 'Memory-summary strict-mode regression passed'
