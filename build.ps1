param([switch]$PrintOnly,[switch]$WithLMCache,[switch]$CacheOnly)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = $PSScriptRoot
. "$root/scripts/proxy.ps1"
if($PrintOnly){
    if(-not $CacheOnly){
        Write-Output "git clone --branch magi-v5-public https://github.com/Saren-Arterius/qwen3.8-Flash-DGX-AutoRound.git $root/upstream"
        Write-Output "git -C $root/upstream checkout --detach 1c66e5b1a69c7bab499ff7649b4143e989bd0ed0"
        Write-Output "wslc build -t n1x-ai-base:cuda13.4-ubuntu26.04-vllm0.32.0 -f $root/Dockerfile.base $root"
        Write-Output "wslc build -t n1x-ai:magi-v5 -f $root/.build/Dockerfile.magi $root/upstream/recipe/build/image"
    }
    if($WithLMCache -or $CacheOnly){Write-Output "wslc build -t n1x-ai:lmcache -f $root/Dockerfile.lmcache $root"}
    return
}
Update-N1xProxyEnvironment
$resetSession=Sync-N1xWslcProxy
try {
$proxyArguments=@(Get-N1xProxyBuildArguments)
if(-not $CacheOnly){
$upstream = Join-Path $root 'upstream'
$revision = '1c66e5b1a69c7bab499ff7649b4143e989bd0ed0'
. "$root/scripts/upstream.ps1"
Initialize-N1xUpstream $root 'https://github.com/Saren-Arterius/qwen3.8-Flash-DGX-AutoRound.git' $revision
$generated = Join-Path $root '.build'
New-Item -ItemType Directory -Force $generated | Out-Null
$dockerfile = Get-Content "$upstream/recipe/build/image/Dockerfile.v032" -Raw
$dockerfile = $dockerfile -replace '(?m)^FROM .+$', 'FROM n1x-ai-base:cuda13.4-ubuntu26.04-vllm0.32.0'
[IO.File]::WriteAllText("$generated/Dockerfile.magi", $dockerfile.Replace("`r`n", "`n"), [Text.UTF8Encoding]::new($false))
$commands = @(
    @('build', '--progress', 'plain', '-t', 'n1x-ai-base:cuda13.4-ubuntu26.04-vllm0.32.0', '-f', "$root/Dockerfile.base", $root),
    @('build', '--progress', 'plain', '-t', 'n1x-ai:magi-v5', '-f', "$generated/Dockerfile.magi", "$upstream/recipe/build/image")
)
foreach ($command in $commands) {
    Write-Host ('wslc ' + ($command -join ' '))
    if (-not $PrintOnly) {
        $withProxy=@($command[0])+$proxyArguments+@($command[1..($command.Length-1)])
        & wslc @withProxy
        if ($LASTEXITCODE -ne 0) { throw "Build failed ($LASTEXITCODE)" }
    }
}
}
if($WithLMCache -or $CacheOnly){
    $arguments=@('build')+$proxyArguments+@('--progress','plain','-t','n1x-ai:lmcache','-f',"$root/Dockerfile.lmcache")
    foreach($entry in @(@('https_proxy','HTTPS_PROXY'),@('http_proxy','HTTP_PROXY'))){
        if([Environment]::GetEnvironmentVariable($entry[1])){$arguments+=@('--secret',"id=$($entry[0]),env=$($entry[1])")}
    }
    $arguments+=$root
    if($PrintOnly){Write-Output ('wslc '+($arguments -join ' '))}
    else{& wslc @arguments;if($LASTEXITCODE -ne 0){throw 'LMCache image build failed'}}
}
} finally {
    if($resetSession){
        # WSLC lifecycle event subscriptions do not survive replacing dockerd.
        # Builds require an idle session; close it so serving gets fresh state.
        & wslc system session terminate
        if($LASTEXITCODE -ne 0){Write-Warning 'Reset the idle WSLC session before serving: wslc system session terminate'}
    }
}
