$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$root=Split-Path $PSScriptRoot -Parent
. "$root/scripts/config.ps1"
. "$root/scripts/myllmbox.ps1"
$config=Get-N1xConfig -Root $root -Profile qwen38fn-best
function OptionValue($Arguments,$Name){
    $index=[array]::IndexOf($Arguments,$Name)
    if($index -lt 0){throw "Missing argument $Name"}
    return $Arguments[$index+1]
}
foreach($slots in @(4,8)){
    $config.MaxSequences=$slots
    $arguments=@(Get-N1xMyllmboxArguments $root $config 'fixture-sha')
    if($arguments -notcontains $config.ImageId){throw 'Immutable image is missing'}
    if((OptionValue $arguments '--served-model-name') -ne 'qwen/qwen38fn-best' -or $arguments -contains 'qwen'){throw 'Client-facing model name changed'}
    if((OptionValue $arguments '--max-num-seqs') -ne [string]$slots){throw 'Slot override lost'}
    if((OptionValue $arguments '--kv-cache-memory-bytes') -ne '11811160064'){throw 'KV pool changed'}
    $spec=OptionValue $arguments '--speculative-config'|ConvertFrom-Json
    if($spec.method -ne 'dflash' -or $spec.num_speculative_tokens -ne 3 -or -not $spec.disable_eagle_block_drop){throw 'Draft contract changed'}
    $graphs=OptionValue $arguments '--compilation-config'|ConvertFrom-Json
    if($graphs.cudagraph_capture_sizes[-1] -ne 4*$slots -or $graphs.compile_ranges_endpoints[0] -ne 4*$slots){throw 'Graph bounds do not follow slots'}
    $generation=OptionValue $arguments '--override-generation-config'|ConvertFrom-Json
    if($generation.max_new_tokens -ne 8192){throw 'Output allowance changed'}
    foreach($required in @('HF_HUB_OFFLINE=1','TRANSFORMERS_OFFLINE=1','N1X_LMCACHE_ENABLED=1','n1x-ai.config-sha=fixture-sha')){
        if($arguments -notcontains $required){throw "Missing $required"}
    }
    foreach($target in @('/model:ro','/drafter:ro','/ple-table-fp8:ro','/state:ro')){
        if(-not @($arguments|Where-Object {$_.EndsWith($target)}).Count){throw "Missing read-only mount $target"}
    }
}
$environment=Get-N1xMyllmboxEnvironment $root $config
foreach($name in @('N1X_LMCACHE_L1_GIB','N1X_LMCACHE_L2_GIB','N1X_CACHE_NAMESPACE')){
    if(-not $environment[$name]){throw "Missing cache setting $name"}
}
if($environment.N1X_LMCACHE_L1_GIB -ne '4' -or $environment.N1X_LMCACHE_L2_GIB -ne '160' -or $arguments -notcontains 'n1x-c8-lmc4-ssd160-v1:/lmcache'){throw 'Promoted cache geometry/mount changed'}
$config.UseLMCache=$false
$off=@(Get-N1xMyllmboxArguments $root $config 'cache-off-fixture')
if($off -notcontains 'N1X_LMCACHE_ENABLED=0' -or @($off|Where-Object {$_.EndsWith(':/lmcache')}).Count){throw 'Cache-off launch inherited cache storage'}
$config.UseLMCache=$true
$preview=& "$root/n1x.ps1" start -Profile qwen38fn-best -ModelRoot "C:\model files\owner's models" -PrintOnly
function wslc { $script:previewArguments=@($args) }
try{
    Invoke-Expression $preview
    $decoded=OptionValue $script:previewArguments '--speculative-config'|ConvertFrom-Json
    if($decoded.method -ne 'dflash'){throw 'Preview quoting corrupts JSON'}
    if($script:previewArguments -notcontains "C:\model files\owner's models\Qwen3.8-Flash-Next-DFlash2:/drafter:ro"){throw 'Preview quoting corrupts model paths'}
}finally{Remove-Item Function:wslc}
New-Item -ItemType Directory -Force "$root/.state"|Out-Null
$lock=[IO.File]::Open("$root/.state/native-lifecycle.lock",[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
try{
    try{& "$root/n1x.ps1" start -Profile qwen38fn-best;throw 'Concurrent lifecycle accepted'}
    catch{if($_.Exception.Message -notlike 'Another serving lifecycle or qualification command*'){throw}}
}finally{$lock.Dispose()}
$script:unexpectedHttp=$false
function wslc {
    param([Parameter(ValueFromRemainingArguments=$true)]$Arguments)
    $global:LASTEXITCODE=0
    switch($Arguments[0]){
        'list' {@{Names='n1x-qwen38fn-best'}|ConvertTo-Json -Compress}
        'inspect' {@(@{Config=@{Labels=@{'n1x-ai.managed'='true';'n1x-ai.config-sha'='different-settings'}};State=@{Running=$true}})|ConvertTo-Json -Depth 5 -Compress}
        default {throw 'Unexpected WSLC action in configuration guard fixture'}
    }
}
function Invoke-WebRequest {$script:unexpectedHttp=$true;throw 'Unexpected HTTP request'}
try{
    foreach($action in @('wait','test')){
        try{& "$root/n1x.ps1" $action -Profile qwen38fn-best;throw 'Changed running configuration accepted'}
        catch{if($_.Exception.Message -notlike 'Container settings differ*'){throw}}
    }
    if($script:unexpectedHttp){throw 'Configuration mismatch sent an API request'}
}finally{Remove-Item Function:wslc;Remove-Item Function:Invoke-WebRequest}
Write-Host 'MyLLMBox offline launch contract checks passed'

# Rebuilding is explicit and cannot silently retag the selected runtime.
$buildPreview=& "$root/build.ps1" -Myllmbox -Rebuild -LmcacheFromSource -PrintOnly
$publicPreview=& "$root/n1x.ps1" build -Profile qwen38fn-best -Rebuild -LmcacheFromSource -PrintOnly
if($publicPreview -ne $buildPreview){throw 'Public build did not forward the selected recipe/options'}
$customPreview=& "$root/n1x.ps1" build -Profile qwen38fn-best -ImageTag n1x-ai:fixture-candidate -PrintOnly
if($customPreview -notlike '*n1x-ai:fixture-candidate*'){throw 'Public build did not forward the candidate tag'}
try{& "$root/n1x.ps1" start -LmcacheFromSource -PrintOnly;throw 'Build option accepted by start'}
catch{if($_.Exception.Message -ne '-LmcacheFromSource and -ImageTag are build options'){throw}}
foreach($required in @('Dockerfile.myllmbox-lmcache','--no-cache','N1X_LMCACHE_FROM_SOURCE=1','n1x-ai:mbx-cache-candidate')){
    if($buildPreview -notlike "*$required*"){throw "Rebuild preview omitted $required"}
}
try{& "$root/build.ps1" -Myllmbox -ImageTag $config.Image -PrintOnly;throw 'Selected serving tag accepted for overwrite'}
catch{if($_.Exception.Message -notlike 'Choose a candidate tag*'){throw}}
try{& "$root/build.ps1" -LmcacheFromSource -PrintOnly;throw 'Source build accepted for wrong backend'}
catch{if($_.Exception.Message -notlike '*require -Myllmbox'){throw}}
$script:volumeExists=$false
$script:volumeCreates=0
function wslc {
    param([Parameter(ValueFromRemainingArguments=$true)]$Arguments)
    if($Arguments[0] -ne 'volume' -or $Arguments[2] -ne $config.LmcacheVolume){throw 'Unexpected volume action'}
    if($Arguments[1] -eq 'create'){$script:volumeCreates++;$script:volumeExists=$true}
    elseif($Arguments[1] -ne 'inspect'){throw 'Unexpected volume mutation'}
    $global:LASTEXITCODE=if($script:volumeExists){0}else{1}
}
try{
    try{Confirm-N1xMyllmboxCacheVolume $config;throw 'Missing cache accepted'}
    catch{if($_.Exception.Message -notlike 'Missing LMCache volume*'){throw}}
    if($script:volumeCreates){throw 'Read-only validation created storage'}
    Confirm-N1xMyllmboxCacheVolume $config -CreateIfMissing
    Confirm-N1xMyllmboxCacheVolume $config -CreateIfMissing
    if($script:volumeCreates -ne 1){throw 'Cache preparation was not idempotent'}
}finally{Remove-Item Function:wslc}
Write-Host 'MyLLMBox rebuild preview and missing-cache preparation checks passed'
