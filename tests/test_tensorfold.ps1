$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$root=Split-Path $PSScriptRoot -Parent
$profile='qwen38-cache-tensorfold-dflash'
$best=Import-PowerShellDataFile "$root/profiles/qwen38fn-best.psd1"
$trial=Import-PowerShellDataFile "$root/profiles/$profile.psd1"
foreach($key in @('MyllmboxModel','MyllmboxDrafter','Context','MaxSequences','BatchedTokens','KvCacheBytes','KvCacheDtype','DFlash','UseLMCache','LmcacheL1GiB','LmcacheL2GiB')){
    if($trial[$key] -ne $best[$key]){throw "Trial changed requested best setting: $key"}
}
$preview=(& "$root/n1x.ps1" test -Profile $profile -PrintOnly | Out-String)
if($preview -notmatch 'NOT implemented' -or $preview -notmatch 'target-only'){throw 'Probe preview conceals unsupported settings or target-only diagnostic'}
foreach($action in @('start','build','recreate','clean','uninstall')){
    try {& "$root/n1x.ps1" $action -Profile $profile -PrintOnly;throw "Unsafe fallthrough: $action"}
    catch {if($_.Exception.Message -notmatch 'feasibility-only profile'){throw}}
}
try {& "$root/benchmark.ps1" -Suite speed -Profile $profile -SpeedPlanOnly;throw 'Unqualified backend accepted by benchmarks'}
catch {if($_.Exception.Message -notmatch 'feasibility-only profile'){throw}}
. "$root/scripts/config.ps1"
$listed=@(Get-N1xProfileList -Root $root | Where-Object Profile -eq $profile)
if($listed.Count -ne 1 -or $listed[0].Speculation -notmatch 'blocked' -or $listed[0].LMCache -notmatch 'unwired'){throw 'Inventory presents the trial as qualified'}
Write-Output 'TensorFold trial isolation and qualification guards passed'
