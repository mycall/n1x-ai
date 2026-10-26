# Read the persistent environment updated by proxy.ps1 before internet work.
function Get-N1xPersistentProxyEnvironment {
    $values=@{}
    foreach($name in @('HTTP_PROXY','HTTPS_PROXY','NO_PROXY','ALL_PROXY')){
        $value=[Environment]::GetEnvironmentVariable($name,'User')
        if($null -eq $value){$value=[Environment]::GetEnvironmentVariable($name,'Machine')}
        $values[$name]=$value
    }
    return $values
}

function Update-N1xProxyEnvironment {
    if($env:N1X_PROXY_SOURCE -and $env:N1X_PROXY_SOURCE -notin @('auto','process')){
        throw 'N1X_PROXY_SOURCE must be auto, process, or unset.'
    }
    # Explicit opt-out for intentional per-terminal overrides.
    if($env:N1X_PROXY_SOURCE -eq 'process'){return}
    $values=Get-N1xPersistentProxyEnvironment
    $changed=$false
    foreach($name in $values.Keys){
        if([string][Environment]::GetEnvironmentVariable($name) -cne [string]$values[$name]){$changed=$true}
        [Environment]::SetEnvironmentVariable($name,$values[$name],'Process')
    }
    if($changed){Write-Host 'Refreshed proxy settings from the Windows user/machine environment.'}
}

function Get-N1xProxyBuildArguments {
    foreach($name in @('HTTP_PROXY','HTTPS_PROXY','NO_PROXY','ALL_PROXY')){
        foreach($variant in @($name,$name.ToLowerInvariant())){
            # Docker's predefined proxy arguments do not persist in the image.
            '--build-arg'; "$variant=$([Environment]::GetEnvironmentVariable($name))"
        }
    }
}

function Sync-N1xWslcProxy {
    $desired=@{}
    foreach($entry in @(@('HttpProxy','HTTP_PROXY'),@('HttpsProxy','HTTPS_PROXY'),@('NoProxy','NO_PROXY'))){
        $desired[$entry[0]]=[string][Environment]::GetEnvironmentVariable($entry[1])
    }
    $raw=& wslc system session run /usr/bin/curl -fsS --max-time 10 --unix-socket /var/run/docker.sock http://localhost/info
    if($LASTEXITCODE -ne 0){throw 'Cannot inspect WSLC proxy settings. Run setup from an interactive, non-elevated PowerShell.'}
    $info=($raw -join "`n") | ConvertFrom-Json
    $matches=$true
    foreach($key in $desired.Keys){if([string]$info.$key -cne $desired[$key]){$matches=$false}}
    if($matches){Write-Host 'WSLC proxy matches the current shell.'; return $false}
    if($info.ContainersRunning -gt 0){throw 'WSLC proxy differs from the current shell. Stop running WSLC containers, then rerun setup to synchronize it.'}
    # Base64 transports values without interpreting proxy credentials as shell code.
    $assignments=@()
    foreach($entry in @(@('HTTP_PROXY','HttpProxy'),@('HTTPS_PROXY','HttpsProxy'),@('NO_PROXY','NoProxy'))){
        $encoded=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($desired[$entry[1]]))
        $assignments+=('export '+$entry[0]+'=$(printf %s '+"'$encoded'"+' | base64 -d)')
    }
    $script=($assignments -join "`n")+"`n"+@'
set -eu
socket=/var/run/docker.sock
running=$(curl -fsS --max-time 10 --unix-socket "$socket" http://localhost/containers/json)
[ "$running" = '[]' ] || { echo 'Stop WSLC containers before changing the proxy.' >&2; exit 1; }
pid=$(pidof dockerd)
# Preserve existing daemon arguments, removing only previous proxy flags.
args=$(mktemp)
trap 'rm -f "$args"' EXIT
tr '\000' '\n' < "/proc/$pid/cmdline" | awk '
skip {skip=0; next}
/^--(http-proxy|https-proxy|no-proxy)$/ {skip=1; next}
/^--(http-proxy|https-proxy|no-proxy)=/ {next}
{print}
' | tr '\n' '\000' > "$args"
kill -TERM "$pid"
for attempt in $(seq 1 100); do
    if ! kill -0 "$pid" 2>/dev/null; then break; fi
    sleep 0.1
done
if kill -0 "$pid" 2>/dev/null; then echo 'WSLC daemon did not stop.' >&2; exit 1; fi
export http_proxy="$HTTP_PROXY" https_proxy="$HTTPS_PROXY" no_proxy="$NO_PROXY"
unset ALL_PROXY all_proxy
# xargs reads NUL-delimited argv: no eval or string-built command execution.
nohup xargs -0 -a "$args" env >/tmp/n1x-dockerd.log 2>&1 </dev/null &
for attempt in $(seq 1 100); do
    if curl -fsS --max-time 1 --unix-socket "$socket" http://localhost/_ping >/dev/null 2>&1; then exit 0; fi
    sleep 0.1
done
echo 'WSLC daemon did not restart; inspect /tmp/n1x-dockerd.log.' >&2
exit 1
'@
    $encoded=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($script.Replace("`r",'')))
    & wslc system session run /usr/bin/sh -c "echo $encoded | base64 -d | /usr/bin/sh"
    if($LASTEXITCODE -ne 0){throw 'WSLC proxy synchronization failed'}
    $raw=& wslc system session run /usr/bin/curl -fsS --max-time 10 --unix-socket /var/run/docker.sock http://localhost/info
    if($LASTEXITCODE -ne 0){throw 'Cannot verify WSLC proxy settings'}
    $info=($raw -join "`n") | ConvertFrom-Json
    foreach($key in $desired.Keys){if([string]$info.$key -cne $desired[$key]){throw 'WSLC proxy settings did not take effect'}}
    Write-Host 'WSLC proxy synchronized with the current shell.'
    return $true
}
