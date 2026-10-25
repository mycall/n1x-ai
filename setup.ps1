param([string]$ModelRoot='', [switch]$WithLMCache, [switch]$SkipDownload, [switch]$SkipBuild, [switch]$SkipPleCopy, [switch]$Rebuild)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
. "$PSScriptRoot/scripts/config.ps1"
. "$PSScriptRoot/scripts/models.ps1"
$config=Get-N1xConfig -Root $PSScriptRoot -Profile baseline -ModelRoot $ModelRoot
foreach($command in @('git','wslc')){if(-not(Get-Command $command -ErrorAction SilentlyContinue)){throw "Install $command and add it to PATH before setup"}}
$models=@(
    @('Saren/Qwen3.8-Flash-Next-W4A16-AutoRound-hybrid','8b82f0b7abe3d1150a7827d298c75e86267636ae','Qwen3.8-Flash-Next-W4A16-AutoRound-hybrid','main'),
    @('Saren/Qwen3.8-Flash-Next-ple-table-fp8','50511b0a41aa1d34b8beb7e5d4bb06a0b650dc14','ple-table-fp8','ple')
)
if($WithLMCache){
    $models+=,@('incoai/Qwen3.8-Flash-Next-DFlash2','a22a1744e85c17364dcc54a6a420af7135d4c7f6','Qwen3.8-Flash-Next-DFlash2','drafter')
}
if(-not $SkipDownload){
    New-Item -ItemType Directory -Force $config.ModelRoot|Out-Null
    foreach($model in $models){
        Get-N1xModelDownload $model[0] $model[1] (Join-Path $config.ModelRoot $model[2]) $model[3]
    }
}
if(-not $SkipBuild){
    $raw=& wslc images --format json
    if($LASTEXITCODE -ne 0){throw 'Cannot inspect local images'}
    $tags=@($raw | Where-Object {$_.Trim()} | ForEach-Object {$row=$_|ConvertFrom-Json; $row.Repository+':'+$row.Tag})
    $required=@('n1x-ai-base:cuda13.4-ubuntu26.04-vllm0.32.0','n1x-ai:magi-v5')
    if($WithLMCache){$required+='n1x-ai:lmcache'}
    if($Rebuild -or @($required | Where-Object {$_ -notin $tags}).Count){& "$PSScriptRoot/build.ps1" -WithLMCache:$WithLMCache}
    else {Write-Host 'Reusing local runtime images. Use setup -Rebuild to apply image-source changes.'}
}
if(-not $SkipPleCopy){
    $raw=& wslc volume list --format json
    if($LASTEXITCODE -ne 0){throw 'Cannot inspect native PLE volumes'}
    $volumes=@($raw | Where-Object {$_.Trim()} | ForEach-Object {($_|ConvertFrom-Json).Name})
    $ready=$false
    if($config.PleVolume -in $volumes){
        & wslc run --rm --entrypoint python --volume "$($config.PleVolume):/table:ro" --volume "${PSScriptRoot}/scripts:/checks:ro" $config.Image /checks/check-ple.py
        $ready=$LASTEXITCODE -eq 0
    }
    if(-not $ready){& "$PSScriptRoot/prepare-native-ple.ps1" -ModelRoot $config.ModelRoot -Volume $config.PleVolume}
    else {Write-Host 'Reusing prepared native PLE volume.'}
}
$localPath=Join-Path $PSScriptRoot 'config.local.psd1'
$settings=if(Test-Path -LiteralPath $localPath){Import-PowerShellDataFile $localPath}else{@{}}
$settings['ModelRoot']=$config.ModelRoot
$settings['DefaultProfile']=if($WithLMCache){'cache-dflash'}else{'baseline'}
$lines=@('@{')
foreach($key in ($settings.Keys|Sort-Object)){
    $value=$settings[$key]
    if($value -is [bool]){$literal=if($value){'$true'}else{'$false'}}
    elseif($value -is [string]){$literal="'"+$value.Replace("'","''")+"'"}
    elseif($value -is [ValueType]){$literal=[string]$value}
    else{throw "Unsupported local setting type: $key; edit config.local.psd1 manually"}
    $lines+="    $key = $literal"
}
$lines+='}'
[IO.File]::WriteAllText($localPath,($lines -join "`n"),[Text.UTF8Encoding]::new($false))
Write-Host "Setup complete. Default profile: $($settings.DefaultProfile)"
Write-Host 'Next: .\n1x.ps1 start; .\n1x.ps1 wait; .\n1x.ps1 test'
