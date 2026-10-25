param(
    [ValidateSet('agents','eager','pressure-immediate','pressure-wait','pressure-wait-v2','prefill-8192','prefill-2048','prefill-4096','mtp-on','mtp-off')]
    [string[]]$Cases = @('agents','eager','pressure-immediate','pressure-wait','prefill-8192','prefill-2048','prefill-4096','mtp-on','mtp-off'),
    [string]$RunPrefix = ('opt-' + (Get-Date -Format yyyyMMdd-HHmmss)),
    [string]$PowerModeNote = 'Eco Mode and Energy Saver (last user-reported mode)',
    [string]$OverridesPath = '',
    [switch]$AllowBattery,
    [switch]$SkipBuild
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($RunPrefix -notmatch '^[a-zA-Z0-9_-]+$') { throw 'Invalid RunPrefix' }
if (-not $OverridesPath) { $OverridesPath = Join-Path $PSScriptRoot "results/$RunPrefix-overrides.json" }
$overrides = if (Test-Path -LiteralPath $OverridesPath) { Get-Content -LiteralPath $OverridesPath -Raw | ConvertFrom-Json } else { [pscustomobject]@{} }
$gpuMiB = @(& nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits)[0]
if ($LASTEXITCODE -ne 0 -or [int]$gpuMiB -ne 90112) { throw 'This comparison matrix requires the verified 88 GiB GPU partition' }
if (-not $SkipBuild) {
    & wslc build -t n1x-ai:lmcache-optimization-test -f "$PSScriptRoot/cache-tests/Dockerfile.optimizations" "$PSScriptRoot/cache-tests"
    if ($LASTEXITCODE -ne 0) { throw 'Optimization image build failed' }
    if ($Cases -contains 'pressure-wait-v2') { & "$PSScriptRoot/build-restore-queue-v2.ps1" }
}
# Sequential launches: one model resident at a time. Every run gets a distinct
# persistent-cache namespace; baseline/eager comparisons cannot inherit hits.
$imageRaw = & wslc image inspect n1x-ai:lmcache-optimization-test
if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve optimization image' }
$matrixImage = @(($imageRaw -join "`n") | ConvertFrom-Json)[0].Id
foreach ($case in $Cases) {
    $imageRaw = & wslc image inspect n1x-ai:lmcache-optimization-test
    if ($LASTEXITCODE -ne 0 -or @(($imageRaw -join "`n") | ConvertFrom-Json)[0].Id -ne $matrixImage) {
        throw 'Optimization image changed during the matrix; use a new run prefix for changed code'
    }
    $options = @{
        RunName="$RunPrefix-$case"; Optimizations=$true; Vmm=$true;
        Admission=$true; Segmented=$true; CapacityCheck=$true; SkipBuild=$true;
        AllowBattery=[bool]$AllowBattery; PowerModeNote=$PowerModeNote;
        LmcacheL1GiB=8; KvCacheBytes='8589934592'; ContextTokens=@(32000);
        SkipConcurrency=$true; AgentLoops=$true; AgentTurns=4;
        AgentContextTokens=131000; ParallelSessions=4; PrefillBatchTokens=8192
    }
    $override = $overrides.PSObject.Properties[$case]
    if ($null -ne $override) { $options.RunName = [string]$override.Value }
    if ($options.RunName -notmatch '^[a-zA-Z0-9_-]+$') { throw 'Invalid case run name' }
    switch ($case) {
        'agents' { $options.PrefixExperiment=$true }
        'eager' { $options.EagerPrefetch=$true }
        'pressure-immediate' {
            $options.AgentLoops=$false; $options.SkipConcurrency=$false;
            $options.ParallelRestore=$true; $options.ParallelSessions=2;
            $options.ParallelContextTokens=261000; $options.LmcacheL1GiB=4
        }
        'pressure-wait' {
            $options.AgentLoops=$false; $options.SkipConcurrency=$false;
            $options.ParallelRestore=$true; $options.ParallelSessions=2;
            $options.ParallelContextTokens=261000; $options.LmcacheL1GiB=4;
            $options.RestoreWaitMs=2000
        }
        'pressure-wait-v2' {
            $options.AgentLoops=$false; $options.SkipConcurrency=$false;
            $options.ParallelRestore=$true; $options.ParallelSessions=2;
            $options.ParallelContextTokens=261000; $options.LmcacheL1GiB=4;
            $options.RestoreWaitMs=2000; $options.RestoreQueueVersion=2;
            $options.TestImageOverride='n1x-ai:lmcache-restore-queue-v2-test'
        }
        { $_ -like 'prefill-*' } {
            $options.AgentConcurrencySweep=$true; $options.AgentContextTokens=32000;
            $options.PrefillBatchTokens=[int]($case.Split('-')[1])
        }
        { $_ -like 'mtp-*' } {
            $options.AgentContextTokens=32000; $options.ParallelSessions=2;
            $options.CodingWorkload=$true; $options.DisableMtp=($case -eq 'mtp-off')
        }
    }
    if ($case -eq 'pressure-wait-v2') {
        $running=@(& wslc list --format json | Where-Object { $_.Trim() })
        if ($LASTEXITCODE -ne 0 -or $running.Count) { throw 'Queue preflight requires no running containers' }
        $probeLog=Join-Path $PSScriptRoot "results/$($options.RunName)-preflight.log"
        if (Test-Path -LiteralPath $probeLog) { throw 'Queue preflight evidence already exists; choose a fresh run name' }
        $savedPreference=$ErrorActionPreference
        try {
            $ErrorActionPreference='Continue'
            & wslc run --rm --name "n1x-$RunPrefix-queue-probe" --gpus all --volume "$PSScriptRoot/cache-tests:/probes:ro" --entrypoint python $options.TestImageOverride -P /probes/probe_mp_restore_queue_v2.py 2>&1 |
                ForEach-Object { $_.ToString() } | Out-File -LiteralPath $probeLog -Encoding UTF8
            $probeExit=$LASTEXITCODE
        } finally { $ErrorActionPreference=$savedPreference }
        if ($probeExit -ne 0) { throw "Queue MP/SSD preflight failed; inspect $probeLog" }
    }
    & "$PSScriptRoot/run-cache-tests.ps1" @options
    & "$PSScriptRoot/summarize-memory.ps1" -RunDirectory "$PSScriptRoot/results/$($options.RunName)"
}
