param([string]$RunName = 'performance-affinity-subset')
$ErrorActionPreference='Stop'
$container='n1x-qwen38-mtp-throughput'
$processList=@(& wslc exec $container ps -eo pid,comm)
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect serving processes' }
$engines=@($processList | Where-Object { $_ -match '^\s*\d+\s+VLLM::EngineCor' })
if ($engines.Count -ne 1) { throw 'Expected exactly one vLLM engine' }
$engineProcessId=[int](($engines[0].Trim() -split '\s+')[0])
$processIds=@(1,$engineProcessId)
$snapshots=@{}
foreach ($processId in $processIds) {
    $lines=@(& wslc exec $container taskset -apc $processId)
    if ($LASTEXITCODE -ne 0) { throw 'Cannot capture thread affinity' }
    foreach ($line in $lines) {
        if ($line -match "pid (\d+)'s current affinity list: (.+)") {
            $snapshots[$Matches[1]]=$Matches[2]
        }
    }
}
if (-not $snapshots.Count) { throw 'Empty affinity snapshot' }
$snapshots | ConvertTo-Json | Set-Content "$PSScriptRoot/results/$RunName-original-affinity.json" -Encoding UTF8
$job=$null
try {
    foreach ($processId in $processIds) {
        & wslc exec $container taskset -apc '5-9,15-19' $processId | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Cannot set trial affinity' }
    }
    $job=Start-Job -ArgumentList $PSScriptRoot,$RunName -ScriptBlock {
        param($root,$name)
        Get-Counter '\Processor Information(*)\% Processor Time' -SampleInterval 2 -MaxSamples 30 |
            Export-Clixml "$root/results/$name-host-cpu.xml"
    }
    & "$PSScriptRoot/benchmark.ps1" -Profile mtp-throughput -RunName $RunName -ContextTokens 1024 -Repeats 2 -OutputTokens 128 -RuntimeNote 'API and engine threads pinned to guest CPUs 5-9,15-19; physical mapping unverified. Restored after trial.'
} finally {
    # Existing threads had the same original mask. Restore all threads, including
    # any created during the trial, in one call per process when possible.
    $masks=@($snapshots.Values | Select-Object -Unique)
    if ($masks.Count -eq 1) {
        foreach ($processId in $processIds) {
            & wslc exec $container taskset -apc $masks[0] $processId | Out-Null
            if ($LASTEXITCODE -ne 0) { Write-Warning "Affinity restore failed for PID $processId" }
        }
    } else {
        foreach ($threadId in $snapshots.Keys) {
            & wslc exec $container taskset -pc $snapshots[$threadId] $threadId | Out-Null
            if ($LASTEXITCODE -ne 0) { Write-Warning "Affinity restore failed for thread $threadId" }
        }
    }
    if ($job) { $job | Wait-Job -Timeout 5 | Out-Null; Receive-Job $job; Stop-Job $job; Remove-Job $job }
}
