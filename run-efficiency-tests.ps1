param([string]$RunPrefix=('eff-'+(Get-Date -Format yyyyMMdd-HHmmss)), [switch]$SkipBuild,
      [string]$CaseList='', [string]$OverridesPath='', [switch]$CollectRejectedReference,
      [string]$ProtocolPath='', [string]$OutputPath='',
      [ValidatePattern('^[a-zA-Z0-9_-]+$')][string]$AfterOptimizationRun='')
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if ($RunPrefix -notmatch '^[a-zA-Z0-9_-]+$') { throw 'Invalid run prefix' }
$root=$PSScriptRoot
if(-not $ProtocolPath){$ProtocolPath="$root/efficiency-protocol.json"}
if(-not $OutputPath){$OutputPath="$root/efficiency-results.json"}
$protocol=Get-Content -LiteralPath $ProtocolPath -Raw | ConvertFrom-Json
[string[]]$cases=if ($CaseList) { @($CaseList.Split(',')) } else { @($protocol.profiles.name) }
if (@($cases|Select-Object -Unique).Count -ne $cases.Count -or @($cases|Where-Object { $_ -notin $protocol.profiles.name }).Count) { throw 'Unknown or duplicate efficiency case' }
if (-not $OverridesPath) { $OverridesPath="$root/results/$RunPrefix-overrides.json" }
$overrides=if(Test-Path -LiteralPath $OverridesPath){Get-Content -LiteralPath $OverridesPath -Raw|ConvertFrom-Json}else{[pscustomobject]@{}}
$profileRuns=@{}
foreach($profile in $protocol.profiles) {
    $override=$overrides.PSObject.Properties[$profile.name]
    $name=if($null -ne $override){[string]$override.Value}else{"$RunPrefix-$($profile.name)"}
    if($name -notmatch '^[a-zA-Z0-9_-]+$'){throw 'Invalid efficiency run override'}
    $profileRuns[$profile.name]=$name
}
$statusPath="$root/results/$RunPrefix-status.json"
if(Test-Path -LiteralPath $statusPath){throw 'Run prefix already has status evidence; choose a fresh prefix'}
New-Item -ItemType Directory -Force "$root/results" | Out-Null
$status=@{processId=$PID;started=(Get-Date).ToString('o');status='running';profile=$null;cases=$cases;runDirectories=$profileRuns}
function Save-Status { [IO.File]::WriteAllText($statusPath,($status|ConvertTo-Json),[Text.UTF8Encoding]::new($false)) }
try {
    Save-Status
    if($AfterOptimizationRun) {
        $dependencyPath="$root/results/$AfterOptimizationRun-worker-status.json"
        $dependency=Get-Content -LiteralPath $dependencyPath -Raw|ConvertFrom-Json
        $process=Get-CimInstance Win32_Process -Filter "ProcessId=$($dependency.processId)"
        if($null -ne $process) {
            if($process.CommandLine -notmatch 'run-optimization-worker\.ps1' -or $process.CommandLine -notmatch [regex]::Escape($AfterOptimizationRun)){throw 'Dependency PID belongs to a different command'}
            $handle=Get-Process -Id $dependency.processId -ErrorAction SilentlyContinue
            if($null -ne $handle) {
                $status.status='waiting';$status.waitingFor=$AfterOptimizationRun;Save-Status
                while(-not $handle.WaitForExit(30000)){}
            }
        }
        $dependency=Get-Content -LiteralPath $dependencyPath -Raw|ConvertFrom-Json
        if($dependency.status -ne 'complete'){throw "Optimization dependency ended with status $($dependency.status)"}
        $status.status='running';Save-Status
    }
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
        $runName=$profileRuns[$profile.name]
        if($profile.name -notin $cases) {
            $prior=Get-Content "$root/results/$runName/summary.json" -Raw|ConvertFrom-Json
            $priorImage=Get-Content "$root/results/$runName/test-image.json" -Raw|ConvertFrom-Json
            if($prior.status -ne 'complete' -or $priorImage.id -ne $image.Id){throw "Cannot reuse incomplete or different-image case: $runName"}
            continue
        }
        $status.profile=$profile.name; Save-Status
        $options=@{RunName=$runName;SkipBuild=$true;Vmm=$true;Admission=$true;Segmented=$true;CapacityCheck=$true;Optimizations=$true;
            AgentLoops=$true;AgentConcurrencies=@($profile.concurrencies|ForEach-Object{[int]$_});AgentTurns=[int]$protocol.agentTurns;AgentContextTokens=[int]$protocol.fixed.agentContextTarget;RequestSeed=[int]$protocol.requestSeed;
            PrefillBatchTokens=[int]$profile.batch;DisableMtp=(-not $profile.mtp);LmcacheL1GiB=[double]$protocol.fixed.lmcacheL1GiB;KvCacheBytes=([long]$protocol.fixed.gpuKvGiB*1GB).ToString();ContextTokens=@(32000);
            SkipConcurrency=$true;TestImageOverride=$image.Id;PowerModeNote='Eco Mode and Energy Saver (last user-reported); no mode changes by harness'}
        if ($CollectRejectedReference -and $profile.name -eq 'batch8192-mtp') { $options.CollectRejectedReference=$true }
        if ($null -ne $profile.PSObject.Properties['twoNear262K'] -and $profile.twoNear262K) {
            $options.SkipConcurrency=$false;$options.ParallelRestore=$true;$options.ParallelSessions=2;$options.ParallelContextTokens=261000
        }
        & "$root/run-cache-tests.ps1" @options
        & "$root/summarize-memory.ps1" -RunDirectory "$root/results/$($options.RunName)"
    }
    $runPaths=@($protocol.profiles|ForEach-Object{"$root/results/$($profileRuns[$_.name])"})
    & python "$root/cache-tests/summarize_efficiency.py" @runPaths --protocol $ProtocolPath --output $OutputPath
    if ($LASTEXITCODE -ne 0) { throw 'Efficiency experiment audit failed; inspect efficiency-results.json' }
    $status.status='complete'
} catch { $status.status='failed';$status.error=$_.Exception.Message;throw }
finally { $status.finished=(Get-Date).ToString('o');Save-Status }
