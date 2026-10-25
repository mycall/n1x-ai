param([string]$ModelRoot='', [switch]$WithLMCache, [switch]$SkipDownload, [switch]$SkipBuild, [switch]$SkipPleCopy)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
. "$PSScriptRoot/scripts/config.ps1"
$config=Get-N1xConfig -Root $PSScriptRoot -Profile baseline -ModelRoot $ModelRoot
foreach($command in @('git','wslc')){if(-not(Get-Command $command -ErrorAction SilentlyContinue)){throw "Install $command and add it to PATH before setup"}}
if(-not $SkipDownload -and -not(Get-Command hf -ErrorAction SilentlyContinue)){throw 'Install the Hugging Face CLI (hf) first; see wiki/Installation.md'}
$models=@(
    @('Saren/Qwen3.8-Flash-Next-W4A16-AutoRound-hybrid','8b82f0b7abe3d1150a7827d298c75e86267636ae','Qwen3.8-Flash-Next-W4A16-AutoRound-hybrid'),
    @('Saren/Qwen3.8-Flash-Next-ple-table-fp8','50511b0a41aa1d34b8beb7e5d4bb06a0b650dc14','ple-table-fp8')
)
if(-not $SkipDownload){
    New-Item -ItemType Directory -Force $config.ModelRoot|Out-Null
    foreach($model in $models){
        & hf download $model[0] --revision $model[1] --local-dir (Join-Path $config.ModelRoot $model[2])
        if($LASTEXITCODE -ne 0){throw 'Model download failed; rerun setup to resume'}
    }
}
if(-not $SkipBuild){& "$PSScriptRoot/build.ps1" -WithLMCache:$WithLMCache}
if(-not $SkipPleCopy){& "$PSScriptRoot/prepare-native-ple.ps1" -ModelRoot $config.ModelRoot -Volume $config.PleVolume}
$localPath=Join-Path $PSScriptRoot 'config.local.psd1'
$settings=if(Test-Path -LiteralPath $localPath){Import-PowerShellDataFile $localPath}else{@{}}
$settings['ModelRoot']=$config.ModelRoot
$settings['DefaultProfile']=if($WithLMCache){'cache-mtp'}else{'baseline'}
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
