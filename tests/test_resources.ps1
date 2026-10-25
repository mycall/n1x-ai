$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
. "$(Split-Path $PSScriptRoot -Parent)/scripts/resources.ps1"
$containers=@(
    @{Name='/n1x-current';Image='sha256:aaaaaaaaaaaa';Config=@{Image='n1x-ai:lmcache';Labels=@{'n1x-ai.managed'='true'}};State=@{Running=$false};Mounts=@(@{Type='volume';Name='kv'},@{Type='volume';Name='ple'})},
    @{Name='/n1x-old';Image='sha256:bbbbbbbbbbbb';Config=@{Image='n1x-ai:old';Labels=@{}};State=@{Running=$false};Mounts=@(@{Type='volume';Name='legacy'})},
    @{Name='/other-app';Image='sha256:cccccccccccc';Config=@{Image='other:latest';Labels=@{}};State=@{Running=$false};Mounts=@(@{Type='volume';Name='shared'})}
) | ConvertTo-Json -Depth 8 | ConvertFrom-Json
$images=@(
    @{Repository='n1x-ai';Tag='lmcache';ID='aaaaaaaaaaaa'},
    @{Repository='n1x-ai';Tag='old';ID='bbbbbbbbbbbb'},
    @{Repository='other';Tag='latest';ID='cccccccccccc'},
    @{Repository='<none>';Tag='<none>';ID='dddddddddddd'}
) | ConvertTo-Json | ConvertFrom-Json
$arguments=@{Containers=$containers;Images=$images;Volumes=@('kv','ple','legacy','shared');KeepImages=@('n1x-ai:lmcache');CacheVolumes=@('kv','legacy','shared');PleVolumes=@('ple')}
$plan=@(Get-N1xResourcePlan @arguments)
if(@($plan | Where-Object {$_.Name -in @('ple','n1x-ai:lmcache','other-app','other:latest','shared','dddddddddddd')}).Count){throw 'Clean removed retained/unrelated resources'}
foreach($name in @('n1x-current','n1x-old','kv','legacy','n1x-ai:old')){
    if($name -notin $plan.Name){throw "Clean omitted $name"}
}
$containers[0].State.Running=$true
try {Get-N1xResourcePlan @arguments;throw 'Clean accepted running service'}
catch {if($_.Exception.Message -notlike 'Stop project containers*'){throw}}
$plan=@(Get-N1xResourcePlan @arguments -Uninstall)
if($plan[0].Kind -ne 'stop' -or 'ple' -notin $plan.Name -or 'n1x-ai:lmcache' -notin $plan.Name){throw 'Uninstall omitted owned resources'}
Write-Host 'Clean/uninstall scope and offline resource retention checks passed.'
