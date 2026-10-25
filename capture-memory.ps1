param(
    [string]$Container = 'n1x-qwen38-mtp-long',
    [string]$OutputPath = "$PSScriptRoot/results/memory.jsonl",
    [string]$StopFile = '',
    [int]$IntervalSeconds = 5,
    [string]$ApiEndpoint = '',
    [string]$BudgetPath = ''
)
$ErrorActionPreference = 'Stop'
$memoryBudget = @{WindowsAvailableTargetGiB=6.0; WindowsAvailableMinimumGiB=4.0}
# Start-Job -FilePath runs a serialized script block with no PSScriptRoot.
if ($BudgetPath) { $memoryBudget = Import-PowerShellDataFile $BudgetPath }
elseif ($PSScriptRoot) { $memoryBudget = Import-PowerShellDataFile (Join-Path $PSScriptRoot 'memory-budget.psd1') }
Add-Type -AssemblyName System.Windows.Forms
$utf8 = [Text.UTF8Encoding]::new($false)
do {
    $sample = [ordered]@{ timestamp = [DateTimeOffset]::Now.ToString('o'); container = $Container }
    try {
        $os = Get-CimInstance Win32_OperatingSystem
        $sample.windows = @{ totalGiB = $os.TotalVisibleMemorySize / 1MB; availableGiB = $os.FreePhysicalMemory / 1MB }
        $sample.windows.headroomTargetGiB = $memoryBudget.WindowsAvailableTargetGiB
        $sample.windows.headroomMinimumGiB = $memoryBudget.WindowsAvailableMinimumGiB
        $sample.windows.belowHeadroomTarget = $sample.windows.availableGiB -lt $memoryBudget.WindowsAvailableTargetGiB
        $sample.windows.belowHeadroomMinimum = $sample.windows.availableGiB -lt $memoryBudget.WindowsAvailableMinimumGiB
        $power = [System.Windows.Forms.SystemInformation]::PowerStatus
        $sample.windows.powerLineStatus = [string]$power.PowerLineStatus
        $sample.windows.batteryChargeStatus = [string]$power.BatteryChargeStatus
        $sample.windows.batteryLifePercent = $power.BatteryLifePercent
        $gpu = & nvidia-smi --id=0 --query-gpu=memory.used,memory.total,power.draw,clocks.sm,temperature.gpu,utilization.gpu,utilization.memory,pstate,power.draw.instant,clocks_event_reasons.sw_power_cap,clocks_event_reasons.sw_thermal_slowdown,clocks_event_reasons.hw_thermal_slowdown,clocks_event_reasons.hw_power_brake_slowdown,clocks_event_reasons.board_limit,clocks_event_reasons.reliability,clocks_event_reasons_counters.sw_power_cap,clocks_event_reasons_counters.sw_thermal_slowdown,module.power.draw.average,power.limit --format=csv,noheader,nounits
        if ($LASTEXITCODE -ne 0) { throw 'nvidia-smi failed' }
        $fields = $gpu.Split(',').Trim()
        $sample.gpu = @{ usedMiB = [double]$fields[0]; totalMiB = [double]$fields[1]; powerWatts = $fields[2]; smMHz = $fields[3]; temperatureC = $fields[4] }
        # Preserve unsupported values as N/A rather than treating them as zero.
        $sample.gpu.utilizationPercent = $fields[5]
        $sample.gpu.memoryUtilizationPercent = $fields[6]
        $sample.gpu.pstate = $fields[7]
        $sample.gpu.instantPowerWatts = $fields[8]
        $sample.gpu.clockEvents = @{
            swPowerCap=$fields[9]; swThermalSlowdown=$fields[10]
            hwThermalSlowdown=$fields[11]; hwPowerBrake=$fields[12]
            boardLimit=$fields[13]; reliability=$fields[14]
        }
        $sample.gpu.swPowerCapMicroseconds = $fields[15]
        $sample.gpu.swThermalSlowdownMicroseconds = $fields[16]
        $sample.gpu.modulePowerWatts = $fields[17]
        $sample.gpu.powerLimitWatts = $fields[18]
        $mem = & wslc exec $Container cat /proc/meminfo /proc/vmstat /proc/pressure/memory
        if ($LASTEXITCODE -ne 0) { throw 'Guest memory query failed' }
        $values = @{}
        foreach ($line in $mem) { if ($line -match '^(MemTotal|MemFree|MemAvailable|Cached|SReclaimable|SwapTotal|SwapFree):\s+(\d+)') { $values[$Matches[1]] = [double]$Matches[2] / 1MB } }
        $sample.guest = $values
        $faults = @{}
        foreach ($line in $mem) { if ($line -match '^(pgmajfault|pgpgin|pswpin|pswpout)\s+(\d+)') { $faults[$Matches[1]] = [long]$Matches[2] } }
        $sample.guestVmCounters = $faults
        $pressure=@{}
        foreach ($line in $mem) {
            if ($line -match '^(some|full)\s+avg10=(\S+)\s+avg60=(\S+)\s+avg300=(\S+)\s+total=(\d+)') {
                $pressure[$Matches[1]]=@{avg10Percent=[double]::Parse($Matches[2],[Globalization.CultureInfo]::InvariantCulture); avg60Percent=[double]::Parse($Matches[3],[Globalization.CultureInfo]::InvariantCulture); totalMicroseconds=[long]$Matches[5]}
            }
        }
        $sample.guestMemoryPressure=$pressure
    } catch { $sample.error = $_.Exception.Message }
    if ($ApiEndpoint) {
        try {
            $metrics = (Invoke-WebRequest "$ApiEndpoint/metrics" -UseBasicParsing -TimeoutSec 3).Content
            $server = @{}
            foreach ($line in ($metrics -split "`n")) {
                if ($line -match '^vllm:(num_requests_running|num_requests_waiting|num_preemptions_total|kv_cache_usage_perc)\{[^}]*\}\s+(\S+)') {
                    $key=$Matches[1]
                    $value=[double]::Parse($Matches[2],[Globalization.CultureInfo]::InvariantCulture)
                    if (-not $server.ContainsKey($key)) { $server[$key]=0.0 }
                    $server[$key]+=$value
                }
            }
            $sample.server=$server
        } catch { $sample.serverError=$_.Exception.Message }
    }
    [IO.File]::AppendAllText($OutputPath, (($sample | ConvertTo-Json -Depth 6 -Compress) + [Environment]::NewLine), $utf8)
    if (-not $StopFile) { break }
    Start-Sleep -Seconds $IntervalSeconds
} while (-not (Test-Path -LiteralPath $StopFile))
