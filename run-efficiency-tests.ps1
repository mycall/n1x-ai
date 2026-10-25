param([string]$RunPrefix='eff-20261024', [switch]$SkipBuild)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if ($RunPrefix -notmatch '^[a-zA-Z0-9_-]+$') { throw 'Invalid run prefix' }
$root=$PSScriptRoot
$protocol=Get-Content "$root/efficiency-protocol.json" -Raw | ConvertFrom-Json
$statusPath="$root/results/$RunPrefix-status.json"
$status=@{processId=$PID;started=(Get-Date).ToString('o');status='running';profile=$null}
function Save-Status { [IO.File]::WriteAllText($statusPath,($status|ConvertTo-Json),[Text.UTF8Encoding]::new($false)) }
try {
    Save-Status
    if (@(& wslc list --format json | Where-Object { $_.Trim() }).Count) { throw 'Other containers are running' }
    $gpu=@(& nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits)[0]
    if ($LASTEXITCODE -ne 0 -or [int]$gpu -ne 90112) { throw 'Requires 88 GiB GPU partition' }
    $raw=& wslc image inspect n1x-ai:lmcache-optimization-test
    if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect frozen parent' }
    $parent=@(($raw -join "`n")|ConvertFrom-Json)[0].Id
    $tag='n1x-ai:efficiency-test'
    if (-not $SkipBuild) {
        $pin='n1x-ai:efficiency-parent-'+$parent.Substring(7,12)
        & wslc tag $parent $pin
        if ($LASTEXITCODE -ne 0) { throw 'Cannot pin parent' }
        & wslc build --build-arg "COMPARISON_IMAGE=$pin" --build-arg "COMPARISON_IMAGE_ID=$parent" -t $tag -f "$root/cache-tests/Dockerfile.efficiency" "$root/cache-tests"
        if ($LASTEXITCODE -ne 0) { throw 'Efficiency image build failed' }
    }
    $raw=& wslc image inspect $tag
    if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve efficiency image' }
    $image=@(($raw -join "`n")|ConvertFrom-Json)[0]
    if ($image.Config.Labels.'n1x-ai.comparison-base' -ne $parent -or $image.Config.Labels.'n1x-ai.efficiency-protocol' -ne '1') { throw 'Image provenance mismatch' }
    foreach($profile in $protocol.profiles) {
        $status.profile=$profile.name; Save-Status
        $options=@{RunName="$RunPrefix-$($profile.name)";SkipBuild=$true;Vmm=$true;Admission=$true;Segmented=$true;CapacityCheck=$true;Optimizations=$true;
            AgentLoops=$true;AgentConcurrencies=@($profile.concurrencies|ForEach-Object{[int]$_});AgentTurns=12;AgentContextTokens=131000;RequestSeed=0;
            PrefillBatchTokens=[int]$profile.batch;DisableMtp=(-not $profile.mtp);LmcacheL1GiB=8;KvCacheBytes='8589934592';ContextTokens=@(32000);
            SkipConcurrency=$true;TestImageOverride=$image.Id;PowerModeNote='Eco Mode and Energy Saver (last user-reported); no mode changes by harness'}
        if ($null -ne $profile.PSObject.Properties['twoNear262K'] -and $profile.twoNear262K) {
            $options.SkipConcurrency=$false;$options.ParallelRestore=$true;$options.ParallelSessions=2;$options.ParallelContextTokens=261000
        }
        & "$root/run-cache-tests.ps1" @options
        & "$root/summarize-memory.ps1" -RunDirectory "$root/results/$($options.RunName)"
    }
    $runPaths=@($protocol.profiles|ForEach-Object{"$root/results/$RunPrefix-$($_.name)"})
    & python "$root/cache-tests/summarize_efficiency.py" @runPaths --protocol "$root/efficiency-protocol.json" --output "$root/efficiency-results.json"
    if ($LASTEXITCODE -ne 0) { throw 'Efficiency qualification failed; inspect efficiency-results.json' }
    $status.status='complete'
} catch { $status.status='failed';$status.error=$_.Exception.Message;throw }
finally { $status.finished=(Get-Date).ToString('o');Save-Status }
