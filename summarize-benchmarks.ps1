param(
    [string[]]$RunNames = @('performance-mtp-on','performance-mtp-off'),
    [string]$OutputPath = "$PSScriptRoot/performance-results.json"
)
$ErrorActionPreference = 'Stop'
$memoryBudget = Import-PowerShellDataFile (Join-Path $PSScriptRoot 'memory-budget.psd1')
function Distribution($Values) {
    $sorted = @($Values | Sort-Object)
    if (-not $sorted.Count) { return $null }
    $middle = [int][Math]::Floor($sorted.Count/2)
    $median = $sorted[$middle]
    if ($sorted.Count % 2 -eq 0) { $median = ($sorted[$middle-1]+$median)/2 }
    return @{ median=$median; min=$sorted[0]; max=$sorted[-1]; samples=$sorted.Count }
}
function Read-MetricTotal([string]$Path, [string]$Metric) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    $pattern='^'+[regex]::Escape($Metric)+'(?:\{[^}]*\})?\s+(\S+)'
    $total=0.0
    foreach ($line in (Get-Content -LiteralPath $Path)) {
        if ($line -match $pattern) { $total += [double]::Parse($Matches[1],[Globalization.CultureInfo]::InvariantCulture) }
    }
    return $total
}
$summary = @()
foreach ($name in $RunNames) {
    $dir = Join-Path "$PSScriptRoot/results" $name
    $conditions = Get-Content "$dir/conditions.json" -Raw -Encoding UTF8 | ConvertFrom-Json
    $samples = @(Get-Content "$dir/memory.jsonl" -Encoding UTF8 | ForEach-Object { $_ | ConvertFrom-Json })
    $valid = @($samples | Where-Object { -not $_.error })
    $entry = [ordered]@{
        run=$name; evidence="results/$name"; profile=$conditions.profile
        started=$conditions.started; windowsPowerMode=$conditions.windowsPowerMode
        msiMode=$conditions.msiMode; underlyingPowerPlan=$conditions.underlyingPowerPlan
        methodology=$conditions.methodology
        runtimeNote=$conditions.runtimeNote
        powerCondition=$conditions.powerCondition
        acPower=@{
            recordedSamples=@($samples | Where-Object { $_.windows.powerLineStatus }).Count
            states=@($samples | Where-Object { $_.windows.powerLineStatus } | Group-Object { $_.windows.powerLineStatus } | ForEach-Object { @{state=$_.Name; samples=$_.Count} })
            note='Sampled AC status; very brief interruptions between samples may not be captured. Missing for older runs.'
        }
        memory=@{
            samples=$samples.Count; failedSamples=$samples.Count-$valid.Count
            windowsAvailableGiB=Distribution @($valid | ForEach-Object { $_.windows.availableGiB })
            guestAvailableGiB=Distribution @($valid | ForEach-Object { $_.guest.MemAvailable })
            gpuUsedGiB=Distribution @($valid | ForEach-Object { $_.gpu.usedMiB/1024 })
            guestSwapUsedGiB=Distribution @($valid | ForEach-Object { $_.guest.SwapTotal-$_.guest.SwapFree })
            note='Sampled extrema, not instantaneous peaks. Windows and guest available RAM are separate views; do not sum.'
        }
        windowsHeadroom=@{
            targetGiB=$memoryBudget.WindowsAvailableTargetGiB
            minimumGiB=$memoryBudget.WindowsAvailableMinimumGiB
            measuredSamples=@($samples | Where-Object { $null -ne $_.windows.availableGiB }).Count
            belowTargetSamples=@($samples | Where-Object { $null -ne $_.windows.availableGiB -and $_.windows.availableGiB -lt $memoryBudget.WindowsAvailableTargetGiB }).Count
            belowMinimumSamples=@($samples | Where-Object { $null -ne $_.windows.availableGiB -and $_.windows.availableGiB -lt $memoryBudget.WindowsAvailableMinimumGiB }).Count
            note='Assessed against the current desktop headroom policy, including historical runs. Sampling does not enforce a Windows RAM reservation.'
        }
        gpuTelemetry=@{
            reportedPowerWatts=Distribution @($valid | Where-Object { $_.gpu.powerWatts -match '^\d+(\.\d+)?$' } | ForEach-Object { [double]$_.gpu.powerWatts })
            smMHz=Distribution @($valid | Where-Object { $_.gpu.smMHz -match '^\d+(\.\d+)?$' } | ForEach-Object { [double]$_.gpu.smMHz })
            utilizationPercent=Distribution @($valid | Where-Object { $_.gpu.utilizationPercent -match '^\d+(\.\d+)?$' } | ForEach-Object { [double]$_.gpu.utilizationPercent })
            pstateCounts=@($valid | Where-Object { $_.gpu.pstate } | Group-Object { $_.gpu.pstate } | ForEach-Object { @{state=$_.Name; samples=$_.Count} })
            note='Includes inter-request idle time. GPU telemetry does not establish whole-superchip power; module power and limit are unavailable on this system.'
        }
        serverTelemetry=@{
            samples=@($samples | Where-Object { $_.server }).Count
            failedSamples=@($samples | Where-Object { $_.serverError }).Count
            activeRequests=Distribution @($samples | Where-Object { $_.server } | ForEach-Object { $_.server.num_requests_running })
            waitingRequests=Distribution @($samples | Where-Object { $_.server } | ForEach-Object { $_.server.num_requests_waiting })
            kvCacheUsageFraction=Distribution @($samples | Where-Object { $_.server } | ForEach-Object { $_.server.kv_cache_usage_perc })
            note='Sampled server metrics include inter-request idle time and metrics publication delay. Missing for older runs.'
        }
    }
    if (Test-Path "$dir/requests.json") {
        $requests = Get-Content "$dir/requests.json" -Raw -Encoding UTF8 | ConvertFrom-Json
        $groups = @()
        foreach ($group in ($requests | Group-Object targetInputTokens)) {
            $drafted = ($group.Group | ForEach-Object { $_.metricsDelta.'vllm:spec_decode_num_draft_tokens_total' } | Measure-Object -Sum).Sum
            $accepted = ($group.Group | ForEach-Object { $_.metricsDelta.'vllm:spec_decode_num_accepted_tokens_total' } | Measure-Object -Sum).Sum
            $groups += @{
                targetInputTokens=[int]$group.Name; actualInputTokens=@($group.Group.promptTokens | Select-Object -Unique)
                requests=$group.Count; outputTokens=@($group.Group.outputTokens | Select-Object -Unique)
                ttftSeconds=Distribution $group.Group.ttftSeconds
                serverDecodeTokensPerSecond=Distribution $group.Group.serverDecodeTokensPerSecond
                totalSeconds=Distribution $group.Group.totalSeconds
                draftedTokens=$drafted; acceptedTokens=$accepted
                prefixCacheHits=($group.Group | ForEach-Object { $_.metricsDelta.'vllm:prefix_cache_hits_total' } | Measure-Object -Sum).Sum
                healthyAfterAll=(@($group.Group | Where-Object { -not $_.healthyAfter }).Count -eq 0)
            }
        }
        $entry.measurements = $groups
    } else {
        $measurements = @()
        foreach ($file in (Get-ChildItem "$dir/input-*-concurrency-*.json" | Where-Object { $_.Name -match '^input-(\d+)-concurrency-(\d+)\.json$' })) {
            $null = $file.Name -match '^input-(\d+)-concurrency-(\d+)\.json$'
            $inputLength = [int]$Matches[1]; $clients = [int]$Matches[2]
            $result = Get-Content $file.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
            $before=Read-MetricTotal "$dir/$($file.BaseName)-metrics-before.txt" 'vllm:num_preemptions_total'
            $after=Read-MetricTotal "$dir/$($file.BaseName)-metrics-after.txt" 'vllm:num_preemptions_total'
            $preemptions=if ($null -ne $before -and $null -ne $after) { $after-$before } else { $null }
            $phaseTelemetry=$null
            $windowPath="$dir/$($file.BaseName)-window.json"
            if (Test-Path -LiteralPath $windowPath) {
                $window=Get-Content -LiteralPath $windowPath -Raw | ConvertFrom-Json
                $phase=@($valid | Where-Object { [DateTimeOffset]$_.timestamp -ge [DateTimeOffset]$window.started -and [DateTimeOffset]$_.timestamp -le [DateTimeOffset]$window.finished })
                $phaseTelemetry=@{
                    samples=$phase.Count
                    gpuUsedGiB=Distribution @($phase | ForEach-Object { $_.gpu.usedMiB/1024 })
                    windowsAvailableGiB=Distribution @($phase | ForEach-Object { $_.windows.availableGiB })
                    guestFreeGiB=Distribution @($phase | Where-Object { $null -ne $_.guest.MemFree } | ForEach-Object { $_.guest.MemFree })
                    memorySomeStallAvg10Percent=Distribution @($phase | Where-Object { $_.guestMemoryPressure } | ForEach-Object { $_.guestMemoryPressure.some.avg10Percent })
                    memoryFullStallAvg10Percent=Distribution @($phase | Where-Object { $_.guestMemoryPressure } | ForEach-Object { $_.guestMemoryPressure.full.avg10Percent })
                    reportedPowerWatts=Distribution @($phase | Where-Object { $_.gpu.powerWatts -match '^\d+(\.\d+)?$' } | ForEach-Object { [double]$_.gpu.powerWatts })
                    smMHz=Distribution @($phase | Where-Object { $_.gpu.smMHz -match '^\d+(\.\d+)?$' } | ForEach-Object { [double]$_.gpu.smMHz })
                    temperatureC=Distribution @($phase | Where-Object { $_.gpu.temperatureC -match '^\d+(\.\d+)?$' } | ForEach-Object { [double]$_.gpu.temperatureC })
                    activeRequests=Distribution @($phase | Where-Object { $_.server } | ForEach-Object { $_.server.num_requests_running })
                    kvCacheUsageFraction=Distribution @($phase | Where-Object { $_.server } | ForEach-Object { $_.server.kv_cache_usage_perc })
                    note=$window.note
                }
            }
            $measurements += @{ inputTokens=$inputLength; concurrency=$clients; completed=$result.completed; failed=$result.failed; preemptions=$preemptions; telemetry=$phaseTelemetry; totalOutputTokens=$result.total_output_tokens; durationSeconds=$result.duration; outputTokensPerSecond=$result.output_throughput; medianTtftMs=$result.median_ttft_ms; p99TtftMs=$result.p99_ttft_ms; medianTpotMs=$result.median_tpot_ms; p99TpotMs=$result.p99_tpot_ms; medianE2eMs=$result.median_e2el_ms; p99E2eMs=$result.p99_e2el_ms }
        }
        $entry.measurements = $measurements
    }
    $summary += $entry
}
$document = @{ recorded=[DateTimeOffset]::Now.ToString('o'); timezone='America/Los_Angeles'; runs=$summary; limitations=@('Synthetic finite workloads; no quality score or sustained serving qualification.','Sequential profile order and changing clocks/temperature are not controlled.','Performance mode names are user reported; underlying Balanced plan is recorded separately.','Python version remains 3.12.15 inside the server. No Python upgrade measured.') }
[IO.File]::WriteAllText($OutputPath,($document | ConvertTo-Json -Depth 30),[Text.UTF8Encoding]::new($false))
Write-Host "Saved $OutputPath"
