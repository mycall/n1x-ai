$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$root=Split-Path $PSScriptRoot -Parent
. "$root/scripts/myllmbox.ps1"
$fixture=Join-Path ([IO.Path]::GetTempPath()) ('n1x-ple-setup-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory (Join-Path $fixture 'scripts') -Force|Out-Null
@'
function Get-N1xModelDownload($Repository,$Revision,$Directory,$Kind){
    if($Repository -ne 'Saren/Qwen3.8-Flash-Next-ple-table-fp8' -or $Revision -ne '50511b0a41aa1d34b8beb7e5d4bb06a0b650dc14' -or $Kind -ne 'ple'){throw 'Wrong PLE download'}
    $global:n1xStorageFixture.downloads++
}
'@ | Set-Content (Join-Path $fixture 'scripts/models.ps1')
@'
param($Volume,$ModelRoot,$Image,$PythonExecutable)
if($PythonExecutable -ne 'python3'){throw 'MyLLMBox preparation must use python3'}
if($Volume -ne 'fixture-ple' -or $Image -ne ('sha256:'+('a'*64)) -or $ModelRoot -ne 'C:\fixture models'){throw 'Wrong PLE preparation parameters'}
$global:n1xStorageFixture.copies++
$global:n1xStorageFixture.ready=-not $global:n1xStorageFixture.failCopy
if('fixture-ple' -notin $global:n1xStorageFixture.volumes){$global:n1xStorageFixture.volumes+='fixture-ple'}
'@ | Set-Content (Join-Path $fixture 'prepare-native-ple.ps1')
$config=@{PleVolume='fixture-ple';CacheVolume='fixture-cache';ImageId='sha256:'+('a'*64);ModelRoot='C:\fixture models';Profile='fixture'}
$global:n1xStorageFixture=@{volumes=@();ready=$false;downloads=0;copies=0;creates=0;failList=$false;failCopy=$false;running=$false}
function wslc {
    param([Parameter(ValueFromRemainingArguments=$true)]$Arguments)
    $state=$global:n1xStorageFixture
    $global:LASTEXITCODE=0
    switch($Arguments[0]){
        'volume' {
            switch($Arguments[1]){
                'list' {
                    if($state.failList){$global:LASTEXITCODE=1;return}
                    foreach($name in $state.volumes){@{Name=$name}|ConvertTo-Json -Compress}
                }
                'create' {$state.creates++;$state.volumes+= $Arguments[2]}
                'inspect' {if($Arguments[2] -notin $state.volumes){$global:LASTEXITCODE=1}}
                default {throw 'Unexpected volume operation'}
            }
        }
        'list' {if($state.running){'{}'}}
        'run' {
            if($Arguments[[array]::IndexOf($Arguments,'--entrypoint')+1] -ne 'python3'){throw 'MyLLMBox verification must use python3'}
            if($Arguments -notcontains $config.ImageId -or $Arguments[-1] -ne '/checks/check-ple.py'){throw 'Wrong verification image/command'}
            $global:LASTEXITCODE=if($state.ready){0}else{1}
        }
        default {throw 'Unexpected WSLC command'}
    }
}
try{
    try{Confirm-N1xMyllmboxStorage $fixture $config;throw 'Validation mutated missing storage'}
    catch{if($_.Exception.Message -notlike 'Missing or incomplete FP8 PLE volume*'){throw}}
    $global:n1xStorageFixture.failList=$true
    try{Confirm-N1xMyllmboxStorage $fixture $config -Prepare;throw 'Transport failure treated as missing storage'}
    catch{if($_.Exception.Message -notlike 'Cannot inspect WSLC volumes*'){throw}}
    $global:n1xStorageFixture.failList=$false
    $global:n1xStorageFixture.running=$true
    try{Confirm-N1xMyllmboxStorage $fixture $config -Prepare;throw 'Prepared PLE while serving'}
    catch{if($_.Exception.Message -notlike 'Stop managed containers*'){throw}}
    $global:n1xStorageFixture.running=$false
    Confirm-N1xMyllmboxStorage $fixture $config -Prepare
    Confirm-N1xMyllmboxStorage $fixture $config -Prepare
    if($global:n1xStorageFixture.downloads -ne 1 -or $global:n1xStorageFixture.copies -ne 1 -or $global:n1xStorageFixture.creates -ne 1){throw 'Storage setup was not idempotent'}
    $global:n1xStorageFixture.ready=$false
    $global:n1xStorageFixture.failCopy=$true
    try{Confirm-N1xMyllmboxStorage $fixture $config -Prepare -SkipDownload;throw 'Invalid copied PLE accepted'}
    catch{if($_.Exception.Message -notlike 'Prepared FP8 PLE volume failed verification*'){throw}}
    if($global:n1xStorageFixture.downloads -ne 1){throw 'SkipDownload ignored'}
    $global:n1xStorageFixture.failCopy=$false
    Confirm-N1xMyllmboxStorage $fixture $config -Prepare -SkipDownload
    if($global:n1xStorageFixture.copies -ne 3 -or $global:n1xStorageFixture.creates -ne 1){throw 'Incomplete PLE copy did not resume'}
    $global:n1xStorageFixture.ready=$false
    try{Confirm-N1xMyllmboxStorage $fixture $config -Prepare -SkipPleCopy;throw 'SkipPleCopy ignored'}
    catch{if($_.Exception.Message -notlike 'Missing or incomplete FP8 PLE volume*'){throw}}
}finally{
    Remove-Item Function:wslc
    Remove-Variable n1xStorageFixture -Scope Global
    Remove-Item -LiteralPath (Join-Path $fixture 'scripts/models.ps1'),(Join-Path $fixture 'prepare-native-ple.ps1')
    Remove-Item -LiteralPath (Join-Path $fixture 'scripts')
    Remove-Item -LiteralPath $fixture
}
Write-Host 'MyLLMBox PLE and runtime storage recovery checks passed'
