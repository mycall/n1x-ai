param(
    [ValidateSet('help', 'list', 'setup', 'build', 'clean', 'uninstall', 'start', 'stop', 'restart', 'recreate', 'status', 'wait', 'logs', 'test', 'doctor')]
    [string]$Action = 'status',
    [string]$Profile = '',
    [string]$ModelRoot = '',
    [int]$Port = 0,
    [ValidateSet('smoke', 'features', 'context', 'all')]
    [string]$Suite = 'smoke',
    [ValidateRange(1, 86400)]
    [int]$TimeoutSeconds = 3600,
    [switch]$PrintOnly,
    [switch]$DenyFirewall,
    [switch]$SkipDownload,
    [switch]$SkipBuild,
    [switch]$SkipPleCopy,
    [switch]$Rebuild,
    [switch]$LmcacheFromSource,
    [string]$ImageTag = '',
    [string]$VhdPath = ''
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. "$PSScriptRoot/scripts/config.ps1"
function Update-LanAccess([switch]$Remove) {
    if($PrintOnly){return}
    . "$PSScriptRoot/scripts/firewall.ps1"
    Set-N1xFirewall -Root $PSScriptRoot -Port $config.Port -Remove:($Remove -or $DenyFirewall -or -not $config.LanAccess)
}
function Update-ClientRegistrations([switch]$Remove) {
    if($PrintOnly -or $env:N1X_CLIENT_CONFIG -eq 'off'){return}
    try {
        . "$PSScriptRoot/scripts/clients.ps1"
        Sync-N1xClients -Root $PSScriptRoot -Port $config.Port -Context $config.Context -MaxOutputTokens $config.MaxOutputTokens -Remove:$Remove
    } catch {Write-Warning "Client registration failed: $($_.Exception.Message)"}
}
if($Action -eq 'help'){
    @"
n1x.ps1 - manage the n1x-ai local model server

Actions:
  help        Show this help
  list profiles  List available profiles and the configured default
  setup       Install prerequisites, download models, build image (with LMCache)
  build       Build the selected container runtime (MyLLMBox creates a candidate)
  start       Start the selected container or native Windows profile
  stop        Stop the container and remove client/firewall registrations
  restart     Restart the running container with its existing configuration
  recreate    Remove and re-create the container to apply configuration changes
  status      Show container state and API readiness
  wait        Block until the API reports ready (default timeout 3600s)
  logs        Show the last 100 lines of container logs
  test        Run smoke checks, or -Suite features|context|all for full suites
  doctor      Show WSLC info, images, GPU state, and model root
  clean       Delete caches and volumes (optionally compact a VHD: -VhdPath)
  uninstall   Clean up everything this project created

Common options:
  -Profile <name>      Serving profile (see list profiles; default: configured DefaultProfile)
  -Port <n>            Override the configured API port
  -ModelRoot <path>    Override the configured model root
  -PrintOnly           Preview what would run without changing anything
  -TimeoutSeconds <n>  For wait
  -Rebuild             For MyLLMBox build: bypass image layer cache
  -LmcacheFromSource   For MyLLMBox build: compile LMCache against the guest stack
  -ImageTag <tag>      Candidate output tag for MyLLMBox build

Examples:
  .\n1x.ps1 list profiles
  .\n1x.ps1 start
  .\n1x.ps1 status -Profile qwen38fn-mtp
  .\n1x.ps1 wait -TimeoutSeconds 600
  .\n1x.ps1 start -PrintOnly
"@
    return
}
if($Action -eq 'list'){
    # For list, the second positional argument selects the resource to list.
    if($Profile -ne 'profiles'){throw 'Usage: .\n1x.ps1 list profiles'}
    Get-N1xProfileList -Root $PSScriptRoot | Format-Table -AutoSize
    return
}
if($Action -ne 'build' -and ($LmcacheFromSource -or $ImageTag)){
    throw '-LmcacheFromSource and -ImageTag are build options'
}
if($Action -eq 'build'){
    $buildConfig=Get-N1xConfig -Root $PSScriptRoot -Profile $Profile -ModelRoot $ModelRoot -Port $Port
    if($buildConfig.ContainsKey('Backend') -and $buildConfig.Backend -eq 'native'){
        throw 'Native runtime builds belong to the separate RTX Spark installation; see wiki/Native-vLLM.md'
    }
    if($buildConfig.ContainsKey('Backend') -and $buildConfig.Backend -eq 'wslc-myllmbox'){
        $options=@{Myllmbox=$true;Rebuild=$Rebuild;LmcacheFromSource=$LmcacheFromSource;PrintOnly=$PrintOnly}
        if($ImageTag){$options.ImageTag=$ImageTag}
        & "$PSScriptRoot/build.ps1" @options
    }else{
        if($Rebuild -or $LmcacheFromSource -or $ImageTag){throw 'These candidate rebuild options require a MyLLMBox profile'}
        & "$PSScriptRoot/build.ps1" -WithLMCache:$buildConfig.UseLMCache -PrintOnly:$PrintOnly
    }
    return
}
if($Action -eq 'setup'){
    $config=@{}
    if(Test-Path -LiteralPath "$PSScriptRoot/config.psd1"){
        $config=Get-N1xConfig -Root $PSScriptRoot -Profile $Profile -ModelRoot $ModelRoot -Port $Port
        if($config.ContainsKey('Backend') -and $config.Backend -eq 'native'){
            . "$PSScriptRoot/scripts/native.ps1"
            $paths=Get-N1xNativePaths $PSScriptRoot $config
            if($PrintOnly){Write-Output "Validate existing native installation at $($paths.Runtime) and model at $($paths.Model); see wiki/Native-vLLM.md";return}
            Assert-N1xNativeInstallation $paths
            return
        }
    }
    if($config.ContainsKey('Backend') -and $config.Backend -eq 'wslc-myllmbox'){
        . "$PSScriptRoot/scripts/myllmbox.ps1"
        if($PrintOnly){Write-Output 'Validate MyLLMBox weights, prepared PLE and partition; restore a missing image tag or build and select a missing runtime; create the configured LMCache volume if missing. See wiki/MyLLMBox.md';return}
        New-Item -ItemType Directory -Force "$PSScriptRoot/.state"|Out-Null
        try {$setupLock=[IO.File]::Open("$PSScriptRoot/.state/native-lifecycle.lock",[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)}
        catch {throw 'Another serving lifecycle or qualification command is in progress; retry after it finishes.'}
        try {Assert-N1xMyllmboxInstallation $PSScriptRoot $config -PrepareCache -PrepareRuntime}
        finally {$setupLock.Dispose()}
        return
    }
    if($PrintOnly){Write-Output '.\setup.ps1 -WithLMCache -ModelRoot <configured ModelRoot or ~/Models>'; return}
    & "$PSScriptRoot/setup.ps1" -WithLMCache -ModelRoot $ModelRoot -SkipDownload:$SkipDownload -SkipBuild:$SkipBuild -SkipPleCopy:$SkipPleCopy -Rebuild:$Rebuild
    return
}
$config = Get-N1xConfig -Root $PSScriptRoot -Profile $Profile -ModelRoot $ModelRoot -Port $Port
$native=$config.ContainsKey('Backend') -and $config.Backend -eq 'native'
$myllmbox=$config.ContainsKey('Backend') -and $config.Backend -eq 'wslc-myllmbox'
$requiresHostMonitor=$config.UseLMCache -or $myllmbox
if($myllmbox){
    . "$PSScriptRoot/scripts/myllmbox.ps1"
    $myllmboxPaths=Get-N1xMyllmboxPaths $PSScriptRoot $config
    $config['MyllmboxRecipeHash']=(Get-FileHash -LiteralPath $myllmboxPaths.Recipe).Hash
    $config['MyllmboxEnvironmentHash']=(Get-FileHash -LiteralPath $myllmboxPaths.Environment).Hash
}

if(Test-Path -LiteralPath "$PSScriptRoot/scripts/native.ps1"){
    . "$PSScriptRoot/scripts/native.ps1"
    # Cleanup must not delete the identity of a running native process.
    if($Action -in @('clean','uninstall') -and -not $PrintOnly){Assert-N1xNoNativeProfile $PSScriptRoot}
}
if($native -and $Action -in @('clean','uninstall')){
    throw 'Native dependencies and caches are externally managed. Use stop for this profile; see wiki/Native-vLLM.md.'
}
if($Action -in @('clean','uninstall')){
    if(-not $VhdPath){
        . "$PSScriptRoot/scripts/resources.ps1"
        Invoke-N1xResourceCleanup -Root $PSScriptRoot -Uninstall:($Action -eq 'uninstall') -PrintOnly:$PrintOnly
        Update-ClientRegistrations -Remove
        Update-LanAccess -Remove
    } elseif($Action -eq 'uninstall'){throw 'Use clean -VhdPath for offline compaction after uninstall'}
    & "$PSScriptRoot/scripts/clean.ps1" -Root $PSScriptRoot -ModelRoot $config.ModelRoot -PrintOnly:$PrintOnly -VhdPath $VhdPath
    return
}
$Profile=$config.Profile
function Get-ConfigFingerprint([string]$LegacyDefault='') {
    $canonical=[ordered]@{}
    $canonical['__ServedModelName']='qwen/qwen38fn-best'
    foreach($key in ($config.Keys|Sort-Object)){
        # K3 was implicit before DFlashTokens existed; its launch is unchanged.
        if($key -eq 'DFlashTokens' -and $config[$key] -eq 3){continue}
        if($key -eq 'DefaultProfile'){
            if($LegacyDefault){$canonical[$key]=$LegacyDefault}
        } else {$canonical[$key]=$config[$key]}
    }
    if($myllmbox){
        foreach($setting in @('MyllmboxConfig','MyllmboxEnvironment')){
            $file=Join-Path $PSScriptRoot $config[$setting]
            $canonical['__'+$setting+'Sha256']=if(Test-Path -LiteralPath $file -PathType Leaf){(Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()}else{'missing'}
        }
    }
    $sha=[Security.Cryptography.SHA256]::Create()
    try {return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes(($canonical|ConvertTo-Json -Compress))))).Replace('-','').ToLowerInvariant()}
    finally {$sha.Dispose()}
}
$fingerprint=Get-ConfigFingerprint
$name = $config.Container
$endpoint = "http://127.0.0.1:$($config.Port)"

