param([string]$Action,[hashtable]$Config,[int]$TimeoutSeconds,[string]$Suite,[switch]$PrintOnly)
$ErrorActionPreference='Stop'
$root=if($Config.ContainsKey('InfernixRoot')){$Config.InfernixRoot}else{Join-Path $PSScriptRoot '../../Infernix-dgx-spark-gb10'}
$root=(Resolve-Path -LiteralPath $root).Path
$launcher=Join-Path $root 'tools/run_wslc_hc4_dflash2.ps1'
$name=$Config.Container
$url="http://127.0.0.1:$($Config.Port)"
$options=@{Name=$name;Image=$Config.InfernixImage;NgramVolume=$Config.InfernixVolume;ModelsDirectory=$Config.ModelRoot;Port=$Config.Port;MaxConcurrency=$Config.MaxSequences;MaxContext=$Config.Context;DefaultMaxTokens=$Config.MaxOutputTokens}
function Invoke-Container([string[]]$Arguments){
    & wslc @Arguments
    if($LASTEXITCODE){throw "WSLC $($Arguments[0]) failed for $name"}
}
function Assert-Ready {
    if((Invoke-RestMethod "$url/health" -TimeoutSec 5).status -ne 'ok' -or 'infernix-hc4' -cnotin (Invoke-RestMethod "$url/v1/models" -TimeoutSec 5).data.id){throw "Expected infernix-hc4 at $url"}
}
if($Action -notin @('build','start','status','wait','test','logs','stop','restart','recreate','doctor','setup')){throw "Infernix does not implement $Action"}
if($Action -eq 'test' -and $Suite -ne 'smoke'){throw 'The Infernix profile supports the smoke suite.'}
if($Action -eq 'setup'){
    & "$root/tools/prepare_wslc_hc4_ngram.ps1" -NgramVolume $Config.InfernixVolume -ModelsDirectory $Config.ModelRoot -Image $Config.InfernixImage -PrintOnly:$PrintOnly
    return
}
if($PrintOnly){
    if($Action -in 'start','recreate'){& $launcher @options -PrintOnly}
    elseif($Action -eq 'build'){"wslc build -f $(Join-Path $root Dockerfile.n1x) -t $($Config.InfernixImage) $root"}
    else{"$Action $name ($url, infernix-hc4)"}
    return
}
if($Action -eq 'build'){Invoke-Container @('build','-f',(Join-Path $root Dockerfile.n1x),'-t',$Config.InfernixImage,$root);return}
if($Action -eq 'doctor'){
    & $launcher @options -PrintOnly | Out-Null
    Invoke-Container @('volume','inspect',$Config.InfernixVolume)
    Invoke-Container @('image','inspect',$Config.InfernixImage)
    return
}
$containers=@(Invoke-Container @('ps','-a','--format','json') | ForEach-Object {$_ | ConvertFrom-Json})
$exists=@($containers|Where-Object Names -ceq $name).Count -gt 0
if($exists){
    $info=@((Invoke-Container @('inspect',$name)) -join "`n" | ConvertFrom-Json)[0]
    if($info.Config.Image -cne $Config.InfernixImage -or $info.Config.Cmd[0] -cne 'infernix-serve' -or 'infernix-hc4' -cnotin $info.Config.Cmd){throw "Container $name belongs to another configuration"}
}
if($Action -eq 'status'){
    if(!$exists){return "$name has not been created"}
    if(!$info.State.Running){return "$name is stopped"}
    Assert-Ready
    return "$name is ready at $url/v1 (infernix-hc4)"
}
if($Action -eq 'recreate' -and $exists){if($info.State.Running){Invoke-Container @('stop',$name)};Invoke-Container @('rm',$name);$exists=$false}
if($Action -in 'start','recreate' -and !$exists){& $launcher @options;return}
if(!$exists){if($Action -eq 'stop'){return};throw "Container $name has not been created"}
if($Action -in 'wait','start','restart','test'){
    $expected=& $launcher @options -PrintOnly | Out-String | ConvertFrom-Json
    $imageIndex=[array]::IndexOf($expected,$Config.InfernixImage)
    $mountsMatch=$true
    foreach($spec in $expected | Where-Object {$_ -like 'type=*,source=*,target=*,readonly'}){
        if($spec -match '^type=(bind|volume),source=(.+),target=([^,]+),readonly$'){
            $mounted=@($info.Mounts | Where-Object Destination -ceq $Matches[3])
            if($mounted.Count -ne 1 -or $mounted[0].Source -ne $Matches[2] -or $mounted[0].Type -ne $Matches[1]){$mountsMatch=$false}
        }
    }
    if(!$mountsMatch -or $imageIndex -lt 0 -or ($info.Config.Cmd -join [char]0) -cne ($expected[($imageIndex+1)..($expected.Count-1)] -join [char]0) -or
        $info.Ports.'8002/tcp'[0].HostPort -ne "$($Config.Port)"){throw "Configuration changed for $name. Use recreate to apply it."}
}
switch($Action){
    start {if(!$info.State.Running){Invoke-Container @('start',$name)}}
    restart {Invoke-Container @('restart',$name)}
    stop {if($info.State.Running){Invoke-Container @('stop',$name)}}
    logs {Invoke-Container @('logs','--tail','100',$name)}
    wait {
        if(!$info.State.Running){throw "$name is stopped"}
        try { Assert-Ready;return "$name is ready" } catch {}
        $reader=Start-Job -ScriptBlock {param($n,$at) wslc logs --since $at --follow $n 2>&1|Where-Object {"$_" -match 'listening on http|FATAL| ERROR '}|Select-Object -First 1} -ArgumentList $name,([DateTimeOffset]$info.State.StartedAt).ToUnixTimeSeconds()
        try {
            if(!(Wait-Job $reader -Timeout $TimeoutSeconds)){throw "Timed out waiting for $name"}
            Receive-Job $reader
            Assert-Ready
        }finally{Remove-Job $reader -Force}
    }
    test {
        Assert-Ready
        $body=@{model='infernix-hc4';messages=@(@{role='user';content='Reply with exactly READY.'});temperature=0;max_tokens=32;chat_template_kwargs=@{enable_thinking=$false}}|ConvertTo-Json -Depth 6
        $reply=Invoke-RestMethod "$url/v1/chat/completions" -Method Post -ContentType application/json -Body $body -TimeoutSec $TimeoutSeconds
        if($reply.choices[0].message.content.Trim() -cne 'READY'){throw 'Infernix smoke response did not match READY'}
        'Infernix smoke passed'
    }
}
