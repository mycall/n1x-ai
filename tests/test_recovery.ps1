$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$root=Split-Path $PSScriptRoot -Parent
$temporary=Join-Path ([IO.Path]::GetTempPath()) ('n1x-recovery-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force "$temporary/scripts","$temporary/profiles","$temporary/models/Qwen3.8-Flash-Next-W4A16-AutoRound-hybrid"|Out-Null
try {
    Copy-Item "$root/n1x.ps1","$root/config.psd1" $temporary
    Copy-Item "$root/scripts/config.ps1" "$temporary/scripts/config.ps1"
    Set-Content "$temporary/scripts/firewall.ps1" 'function Set-N1xFirewall { param($Root,$Port,[switch]$Remove); Set-Content (Join-Path $Root "firewall-mode.txt") ([string][bool]$Remove) }'
    Set-Content "$temporary/scripts/clients.ps1" 'function Sync-N1xClients { param($Root,$Port,$Context,$MaxOutputTokens,[switch]$Remove) }'
    Copy-Item "$root/profiles/qwen38fn-cache-mtp.psd1" "$temporary/profiles/qwen38fn-cache-mtp.psd1"
    $modelRoot=Join-Path $temporary 'models'
    $model=Join-Path $modelRoot 'Qwen3.8-Flash-Next-W4A16-AutoRound-hybrid'
    Set-Content "$model/config.json" '{}'
    Set-Content "$model/model.safetensors.index.json" '{"weight_map":{"weight":"part.safetensors"}}'
    Set-Content "$model/part.safetensors" 'fixture'
    $preview=& "$temporary/n1x.ps1" start -NoWait -Profile qwen38fn-cache-mtp -ModelRoot $modelRoot -PrintOnly
    $fingerprint=[regex]::Match($preview,'n1x-ai.config-sha=([0-9a-f]{64})').Groups[1].Value
    if(-not $fingerprint){throw 'Missing launch fingerprint'}
    Set-Content "$temporary/config.local.psd1" "@{DefaultProfile='qwen38fn-baseline'}"
    $changedDefault=& "$temporary/n1x.ps1" start -NoWait -Profile qwen38fn-cache-mtp -ModelRoot $modelRoot -PrintOnly
    $changedFingerprint=[regex]::Match($changedDefault,'n1x-ai.config-sha=([0-9a-f]{64})').Groups[1].Value
    if($changedFingerprint -ne $fingerprint){throw 'Changing only the default selection invalidated an explicit profile'}
    $recoveryState=[pscustomobject]@{exitCode=1; fingerprint=$fingerprint; exists=$true; running=$false; managed='true'; imageExists=$true; freeCommitGiB=32; healthChecks=0; healthUri=''; healthTimeout=0; calls=[Collections.Generic.List[string]]::new()}
    function wslc {
        param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)
        $global:LASTEXITCODE=0
        $recoveryState.calls.Add(($Arguments -join ' '))
        switch($Arguments[0]) {
            'image' {if(-not $recoveryState.imageExists){$global:LASTEXITCODE=1};return}
            'list' {if($recoveryState.exists -and $Arguments -contains '--all'){'{"Names":"n1x-qwen38-cache-mtp"}'};return}
            'inspect' {
                @{Config=@{Labels=@{'n1x-ai.managed'=$recoveryState.managed;'n1x-ai.config-sha'=$recoveryState.fingerprint}};
                  State=@{Running=$recoveryState.running;ExitCode=$recoveryState.exitCode}}|ConvertTo-Json -Depth 6
                return
            }
            'run' {
                if($Arguments -contains '--entrypoint'){'{"sourceRevision":"50511b0a41aa1d34b8beb7e5d4bb06a0b650dc14","files":[{"name":"table.safetensors"}]}'}
                else{'replacement-container'}
                return
            }
            'rm' {return}
            'start' {return}
            'stop' {return}
            default {throw "Unexpected WSLC command: $Arguments"}
        }
    }
    function Get-CimInstance {
        param($ClassName,$Filter)
        if($ClassName -eq 'Win32_OperatingSystem'){[pscustomobject]@{FreePhysicalMemory=16*1MB;FreeVirtualMemory=$recoveryState.freeCommitGiB*1MB}}
    }
    function Start-Process {
        param($FilePath,$WindowStyle,$ArgumentList,[switch]$PassThru)
        $recoveryState.calls.Add('monitor-start')
        [pscustomobject]@{Id=987654}
    }
    foreach($action in @('start','restart')){
        $recoveryState.calls.Clear()
        & "$temporary/n1x.ps1" $action -NoWait:($action -eq 'start') -Profile qwen38fn-cache-mtp -ModelRoot $modelRoot | Out-Null
        if($recoveryState.calls -notcontains 'rm n1x-qwen38-cache-mtp' -or -not @($recoveryState.calls|Where-Object {$_ -like 'run -d *'}).Count){throw "Failed cache container was not replaced by $action"}
        if($recoveryState.calls -contains 'start n1x-qwen38-cache-mtp'){throw 'Failed cache container was reused'}
        $launch=@($recoveryState.calls | Where-Object {$_ -like 'run -d *'})[0]
        if($recoveryState.calls.IndexOf('monitor-start') -gt $recoveryState.calls.IndexOf($launch)){throw 'Monitor started after blocking launch'}
    }
    $recoveryState.exitCode=0
    foreach($action in @('start','restart')){
        # restart with an unsuccessful exit delegates to start.
        $recoveryState.exitCode=1
        & "$temporary/n1x.ps1" $action -NoWait:($action -eq 'start') -Profile qwen38fn-cache-mtp -ModelRoot $modelRoot -DenyFirewall | Out-Null
        if((Get-Content "$temporary/firewall-mode.txt") -ne 'True'){throw "$action lost DenyFirewall"}
    }
    $recoveryState.exitCode=0
    $recoveryState.calls.Clear()
    & "$temporary/n1x.ps1" start -NoWait -Profile qwen38fn-cache-mtp -ModelRoot $modelRoot | Out-Null
    if((Get-Content "$temporary/firewall-mode.txt") -ne 'False'){throw 'Plain start should enable the firewall allowance'}
    if($recoveryState.calls -notcontains 'start n1x-qwen38-cache-mtp' -or @($recoveryState.calls|Where-Object {$_ -like 'rm *'}).Count){throw 'Cleanly stopped container should be reused'}
    $recoveryState.freeCommitGiB=.5
    $recoveryState.calls.Clear()
    try{
        & "$temporary/n1x.ps1" start -NoWait -Profile qwen38fn-cache-mtp -ModelRoot $modelRoot | Out-Null
        throw 'Low commit headroom accepted despite free physical RAM'
    }catch{if($_.Exception.Message -ne 'Insufficient Windows commit headroom'){throw}}
    if($recoveryState.calls -contains 'monitor-start' -or $recoveryState.calls -contains 'start n1x-qwen38-cache-mtp'){throw 'Low commit headroom launched serving'}
    $recoveryState.freeCommitGiB=32
    function Invoke-WebRequest {
        param($Uri,[switch]$UseBasicParsing,$TimeoutSec)
        $recoveryState.healthChecks++
        $recoveryState.healthUri=$Uri
        $recoveryState.healthTimeout=$TimeoutSec
        [pscustomobject]@{StatusCode=200}
    }
    $portPreview=& "$temporary/n1x.ps1" start -NoWait -Profile qwen38fn-cache-mtp -ModelRoot $modelRoot -Port 8010 -PrintOnly
    $recoveryState.fingerprint=[regex]::Match($portPreview,'n1x-ai.config-sha=([0-9a-f]{64})').Groups[1].Value
    $recoveryState.running=$true
    foreach($options in @(@{}, @{Wait=$true})){
        $recoveryState.healthChecks=0
        & "$temporary/n1x.ps1" start @options -Profile qwen38fn-cache-mtp -ModelRoot $modelRoot -Port 8010 -TimeoutSeconds 7 -DenyFirewall | Out-Null
        if($recoveryState.healthChecks -ne 1){throw 'Default or explicit start wait did not check readiness'}
    }
    $recoveryState.healthChecks=0
    & "$temporary/n1x.ps1" start -NoWait -Profile qwen38fn-cache-mtp -ModelRoot $modelRoot -Port 8010 | Out-Null
    if($recoveryState.healthChecks){throw 'NoWait queried readiness'}
    & "$temporary/n1x.ps1" start -Profile qwen38fn-cache-mtp -ModelRoot $modelRoot -Port 8010 -TimeoutSeconds 7 -DenyFirewall | Out-Null
    if($recoveryState.healthChecks -ne 1 -or $recoveryState.healthUri -ne 'http://127.0.0.1:8010/health' -or $recoveryState.healthTimeout -gt 7){throw 'Start -Wait lost profile, port or timeout options'}
    if((Get-Content "$temporary/firewall-mode.txt") -ne 'True'){throw 'Start -Wait lost DenyFirewall'}
    $recoveryState.calls.Clear()
    & "$temporary/n1x.ps1" start -Wait -PrintOnly -Profile qwen38fn-cache-mtp -ModelRoot $modelRoot | Out-Null
    if($recoveryState.calls.Count -or $recoveryState.healthChecks -ne 1){throw 'Start -Wait preview touched the service'}
    try {& "$temporary/n1x.ps1" stop -Wait;throw 'Wait switch accepted for stop'}
    catch {if($_.Exception.Message -notlike '-Wait and -NoWait apply only to start.*'){throw}}
    try {& "$temporary/n1x.ps1" start -Wait -NoWait;throw 'Conflicting wait switches accepted'}
    catch {if($_.Exception.Message -ne 'Choose either -Wait or -NoWait.'){throw}}
    if($recoveryState.calls.Count){throw 'Invalid Wait switch mutated the service'}
    $recoveryState.running=$false
    . "$root/scripts/config.ps1"
    $legacyConfig=Get-N1xConfig -Root $temporary -Profile qwen38fn-cache-mtp -ModelRoot $modelRoot
    $legacyCanonical=[ordered]@{}
    foreach($key in ($legacyConfig.Keys|Sort-Object)){$legacyCanonical[$key]=$legacyConfig[$key]}
    $sha=[Security.Cryptography.SHA256]::Create()
    try {$fingerprint=([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes(($legacyCanonical|ConvertTo-Json -Compress))))).Replace('-','').ToLowerInvariant()}
    finally {$sha.Dispose()}
    $recoveryState.fingerprint=$fingerprint
    $recoveryState.calls.Clear()
    & "$temporary/n1x.ps1" start -NoWait -Profile qwen38fn-cache-mtp -ModelRoot $modelRoot | Out-Null
    if($recoveryState.calls -notcontains 'rm n1x-qwen38-cache-mtp' -or -not @($recoveryState.calls|Where-Object {$_ -like 'run -d *'}).Count){throw 'Container with the retired model alias was not replaced'}
    $recoveryState.fingerprint=$changedFingerprint
    Set-Content "$temporary/config.local.psd1" "@{DefaultProfile='qwen38fn-baseline';Port=8005}"
    foreach($running in @($false,$true)){
        $recoveryState.running=$running
        $recoveryState.calls.Clear()
        & "$temporary/n1x.ps1" start -NoWait -Profile qwen38fn-cache-mtp -ModelRoot $modelRoot | Out-Null
        if($recoveryState.calls -notcontains 'rm n1x-qwen38-cache-mtp' -or -not @($recoveryState.calls|Where-Object {$_ -like 'run -d *'}).Count){throw 'Stale runtime settings were not replaced'}
        if(($recoveryState.calls -contains 'stop n1x-qwen38-cache-mtp') -ne $running){throw 'Stale running container must stop before replacement'}
    }
    $recoveryState.managed='false'
    $recoveryState.calls.Clear()
    try {& "$temporary/n1x.ps1" start -NoWait -Profile qwen38fn-cache-mtp -ModelRoot $modelRoot;throw 'Unowned container accepted'}
    catch {if($_.Exception.Message -notlike '*not managed by n1x-ai*'){throw}}
    if(@($recoveryState.calls|Where-Object {$_ -match '^(stop|rm|run) '}).Count){throw 'Unowned container was mutated'}
    $recoveryState.managed='true'
    try {
        & "$temporary/n1x.ps1" wait -Profile qwen38fn-cache-mtp -ModelRoot $modelRoot -TimeoutSeconds 1
        throw 'Wait accepted a stale serving configuration before benchmarking'
    } catch {if($_.Exception.Message -notlike 'Container settings differ.*'){throw}}
    $recoveryState.exists=$false
    try {
        & "$temporary/n1x.ps1" wait -Profile qwen38fn-cache-mtp -ModelRoot $modelRoot
        throw 'Wait accepted a missing container'
    } catch {if($_.Exception.Message -notlike "Container '*does not exist in this WSLC session.*"){throw}}
    $recoveryState.imageExists=$false
    $recoveryState.calls.Clear()
    try {
        & "$temporary/n1x.ps1" start -Wait -Profile qwen38fn-cache-mtp -ModelRoot $modelRoot
        throw 'Start accepted a missing image'
    } catch {if($_.Exception.Message -notlike "Local image '*unavailable in this WSLC session.*"){throw}}
    if(@($recoveryState.calls | Where-Object {$_ -like 'run *'}).Count){throw 'Missing image triggered an implicit pull'}
    if($recoveryState.healthChecks -ne 1){throw 'Start -Wait waited after startup failed'}
    Write-Output 'Failed-start recovery, start -Wait, missing resources, ownership, and stale-setting reconciliation checks passed'
} finally {
    $resolved=[IO.Path]::GetFullPath($temporary)
    if(-not $resolved.StartsWith([IO.Path]::GetFullPath([IO.Path]::GetTempPath()),[StringComparison]::OrdinalIgnoreCase)){throw 'Unsafe test cleanup path'}
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
