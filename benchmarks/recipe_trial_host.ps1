param([Parameter(Mandatory)][string]$Variant,[Parameter(Mandatory)][string]$Out,[ValidateSet('launch','capture','stop','restart')][string]$Action='launch')
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
. "$root/scripts/config.ps1"
. "$root/scripts/native.ps1"
. "$root/scripts/myllmbox.ps1"
$v=Get-Content -LiteralPath $Variant -Raw | ConvertFrom-Json -AsHashtable
$c=Get-N1xConfig -Root $root -Profile qwen38fn-best
foreach($k in $v.config.Keys){$c[$k]=$v.config[$k]}
if($c.Container -ne 'n1x-recipe-trial'){throw 'Only the isolated recipe trial container is supported'}
New-Item -ItemType Directory -Force $Out | Out-Null
if($Action -eq 'stop'){
    & wslc stop $c.Container
    exit $LASTEXITCODE
}
if($Action -eq 'restart'){
    & wslc stop $c.Container | Out-Null
    if($LASTEXITCODE){throw 'Cannot stop trial for restore test'}
    Start-N1xMyllmboxMonitor $root $c
    & wslc start $c.Container
    if($LASTEXITCODE){throw 'Cannot restart trial for restore test'}
    exit
}
if($Action -eq 'capture'){
    $gpuFree=[int]((& nvidia-smi --id=0 --query-gpu=memory.free --format=csv,noheader,nounits | Out-String).Trim())
    $record=@{config=$c;server=(& wslc inspect $c.Container | Out-String | ConvertFrom-Json);models=(Invoke-RestMethod 'http://127.0.0.1:8000/v1/models');gpu=(& nvidia-smi --id=0 --query-gpu=name,driver_version,memory.total,memory.used --format=csv,noheader | Out-String);gpuFreeMiB=$gpuFree;recordedUtc=[datetime]::UtcNow.ToString('o')}
    $record | ConvertTo-Json -Depth 40 | Set-Content "$Out/host.json"
    if($gpuFree -lt 2048){throw 'Less than 2 GiB GPU headroom; reduce candidate allocation before benchmarking'}
    exit
}
$running=@(& wslc list --format json | Where-Object {$_.Trim()})
if($LASTEXITCODE -ne 0 -or $running.Count){throw 'Trial requires no running WSLC containers'}
if(((& nvidia-smi --id=0 --query-gpu=memory.total --format=csv,noheader,nounits)|Out-String).Trim() -ne '98304'){throw 'Trial requires 96 GiB GPU allocation'}
$releaseDeadline=(Get-Date).AddSeconds(90)
while([int]((& nvidia-smi --id=0 --query-gpu=memory.used --format=csv,noheader,nounits | Out-String).Trim()) -gt 4096){
    if((Get-Date) -gt $releaseDeadline){throw 'GPU allocations have not returned to idle after the previous trial'}
    Start-Sleep -Seconds 3
}
$paths=Get-N1xMyllmboxPaths $root $c
Copy-Item -LiteralPath $paths.Recipe -Destination (Join-Path $Out 'recipe.yaml')
Copy-Item -LiteralPath $paths.Environment -Destination (Join-Path $Out 'environment.psd1')
foreach($file in @('config.json','model.safetensors.index.json','tokenizer.json','tokenizer_config.json','chat_template.jinja')){
    if(-not(Test-Path -LiteralPath (Join-Path $paths.Model $file))){throw "Model download is incomplete: $file"}
}
if($c.UseLMCache -and -not $c.LmcacheNamespace.StartsWith('qwen-')){throw 'Trial LMCache namespace must start with qwen-'}
& wslc inspect $c.Container 2>$null | Out-Null
if($LASTEXITCODE -eq 0){& wslc rm $c.Container | Out-Null; if($LASTEXITCODE){throw 'Cannot remove stopped trial container'}}
foreach($volume in @($c.CacheVolume)+$(if($c.UseLMCache){@($c.LmcacheVolume)}else{@()})){
    & wslc volume inspect $volume 2>$null | Out-Null
    if($LASTEXITCODE){
        & wslc volume create $volume | Out-Null
        if($LASTEXITCODE){throw 'Cannot prepare trial volume'}
    }
}
if($v.ContainsKey('prepare_mtp10') -and $v.prepare_mtp10){
    $paths=Get-N1xMyllmboxPaths $root $c
    & wslc run --rm --entrypoint python3 --volume "$($paths.Model):/model:ro" --volume "$($c.CacheVolume):/cache" --volume "${root}/benchmarks:/benchmarks:ro" $c.ImageId /benchmarks/prepare_mtp_draft.py /model /cache/draft-k10
    if($LASTEXITCODE){throw 'Cannot prepare ten-expert MTP view'}
}
Start-N1xMyllmboxMonitor $root $c
$a=@(Get-N1xMyllmboxArguments $root $c 'recipe-trial')
if($v.ContainsKey('loader_diagnostics') -and $v.loader_diagnostics){
    $diagnostics=Join-Path $root 'results/benchmarks/recipe-mix-20261116/runtime-source/loader_utils_diagnostic.py'
    if(-not(Test-Path -LiteralPath $diagnostics)){throw 'Missing diagnostic loader'}
    $imageIndex=[array]::IndexOf($a,[string]$c.ImageId)
    if($imageIndex -lt 1){throw 'Cannot locate image argument for diagnostic mount'}
    $a=@($a[0..($imageIndex-1)])+@('--volume',"${diagnostics}:/usr/local/lib/python3.12/dist-packages/vllm/model_executor/model_loader/utils.py:ro")+@($a[$imageIndex..($a.Count-1)])
}
# Explicit trial overrides are applied after the regular argument generator.
foreach($k in $v.flags.Keys){
    $flag='--'+$k
    $idx=[array]::IndexOf($a,$flag)
    if($idx -ge 0){$a[$idx+1]=[string]$v.flags[$k]}else{$a+=@($flag,[string]$v.flags[$k])}
}
$a | ConvertTo-Json -Depth 8 | Set-Content "$Out/launch-arguments.json"
$c | ConvertTo-Json -Depth 8 | Set-Content "$Out/config.json"
& wslc @a
if($LASTEXITCODE){throw 'Trial launch failed'}
