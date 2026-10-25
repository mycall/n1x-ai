$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$root=Split-Path $PSScriptRoot -Parent
$temporary=Join-Path ([IO.Path]::GetTempPath()) ('n1x-recovery-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force "$temporary/scripts","$temporary/profiles","$temporary/models/Qwen3.8-Flash-Next-W4A16-AutoRound-hybrid"|Out-Null
try {
    Copy-Item "$root/n1x.ps1","$root/config.psd1" $temporary
    Copy-Item "$root/scripts/config.ps1" "$temporary/scripts/config.ps1"
    Copy-Item "$root/profiles/cache-mtp.psd1" "$temporary/profiles/cache-mtp.psd1"
    $modelRoot=Join-Path $temporary 'models'
    $model=Join-Path $modelRoot 'Qwen3.8-Flash-Next-W4A16-AutoRound-hybrid'
    Set-Content "$model/config.json" '{}'
    Set-Content "$model/model.safetensors.index.json" '{"weight_map":{"weight":"part.safetensors"}}'
    Set-Content "$model/part.safetensors" 'fixture'
    $preview=& "$temporary/n1x.ps1" start -Profile cache-mtp -ModelRoot $modelRoot -PrintOnly
    $fingerprint=[regex]::Match($preview,'n1x-ai.config-sha=([0-9a-f]{64})').Groups[1].Value
    if(-not $fingerprint){throw 'Missing launch fingerprint'}
    $recoveryState=[pscustomobject]@{exitCode=1; calls=[Collections.Generic.List[string]]::new()}
    function wslc {
        param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)
        $global:LASTEXITCODE=0
        $recoveryState.calls.Add(($Arguments -join ' '))
        switch($Arguments[0]) {
            'list' {if($Arguments -contains '--all'){'{"Names":"n1x-qwen38-cache-mtp"}'};return}
            'inspect' {
                @{Config=@{Labels=@{'n1x-ai.managed'='true';'n1x-ai.config-sha'=$fingerprint}};
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
        [pscustomobject]@{Id=987654}
    }
    foreach($action in @('start','restart')){
        $recoveryState.calls.Clear()
        & "$temporary/n1x.ps1" $action -Profile cache-mtp -ModelRoot $modelRoot | Out-Null
        if($recoveryState.calls -notcontains 'rm n1x-qwen38-cache-mtp' -or -not @($recoveryState.calls|Where-Object {$_ -like 'run -d *'}).Count){throw "Failed cache container was not replaced by $action"}
        if($recoveryState.calls -contains 'start n1x-qwen38-cache-mtp'){throw 'Failed cache container was reused'}
    }
    $recoveryState.exitCode=0
    $recoveryState.calls.Clear()
    & "$temporary/n1x.ps1" start -Profile cache-mtp -ModelRoot $modelRoot | Out-Null
    if($recoveryState.calls -notcontains 'start n1x-qwen38-cache-mtp' -or @($recoveryState.calls|Where-Object {$_ -like 'rm *'}).Count){throw 'Cleanly stopped container should be reused'}
    Write-Output 'Failed-start recovery and clean restart checks passed'
} finally {
    $resolved=[IO.Path]::GetFullPath($temporary)
    if(-not $resolved.StartsWith([IO.Path]::GetFullPath([IO.Path]::GetTempPath()),[StringComparison]::OrdinalIgnoreCase)){throw 'Unsafe test cleanup path'}
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
