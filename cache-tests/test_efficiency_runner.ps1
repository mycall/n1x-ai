$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$root=Split-Path $PSScriptRoot -Parent
$prefix='eff-case-regression-'+[guid]::NewGuid().ToString('N')
New-Item -ItemType Directory -Force (Join-Path $root '.build') | Out-Null
$fixture=Join-Path $root ".build/$prefix-protocol.json"
$status=Join-Path $root "results/$prefix-status.json"
[IO.File]::WriteAllText($fixture,'{"profiles":[{"name":"one"}]}',[Text.UTF8Encoding]::new($false))
# Stop the actual runner immediately after case validation and status writing;
# no GPU, image, or container operation is permitted by this regression test.
function wslc { throw 'CASE-VALIDATION-STOP' }
try {
    try {
        & "$root/run-efficiency-tests.ps1" -RunPrefix $prefix -ProtocolPath $fixture -SkipBuild
        throw 'Runner unexpectedly passed the mock boundary'
    } catch {
        if($_.Exception.Message -ne 'CASE-VALIDATION-STOP'){throw}
    }
    $record=Get-Content -LiteralPath $status -Raw|ConvertFrom-Json
    if(@($record.cases).Count -ne 1 -or $record.cases[0] -ne 'one'){throw 'Single case was not preserved as an array'}
    Write-Output 'Efficiency runner single-case strict-mode regression passed'
} finally {
    Remove-Item Function:\wslc
    if(Test-Path -LiteralPath $status){Remove-Item -LiteralPath $status}
    if(Test-Path -LiteralPath $fixture){Remove-Item -LiteralPath $fixture}
}
