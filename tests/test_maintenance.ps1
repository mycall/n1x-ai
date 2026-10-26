$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$root=Split-Path $PSScriptRoot -Parent
. "$root/scripts/models.ps1"
. "$root/scripts/config.ps1"
. "$root/scripts/upstream.ps1"
$temporary=Join-Path ([IO.Path]::GetTempPath()) ('n1x-maintenance-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temporary | Out-Null
try {
    & git init --quiet $temporary
    if($LASTEXITCODE -ne 0){throw 'Fixture git init failed'}
    [IO.File]::WriteAllText("$temporary/.gitignore",".build/`nresults/`nconfig.local.psd1`nmodels/`n.state/`nnested/`n")
    & git init --quiet "$temporary/nested"
    [IO.File]::WriteAllText("$temporary/nested/source.txt",'ignored checkout')
    foreach($directory in @('results','models','.state')){New-Item -ItemType Directory "$temporary/$directory" | Out-Null}
    New-Item -ItemType Directory -Force "$temporary/results/empty/child","$temporary/.build/empty/.git/objects/info" | Out-Null
    foreach($file in @('results/disposable.txt','config.local.psd1','models/weights.bin','.state/host.json','untracked.txt')){
        [IO.File]::WriteAllText("$temporary/$file",'keep or clean')
    }
    $maintenanceState=@{running=$true}
    function wslc {
        $global:LASTEXITCODE=0
        if($args[0] -eq 'list' -and $maintenanceState.running){'{"Names":"model"}'}
    }
    try {& "$root/scripts/clean.ps1" -Root $temporary -ModelRoot "$temporary/models"; throw 'Running service accepted'}
    catch {if($_.Exception.Message -notlike 'Stop project containers*'){throw}}
    if(-not(Test-Path "$temporary/results/disposable.txt")){throw 'Refusal deleted data'}
    $maintenanceState.running=$false
    & "$root/scripts/clean.ps1" -Root $temporary -ModelRoot "$temporary/models" -PrintOnly | Out-Null
    if(-not(Test-Path "$temporary/results/disposable.txt")){throw 'Preview deleted data'}
    & "$root/scripts/clean.ps1" -Root $temporary -ModelRoot "$temporary/models"
    if(Test-Path "$temporary/results/disposable.txt"){throw 'Ignored file retained'}
    if(Test-Path "$temporary/nested/source.txt"){throw 'Ignored checkout retained'}
    if(Test-Path "$temporary/nested/.git"){throw 'Empty Git directories retained'}
    foreach($directory in @('.build','.state','results')){
        if(Test-Path "$temporary/$directory"){throw "Generated directory retained: $directory"}
    }
    & "$root/scripts/clean.ps1" -Root $temporary -ModelRoot "$temporary/models" -PrintOnly | Out-Null
    foreach($file in @('config.local.psd1','models/weights.bin','untracked.txt')){
        if(-not(Test-Path "$temporary/$file")){throw "Protected file deleted: $file"}
    }
    New-Item -ItemType Directory "$temporary/.build" | Out-Null
    [IO.File]::WriteAllText("$temporary/.build/tracked.txt",'tracked exception')
    [IO.File]::WriteAllText("$temporary/.build/disposable.txt",'generated')
    & git -C $temporary add -f .build/tracked.txt
    if($LASTEXITCODE -ne 0){throw 'Cannot create tracked-file fixture'}
    & "$root/scripts/clean.ps1" -Root $temporary -ModelRoot "$temporary/models"
    if(-not(Test-Path "$temporary/.build/tracked.txt") -or (Test-Path "$temporary/.build/disposable.txt")){throw 'Tracked file inside ignored directory not protected'}
    $model="$temporary/models"
    New-Item -ItemType Directory -Force "$model/.cache/huggingface/download" | Out-Null
    foreach($file in @('config.json','model.safetensors')){
        [IO.File]::WriteAllText("$model/$file",'fixture')
        $timestamp=([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()+5).ToString()
        [IO.File]::WriteAllText("$model/.cache/huggingface/download/$file.metadata","revision`nhash`n$timestamp")
    }
    if(-not(Test-N1xModelDownload $model 'revision' 'drafter')){throw 'Complete pinned download not recognized'}
    if(Test-N1xModelDownload $model 'wrong' 'drafter'){throw 'Wrong revision accepted'}
    Remove-Item -LiteralPath "$model/model.safetensors"
    if(Test-N1xModelDownload $model 'revision' 'drafter'){throw 'Partial download accepted'}
    # Exercise the public setup dispatch without invoking downloads or builds.
    New-Item -ItemType Directory "$temporary/scripts" | Out-Null
    Copy-Item "$root/n1x.ps1" "$temporary/n1x.ps1"
    Copy-Item "$root/scripts/config.ps1" "$temporary/scripts/config.ps1"
    Set-Content "$temporary/scripts/firewall.ps1" 'function Set-N1xFirewall { param($Root,$Port,[switch]$Remove) }'
    Set-Content "$temporary/scripts/clients.ps1" 'function Sync-N1xClients { param($Root,$Port,$Context,[switch]$Remove) }'
    [IO.File]::WriteAllText("$temporary/setup.ps1",@'
param([string]$ModelRoot,[switch]$WithLMCache,[switch]$SkipDownload,[switch]$SkipBuild,[switch]$SkipPleCopy,[switch]$Rebuild)
if(-not $WithLMCache -or -not $SkipBuild -or $ModelRoot -ne '~\Models'){throw 'Setup arguments not forwarded'}
'@)
    & "$temporary/n1x.ps1" setup -ModelRoot '~\Models' -SkipBuild
    $tildeConfig=Get-N1xConfig -Root $root -ModelRoot '~\Models'
    if($tildeConfig.ModelRoot -ne (Join-Path ([Environment]::GetFolderPath('UserProfile')) 'Models')){throw 'Home expansion failed'}
    # An empty nested .git must not inherit the parent checkout's HEAD.
    $origin="$temporary/origin"
    & git init --quiet $origin
    [IO.File]::WriteAllText("$origin/source.txt",'upstream fixture')
    & git -C $origin add source.txt
    & git -C $origin -c user.name=Test -c user.email=test@example.invalid commit --quiet -m fixture
    if($LASTEXITCODE -ne 0){throw 'Fixture commit failed'}
    $revision=& git -C $origin rev-parse HEAD
    New-Item -ItemType Directory -Force "$temporary/upstream/.git/objects/info" | Out-Null
    Initialize-N1xUpstream $temporary $origin $revision
    Initialize-N1xUpstream $temporary $origin $revision
    if(-not(Test-Path "$temporary/upstream/source.txt")){throw 'Incomplete upstream not repaired'}
    Write-Host 'Maintenance checks passed.'
} finally {
    $resolved=[IO.Path]::GetFullPath($temporary)
    $tempRoot=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')+'\'
    if(-not $resolved.StartsWith($tempRoot,[StringComparison]::OrdinalIgnoreCase) -or (Split-Path $resolved -Leaf) -notlike 'n1x-maintenance-*'){throw 'Unsafe fixture cleanup path'}
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
