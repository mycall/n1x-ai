function Get-N1xMyllmboxPaths {
    param([string]$Root,[hashtable]$Config)
    @{
        Recipe=[IO.Path]::GetFullPath((Join-Path $Root $Config.MyllmboxConfig))
        Environment=[IO.Path]::GetFullPath((Join-Path $Root $Config.MyllmboxEnvironment))
        Model=Join-Path $Config.ModelRoot $Config.MyllmboxModel
        Drafter=Join-Path $Config.ModelRoot $Config.MyllmboxDrafter
        State=Join-Path $Root ".state/$($Config.Container)"
    }
}

function Get-N1xMyllmboxEnvironment {
    param([string]$Root,[hashtable]$Config)
    $paths=Get-N1xMyllmboxPaths $Root $Config
    $environment=Import-PowerShellDataFile $paths.Environment
    if($environment.HF_HUB_OFFLINE -ne '1' -or $environment.TRANSFORMERS_OFFLINE -ne '1'){
        throw 'MyLLMBox requires offline loading of the existing local weights'
    }
    $environment.N1X_LMCACHE_ENABLED=if($Config.UseLMCache){'1'}else{'0'}
    if($Config.UseLMCache){
        $environment.N1X_LMCACHE_L1_GIB=[string]$Config.LmcacheL1GiB
        $environment.N1X_LMCACHE_L2_GIB=[string]$Config.LmcacheL2GiB
        $environment.N1X_LMCACHE_STAGED_TRANSFER='1'
        $environment.N1X_RESTORE_WAIT_MS=[string]$Config.RestoreWaitMs
        $environment.N1X_CACHE_NAMESPACE=$Config.LmcacheNamespace
    }
    $environment.N1X_WINDOWS_MINIMUM_GIB=[string]$Config.WindowsMinimumGiB
    $environment.N1X_CACHE_BLOCK_TOKENS=[string]$Config.CacheBlockTokens
    $environment.N1X_LMCACHE_CHUNK_TOKENS=[string]$Config.LmcacheChunkTokens
    return $environment
}

function Get-N1xMyllmboxArguments {
    param([string]$Root,[hashtable]$Config,[string]$Fingerprint)
    $paths=Get-N1xMyllmboxPaths $Root $Config
    $environment=Get-N1xMyllmboxEnvironment $Root $Config
    $recipeDirectory=Split-Path $paths.Recipe -Parent
    $recipeName=Split-Path $paths.Recipe -Leaf
    $captures=@(1,2,3,4)
    for($size=8;$size -le 4*$Config.MaxSequences;$size+=4){$captures+=$size}
    $compilation=@{cudagraph_mode='FULL_AND_PIECEWISE';cudagraph_capture_sizes=$captures;compile_ranges_endpoints=@(4*$Config.MaxSequences)}
    $spec=@{method='dflash';model='/drafter';num_speculative_tokens=3;disable_eagle_block_drop=$true;
        max_model_len=$Config.Context;kv_cache_dtype='auto';draft_load_config=@{load_format='safetensors'};attention_backend='TRITON_ATTN'}
    $publish=if($Config.LanAccess){'0.0.0.0'}else{'127.0.0.1'}
    $arguments=@('run','-d','--name',$Config.Container,'--label','n1x-ai.managed=true',
        '--label',"n1x-ai.profile=$($Config.Profile)",'--label',"n1x-ai.config-sha=$Fingerprint",
        '--gpus','all','--shm-size','1g','--stop-timeout','60','--ulimit','memlock=-1:-1',
        '--publish',"${publish}:$($Config.Port):8000",'--volume',"$($paths.Model):/model:ro",
        '--volume',"$($paths.Drafter):/drafter:ro",'--volume',"$($Config.PleVolume):/ple-table-fp8:ro",
        '--volume',"$($Config.CacheVolume):/cache",'--volume',"${recipeDirectory}:/n1x-config:ro",
        '--volume',"$($paths.State):/state:ro")
    if($Config.UseLMCache){$arguments+=@('--volume',"$($Config.LmcacheVolume):/lmcache")}
    foreach($key in @($environment.Keys|Sort-Object)){$arguments+=@('--env',"$key=$($environment[$key])")}
    $arguments+=@($Config.ImageId,'--model','/model','--config',"/n1x-config/$recipeName",'--host','0.0.0.0',
        '--port','8000','--served-model-name','qwen/qwen38fn-best','Qwen/Qwen3.8-Flash-Next',
        '--override-generation-config',(@{max_new_tokens=$Config.MaxOutputTokens}|ConvertTo-Json -Compress),
        '--max-model-len',[string]$Config.Context,'--max-num-seqs',[string]$Config.MaxSequences,
        '--max-num-batched-tokens',[string]$Config.BatchedTokens,'--kv-cache-memory-bytes',[string]$Config.KvCacheBytes,
        '--kv-cache-dtype',$Config.KvCacheDtype,'--compilation-config',($compilation|ConvertTo-Json -Depth 4 -Compress),
        '--speculative-config',($spec|ConvertTo-Json -Depth 4 -Compress))
    return $arguments
}

