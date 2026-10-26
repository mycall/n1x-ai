$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
. "$(Split-Path $PSScriptRoot -Parent)/scripts/proxy.ps1"
$names=@('HTTP_PROXY','HTTPS_PROXY','NO_PROXY','ALL_PROXY')
$saved=@{}
$savedSource=$env:N1X_PROXY_SOURCE
foreach($name in $names){$saved[$name]=[Environment]::GetEnvironmentVariable($name)}
try {
    $env:N1X_PROXY_SOURCE='auto'
    $persistent=@{HTTP_PROXY='http://updated.invalid:8080';HTTPS_PROXY='http://updated.invalid:8080';NO_PROXY='localhost';ALL_PROXY=$null}
    function Get-N1xPersistentProxyEnvironment {return $persistent}
    $env:HTTPS_PROXY='http://stale.invalid:8080'
    Update-N1xProxyEnvironment
    if($env:HTTPS_PROXY -ne $persistent.HTTPS_PROXY){throw 'Persistent proxy change not detected'}
    $env:N1X_PROXY_SOURCE='process'
    $env:HTTPS_PROXY='http://terminal.invalid:8080'
    Update-N1xProxyEnvironment
    if($env:HTTPS_PROXY -ne 'http://terminal.invalid:8080'){throw 'Process override discarded'}
    $env:N1X_PROXY_SOURCE=$null
    foreach($name in $names){$persistent[$name]=$null}
    Update-N1xProxyEnvironment
    if($env:HTTPS_PROXY -or $env:HTTP_PROXY){throw 'Stale proxy not cleared after persistent proxy-off'}
    $env:N1X_PROXY_SOURCE='typo'
    try {Update-N1xProxyEnvironment;throw 'Invalid proxy source accepted'}
    catch {if($_.Exception.Message -notlike 'N1X_PROXY_SOURCE must be*'){throw}}
    $env:N1X_PROXY_SOURCE=$null
    $env:HTTP_PROXY='http://example.invalid:8080'
    $env:HTTPS_PROXY=$env:HTTP_PROXY
    $env:NO_PROXY='localhost,127.0.0.1'
    $proxyState=@{HttpProxy='';HttpsProxy='';NoProxy='';ContainersRunning=1;restarts=0}
    function wslc {
        param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)
        $global:LASTEXITCODE=0
        if($Arguments -contains '/usr/bin/curl'){
            $proxyState | ConvertTo-Json -Compress
        } elseif($Arguments -contains '/usr/bin/sh'){
            $proxyState.restarts++
            $proxyState.HttpProxy=[string]$env:HTTP_PROXY
            $proxyState.HttpsProxy=[string]$env:HTTPS_PROXY
            $proxyState.NoProxy=[string]$env:NO_PROXY
        } else {throw 'Unexpected proxy command'}
    }
    try {Sync-N1xWslcProxy; throw 'Active container accepted'}
    catch {if($_.Exception.Message -notlike 'WSLC proxy differs*'){throw}}
    if($proxyState.restarts -ne 0){throw 'Active daemon restarted'}
    $proxyState.ContainersRunning=0
    Sync-N1xWslcProxy
    Sync-N1xWslcProxy
    if($proxyState.restarts -ne 1){throw 'Proxy synchronization not idempotent'}
    $arguments=@(Get-N1xProxyBuildArguments)
    if($arguments -notcontains "HTTPS_PROXY=$env:HTTPS_PROXY" -or $arguments -notcontains "https_proxy=$env:HTTPS_PROXY"){throw 'Build proxy arguments missing'}
    foreach($name in $names){[Environment]::SetEnvironmentVariable($name,$null,'Process')}
    Sync-N1xWslcProxy
    if($proxyState.restarts -ne 2 -or $proxyState.HttpProxy -ne '' -or $proxyState.HttpsProxy -ne ''){throw 'Proxy-off not applied'}
    if(@(Get-N1xProxyBuildArguments) -notcontains 'HTTPS_PROXY='){throw 'Proxy-off build argument missing'}
    Write-Host 'Proxy on/off, active-container guard, and build forwarding checks passed.'
} finally {
    [Environment]::SetEnvironmentVariable('N1X_PROXY_SOURCE',$savedSource,'Process')
    foreach($name in $names){[Environment]::SetEnvironmentVariable($name,$saved[$name],'Process')}
}
