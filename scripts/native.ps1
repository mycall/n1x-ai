# Native Windows vLLM lifecycle. State belongs to this checkout, never a bare PID.
function Get-N1xNativePaths([string]$Root, $Config) {
    $runtime=$Config.NativeRuntimeRoot
    if(-not [IO.Path]::IsPathRooted($runtime)){$runtime=Join-Path $Root $runtime}
    $runtime=[IO.Path]::GetFullPath($runtime)
    $recipe=$Config.NativeConfig
    if(-not [IO.Path]::IsPathRooted($recipe)){$recipe=Join-Path $Root $recipe}
    $directory=Join-Path $Root ".state/$($Config.Container)"
    @{
        Runtime=$runtime
        Python=Join-Path $runtime '.venv/Scripts/python.exe'
        Recipe=[IO.Path]::GetFullPath($recipe)
        Model=Join-Path $Config.ModelRoot $Config.NativeModel
        Directory=$directory
        State=Join-Path $directory 'native.json'
        Stdout=Join-Path $directory 'stdout.log'
        Stderr=Join-Path $directory 'stderr.log'
    }
}

function Get-N1xNativeArguments($Config, $Paths) {
    @('-m','vllm.entrypoints.cli.main','serve',$Paths.Model,'--config',$Paths.Recipe,
        '--host',$(if($Config.LanAccess){'0.0.0.0'}else{'127.0.0.1'}),'--port',[string]$Config.Port,
        '--served-model-name','qwen/qwen38fn-best','Qwen/Qwen3.8-Flash-Next',
        '--max-model-len',[string]$Config.Context,'--max-num-seqs',[string]$Config.MaxSequences,
        '--override-generation-config',(@{max_new_tokens=$Config.MaxOutputTokens}|ConvertTo-Json -Compress),
        '--max-num-batched-tokens',[string]$Config.BatchedTokens,
        '--kv-cache-memory-bytes',[string]$Config.KvCacheBytes,'--kv-cache-dtype',$Config.KvCacheDtype)
}

function ConvertTo-N1xNativeCommandLine([string[]]$Arguments) {
    # Windows CommandLineToArgvW quoting, including embedded quotes and final slashes.
    ($Arguments | ForEach-Object {
        '"'+[regex]::Replace([regex]::Replace($_,'(\\*)"','$1$1\"'),'(\\+)$','$1$1')+'"'
    }) -join ' '
}

function Get-N1xNativeProcess([string]$StatePath) {
    if(-not(Test-Path -LiteralPath $StatePath)){return $null}
    $saved=Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
    $process=Get-CimInstance Win32_Process -Filter "ProcessId=$([int]$saved.processId)"
    if($null -eq $process){return $null}
    # PID reuse must never stop an unrelated process or report it as our server.
    if($process.CreationDate.ToUniversalTime().Ticks.ToString() -ne $saved.creationTicks -or
        $process.ExecutablePath -ne $saved.executable -or $process.CommandLine -ne $saved.commandLine){
        throw "Native process identity changed; refusing to use PID $($saved.processId). Inspect $StatePath."
    }
    $process
}

function Assert-N1xNoNativeProfile([string]$Root, [string]$Except='') {
    $stateRoot=Join-Path $Root '.state'
    if(-not(Test-Path -LiteralPath $stateRoot)){return}
    foreach($directory in (Get-ChildItem -LiteralPath $stateRoot -Directory)){
        if($directory.Name -eq $Except){continue}
        if(Get-N1xNativeProcess (Join-Path $directory.FullName 'native.json')){
            throw "Another native project profile is running: $($directory.Name). Stop it first."
        }
    }
}

function Assert-N1xNativeInstallation($Paths) {
    foreach($file in @($Paths.Python,$Paths.Recipe,(Join-Path $Paths.Model 'config.json'))){
        if(-not(Test-Path -LiteralPath $file -PathType Leaf)){
            throw "Missing native runtime/model file: $file. Follow wiki/Native-vLLM.md to install the ARM64 release and FP4 checkpoint."
        }
    }
    & $Paths.Python -m vllm._rtx_spark.runtime.check doctor
    if($LASTEXITCODE -ne 0){throw 'Native vLLM installation check failed'}
}

