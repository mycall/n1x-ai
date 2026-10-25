function Get-N1xResourcePlan($Containers,$Images,$Volumes,[string[]]$KeepImages,[string[]]$CacheVolumes,[string[]]$PleVolumes,[switch]$Uninstall,[switch]$Preview){
    $owned=@($Containers | Where-Object {
        $label=$null
        if($null -ne $_.Config.Labels){$label=$_.Config.Labels.PSObject.Properties['n1x-ai.managed']}
        ($null -ne $label -and $label.Value -eq 'true') -or
        ($_.Name -like '/n1x-*' -and $_.Config.Image -match '^n1x-ai[:@]')
    })
    $others=@($Containers | Where-Object {$_ -notin $owned})
    foreach($container in $owned){
        if($container.State.Running){
            if(-not $Uninstall -and -not $Preview){throw 'Stop project containers before cleaning. clean preserves offline startup resources; uninstall also stops services.'}
            if($Uninstall){[pscustomobject]@{Kind='stop';Name=$container.Name.TrimStart('/')}}
            else {Write-Warning "Stop before cleaning: $($container.Name)"}
        }
        [pscustomobject]@{Kind='container';Name=$container.Name.TrimStart('/')}
    }
    $targets=@($CacheVolumes)
    if($Uninstall){$targets+=@($PleVolumes)}
    foreach($volume in ($targets | Sort-Object -Unique)){
        if($volume -notin $Volumes){continue}
        if(@($others | Where-Object {@($_.Mounts | Where-Object { $_.Type -eq 'volume' -and $_.Name -eq $volume }).Count}).Count){
            Write-Warning "Preserving volume referenced by another container: $volume"; continue
        }
        [pscustomobject]@{Kind='volume';Name=$volume}
    }
    $ownedIds=@($owned | ForEach-Object {$_.Image.Replace('sha256:','')})
    $otherIds=@($others | ForEach-Object {$_.Image.Replace('sha256:','')})
    $keepIds=@($Images | Where-Object {($_.Repository+':'+$_.Tag) -in $KeepImages} | ForEach-Object {$_.ID.Replace('sha256:','')})
    foreach($image in $Images){
        $tag=$image.Repository+':'+$image.Tag
        if($image.Repository -in @('n1x-ai','n1x-ai-base')){
            if(-not $Uninstall -and $tag -in $KeepImages){continue}
            $id=$image.ID.Replace('sha256:','')
            if(@($otherIds | Where-Object {$_.StartsWith($id)}).Count){Write-Warning "Preserving image used by another container: $tag";continue}
            [pscustomobject]@{Kind='image';Name=$tag}
        } elseif($image.Repository -eq '<none>'){
            $id=$image.ID.Replace('sha256:','')
            if(-not @($ownedIds | Where-Object {$_.StartsWith($id)}).Count){continue}
            if(@($otherIds | Where-Object {$_.StartsWith($id)}).Count){continue}
            if(-not $Uninstall -and $id -in $keepIds){continue}
            [pscustomobject]@{Kind='image';Name=$image.ID}
        }
    }
}

function Invoke-N1xResourceCleanup([string]$Root,[switch]$Uninstall,[switch]$PrintOnly){
    . "$Root/scripts/config.ps1"
    $profiles=@('baseline')+@(Get-ChildItem "$Root/profiles" -Filter '*.psd1' | ForEach-Object BaseName)
    $configs=@($profiles | ForEach-Object {Get-N1xConfig -Root $Root -Profile $_})
    $keepImages=@($configs | ForEach-Object Image)+@('n1x-ai:benchmarks','n1x-ai-base:cuda13.4-ubuntu26.04-vllm0.32.0')
    $cacheVolumes=@($configs | ForEach-Object CacheVolume)+@($configs | ForEach-Object LmcacheVolume)+@('n1x-lmcache-tests')
    $pleVolumes=@($configs | ForEach-Object PleVolume)
    $rows=@(& wslc list --all --format json)
    if($LASTEXITCODE -ne 0){throw 'Cannot list containers for cleanup'}
    $names=@($rows | Where-Object {$_.Trim()} | ForEach-Object {($_ | ConvertFrom-Json).Names})
    $containers=@()
    if($names.Count){
        $raw=& wslc inspect @names
        if($LASTEXITCODE -ne 0){throw 'Cannot inspect containers for cleanup'}
        $containers=($raw -join "`n") | ConvertFrom-Json
    }
    $raw=& wslc images --format json
    if($LASTEXITCODE -ne 0){throw 'Cannot list images for cleanup'}
    $images=@($raw | Where-Object {$_.Trim()} | ForEach-Object {$_ | ConvertFrom-Json})
    $raw=& wslc volume list --format json
    if($LASTEXITCODE -ne 0){throw 'Cannot list volumes for cleanup'}
    $volumes=@($raw | Where-Object {$_.Trim()} | ForEach-Object {($_ | ConvertFrom-Json).Name})
    $plan=@(Get-N1xResourcePlan $containers $images $volumes $keepImages $cacheVolumes $pleVolumes -Uninstall:$Uninstall -Preview:$PrintOnly)
    foreach($item in $plan){
        Write-Host "$($item.Kind): $($item.Name)"
        if($PrintOnly){continue}
        if($item.Kind -eq 'container'){
            $pidFile=Join-Path $Root ".state/$($item.Name)/monitor.json"
            if(Test-Path -LiteralPath $pidFile){
                $saved=Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
                $process=Get-CimInstance Win32_Process -Filter "ProcessId=$($saved.processId)"
                if($null -ne $process -and $process.CommandLine -match '\-File\s+"?[^"\r\n]*monitor-memory.ps1' -and
                    $process.CommandLine -match [regex]::Escape($Root) -and $process.CommandLine -match [regex]::Escape($item.Name)){
                    Stop-Process -Id $process.ProcessId -Force
                }
            }
        }
        switch($item.Kind){
            'stop' {& wslc stop $item.Name}
            'container' {& wslc rm $item.Name}
            'volume' {& wslc volume remove $item.Name}
            'image' {& wslc rmi $item.Name}
        }
        if($LASTEXITCODE -ne 0){throw "Could not remove $($item.Kind) '$($item.Name)'; resources still referenced by other containers are preserved. Rerun after resolving the reference."}
    }
}