function Confirm-N1xMyllmboxCacheVolume {
    param([hashtable]$Config,[switch]$CreateIfMissing)
    if(-not $Config.UseLMCache){return}
    & wslc volume inspect $Config.LmcacheVolume 2>$null | Out-Null
    if($LASTEXITCODE -eq 0){return}
    if(-not $CreateIfMissing){throw "Missing LMCache volume: $($Config.LmcacheVolume); run n1x.ps1 setup -Profile $($Config.Profile) to create an empty cache"}
    & wslc volume create $Config.LmcacheVolume | Out-Null
    if($LASTEXITCODE -ne 0){throw 'Cannot create the configured LMCache volume'}
    & wslc volume inspect $Config.LmcacheVolume | Out-Null
    if($LASTEXITCODE -ne 0){throw 'New LMCache volume could not be verified'}
    Write-Host "Created empty LMCache volume $($Config.LmcacheVolume); prompt KV will regenerate on use."
}

function Assert-N1xMyllmboxInstallation {
    param([string]$Root,[hashtable]$Config,[switch]$PrepareCache)
    $paths=Get-N1xMyllmboxPaths $Root $Config
    $null=Get-N1xMyllmboxEnvironment $Root $Config
    foreach($path in @($paths.Recipe,"$($paths.Model)/config.json","$($paths.Model)/model.safetensors.index.json","$($paths.Drafter)/config.json","$($paths.Drafter)/model.safetensors")){
        if(-not(Test-Path -LiteralPath $path)){throw "Missing MyLLMBox input: $path; existing local weights are required"}
    }
    $index=Get-Content "$($paths.Model)/model.safetensors.index.json" -Raw|ConvertFrom-Json
    foreach($shard in ($index.weight_map.PSObject.Properties.Value|Sort-Object -Unique)){
        if(-not(Test-Path -LiteralPath (Join-Path $paths.Model $shard))){throw "Missing model shard: $shard"}
    }
    $tool=Get-Command wslc.exe -ErrorAction Stop
    $version=[Diagnostics.FileVersionInfo]::GetVersionInfo($tool.Source).FileVersion
    if($version -ne $Config.MyllmboxWSLCVersion){throw "This MyLLMBox recipe requires WSLC $($Config.MyllmboxWSLCVersion); found $version"}
    $raw=@(& wslc image inspect $Config.Image)
    if($LASTEXITCODE -ne 0){throw "Prepared MyLLMBox image '$($Config.Image)' is missing; see wiki/MyLLMBox.md"}
    $image=@(($raw -join "`n")|ConvertFrom-Json)[0]
    if($image.Id -ne $Config.ImageId){throw 'MyLLMBox image identity changed; qualify the new build before updating ImageId'}
    & wslc volume inspect $Config.PleVolume | Out-Null
    if($LASTEXITCODE -ne 0){throw "Missing existing FP8 PLE volume: $($Config.PleVolume)"}
    & wslc volume inspect $Config.CacheVolume | Out-Null
    if($LASTEXITCODE -ne 0){throw "Missing prepared MyLLMBox cache volume: $($Config.CacheVolume); reuse the qualified PLE map"}
    $partition=@(& nvidia-smi --id=0 --query-gpu=memory.total --format=csv,noheader,nounits)
    if($LASTEXITCODE -ne 0 -or $partition.Count -ne 1 -or $partition[0].Trim() -ne [string]$Config.RequiredPartitionMiB){
        throw "This MyLLMBox recipe requires $($Config.RequiredPartitionMiB) MiB of GPU memory; change the partition manually before starting"
    }
    Confirm-N1xMyllmboxCacheVolume $Config -CreateIfMissing:$PrepareCache
}

function Start-N1xMyllmboxMonitor {
    param([string]$Root,[hashtable]$Config)
    $paths=Get-N1xMyllmboxPaths $Root $Config
    New-Item -ItemType Directory -Force $paths.State|Out-Null
    $recordPath=Join-Path $paths.State 'monitor.json'
    $scriptPath=Join-Path $Root 'scripts/monitor-memory.ps1'
    if(Test-Path -LiteralPath $recordPath){
        $saved=Get-Content $recordPath -Raw|ConvertFrom-Json
        $process=Get-Process -Id $saved.pid -ErrorAction SilentlyContinue
        if($process){
            try{
                # Hold the OS handle before checking identity so PID reuse cannot
                # change the target between inspection and termination.
                $null=$process.Handle
                if(-not $process.HasExited -and $process.StartTime.ToUniversalTime().Ticks -eq $saved.startTicks){
                    $identity=Get-CimInstance Win32_Process -Filter "ProcessId=$($process.Id)"
                    if(-not $process.HasExited){
                        if($null -eq $identity -or $identity.CommandLine -notmatch [regex]::Escape($scriptPath) -or
                           $identity.CommandLine -notmatch [regex]::Escape($Config.Container)){
                            throw 'Saved MyLLMBox monitor identity is inconsistent; refusing to stop it'
                        }
                        try{$process.Kill()}catch [InvalidOperationException]{if(-not $process.HasExited){throw}}
                        if(-not $process.WaitForExit(5000)){throw 'Previous memory monitor has not exited'}
                    }
                }
            }finally{
                $process.Dispose()
            }
        }
    }
    $arguments=ConvertTo-N1xNativeCommandLine @('-NoProfile','-File',$scriptPath,'-Container',$Config.Container,
        '-OutputPath',(Join-Path $paths.State 'host.json'))
    $process=Start-Process pwsh -ArgumentList $arguments -WorkingDirectory $Root -WindowStyle Hidden -PassThru
    @{pid=$process.Id;startTicks=$process.StartTime.ToUniversalTime().Ticks}|ConvertTo-Json|
        Set-Content $recordPath -Encoding UTF8
}
