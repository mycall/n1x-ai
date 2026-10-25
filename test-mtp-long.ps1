param(
    [ValidatePattern('^[a-zA-Z0-9_-]+$')][string]$ResultName = 'mtp-long-limit',
    [string]$MemoryContainer = ''
)
# Run after an MTP-enabled 262K profile is ready and other test requests finish.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$config = Import-PowerShellDataFile (Join-Path $PSScriptRoot 'config.psd1')
$endpoint = "http://127.0.0.1:$($config.Port)"
$models = Invoke-RestMethod "$endpoint/v1/models" -TimeoutSec 30
if ($models.data[0].max_model_len -ne 262144) { throw 'Expected the 262144-token profile to be running.' }

function Get-MtpCounters {
    $metrics = (Invoke-WebRequest "$endpoint/metrics" -UseBasicParsing -TimeoutSec 30).Content
    $counters = @{drafted=[double]0; accepted=[double]0}
    foreach ($line in ($metrics -split "`n")) {
        if ($line -match '^vllm:spec_decode_num_draft_tokens_total\{[^}]*\}\s+(\S+)') {
            $counters.drafted += [double]::Parse($Matches[1], [Globalization.CultureInfo]::InvariantCulture)
        }
        if ($line -match '^vllm:spec_decode_num_accepted_tokens_total\{[^}]*\}\s+(\S+)') {
            $counters.accepted += [double]::Parse($Matches[1], [Globalization.CultureInfo]::InvariantCulture)
        }
    }
    return $counters
}

# Let the periodic metrics publisher flush any preceding requests.
Start-Sleep -Seconds 12
$before = Get-MtpCounters
$memoryJob = $null
if (-not $MemoryContainer) {
    # Only capture when the serving container can be identified unambiguously.
    $running = @(& wslc list --format json | ForEach-Object { $_ | ConvertFrom-Json } | Where-Object { $_.Names -like 'n1x-qwen38*' })
    if ($running.Count -eq 1) { $MemoryContainer = [string]$running[0].Names }
}
$memoryStop = Join-Path $PSScriptRoot "results/$ResultName-memory.stop"
if ($MemoryContainer -and -not (Test-Path $memoryStop)) {
    $memoryJob = Start-Job -FilePath "$PSScriptRoot/capture-memory.ps1" -ArgumentList $MemoryContainer,(Join-Path $PSScriptRoot "results/$ResultName-memory.jsonl"),$memoryStop,5
}
try {
    & (Join-Path $PSScriptRoot 'test.ps1') -Suite context -ContextTokens 261120 -ResultName $ResultName
} finally {
    if ($memoryJob) {
        Set-Content -LiteralPath $memoryStop -Value stop
        $null = Wait-Job $memoryJob -Timeout 10
        if ($memoryJob.State -eq 'Running') { Stop-Job $memoryJob }
        Receive-Job $memoryJob
        Remove-Job $memoryJob
    }
}
$deadline = (Get-Date).AddSeconds(30)
do {
    $after = Get-MtpCounters
    if ($after.drafted -gt $before.drafted) { break }
    Start-Sleep -Seconds 5
} while ((Get-Date) -lt $deadline)

$record = [ordered]@{
    recordedAt = (Get-Date).ToString('o')
    scope = 'Counter delta around the isolated 261K retrieval request; run without other clients.'
    before = $before
    after = $after
    draftedDelta = $after.drafted - $before.drafted
    acceptedDelta = $after.accepted - $before.accepted
    mtpActive = $after.drafted -gt $before.drafted
    contextEvidence = "results/$ResultName.json"
}
$record | ConvertTo-Json -Depth 6 | Set-Content (Join-Path $PSScriptRoot "results/$ResultName-counters.json") -Encoding UTF8
if (-not $record.mtpActive) { throw 'No new MTP draft tokens observed for the longest request.' }
Write-Host "MTP active at the context limit: $($record.draftedDelta) draft tokens, $($record.acceptedDelta) accepted."
