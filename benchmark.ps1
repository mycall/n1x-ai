#Requires -Version 5.1
param(
    [ValidateSet('all','vllm','aiperf','ruler','scheduler','speculation','agents','restores','soak','recovery','mixed','speed','capacity')][string]$Suite='all',
    [string]$Profile='',
    [string]$PowerMode='Not recorded',
    [ValidateRange(1,16)][int]$SchedulerConcurrency=4,
    [ValidateRange(1,4096)][int]$SchedulerOutputTokens=256,
    [switch]$Build,
    [switch]$Smoke,
    [switch]$AgentThinking,
    [switch]$NoThinking,
    [switch]$LocalClient,
    [string]$Python='python',
    [ValidateRange(1,16)][int[]]$AgentConcurrency=@(),
    [ValidateRange(0,65536)][int]$AgentOutputTokens=0,
    [ValidateRange(1,16)][int]$AgentSessions=4,
    [ValidateRange(1,100)][int]$AgentTurns=3,
    [ValidateRange(0,262144)][int[]]$SpeedDepths=@(0,4096,16384,32768,65536,131072),
    [ValidateRange(1,16)][int[]]$SpeedConcurrency=@(1),
    [ValidateRange(1,100)][int]$SpeedRepeats=3,
    [ValidateRange(128,65536)][int]$SpeedExtensionTokens=2048,
    [ValidateRange(2,8192)][int]$SpeedOutputTokens=256,
    [ValidateSet('incremental','cold','both')][string]$SpeedMode='incremental',
    [ValidateSet('xhigh','medium','low')][string]$SpeedReasoningEffort='xhigh',
    [switch]$SpeedPlanOnly,
    [string[]]$SpeedRuns=@(),
    [string]$ReportOut='',
    [ValidateRange(1,10)][int]$CapacityRepeats=3,
    [ValidateCount(1,3)][ValidateSet(1,6,8)][int[]]$CapacityConcurrency=@(1,6),
    [ValidateRange(128,8192)][int]$CapacityOutputTokens=8192
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if(@($PSBoundParameters.Keys | Where-Object {$_ -like 'Capacity*'}).Count -and $Suite -ne 'capacity'){
    throw 'Capacity controls require -Suite capacity.'
}
if($CapacityConcurrency.Count -ne @($CapacityConcurrency | Sort-Object -Unique).Count){
    throw 'Capacity concurrency points must be unique.'
}
if(@($PSBoundParameters.Keys | Where-Object {$_ -like 'Speed*' -or $_ -eq 'ReportOut'}).Count -and $Suite -ne 'speed'){
    throw 'Speed controls require -Suite speed.'
}
if($SpeedRuns.Count){
    if($Profile -or $Build -or $Smoke -or $LocalClient -or $NoThinking -or $AgentThinking -or
        @($PSBoundParameters.Keys | Where-Object {$_ -like 'Speed*' -and $_ -ne 'SpeedRuns'}).Count){
        throw 'Offline -SpeedRuns compares saved runs; omit live profile/workload controls.'
    }
    if(-not $ReportOut){$ReportOut=Join-Path $PSScriptRoot ('results/benchmarks/speed-comparison-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'-'+[guid]::NewGuid().ToString('N').Substring(0,8))}
    # Deliberately before configuration, partition prompts, WSLC or API access.
    & $Python "$PSScriptRoot/benchmarks/speed_report.py" --out $ReportOut --runs @SpeedRuns
    if($LASTEXITCODE -ne 0){throw 'Offline speed report failed.'}
    return
}
if($ReportOut){throw '-ReportOut requires -SpeedRuns.'}
if($Suite -in @('speed','capacity') -and ($Build -or $Smoke)){throw 'Speed/capacity uses the local Python standard library and an explicit workload; omit -Build and -Smoke.'}
if($NoThinking -and $PSBoundParameters.ContainsKey('SpeedReasoningEffort')){throw '-SpeedReasoningEffort requires thinking enabled; omit -NoThinking.'}
if($AgentThinking -and $NoThinking){throw 'Choose thinking or -NoThinking, not both.'}
if($NoThinking -and $Suite -in @('recovery','mixed','capacity')){throw 'Recovery, mixed and capacity qualification always enable thinking.'}
if($AgentThinking -and $Suite -ne 'agents'){throw '-AgentThinking applies only to -Suite agents.'}
if($Smoke -and $Suite -in @('agents','restores','soak','recovery','mixed')){
    throw 'The agents, restores, soak, recovery, and mixed suites have fixed qualification workloads; omit -Smoke.'
}
. "$PSScriptRoot/scripts/config.ps1"
$config=Get-N1xConfig -Root $PSScriptRoot -Profile $Profile
if($SpeedPlanOnly){
    $planOut=Join-Path $PSScriptRoot ('results/benchmarks/speed-plan-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'-'+[guid]::NewGuid().ToString('N').Substring(0,8))
    $planArgs=@("$PSScriptRoot/benchmarks/speed_probe.py",'--plan-only','--out',$planOut,
        '--profile',$config.Profile,'--context-limit',[string]$config.Context,'--mode',$SpeedMode,
        '--repeats',[string]$SpeedRepeats,'--extension-tokens',[string]$SpeedExtensionTokens,
        '--output-tokens',[string]$SpeedOutputTokens,'--depths')+
        @($SpeedDepths | ForEach-Object {[string]$_})+@('--concurrency')+
        @($SpeedConcurrency | ForEach-Object {[string]$_})
    if($NoThinking){$planArgs+='--no-thinking'}
    else {$planArgs+=@('--reasoning-effort',$SpeedReasoningEffort)}
    & $Python @planArgs
    if($LASTEXITCODE -ne 0){throw 'Speed matrix planning failed.'}
    return
}
. "$PSScriptRoot/scripts/benchmark-partition.ps1"
if(($AgentConcurrency.Count -or $AgentOutputTokens -or $AgentSessions -ne 4 -or $AgentTurns -ne 3) -and $Suite -ne 'agents'){throw 'Agent workload controls require -Suite agents'}
if($AgentOutputTokens -ge $config.Context){throw 'Agent output allowance must leave room for input within the configured context'}
$native=$config.ContainsKey('Backend') -and $config.Backend -eq 'native'
$partitionCheck=$null
if($config.UseLMCache){
    $requiredPartition=if($config.ContainsKey('RequiredPartitionMiB')){$config.RequiredPartitionMiB}else{90112}
    $partitionCheck=Confirm-N1xBenchmarkPartition -Group "LMCache benchmarks ($($config.Profile), $Suite)" -RequiredMiB $requiredPartition
}
if($native -or $LocalClient -or $Suite -in @('speed','capacity')){
    if($Suite -notin @('agents','recovery','mixed','speculation','scheduler','speed','capacity') -or $Build -or $Smoke){throw 'The Windows client supports agents, recovery, mixed, speculation, scheduler, speed and capacity without -Build or -Smoke.'}
    & "$PSScriptRoot/n1x.ps1" wait -Profile $config.Profile -TimeoutSeconds 15
    $stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
    if($Suite -in @('speed','capacity')){$stamp+='-'+[guid]::NewGuid().ToString('N').Substring(0,8)}
    $destination=Join-Path $PSScriptRoot "results/benchmarks/$stamp-$($config.Profile)-$Suite"
    New-Item -ItemType Directory -Force $destination | Out-Null
    $server=if($native){
        . "$PSScriptRoot/scripts/native.ps1"
        $paths=Get-N1xNativePaths $PSScriptRoot $config
        Get-Content -LiteralPath $paths.State -Raw | ConvertFrom-Json
    } else {& wslc inspect $config.Container | Out-String | ConvertFrom-Json}
    $record=@{started=(Get-Date).ToUniversalTime().ToString('o');config=$config;git=(& git -C $PSScriptRoot rev-parse HEAD);
        dirty=([bool](& git -C $PSScriptRoot status --porcelain));powerMode=$PowerMode;
        windowsScheme=(& powercfg /getactivescheme | Out-String).Trim();server=$server;
        gpu=(& nvidia-smi --query-gpu=name,driver_version,memory.total,memory.used --format=csv,noheader | Out-String).Trim();
        gpuQueryFields='name,driver_version,memory.total,memory.used';
        client='Windows Python';clientPython=$Python;lmcacheMetrics=$false;partitionCheck=$partitionCheck;
        models=(Invoke-RestMethod "http://127.0.0.1:$($config.Port)/v1/models" -TimeoutSec 15)}
    $record | ConvertTo-Json -Depth 30 | Set-Content "$destination/host.json" -Encoding UTF8
    $clientArgs=@('--out',"$destination/$Suite",'--url',"http://127.0.0.1:$($config.Port)")
    switch($Suite){
        'agents' {
            $clientArgs=@("$PSScriptRoot/benchmarks/agent_cache_probe.py",'--phase','agents')+$clientArgs+@('--no-lmcache-metrics',
                '--agent-sessions',[string]$AgentSessions,'--agent-turns',[string]$AgentTurns)
            if(-not $NoThinking){$clientArgs+='--agent-thinking'}
            if($AgentConcurrency.Count){$clientArgs+=@('--agent-concurrency')+@($AgentConcurrency | ForEach-Object {[string]$_})}
            if($AgentOutputTokens){$clientArgs+=@('--agent-output-tokens',[string]$AgentOutputTokens)}
        }
        'recovery' {$clientArgs=@("$PSScriptRoot/benchmarks/tool_recovery_probe.py")+$clientArgs+'--no-lmcache-metrics'}
        'mixed' {$clientArgs=@("$PSScriptRoot/benchmarks/mixed_probe.py")+$clientArgs+'--no-lmcache-metrics'}
        'speculation' {
            $clientArgs=@("$PSScriptRoot/benchmarks/speculation_probe.py")+$clientArgs
            if($NoThinking){$clientArgs+='--no-thinking'}
        }
        'scheduler' {
            $clientArgs=@("$PSScriptRoot/benchmarks/scheduler_probe.py")+$clientArgs+@('--concurrency',[string]$SchedulerConcurrency,'--output-tokens',[string]$SchedulerOutputTokens)
            if($NoThinking){$clientArgs+='--no-thinking'}
        }
        'speed' {
            $clientArgs=@("$PSScriptRoot/benchmarks/speed_probe.py")+$clientArgs+@(
                '--profile',$config.Profile,'--context-limit',[string]$config.Context,
                '--host-record',"$destination/host.json",'--mode',$SpeedMode,
                '--repeats',[string]$SpeedRepeats,'--extension-tokens',[string]$SpeedExtensionTokens,
                '--output-tokens',[string]$SpeedOutputTokens,'--depths')+
                @($SpeedDepths | ForEach-Object {[string]$_})+@('--concurrency')+
                @($SpeedConcurrency | ForEach-Object {[string]$_})
            if($NoThinking){$clientArgs+='--no-thinking'}
            else {$clientArgs+=@('--reasoning-effort',$SpeedReasoningEffort)}
        }
        'capacity' {
            $clientArgs=@("$PSScriptRoot/benchmarks/context_capacity_probe.py")+$clientArgs+@(
                '--profile',$config.Profile,'--context-limit',[string]$config.Context,
                '--host-record',"$destination/host.json",'--repeats',[string]$CapacityRepeats,
                '--output-tokens',[string]$CapacityOutputTokens,'--concurrency')+
                @($CapacityConcurrency | ForEach-Object {[string]$_})
        }
    }
    & $Python --version | Set-Content "$destination/client-python.txt"
    if($LASTEXITCODE -ne 0){throw 'Cannot run benchmark Python'}
    $clientArgs | ConvertTo-Json | Set-Content "$destination/client-arguments.json" -Encoding UTF8
    Write-Host "Results: $destination"
    & $Python @clientArgs
    if($LASTEXITCODE -ne 0){throw "Benchmark failed; inspect $destination"}
    Write-Host "Completed. Raw results: $destination"
    return
}
if(-not $Smoke -and $Suite -in @('all','ruler') -and $config.Context -lt 262144){
    throw 'The full RULER sweep needs a 262144-token profile. Use -Profile qwen38fn-cache-mtp, or -Smoke for a small check.'
}
$model=Join-Path $config.ModelRoot 'Qwen3.8-Flash-Next-W4A16-AutoRound-hybrid'
if(-not(Test-Path -LiteralPath "$model/tokenizer_config.json")){throw "Tokenizer not found at $model"}
if($Build){
    . "$PSScriptRoot/scripts/proxy.ps1"
    Update-N1xProxyEnvironment
    $resetSession=Sync-N1xWslcProxy
    try {
    $buildArgs=@('build')+@(Get-N1xProxyBuildArguments)+@('--progress','plain','-t','n1x-ai:benchmarks')
    foreach($entry in @(@('https_proxy','HTTPS_PROXY'),@('http_proxy','HTTP_PROXY'))){
        if([Environment]::GetEnvironmentVariable($entry[1])){$buildArgs+=@('--secret',"id=$($entry[0]),env=$($entry[1])")}
    }
    $buildArgs+="$PSScriptRoot/benchmarks"
    & wslc @buildArgs
    if($LASTEXITCODE -ne 0){throw 'Benchmark image build failed'}
    } finally {
        if($resetSession){
            & wslc system session terminate
            if($LASTEXITCODE -ne 0){Write-Warning 'Reset the idle WSLC session before serving: wslc system session terminate'}
        }
    }
}
$health=Invoke-WebRequest "http://127.0.0.1:$($config.Port)/health" -UseBasicParsing -TimeoutSec 15
if($health.StatusCode -ne 200){throw 'Start the model service before benchmarking'}
$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$destination=Join-Path $PSScriptRoot "results/benchmarks/$stamp-$Suite"
New-Item -ItemType Directory -Force $destination | Out-Null
$os=Get-CimInstance Win32_OperatingSystem
Add-Type -AssemblyName System.Windows.Forms
$power=[System.Windows.Forms.SystemInformation]::PowerStatus
$record=@{
    started=(Get-Date).ToUniversalTime().ToString('o'); powerMode=$PowerMode
    windowsScheme=(& powercfg /getactivescheme | Out-String).Trim()
    availableGiB=[math]::Round($os.FreePhysicalMemory/1MB,2)
    config=$config; git=(& git -C $PSScriptRoot rev-parse HEAD)
    partitionCheck=$partitionCheck
    battery=@(Get-CimInstance Win32_Battery | Select-Object BatteryStatus,EstimatedChargeRemaining)
    powerSource=$power.PowerLineStatus.ToString()
    server=(& wslc inspect $config.Container | Out-String | ConvertFrom-Json)
    clientImage=(& wslc image inspect n1x-ai:benchmarks | Out-String | ConvertFrom-Json)
}
$record | ConvertTo-Json -Depth 30 | Set-Content "$destination/host.json" -Encoding UTF8
$runArgs=@('run','--rm','--name','n1x-benchmark-client','--network',"container:$($config.Container)",
    '-v',"${model}:/model:ro",'-v',"${destination}:/results",'n1x-ai:benchmarks','--suite',$Suite)
if($Suite -eq 'scheduler'){$runArgs+=@('--scheduler-concurrency',[string]$SchedulerConcurrency,
    '--scheduler-output-tokens',[string]$SchedulerOutputTokens)}
if($AgentThinking){$runArgs+='--agent-thinking'}
if($AgentConcurrency.Count){$runArgs+=@('--agent-concurrency')+@($AgentConcurrency | ForEach-Object {[string]$_})}
if($AgentOutputTokens){$runArgs+=@('--agent-output-tokens',[string]$AgentOutputTokens)}
if($AgentSessions -ne 4){$runArgs+=@('--agent-sessions',[string]$AgentSessions)}
if($AgentTurns -ne 3){$runArgs+=@('--agent-turns',[string]$AgentTurns)}
if($NoThinking){$runArgs+='--no-thinking'}
if($Smoke){$runArgs+=@('--concurrency','1','--input-lengths','512','--requests','2','--output-tokens','16',
    '--agent-concurrency','1','--conversations','1','--context-lengths','4096','--samples','1')}
Write-Host "Results: $destination"
& wslc @runArgs
if($LASTEXITCODE -ne 0){throw "Benchmark failed; inspect $destination"}
Write-Host "Completed. Raw results: $destination"
