$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
. "$(Split-Path $PSScriptRoot -Parent)/scripts/resources.ps1"
foreach($record in @([pscustomobject]@{pid=123},[pscustomobject]@{processId=123})){
    if((Get-N1xResourceMonitorId $record) -ne 123){throw 'Monitor format was not recognized'}
}
foreach($record in @([pscustomobject]@{},[pscustomobject]@{pid=0},[pscustomobject]@{pid='invalid'})){
    try{Get-N1xResourceMonitorId $record;throw 'Invalid monitor ID accepted'}
    catch{if($_.Exception.Message -ne 'Invalid saved memory monitor process ID'){throw}}
}
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
$arguments=@{Containers=$containers;Images=$images;Volumes=@('kv','ple','legacy','shared','mbx-prepared');KeepImages=@('n1x-ai:lmcache');CacheVolumes=@('kv','legacy','shared','mbx-prepared');PleVolumes=@('ple');KeepVolumes=@('mbx-prepared')}
$plan=@(Get-N1xResourcePlan @arguments)
if(@($plan | Where-Object {$_.Name -in @('ple','mbx-prepared','n1x-ai:lmcache','other-app','other:latest','shared','dddddddddddd')}).Count){throw 'Clean removed retained/unrelated resources'}
foreach($name in @('n1x-current','n1x-old','kv','legacy','n1x-ai:old')){
    if($name -notin $plan.Name){throw "Clean omitted $name"}
}
$containers[0].State.Running=$true
try {Get-N1xResourcePlan @arguments;throw 'Clean accepted running service'}
catch {if($_.Exception.Message -notlike 'Stop project containers*'){throw}}
$plan=@(Get-N1xResourcePlan @arguments -Uninstall)
if($plan[0].Kind -ne 'stop' -or 'ple' -notin $plan.Name -or 'mbx-prepared' -notin $plan.Name -or 'n1x-ai:lmcache' -notin $plan.Name){throw 'Uninstall omitted owned resources'}
function wslc {
    param([Parameter(ValueFromRemainingArguments=$true)]$Arguments)
    $global:LASTEXITCODE=0
    switch($Arguments[0]){
        'list' {return}
        'images' {return}
        'volume' {
            if($Arguments[1] -ne 'list'){throw 'Fixture attempted a volume mutation'}
            foreach($name in @('n1x-mbx-w4-dflash-test-cache','n1x-c8-lmc4-ssd160-v1','n1x-qwen38-cache')){@{Name=$name}|ConvertTo-Json -Compress}
        }
        default {throw 'Fixture attempted an unexpected resource action'}
    }
}
try{
    $root=Split-Path $PSScriptRoot -Parent
    $cleanPreview=@(Invoke-N1xResourceCleanup -Root $root -PrintOnly 6>&1)|Out-String
    if($cleanPreview -match 'volume: n1x-mbx-w4-dflash-test-cache' -or $cleanPreview -notmatch 'volume: n1x-qwen38-cache'){throw 'Configured MyLLMBox cache retention did not reach the clean plan'}
    if($cleanPreview -match 'volume: n1x-c8-lmc4-ssd160-v1'){throw 'Clean removed the required MyLLMBox LMCache volume'}
    $uninstallPreview=@(Invoke-N1xResourceCleanup -Root $root -Uninstall -PrintOnly 6>&1)|Out-String
    if($uninstallPreview -notmatch 'volume: n1x-mbx-w4-dflash-test-cache'){throw 'Uninstall did not include the configured prepared cache'}
    if($uninstallPreview -notmatch 'volume: n1x-c8-lmc4-ssd160-v1'){throw 'Uninstall did not include the configured LMCache volume'}
}finally{Remove-Item Function:wslc}
Write-Host 'Clean/uninstall scope and offline resource retention checks passed.'
