#Requires -Version 5.1
param([string]$Profile='cache-dflash')
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
. "$PSScriptRoot/scripts/config.ps1"
$config=Get-N1xConfig -Root $PSScriptRoot -Profile $Profile
if(-not $config.UseLMCache){throw 'Select an LMCache profile.'}
$destination=Join-Path $PSScriptRoot ('results/restores/'+(Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Force $destination | Out-Null
function Run-Probe([string]$Stage) {
    & wslc run --rm --network "container:$($config.Container)" --entrypoint python `
        -v "${PSScriptRoot}/benchmarks:/probe:ro" -v "${destination}:/results" `
        n1x-ai:benchmarks /probe/restart_restore_probe.py $Stage
    if($LASTEXITCODE -ne 0){throw "Restore probe failed at $Stage; inspect $destination"}
}
& "$PSScriptRoot/n1x.ps1" wait -Profile $Profile -TimeoutSeconds 1800
Run-Probe seed
# Restart clears both GPU and host caches while retaining SSD files.
& "$PSScriptRoot/n1x.ps1" restart -Profile $Profile
& "$PSScriptRoot/n1x.ps1" wait -Profile $Profile -TimeoutSeconds 1800
Run-Probe verify
Write-Host "Results: $destination"
