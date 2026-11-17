# Bounded feasibility probes, not a serving backend or an LMCache adapter.
param(
    [ValidateSet('setup','test','status')][string]$Action,
    [Parameter(Mandatory)][hashtable]$Config,
    [Parameter(Mandatory)][string]$Root,
    [switch]$PrintOnly
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$version=$Config.TensorFoldVersion
if($version -notmatch '^\d+\.\d+\.\d+$'){throw 'Invalid TensorFold version'}
$archiveName="tensorfold-$version-linux-aarch64"
$install=Join-Path $Root ".build/tensorfold-$version"
$runtime=Join-Path $install $archiveName
$archive=Join-Path $install 'runtime.tar.gz'
$url="https://github.com/ashhart/TensorFold/releases/download/v$version/$archiveName.tar.gz"
if($PrintOnly){
    Write-Output "TensorFold $version $Action; binary: $runtime; base image: $($Config.ImageId)"
    Write-Output 'test runs two isolated, 120-second load probes: external DFlash2 and target-only (--no-drafts). No published port or persistent cache writes.'
    Write-Output 'Requested LMCache, PLE map, scheduler, KV precision and draft-depth settings are NOT implemented by this trial launcher.'
    return
}
if($Action -eq 'status'){
    [pscustomobject]@{Profile=$Config.Profile;Version=$version;Installed=(Test-Path "$runtime/bin/tensorfold-native");Qualified=$false;Guide='wiki/TensorFold-trial.md'}
    return
}
if($Action -eq 'setup'){
    New-Item -ItemType Directory -Force $install | Out-Null
    if(-not(Test-Path -LiteralPath $archive)){Invoke-WebRequest $url -OutFile $archive}
    if((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $Config.TensorFoldArchiveSha256){throw 'TensorFold archive checksum mismatch'}
    & tar -xzf $archive -C $install
    if($LASTEXITCODE -ne 0){throw 'TensorFold archive extraction failed'}
    Write-Output "Installed checksum-pinned TensorFold $version in $runtime"
    return
}
if(-not(Test-Path "$runtime/bin/tensorfold-native")){throw 'Run n1x.ps1 setup -Profile qwen38-cache-tensorfold-dflash first'}
if(-not(Test-Path $archive) -or (Get-FileHash $archive -Algorithm SHA256).Hash -ne $Config.TensorFoldArchiveSha256){throw 'Pinned TensorFold archive missing or changed; run setup'}
$target=Join-Path $Config.ModelRoot $Config.MyllmboxModel
$drafter=Join-Path $Config.ModelRoot $Config.MyllmboxDrafter
foreach($path in @($target,$drafter)){
    if(-not(Test-Path "$path/config.json")){throw "Missing checkpoint: $path"}
}
New-Item -ItemType Directory -Force "$Root/.state" | Out-Null
try {$trialLock=[IO.File]::Open("$Root/.state/native-lifecycle.lock",[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)}
catch {throw 'Another serving lifecycle or qualification command is in progress'}
try {
    # Avoid a second model load beside another running GPU service. No service is stopped.
    $gpu=(& nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | Out-String)
    if($LASTEXITCODE -ne 0){throw 'Cannot check GPU memory before the trial'}
    foreach($line in ($gpu -split '\r?\n')){
        $used=0
        if([int]::TryParse($line.Trim(),[ref]$used) -and $used -gt 8192){throw 'GPU is occupied (>8 GiB); stop the active model before running the load trial'}
    }
    $out=Join-Path $Root ('results/tensorfold-trial-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'-'+[guid]::NewGuid().ToString('N').Substring(0,8))
    New-Item -ItemType Directory -Force $out | Out-Null
    # Use the immutable existing CUDA userspace image, overriding its entrypoint.
    # No vLLM process is launched. All checkpoint and runtime mounts are read-only.
    $common=@('run','--rm','--pull','never','--gpus','all','--network','none',
        '--mount',"type=bind,source=$runtime,target=/tf,readonly",
        '--mount',"type=bind,source=$target,target=/model,readonly",
        '--mount',"type=bind,source=$drafter,target=/drafter,readonly")
    $checks=@(
        @{Name='version';Args=@('--version')},
        @{Name='capabilities';Args=@('capabilities','--json')},
        @{Name='info';Args=@('info','/model')}
    )
    $rows=@()
    foreach($check in $checks){
        $arguments=$common+@('--entrypoint','/usr/bin/timeout',$Config.ImageId,'--signal=TERM','--kill-after=10','120','/tf/bin/tensorfold-native')+$check.Args
        $output=@(& wslc @arguments 2>&1 | ForEach-Object {"$_"})
        $code=$LASTEXITCODE
        $output | Set-Content (Join-Path $out ($check.Name+'.log'))
        $rows+=@{name=$check.Name;exitCode=$code;arguments=$arguments}
        if($check.Name -eq 'version' -and ($code -ne 0 -or ($output -join '') -ne "tensorfold-native $version")){throw "Runtime version check failed; see $out"}
    }
    $serve=@('serve','/model','--backend','cuda','--context',[string]$Config.Context,
        '--parallel',[string]$Config.MaxSequences,'--max-tokens',[string]$Config.MaxOutputTokens,
        '--thinking','--reasoning-effort','xhigh','--host','127.0.0.1','--port',[string]$Config.Port,
        '--name',"qwen/$($Config.Profile)",'--no-update-check')
    foreach($probe in @(@{Name='dflash-load';Args=@('--drafter','/drafter')},@{Name='target-only-load';Args=@('--no-drafts')})){
        $arguments=$common+@('--entrypoint','/usr/bin/timeout',$Config.ImageId,'--signal=TERM','--kill-after=10','120','/tf/bin/tensorfold-native')+$serve+$probe.Args
        Write-Host "TensorFold $($probe.Name) (maximum 130 seconds)"
        $output=@(& wslc @arguments 2>&1 | ForEach-Object {"$_"})
        $code=$LASTEXITCODE
        $output | Set-Content (Join-Path $out ($probe.Name+'.log'))
        $output | Write-Output
        $rows+=@{name=$probe.Name;exitCode=$code;arguments=$arguments}
    }
    @{
        profile=$Config.Profile;version=$version;archiveSha256=$Config.TensorFoldArchiveSha256
        configuration=$Config;gpuMemoryBefore=$gpu;probes=$rows;servingQualified=$false
        targetConfigSha256=(Get-FileHash "$target/config.json").Hash
        quantizationConfigSha256=(Get-FileHash "$target/quantization_config.json").Hash
        drafterConfigSha256=(Get-FileHash "$drafter/config.json").Hash
        unappliedSettings=@('LMCache','prepared PLE map','BatchedTokens','KvCacheBytes','KvCacheDtype','CacheBlockTokens','DFlashTokens')
        note='Exit 124/137 is a bounded timeout, not successful loading. No API or speed qualification is implied.'
    } | ConvertTo-Json -Depth 12 | Set-Content "$out/result.json"
    Write-Output "Evidence: $out"
    if(@($rows | Where-Object {$_.exitCode -ne 0}).Count){throw "TensorFold feasibility probes did not pass; see $out"}
} finally {$trialLock.Dispose()}
