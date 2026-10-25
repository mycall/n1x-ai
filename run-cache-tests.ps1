param(
    [string]$RunName = ('cache-suite-' + (Get-Date -Format yyyyMMdd-HHmmss)),
    [switch]$SkipBuild,
    [switch]$Vmm,
    [switch]$Admission,
    [switch]$Segmented,
    [switch]$CapacityCheck,
    [string]$PowerModeNote = 'Not recorded for this run',
    [switch]$AllowBattery,
    [ValidateRange(0.125,8)][double]$LmcacheL1GiB = 0.5,
    [int[]]$ContextTokens = @(32000,128000,261000),
    [ValidateRange(4096,261000)][int]$ParallelContextTokens = 129000,
    [ValidateRange(1,16)][int]$ParallelSessions = 2,
    [switch]$ParallelRestore,
    [switch]$SkipConcurrency,
    [string]$KvCacheBytes = '4194304000',
    [int]$BlockSize = 2048,
    [ValidateSet('auto','fp8_e4m3')][string]$KvCacheDtype = 'fp8_e4m3'
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($RunName -notmatch '^[a-zA-Z0-9_-]+$') { throw 'Invalid RunName' }
if ($Admission -and -not $Vmm) { throw '-Admission requires -Vmm' }
if ($Segmented -and (-not $Admission -or -not $Vmm)) { throw '-Segmented requires -Vmm -Admission' }
$root = $PSScriptRoot
$out = Join-Path $root "results/$RunName"
if (Test-Path $out) { throw 'RunName already exists; choose a new name. Completed evidence will not be overwritten.' }
$running = @(& wslc list --format json | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json })
if ($running.Count) { throw "Stop current WSLC workloads first: $($running.Names -join ', ')" }
New-Item -ItemType Directory -Force $out | Out-Null
@{externalPower='100 W USB-C supply (user reported; connection state monitored separately)'; msiMode=$PowerModeNote;
    allowBattery=[bool]$AllowBattery; timingUse=$(if ($AllowBattery) { 'Correctness only; battery operation authorized. Not a comparable performance benchmark.' } else { 'Requires external power Online.' });
    note='Windows PowerLineStatus Online indicates external power. It does not measure USB-C negotiated power or system draw.'} |
    ConvertTo-Json | Set-Content "$out/power-condition.json" -Encoding UTF8
$data = Join-Path $root '.build/test-data'
& python (Join-Path $root 'cache-tests/prepare_data.py') $data
if ($LASTEXITCODE -ne 0) { throw 'Pinned dataset preparation failed' }
$fixture = Join-Path $root 'results/vision-fixture.png'
if (-not (Test-Path $fixture)) { throw 'Missing vision fixture; run the existing feature suite once to generate it' }
Copy-Item -LiteralPath $fixture -Destination (Join-Path $data 'vision-fixture.png')
if (-not $SkipBuild) {
    # Build secrets reach pip without persisting proxy settings in the image.
    # The base image is local; no engine proxy restart is needed for this build.
    & wslc build --progress plain --secret 'id=https_proxy,env=HTTPS_PROXY' --secret 'id=http_proxy,env=HTTP_PROXY' -t n1x-ai:lmcache-test -f "$root/cache-tests/Dockerfile" "$root/cache-tests"
    if ($LASTEXITCODE -ne 0) { throw 'Test image build failed' }
    if ($Vmm) {
        & wslc build -t n1x-ai:lmcache-vmm-test -f "$root/cache-tests/Dockerfile.vmm" "$root/cache-tests"
        if ($LASTEXITCODE -ne 0) { throw 'VMM test image build failed' }
        if ($Admission) {
            & wslc build -t n1x-ai:lmcache-admission-test -f "$root/cache-tests/Dockerfile.admission" "$root/cache-tests"
            if ($LASTEXITCODE -ne 0) { throw 'Admission test image build failed' }
            if ($Segmented) {
                & wslc build -t n1x-ai:lmcache-segmented-test -f "$root/cache-tests/Dockerfile.segmented" "$root/cache-tests"
                if ($LASTEXITCODE -ne 0) { throw 'Segmented test image build failed' }
            }
        }
    }
}
$raw = & wslc inspect n1x-qwen38-candidate-16
if ($LASTEXITCODE -ne 0) { throw 'The qualified candidate-16 container configuration is required' }
$old = @(($raw -join "`n") | ConvertFrom-Json)[0]
$utf8 = [Text.UTF8Encoding]::new($false)
$modelArgs=@($old.Config.Cmd)
if ($KvCacheBytes) { $modelArgs[[Array]::IndexOf($modelArgs,'--kv-cache-memory-bytes')+1]=$KvCacheBytes }
$modelArgs[[Array]::IndexOf($modelArgs,'--kv-cache-dtype')+1]=$KvCacheDtype
if ($BlockSize -gt 0) { $modelArgs += @('--block-size',[string]$BlockSize) }
[IO.File]::WriteAllText((Join-Path $out 'run-config.json'), (@{modelArgs=$modelArgs;kvCacheDtype=$KvCacheDtype;useVmm=[bool]$Vmm;allowBattery=[bool]$AllowBattery;
    lmcacheL1GiB=$LmcacheL1GiB; demandAdmission=[bool]$Admission; segmented=[bool]$Segmented; capacityCheck=[bool]$CapacityCheck;
    parallelContextTokens=$ParallelContextTokens; parallelSessions=$ParallelSessions; parallelRestore=[bool]$ParallelRestore;
    lmcacheChunkSize=$(if ($BlockSize -gt 0) { $BlockSize } elseif ($KvCacheDtype -eq 'fp8_e4m3') { 1616 } else { 816 });
    note='Both comparison phases use this same precision and KV capacity. FP8 is experimental; not a BF16 quality-equivalence claim.'} | ConvertTo-Json -Depth 10), $utf8)
