param([switch]$PrintOnly)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = $PSScriptRoot
$upstream = Join-Path $root 'upstream'
$revision = '1c66e5b1a69c7bab499ff7649b4143e989bd0ed0'
if (-not (Test-Path "$upstream/.git")) {
    & git clone --branch magi-v5-public https://github.com/Saren-Arterius/qwen3.8-Flash-DGX-AutoRound.git $upstream
    if ($LASTEXITCODE -ne 0) { throw 'Upstream clone failed' }
    & git -C $upstream checkout --detach $revision
    if ($LASTEXITCODE -ne 0) { throw 'Upstream checkout failed' }
}
$actual = & git -C $upstream rev-parse HEAD
if ($actual -ne $revision) { throw "Expected upstream $revision, found $actual" }
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
        & wslc @command
        if ($LASTEXITCODE -ne 0) { throw "Build failed ($LASTEXITCODE)" }
    }
}
