param(
    [string]$OutputPath = "$PSScriptRoot/results/power.jsonl",
    [string]$StopFile = '',
    [int]$IntervalSeconds = 2
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
$utf8 = [Text.UTF8Encoding]::new($false)
do {
    $power = [System.Windows.Forms.SystemInformation]::PowerStatus
    $sample = [ordered]@{
        recordedAt=[DateTimeOffset]::Now.ToString('o')
        powerLineStatus=[string]$power.PowerLineStatus
        batteryChargeStatus=[string]$power.BatteryChargeStatus
        batteryLifePercent=$power.BatteryLifePercent
    }
    [IO.File]::AppendAllText($OutputPath,($sample | ConvertTo-Json -Compress)+[Environment]::NewLine,$utf8)
    if (-not $StopFile) { break }
    Start-Sleep -Seconds $IntervalSeconds
} while (-not (Test-Path -LiteralPath $StopFile))
