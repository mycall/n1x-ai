$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$root=Split-Path $PSScriptRoot -Parent
$temporary=Join-Path ([IO.Path]::GetTempPath()) ('n1x-recovery-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force "$temporary/scripts","$temporary/profiles","$temporary/models/Qwen3.8-Flash-Next-W4A16-AutoRound-hybrid"|Out-Null
try {
    Copy-Item "$root/n1x.ps1","$root/config.psd1" $temporary
    Copy-Item "$root/scripts/config.ps1" "$temporary/scripts/config.ps1"
    Set-Content "$temporary/scripts/firewall.ps1" 'function Set-N1xFirewall { param($Root,$Port,[switch]$Remove); Set-Content (Join-Path $Root "firewall-mode.txt") ([string][bool]$Remove) }'
    Set-Content "$temporary/scripts/clients.ps1" 'function Sync-N1xClients { param($Root,$Port,$Context,[switch]$Remove) }'
    Copy-Item "$root/profiles/cache-mtp.psd1" "$temporary/profiles/cache-mtp.psd1"
    $modelRoot=Join-Path $temporary 'models'
    $model=Join-Path $modelRoot 'Qwen3.8-Flash-Next-W4A16-AutoRound-hybrid'
    Set-Content "$model/config.json" '{}'
    Set-Content "$model/model.safetensors.index.json" '{"weight_map":{"weight":"part.safetensors"}}'
    Set-Content "$model/part.safetensors" 'fixture'
    $preview=& "$temporary/n1x.ps1" start -Profile cache-mtp -ModelRoot $modelRoot -PrintOnly
    $fingerprint=[regex]::Match($preview,'n1x-ai.config-sha=([0-9a-f]{64})').Groups[1].Value
    if(-not $fingerprint){throw 'Missing launch fingerprint'}
    Set-Content "$temporary/config.local.psd1" "@{DefaultProfile='baseline'}"
    $changedDefault=& "$temporary/n1x.ps1" start -Profile cache-mtp -ModelRoot $modelRoot -PrintOnly
    $changedFingerprint=[regex]::Match($changedDefault,'n1x-ai.config-sha=([0-9a-f]{64})').Groups[1].Value
    if($changedFingerprint -ne $fingerprint){throw 'Changing only the default selection invalidated an explicit profile'}
    $recoveryState=[pscustomobject]@{exitCode=1; fingerprint=$fingerprint; exists=$true; imageExists=$true; calls=[Collections.Generic.List[string]]::new()}
    function wslc {
        param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)
        $global:LASTEXITCODE=0
        $recoveryState.calls.Add(($Arguments -join ' '))
        switch($Arguments[0]) {
            'image' {if(-not $recoveryState.imageExists){$global:LASTEXITCODE=1};return}
            'list' {if($recoveryState.exists -and $Arguments -contains '--all'){'{"Names":"n1x-qwen38-cache-mtp"}'};return}
            'inspect' {
                @{Config=@{Labels=@{'n1x-ai.managed'='true';'n1x-ai.config-sha'=$recoveryState.fingerprint}};
                  State=@{Running=$false;ExitCode=$recoveryState.exitCode}}|ConvertTo-Json -Depth 6
                return
            }
            'run' {
                if($Arguments -contains '--entrypoint'){'{"sourceRevision":"50511b0a41aa1d34b8beb7e5d4bb06a0b650dc14","files":[{"name":"table.safetensors"}]}'}
                else{'replacement-container'}
                return
            }
            'rm' {return}
            'start' {return}
            default {throw "Unexpected WSLC command: $Arguments"}
        }
    }
    function Get-CimInstance {
        param($ClassName,$Filter)
        if($ClassName -eq 'Win32_OperatingSystem'){[pscustomobject]@{FreePhysicalMemory=16*1MB}}
    }
    function Start-Process {
        param($FilePath,$WindowStyle,$ArgumentList,[switch]$PassThru)
        $recoveryState.calls.Add('monitor-start')
        [pscustomobject]@{Id=987654}
    }
    foreach($action in @('start','restart')){
        $recoveryState.calls.Clear()
        & "$temporary/n1x.ps1" $action -Profile cache-mtp -ModelRoot $modelRoot | Out-Null
        if($recoveryState.calls -notcontains 'rm n1x-qwen38-cache-mtp' -or -not @($recoveryState.calls|Where-Object {$_ -like 'run -d *'}).Count){throw "Failed cache container was not replaced by $action"}
        if($recoveryState.calls -contains 'start n1x-qwen38-cache-mtp'){throw 'Failed cache container was reused'}
        $launch=@($recoveryState.calls | Where-Object {$_ -like 'run -d *'})[0]
        if($recoveryState.calls.IndexOf('monitor-start') -gt $recoveryState.calls.IndexOf($launch)){throw 'Monitor started after blocking launch'}
    }
    $recoveryState.exitCode=0
    foreach($action in @('start','restart')){
        # restart with an unsuccessful exit delegates to start.
        $recoveryState.exitCode=1
        & "$temporary/n1x.ps1" $action -Profile cache-mtp -ModelRoot $modelRoot -DenyFirewall | Out-Null
        if((Get-Content "$temporary/firewall-mode.txt") -ne 'True'){throw "$action lost DenyFirewall"}
    }
    $recoveryState.exitCode=0
    $recoveryState.calls.Clear()
    & "$temporary/n1x.ps1" start -Profile cache-mtp -ModelRoot $modelRoot | Out-Null
    if((Get-Content "$temporary/firewall-mode.txt") -ne 'False'){throw 'Plain start should enable the firewall allowance'}
    if($recoveryState.calls -notcontains 'start n1x-qwen38-cache-mtp' -or @($recoveryState.calls|Where-Object {$_ -like 'rm *'}).Count){throw 'Cleanly stopped container should be reused'}
    . "$root/scripts/config.ps1"
    $legacyConfig=Get-N1xConfig -Root $temporary -Profile cache-mtp -ModelRoot $modelRoot
    $legacyCanonical=[ordered]@{}
    foreach($key in ($legacyConfig.Keys|Sort-Object)){$legacyCanonical[$key]=$legacyConfig[$key]}
    $sha=[Security.Cryptography.SHA256]::Create()
    try {$fingerprint=([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes(($legacyCanonical|ConvertTo-Json -Compress))))).Replace('-','').ToLowerInvariant()}
    finally {$sha.Dispose()}
    $recoveryState.fingerprint=$fingerprint
    & "$temporary/n1x.ps1" start -Profile cache-mtp -ModelRoot $modelRoot | Out-Null
    Set-Content "$temporary/config.local.psd1" "@{DefaultProfile='baseline';Port=8005}"
    try {
        & "$temporary/n1x.ps1" start -Profile cache-mtp -ModelRoot $modelRoot | Out-Null
        throw 'Changed runtime settings accepted'
    } catch {if($_.Exception.Message -notlike 'Container settings differ.*'){throw}}
    $recoveryState.exists=$false
    try {
        & "$temporary/n1x.ps1" wait -Profile cache-mtp -ModelRoot $modelRoot
        throw 'Wait accepted a missing container'
    } catch {if($_.Exception.Message -notlike "Container '*does not exist in this WSLC session.*"){throw}}
    $recoveryState.imageExists=$false
    $recoveryState.calls.Clear()
    try {
        & "$temporary/n1x.ps1" start -Profile cache-mtp -ModelRoot $modelRoot
        throw 'Start accepted a missing image'
    } catch {if($_.Exception.Message -notlike "Local image '*unavailable in this WSLC session.*"){throw}}
    if(@($recoveryState.calls | Where-Object {$_ -like 'run *'}).Count){throw 'Missing image triggered an implicit pull'}
    Write-Output 'Failed-start recovery, missing resources, legacy labels, and runtime-setting checks passed'
} finally {
    $resolved=[IO.Path]::GetFullPath($temporary)
    if(-not $resolved.StartsWith([IO.Path]::GetFullPath([IO.Path]::GetTempPath()),[StringComparison]::OrdinalIgnoreCase)){throw 'Unsafe test cleanup path'}
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
