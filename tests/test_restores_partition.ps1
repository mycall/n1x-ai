$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$root=Split-Path $PSScriptRoot -Parent
$temporary=Join-Path ([IO.Path]::GetTempPath()) ('n1x-restore-gate-'+[guid]::NewGuid().ToString('N'))
$global:N1xRestoreTestCalls=[Collections.Generic.List[string]]::new()
$global:N1xRestoreTestReadings=[Collections.Generic.Queue[string]]::new()
$global:N1xRestoreTestAnswer='cancel'
function nvidia-smi {
    $global:LASTEXITCODE=0
    $global:N1xRestoreTestReadings.Dequeue()
}
function Read-Host {param($Prompt);return $global:N1xRestoreTestAnswer}
function wslc {
    $global:N1xRestoreTestCalls.Add('probe-'+$args[-1])
    $global:LASTEXITCODE=0
}
function Expect-Rejection([string]$Pattern){
    $global:N1xRestoreTestCalls.Clear()
    try {& "$temporary/test-restores.ps1";throw 'Expected rejection did not occur'}
    catch {if($_.Exception.Message -notlike $Pattern){throw}}
    if($global:N1xRestoreTestCalls.Count){throw 'Server or probe command ran before the partition gate passed'}
    if(Test-Path "$temporary/results"){throw 'Rejected restore test created a result directory'}
}
try {
    New-Item -ItemType Directory -Force "$temporary/scripts" | Out-Null
    Copy-Item "$root/test-restores.ps1" "$temporary/test-restores.ps1"
    Copy-Item "$root/scripts/benchmark-partition.ps1" "$temporary/scripts/benchmark-partition.ps1"
    @'
function Get-N1xConfig {
    param($Root,$Profile)
    return @{UseLMCache=$true;Container='n1x-restore-fixture'}
}
'@ | Set-Content "$temporary/scripts/config.ps1" -Encoding UTF8
    @'
param($Action,$Profile,$TimeoutSeconds)
$global:N1xRestoreTestCalls.Add($Action)
'@ | Set-Content "$temporary/n1x.ps1" -Encoding UTF8
    $global:N1xRestoreTestReadings.Enqueue('98304')
    Expect-Rejection 'Cancelled*'
    $global:N1xRestoreTestAnswer='88'
    $global:N1xRestoreTestReadings.Enqueue('98304')
    $global:N1xRestoreTestReadings.Enqueue('98304')
    Expect-Rejection 'Partition still reports*'
    $global:N1xRestoreTestReadings.Enqueue('90112')
    & "$temporary/test-restores.ps1"
    if(($global:N1xRestoreTestCalls -join ',') -ne 'wait,probe-seed,restart,wait,probe-verify'){
        throw 'Verified restore sequence changed'
    }
    $receipt=@(Get-ChildItem "$temporary/results/restores" -Recurse -Filter partition.json)
    if($receipt.Count -ne 1){throw 'Verified partition receipt was not saved'}
    $saved=Get-Content $receipt[0].FullName -Raw|ConvertFrom-Json
    if($saved.actualMiB -ne 90112 -or $saved.requiredMiB -ne 90112){throw 'Wrong partition recorded'}
    Write-Output 'Restore entrypoint partition checks passed; model and GPU commands were mocked'
} finally {
    $resolved=[IO.Path]::GetFullPath($temporary)
    $prefix=[IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    if(-not $resolved.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase) -or
       [IO.Path]::GetFileName($resolved) -notlike 'n1x-restore-gate-*'){throw 'Unsafe test cleanup path'}
    if(Test-Path -LiteralPath $resolved){Remove-Item -LiteralPath $resolved -Recurse -Force}
    Remove-Variable N1xRestoreTestCalls,N1xRestoreTestReadings,N1xRestoreTestAnswer -Scope Global
}
