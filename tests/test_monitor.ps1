$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$snapshot=[IO.Path]::GetTempFileName()
$monitorState=@{inspections=0;sleeps=0}
try {
    function wslc {
        $global:LASTEXITCODE=0
        if($args[0] -eq 'inspect'){
            $monitorState.inspections++
            if($monitorState.inspections -eq 1){'[{"State":{"Running":true}}]'}
            else {$global:LASTEXITCODE=1}
        } elseif($args[0] -ne 'list'){throw 'Unexpected monitor command'}
    }
    function Get-CimInstance {param($ClassName); [pscustomobject]@{FreePhysicalMemory=8*1MB}}
    function Start-Sleep {
        param($Seconds)
        $monitorState.sleeps++
        if($monitorState.sleeps -gt 3){throw 'Monitor kept reopening WSLC after its container was removed'}
    }
    & "$(Split-Path $PSScriptRoot -Parent)/scripts/monitor-memory.ps1" -Container fixture -OutputPath $snapshot
    $data=Get-Content $snapshot -Raw | ConvertFrom-Json
    if($monitorState.inspections -ne 2 -or $data.availableGiB -ne 8){throw 'Monitor lifecycle regression'}
    Write-Host 'Memory monitor exits after container removal.'
} finally {Remove-Item -LiteralPath $snapshot -Force}