if($native){
    $paths=Get-N1xNativePaths $PSScriptRoot $config
    if($PrintOnly -and $Action -notin @('start','stop','restart','recreate')){
        Write-Output "Native $Action for $Profile at $endpoint (state: $($paths.State))"
        return
    }
    if($Action -in @('wait','test') -and (Get-N1xNativeProcess $paths.State)){
        $saved=Get-Content -LiteralPath $paths.State -Raw | ConvertFrom-Json
        if($saved.fingerprint -ne $fingerprint -or $saved.recipeHash -ne (Get-FileHash -LiteralPath $paths.Recipe).Hash){
            throw 'Native settings differ from the running server. Use recreate before qualification.'
        }
    }
    $nativeLock=$null
    if(-not $PrintOnly -and $Action -in @('start','stop','restart','recreate')){
        New-Item -ItemType Directory -Force "$PSScriptRoot/.state" | Out-Null
        try {$nativeLock=[IO.File]::Open("$PSScriptRoot/.state/native-lifecycle.lock",[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)}
        catch {throw 'Another native lifecycle command is in progress; retry after it finishes.'}
    }
    try { switch($Action){
        {$_ -in @('start','restart','recreate')} {
            if($Action -in @('restart','recreate')){
                if($Action -eq 'restart' -and -not $PrintOnly -and (Get-N1xNativeProcess $paths.State)){
                    $saved=Get-Content -LiteralPath $paths.State -Raw | ConvertFrom-Json
                    if($saved.fingerprint -ne $fingerprint -or $saved.recipeHash -ne (Get-FileHash -LiteralPath $paths.Recipe).Hash){throw 'Native settings differ. Use recreate to apply changes.'}
                }
                Stop-N1xNative $PSScriptRoot $config -PrintOnly:$PrintOnly
            }
            Start-N1xNative $PSScriptRoot $config $fingerprint -PrintOnly:$PrintOnly
            Update-ClientRegistrations
            Update-LanAccess
            return
        }
        'stop' {
            Stop-N1xNative $PSScriptRoot $config -PrintOnly:$PrintOnly
            Update-ClientRegistrations -Remove
            Update-LanAccess -Remove
            return
        }
        'wait' {Wait-N1xNative $PSScriptRoot $config $TimeoutSeconds;return}
        'logs' {
            foreach($log in @($paths.Stdout,$paths.Stderr)){
                if(Test-Path -LiteralPath $log){Write-Host $log;Get-Content -LiteralPath $log -Tail 100}
            }
            return
        }
        'status' {
            $process=Get-N1xNativeProcess $paths.State
            if(-not $process){Write-Host "Selected profile '$Profile' is stopped or has not been created.";return}
            $saved=Get-Content -LiteralPath $paths.State -Raw | ConvertFrom-Json
            $endpoint="http://127.0.0.1:$($saved.port)"
            Write-Host "$Profile is running (PID $($process.ProcessId))."
            try {
                Invoke-WebRequest "$endpoint/health" -UseBasicParsing -TimeoutSec 5 | Out-Null
                (Invoke-RestMethod "$endpoint/v1/models" -TimeoutSec 5).data | Select-Object id,max_model_len
            } catch {Write-Host "API not ready: $($_.Exception.Message)"}
            return
        }
        'doctor' {Assert-N1xNativeInstallation $paths; & nvidia-smi;return}
        # The shared test action below uses the qwen/qwen38fn-best alias on both backends.
    }} finally {if($null -ne $nativeLock){$nativeLock.Dispose()}}
}

$containerLock=$null
try {
if($myllmbox -and -not $PrintOnly -and $Action -in @('start','stop','restart','recreate')){
    New-Item -ItemType Directory -Force "$PSScriptRoot/.state"|Out-Null
    try {$containerLock=[IO.File]::Open("$PSScriptRoot/.state/native-lifecycle.lock",[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)}
    catch {throw 'Another serving lifecycle or qualification command is in progress; retry after it finishes.'}
    if($Action -in @('start','restart','recreate')){
        $prepare=$Action -in @('start','recreate')
        Assert-N1xMyllmboxInstallation $PSScriptRoot $config -PrepareCache:$prepare -PrepareRuntime:$prepare
        $fingerprint=Get-ConfigFingerprint
    }
}

function Invoke-Wslc([string[]]$Arguments) {
    & wslc @Arguments
    if ($LASTEXITCODE -ne 0) { throw "wslc failed ($LASTEXITCODE): $($Arguments -join ' ')" }
}

function Get-ManagedContainer {
    $rows = & wslc list --all --filter "name=$name" --format json
    if ($LASTEXITCODE -ne 0) { throw 'Cannot list WSLC containers' }
    # WSLC's name filter also matches profile suffixes; require an exact name.
    $matches = @($rows | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json } | Where-Object { $_.Names -eq $name })
    if (-not $matches.Count) { return $null }
    $raw = & wslc inspect $name
    if ($LASTEXITCODE -ne 0) { throw "Cannot inspect $name" }
    $container = @(($raw -join "`n") | ConvertFrom-Json)[0]
    if ($container.Config.Labels.'n1x-ai.managed' -ne 'true') {
        throw "Container $name is not managed by n1x-ai; refusing to change it"
    }
    return $container
}

function Assert-NoOtherProfile {
    if(Get-Command Assert-N1xNoNativeProfile -ErrorAction SilentlyContinue){Assert-N1xNoNativeProfile $PSScriptRoot}
    $rows = & wslc list --filter 'label=n1x-ai.managed=true' --format json
    if ($LASTEXITCODE -ne 0) { throw 'Cannot check running project containers' }
    $others = @($rows | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json } | Where-Object { $_.Names -ne $name })
    if ($others.Count) {
        throw "Another project profile is running: $($others.Names -join ', '). Stop it before starting $name."
    }
}

function Assert-ProfileRunning {
    if($native){
        if(-not(Get-N1xNativeProcess $paths.State)){throw "Selected native profile '$Profile' is not running."}
        Invoke-WebRequest "$endpoint/health" -UseBasicParsing -TimeoutSec 15 | Out-Null
        return
    }
    $container = Get-ManagedContainer
    if (-not $container -or -not $container.State.Running) {
        throw "Selected profile '$Profile' is not running. Start it or select the active profile."
    }
    if($myllmbox){Assert-Configuration $container}
}

function Assert-Configuration($Container) {
    $property=$Container.Config.Labels.PSObject.Properties['n1x-ai.config-sha']
    if($null -ne $property){
        if($property.Value -eq $fingerprint){return}
        # Older labels included the default selection, which does not affect an
        # already selected profile. All actual settings must still match.
        $legacyDefaults=@('qwen38fn-baseline',$config.DefaultProfile)+@(Get-ChildItem "$PSScriptRoot/profiles" -Filter '*.psd1' -File | ForEach-Object BaseName)
        foreach($legacyDefault in ($legacyDefaults|Select-Object -Unique)){
            if($property.Value -eq (Get-ConfigFingerprint -LegacyDefault $legacyDefault)){return}
        }
    }
    throw "Container settings differ. Run .\n1x.ps1 recreate -Profile $Profile to apply your configuration."
}

function Write-Headroom {
    $directory=Join-Path $PSScriptRoot ".state/$name"
    New-Item -ItemType Directory -Force $directory|Out-Null
    $os=Get-CimInstance Win32_OperatingSystem
    $data=@{availableGiB=$os.FreePhysicalMemory/1MB;availableCommitGiB=$os.FreeVirtualMemory/1MB;updatedUnixSeconds=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()}
    if($data.availableGiB -lt $config.WindowsMinimumGiB){throw 'Insufficient Windows memory headroom'}
    if($data.availableCommitGiB -lt $config.WindowsMinimumGiB){throw 'Insufficient Windows commit headroom'}
    [IO.File]::WriteAllText((Join-Path $directory 'host.json'),($data|ConvertTo-Json),[Text.UTF8Encoding]::new($false))
}

function Start-MemoryMonitor {
    if($myllmbox){Start-N1xMyllmboxMonitor $PSScriptRoot $config;return}
    $directory=Join-Path $PSScriptRoot ".state/$name"
    $pidPath=Join-Path $directory 'monitor.json'
    if(Test-Path -LiteralPath $pidPath){
        $saved=Get-Content -LiteralPath $pidPath -Raw|ConvertFrom-Json
        $process=Get-CimInstance Win32_Process -Filter "ProcessId=$($saved.processId)"
        if($null -ne $process -and $process.CommandLine -match 'monitor-memory.ps1' -and $process.CommandLine -match [regex]::Escape($name)){return}
    }
    $arguments=@('-NoProfile','-ExecutionPolicy','Bypass','-File',('"'+"$PSScriptRoot/scripts/monitor-memory.ps1"+'"'),'-Container',$name,'-OutputPath',('"'+(Join-Path $directory 'host.json')+'"'))
    $process=Start-Process powershell.exe -WindowStyle Hidden -ArgumentList $arguments -PassThru
    [IO.File]::WriteAllText($pidPath,(@{processId=$process.Id}|ConvertTo-Json),[Text.UTF8Encoding]::new($false))
}

if($Action -eq 'recreate'){
    if($PrintOnly){throw 'Use start -PrintOnly to preview the new configuration'}
    Assert-NoOtherProfile
    $old=Get-ManagedContainer
    if($old){if($old.State.Running){Invoke-Wslc @('stop',$name)};Invoke-Wslc @('rm',$name)}
    $Action='start'
}

switch ($Action) {
    'start' {
        if (-not $PrintOnly) {
            Assert-NoOtherProfile
            $existing = Get-ManagedContainer
            if ($existing) {
                Assert-Configuration $existing
                if ($config.UseLMCache -and -not $existing.State.Running -and $existing.State.ExitCode -ne 0) {
                    Write-Host "Recreating $name after an unsuccessful exit; named volumes are preserved."
                    Invoke-Wslc @('rm', $name)
                } else {
                    if($requiresHostMonitor){Write-Headroom; Start-MemoryMonitor}
                    if ($existing.State.Running) { Write-Host "$name is already running. Check status for API readiness." }
                    else { Invoke-Wslc @('start', $name); Write-Host "Starting $name with its existing configuration." }
                    if($requiresHostMonitor){Start-MemoryMonitor}
                    Update-ClientRegistrations
                    Update-LanAccess
                    return
                }
            }
        }
        if($myllmbox){
            $run=Get-N1xMyllmboxArguments $PSScriptRoot $config $fingerprint
            if($PrintOnly){Write-Output ('wslc '+(($run|ForEach-Object {"'"+$_.Replace("'","''")+"'"}) -join ' '));return}
            if($config.DFlashTokens -gt 4){Assert-N1xMyllmboxInstallation $PSScriptRoot $config}
            Write-Headroom
            Start-MemoryMonitor
            Invoke-Wslc $run
            Start-MemoryMonitor
            Update-ClientRegistrations
            Update-LanAccess
            Write-Host "Loading MyLLMBox. Check .\n1x.ps1 status -Profile $Profile. API: $endpoint/v1"
            return
        }
        $model = Join-Path $config.ModelRoot 'Qwen3.8-Flash-Next-W4A16-AutoRound-hybrid'
        $table = Join-Path $config.ModelRoot 'ple-table-fp8'
        if($config.DFlash -and $config.Mtp){throw 'Select either MTP or DFlash, not both'}
        $drafter = Join-Path $config.ModelRoot 'Qwen3.8-Flash-Next-DFlash2'
        if($config.DFlash -and -not $PrintOnly -and -not(Test-Path "$drafter/model.safetensors")){
            throw 'Run .\n1x.ps1 setup to prepare the DFlash2 checkpoint'
        }
        if(-not $PrintOnly){
        foreach ($file in @("$model/config.json", "$model/model.safetensors.index.json")) {
            if (-not (Test-Path -LiteralPath $file)) { throw "Missing model file: $file" }
        }
        $index = Get-Content "$model/model.safetensors.index.json" -Raw | ConvertFrom-Json
        foreach ($shard in ($index.weight_map.PSObject.Properties.Value | Sort-Object -Unique)) {
            if (-not (Test-Path -LiteralPath (Join-Path $model $shard))) { throw "Missing model shard: $shard" }
        }
        }
        $tableMount=$table
        if(-not $PrintOnly){
            & wslc image inspect $config.Image | Out-Null
            if($LASTEXITCODE -ne 0){throw "Local image '$($config.Image)' is unavailable in this WSLC session. Run .\n1x.ps1 setup from the same non-elevated PowerShell used for serving. Elevated terminals can use a separate WSLC session."}
        }
        if ($config.ContainsKey('PleVolume')) {
            $tableMount=$config.PleVolume
            if (-not $PrintOnly) {
                $manifestRaw=& wslc run --rm --entrypoint cat --volume "${tableMount}:/table:ro" $config.Image /table/n1x-copy-manifest.json
                if ($LASTEXITCODE -ne 0) { throw 'Prepare the native PLE volume with prepare-native-ple.ps1 first' }
                $manifest=($manifestRaw -join "`n") | ConvertFrom-Json
                if ($manifest.sourceRevision -ne '50511b0a41aa1d34b8beb7e5d4bb06a0b650dc14') { throw 'Unexpected native PLE revision' }
                if(-not @($manifest.files).Count){throw 'Native PLE volume is empty'}
            }
        }
        $run = @(
            'run', '-d', '--name', $name, '--label', 'n1x-ai.managed=true',
            '--label',"n1x-ai.config-sha=$fingerprint",'--label',"n1x-ai.profile=$Profile",
            '--gpus', 'all', '--shm-size', '1g', '--ulimit', 'memlock=-1:-1',
            '--publish', "$(if($config.LanAccess){'0.0.0.0'}else{'127.0.0.1'}):$($config.Port):8000",
            '--volume', "${model}:/model:ro", '--volume', "${tableMount}:/ple-table-fp8:ro",
            '--volume', "$($config.CacheVolume):/root/.cache",
            '--env', 'HF_HUB_OFFLINE=1', '--env', 'TOKENIZERS_PARALLELISM=false',
            '--env', 'MAX_JOBS=1', '--env', 'FLASHINFER_NVCC_THREADS=1',
            '--env', 'TORCHINDUCTOR_COMPILE_THREADS=1',
            '--env', 'VLLM_PLE_MMAP_DIR=/ple-table-fp8', '--env', 'VLLM_PLE_MMAP_PREWARM=0',
            '--env', "VLLM_PLE_MMAP_WORKERS=$($config.PleWorkers)", '--env', 'VLLM_PLE_MMAP_CHUNK=2048',
            '--env', 'VLLM_FP8_HYBRID=1', '--env', 'VLLM_MARLIN_USE_ATOMIC_ADD=1',
            '--env', 'VLLM_USE_DEEP_GEMM=0', '--env', 'VLLM_USE_FLASHINFER_SAMPLER=1',
            '--env','LMCACHE_TRACK_USAGE=false','--env','DO_NOT_TRACK=1','--env','VLLM_NO_USAGE_STATS=1','--env','HF_HUB_DISABLE_TELEMETRY=1',
            '--volume', "${PSScriptRoot}/profiles:/profiles:ro"
        )
        if($config.DFlash){$run+=@('--volume',"${drafter}:/drafter:ro")}
        if($config.ContainsKey('IndexerFP8') -and $config.IndexerFP8){$run+=@('--env','VLLM_INDEXER_FP8=1')}
        if($config.UseLMCache){
            $stateDirectory=Join-Path $PSScriptRoot ".state/$name"
            if(-not $PrintOnly){Write-Headroom}
            $namespace=if($config.Mtp){'qwen-8b82-v032-lmc056-fp8-mtp'}else{'qwen-8b82-v032-lmc056-fp8'}
            if($config.DFlash){$namespace='qwen-8b82-v032-lmc056-fp8-dflash-a22a'}
            if($config.ContainsKey('IndexerFP8') -and $config.IndexerFP8){$namespace+='-idxfp8'}
            if($config.CacheBlockTokens -ne 2048 -or $config.LmcacheChunkTokens -ne 2048){
                $namespace+="-b$($config.CacheBlockTokens)-c$($config.LmcacheChunkTokens)"
            }
            $run+=@('--volume',"${stateDirectory}:/state:ro",'--volume',"$($config.LmcacheVolume):/lmcache",
                '--env',"N1X_CACHE_NAMESPACE=$namespace",'--env',"N1X_LMCACHE_L1_GIB=$($config.LmcacheL1GiB)",
                '--env',"N1X_LMCACHE_L2_GIB=$($config.LmcacheL2GiB)",
                '--env',"N1X_CACHE_BLOCK_TOKENS=$($config.CacheBlockTokens)",'--env',"N1X_LMCACHE_CHUNK_TOKENS=$($config.LmcacheChunkTokens)",
                '--env',"N1X_RESTORE_WAIT_MS=$($config.RestoreWaitMs)",'--env',"N1X_WINDOWS_MINIMUM_GIB=$($config.WindowsMinimumGiB)")
        }
        $run+=@($config.Image,
            '--model', '/model', '--served-model-name', 'qwen/qwen38fn-best', '--host', '0.0.0.0', '--port', '8000',
            '--max-model-len', [string]$config.Context, '--max-num-seqs', [string]$config.MaxSequences,
            '--override-generation-config', (@{max_new_tokens=$config.MaxOutputTokens}|ConvertTo-Json -Compress),
            '--gpu-memory-utilization', '0.01', '--kv-cache-memory-bytes', $config.KvCacheBytes,
            '--load-format', 'safetensors', '--safetensors-load-strategy', 'lazy',
            '--enable-prefix-caching', '--enable-chunked-prefill',
            '--max-num-batched-tokens', [string]$config.BatchedTokens,
            '--mamba-ssm-cache-dtype', 'bfloat16', '--kv-cache-dtype', $config.KvCacheDtype,
            '--no-enable-flashinfer-autotune',
            '--enable-auto-tool-choice', '--tool-call-parser', 'qwen3_xml', '--reasoning-parser', 'qwen3'
        )
        if ($config.ContainsKey('CudaGraphMode')) { $run += "-cc.cudagraph_mode=$($config.CudaGraphMode)" }
        else { $run += '--enforce-eager' }
        if ($config.Mtp) { $run += @('--config', '/profiles/qwen38fn-mtp.yaml') }
        if ($config.DFlash) { $run += @('--config', '/profiles/qwen38fn-dflash.yaml', '--kv-cache-dtype-skip-layers', 'sliding_window') }
        if ($PrintOnly) { Write-Output ('wslc ' + (($run | ForEach-Object { '"' + $_ + '"' }) -join ' ')); return }
        # WSLC refuses a name collision if another process created it meanwhile.
        if($requiresHostMonitor){Start-MemoryMonitor}
        Invoke-Wslc $run
        if($requiresHostMonitor){Start-MemoryMonitor}
        Update-ClientRegistrations
        Update-LanAccess
        Write-Host "Loading model. Check .\n1x.ps1 status -Profile $Profile and .\n1x.ps1 logs -Profile $Profile. API: $endpoint/v1"
    }
    'stop' {
        try { if (Get-ManagedContainer) { Invoke-Wslc @('stop', $name) }; Update-ClientRegistrations -Remove }
        finally { Update-LanAccess -Remove }
    }
    'restart' {
        Assert-NoOtherProfile
        $old=Get-ManagedContainer
        if(-not $old){throw "No managed container $name"}
        Assert-Configuration $old
        if($config.UseLMCache -and -not $old.State.Running -and $old.State.ExitCode -ne 0){
            & $PSCommandPath start -Profile $Profile -ModelRoot $config.ModelRoot -Port $config.Port -DenyFirewall:$DenyFirewall
        } else {
            if($requiresHostMonitor){Write-Headroom; Start-MemoryMonitor}
            Invoke-Wslc @('restart', $name)
            if($requiresHostMonitor){Start-MemoryMonitor}
            Update-ClientRegistrations
            Update-LanAccess
        }
    }
    'logs' { Invoke-Wslc @('logs', '--tail', '100', $name) }
    'wait' {
        $selected=Get-ManagedContainer
        if(-not $selected){throw "Container '$name' does not exist in this WSLC session. Run .\n1x.ps1 start successfully before wait; use the same non-elevated terminal."}
        Assert-Configuration $selected
        $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
        $lastNotice = [datetime]::MinValue
        Write-Host "Waiting up to $TimeoutSeconds seconds for $Profile at $endpoint ..."
        while ((Get-Date) -lt $deadline) {
            # A WSLC transport timeout does not mean the container has stopped.
            $raw = & wslc inspect $name
            if ($LASTEXITCODE -eq 0) {
                $selected = @(($raw -join "`n") | ConvertFrom-Json)[0]
                if (-not $selected.State.Running) { throw "Container $name stopped before API readiness; inspect its logs." }
                try {
                    $remaining = [math]::Max(1, [int]($deadline - (Get-Date)).TotalSeconds)
                    $health = Invoke-WebRequest "$endpoint/health" -UseBasicParsing -TimeoutSec ([math]::Min(30, $remaining))
                    if ($health.StatusCode -eq 200) { Write-Host "READY: $endpoint/v1 ($Profile)"; return }
                } catch {
                    if (((Get-Date) - $lastNotice).TotalSeconds -ge 60) {
                        Write-Host "API not ready; retrying: $($_.Exception.Message)"
                        $lastNotice = Get-Date
                    }
                }
            } else { Write-Host 'WSLC temporarily unavailable; retrying without stopping the container.' }
            Start-Sleep -Seconds 10
        }
        throw "API did not become ready within $TimeoutSeconds seconds. Container left running for inspection."
    }
    'status' {
        $selected = Get-ManagedContainer
        if ($selected) { Write-Host "${name}: $($selected.State.Status)" }
        if (-not $selected -or -not $selected.State.Running) {
            Write-Host "Selected profile '$Profile' is stopped or has not been created."
            return
        }
        try {
            $models = Invoke-RestMethod "$endpoint/v1/models" -TimeoutSec 5
            Write-Host "READY: $endpoint/v1"
            $models.data | Select-Object id, max_model_len
        } catch { Write-Host "API not ready: $($_.Exception.Message)" }
    }
    'doctor' {
        Invoke-Wslc @('info')
        Invoke-Wslc @('images')
        & nvidia-smi
        Write-Host "Models: $($config.ModelRoot)"
    }
    'test' {
        Assert-ProfileRunning
        if ($Suite -ne 'smoke') {
            & (Join-Path $PSScriptRoot 'test.ps1') -Suite $Suite -Profile $Profile -ResultName "$Suite-$Profile" -Port $config.Port
            return
        }
        $tests = @(
            @{ Name='instruction'; Prompt='Reply with exactly OK and nothing else.'; Expected='^OK[.!]?$' },
            @{ Name='arithmetic'; Prompt='What is 17 plus 25? Reply with only the number.'; Expected='^42[.!]?$' },
            @{ Name='context'; Prompt='Remember this code: RIVER-729. What code did I ask you to remember? Reply with only the code.'; Expected='^RIVER-729[.!]?$' }
        )
        $results = @()
        foreach ($test in $tests) {
            $body = @{
                model='qwen/qwen38fn-best'; messages=@(@{role='user'; content=$test.Prompt})
                max_tokens=128; temperature=0; chat_template_kwargs=@{enable_thinking=$false}
            } | ConvertTo-Json -Depth 8
            $reply = Invoke-RestMethod "$endpoint/v1/chat/completions" -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 600
            $content = [string]$reply.choices[0].message.content
            $passed = $content.Trim() -match $test.Expected -and $reply.choices[0].finish_reason -eq 'stop'
            $results += [pscustomobject]@{test=$test.Name; passed=$passed; content=$content; finish_reason=$reply.choices[0].finish_reason}
        }
        $resultDir = Join-Path $PSScriptRoot '.state/checks'
        New-Item -ItemType Directory -Force $resultDir | Out-Null
        $results | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $resultDir "smoke-$Profile.json") -Encoding UTF8
        $results | Format-Table -AutoSize
        if (@($results | Where-Object { -not $_.passed }).Count) { throw "Model correctness check failed; see .state/checks/smoke-$Profile.json" }
    }
}

} finally {if($containerLock){$containerLock.Dispose()}}