$name = 'n1x-' + $RunName
$modelRoot = (Import-PowerShellDataFile "$root/config.psd1").ModelRoot
$arguments = @('run','-d','--name',$name,'--label','n1x-ai.managed=true','--label','n1x-ai.test=true',
    '--gpus','all','--shm-size','1g','--ulimit','memlock=-1:-1',
    '--publish','127.0.0.1:8000:8000',
    '--volume',"${modelRoot}/Qwen3.8-Flash-Next-W4A16-AutoRound-hybrid:/model:ro",
    '--volume','n1x-ple-native:/ple-table-fp8:ro','--volume','n1x-qwen38-cache:/root/.cache',
    '--volume','n1x-lmcache-tests:/lmcache','--volume',"${root}/profiles:/profiles:ro",
    '--volume',"${data}:/data:ro",'--volume',"${out}:/results")
foreach ($environment in $old.Config.Env) { $arguments += @('--env', $environment) }
# Local test-only cache reset API; the published port is restricted to loopback.
$arguments += @('--env','VLLM_SERVER_DEV_MODE=1')
# Disable outbound usage reporting; retain local Prometheus verification metrics.
$arguments += @('--env','LMCACHE_TRACK_USAGE=false','--env','DO_NOT_TRACK=1',
    '--env','VLLM_NO_USAGE_STATS=1','--env','HF_HUB_DISABLE_TELEMETRY=1')
$testImage = if ($Segmented) { 'n1x-ai:lmcache-segmented-test' } elseif ($Admission) { 'n1x-ai:lmcache-admission-test' } elseif ($Vmm) { 'n1x-ai:lmcache-vmm-test' } else { 'n1x-ai:lmcache-test' }
$arguments += @($testImage,'--run-id',$RunName,'--config','/results/run-config.json','--lengths')
$arguments += @($ContextTokens | ForEach-Object { [string]$_ })
if (-not $SkipConcurrency) { $arguments += '--concurrency' }
$stop = Join-Path $out 'host-monitor.stop'
$monitor = Start-Job -ArgumentList $out,$stop -ScriptBlock {
    param($directory,$stopFile)
    Add-Type -AssemblyName System.Windows.Forms
    $utf8 = [Text.UTF8Encoding]::new($false)
    while (-not (Test-Path -LiteralPath $stopFile)) {
        $os = Get-CimInstance Win32_OperatingSystem
        $state = @{timestamp=[DateTimeOffset]::Now.ToString('o'); availableGiB=$os.FreePhysicalMemory/1MB;
            targetGiB=6; minimumGiB=4; powerLineStatus=[string][Windows.Forms.SystemInformation]::PowerStatus.PowerLineStatus}
        $json=$state | ConvertTo-Json -Compress
        $temp=Join-Path $directory 'host-status.tmp'
        $dest=Join-Path $directory 'host-status.json'
        [IO.File]::WriteAllText($temp,$json,$utf8)
        # Replace in place atomically so the container never sees partial JSON.
        if (Test-Path $dest) { [IO.File]::Replace($temp,$dest,(Join-Path $directory 'host-status.previous')) }
        else { [IO.File]::Move($temp,$dest) }
        [IO.File]::AppendAllText((Join-Path $directory 'windows-memory.jsonl'),$json+"`n",$utf8)
        Start-Sleep -Seconds 5
    }
}
$telemetry=$null
try {
    $deadline=(Get-Date).AddSeconds(30)
    while (-not (Test-Path "$out/host-status.json")) {
        if ((Get-Date) -gt $deadline) { throw 'Host monitor did not start' }
        Start-Sleep -Seconds 1
    }
    & wslc @arguments
    if ($LASTEXITCODE -ne 0) { throw 'Test container failed to start' }
    $telemetry=Start-Job -FilePath "$root/capture-memory.ps1" -ArgumentList $name,"$out/memory.jsonl",$stop,5,'http://127.0.0.1:8000',"$root/memory-budget.psd1"
    $lastNotice=[datetime]::MinValue
    do {
        Start-Sleep -Seconds 5
        $raw=& wslc inspect $name
        if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect test container' }
        $current=@(($raw -join "`n") | ConvertFrom-Json)[0]
        if (((Get-Date)-$lastNotice).TotalSeconds -ge 30) {
            Write-Host "$(Get-Date -Format T) $name $($current.State.Status)"
            & wslc logs --tail 2 $name
            $lastNotice=Get-Date
        }
    } while ($current.State.Running)
    $savedPreference=$ErrorActionPreference
    $ErrorActionPreference='Continue'
    & wslc logs $name 2>&1 | ForEach-Object { $_.ToString() } | Set-Content "$out/runner.log" -Encoding UTF8
    $ErrorActionPreference=$savedPreference
    if ($current.State.ExitCode -ne 0) { throw "Suite failed; inspect $out/summary.json and service logs" }
    Get-Content "$out/summary.json" -Raw | ConvertFrom-Json | Select-Object status,wallSeconds,requests
} finally {
    Set-Content -LiteralPath $stop -Value stop
    foreach ($job in @($telemetry,$monitor)) {
        if ($null -ne $job) {
            $null=Wait-Job $job -Timeout 15
            if ($job.State -eq 'Running') { Stop-Job $job }
            Receive-Job $job -ErrorAction Continue
            Remove-Job $job
        }
    }
}