function Start-N1xNative([string]$Root, $Config, [string]$Fingerprint, [switch]$PrintOnly) {
    $paths=Get-N1xNativePaths $Root $Config
    $arguments=ConvertTo-N1xNativeCommandLine (Get-N1xNativeArguments $Config $paths)
    if($PrintOnly){Write-Output ('& "'+$paths.Python+'" '+$arguments);return}
    Assert-N1xNoNativeProfile $Root $Config.Container
    # A native installation does not require WSLC, but check it when available.
    if(Get-Command wslc -ErrorAction SilentlyContinue){
        $rows=@(& wslc list --filter 'label=n1x-ai.managed=true' --format json)
        if($LASTEXITCODE -ne 0){throw 'Cannot check WSLC workloads before native startup'}
        if(@($rows | Where-Object {$_.Trim()}).Count){throw 'Stop project containers before starting the native profile'}
    }
    $existing=Get-N1xNativeProcess $paths.State
    if($existing){
        $saved=Get-Content -LiteralPath $paths.State -Raw | ConvertFrom-Json
        if($saved.fingerprint -ne $Fingerprint -or $saved.recipeHash -ne (Get-FileHash -LiteralPath $paths.Recipe).Hash){
            throw "Native settings differ. Run .\n1x.ps1 recreate -Profile $($Config.Profile)."
        }
        Write-Host "$($Config.Profile) is already running (PID $($existing.ProcessId))."
        return
    }
    $listener=Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object LocalPort -eq $Config.Port
    if($listener){throw "Port $($Config.Port) is already in use; refusing to adopt or stop its owner"}
    Assert-N1xNativeInstallation $paths
    New-Item -ItemType Directory -Force -Path $paths.Directory | Out-Null
    $previousEncoding=$env:PYTHONIOENCODING
    $previousUnbuffered=$env:PYTHONUNBUFFERED
    try {
        $env:PYTHONIOENCODING='utf-8'
        $env:PYTHONUNBUFFERED='1'
        $process=Start-Process -FilePath $paths.Python -ArgumentList $arguments -WorkingDirectory $paths.Runtime -WindowStyle Hidden -PassThru -RedirectStandardOutput $paths.Stdout -RedirectStandardError $paths.Stderr
    } finally {
        $env:PYTHONIOENCODING=$previousEncoding
        $env:PYTHONUNBUFFERED=$previousUnbuffered
    }
    try {
        $identity=Get-CimInstance Win32_Process -Filter "ProcessId=$($process.Id)"
        if($null -eq $identity){throw "Native server exited during startup; inspect $($paths.Stderr)"}
        $state=@{processId=$process.Id; creationTicks=$identity.CreationDate.ToUniversalTime().Ticks.ToString();
            executable=$identity.ExecutablePath; commandLine=$identity.CommandLine; fingerprint=$Fingerprint;
            recipeHash=(Get-FileHash -LiteralPath $paths.Recipe).Hash; port=$Config.Port}
        [IO.File]::WriteAllText($paths.State,($state|ConvertTo-Json),[Text.UTF8Encoding]::new($false))
    } catch {
        if(-not $process.HasExited){& taskkill.exe /PID $process.Id /T /F | Out-Null}
        throw
    }
    Write-Host "Loading $($Config.Profile) (PID $($process.Id)). Use wait and logs with the same -Profile."
}

function Stop-N1xNative([string]$Root, $Config, [switch]$PrintOnly) {
    $paths=Get-N1xNativePaths $Root $Config
    if($PrintOnly){Write-Output "Stop owned native process tree recorded in $($paths.State)";return}
    $process=Get-N1xNativeProcess $paths.State
    if($process){
        & taskkill.exe /PID $process.ProcessId /T /F
        if($LASTEXITCODE -ne 0){throw 'Could not stop native process tree; state preserved'}
    }
    if(Test-Path -LiteralPath $paths.State){Remove-Item -LiteralPath $paths.State}
}

function Wait-N1xNative([string]$Root, $Config, [int]$TimeoutSeconds) {
    $paths=Get-N1xNativePaths $Root $Config
    $deadline=(Get-Date).AddSeconds($TimeoutSeconds)
    while((Get-Date) -lt $deadline){
        if(-not(Get-N1xNativeProcess $paths.State)){throw "Native profile is stopped; inspect $($paths.Stderr)"}
        $remaining=[math]::Max(1,[int]($deadline-(Get-Date)).TotalSeconds)
        try {
            $health=Invoke-WebRequest "http://127.0.0.1:$($Config.Port)/health" -UseBasicParsing -TimeoutSec ([math]::Min(10,$remaining))
            if($health.StatusCode -eq 200){Write-Host "READY: http://127.0.0.1:$($Config.Port)/v1 ($($Config.Profile))";return}
        } catch {}
        Start-Sleep -Seconds ([math]::Min(5,$remaining))
    }
    throw 'Native API readiness timed out; server left running for inspection'
}
