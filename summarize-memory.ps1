param(
    [Parameter(Mandatory=$true)][string]$RunDirectory
)
$ErrorActionPreference = 'Stop'
$run = (Resolve-Path -LiteralPath $RunDirectory).Path
$samples = @(Get-Content -LiteralPath (Join-Path $run 'memory.jsonl') | ForEach-Object { $_ | ConvertFrom-Json })
$serving = @($samples | Where-Object {
    $names = $_.PSObject.Properties.Name
    $names -contains 'server' -and $names -contains 'gpu' -and $names -contains 'windows' -and
        $null -ne $_.server -and $null -ne $_.gpu -and $null -ne $_.windows
})
if (-not $serving.Count) { throw 'No paired serving GPU/Windows samples found' }
$peak = $serving | Sort-Object { $_.gpu.usedMiB } -Descending | Select-Object -First 1
$low = $serving | Sort-Object { $_.windows.availableGiB } | Select-Object -First 1
$guest = if ($null -ne $low.PSObject.Properties['guest']) { $low.guest } else { $null }
$config = Get-Content -LiteralPath (Join-Path $run 'run-config.json') -Raw | ConvertFrom-Json
$index = [Array]::IndexOf(@($config.modelArgs), '--kv-cache-memory-bytes')
$report = [ordered]@{
    runDirectory = $run
    pairedServingSamples = $serving.Count
    gpuPeakUsedGiB = $peak.gpu.usedMiB / 1024
    gpuReportedCapacityGiB = $peak.gpu.totalMiB / 1024
    gpuUnusedAtPeakGiB = ($peak.gpu.totalMiB - $peak.gpu.usedMiB) / 1024
    configuredGpuKvGiB = $(if ($index -ge 0) { [double]$config.modelArgs[$index+1] / 1GB } else { $null })
    configuredLmcacheL1GiB = $config.lmcacheL1GiB
    lowestWindowsSample = [ordered]@{
        timestamp = $low.timestamp
        availableGiB = $low.windows.availableGiB
        gpuUsedGiB = $low.gpu.usedMiB / 1024
        guestAvailableGiB = $(if ($null -ne $guest) { $guest.MemAvailable } else { $null })
        guestCachedGiB = $(if ($null -ne $guest) { $guest.Cached } else { $null })
        guestSwapUsedGiB = $(if ($null -ne $guest) { $guest.SwapTotal - $guest.SwapFree } else { $null })
    }
    limitations = @(
        'Samples are periodic and fields are collected sequentially, not atomically.'
        'Guest memory is within host memory; do not add guest and Windows totals.'
        'Reported GPU unused memory is not a guarantee of successful allocation.'
        'Guest Cached includes file cache; this capture cannot attribute it to PLE versus other files.'
        'No per-process PSS or PyTorch reserved/allocated breakdown was recorded.'
    )
}
$json = $report | ConvertTo-Json -Depth 5
$json | Set-Content -LiteralPath (Join-Path $run 'memory-balance.json') -Encoding UTF8
$json
