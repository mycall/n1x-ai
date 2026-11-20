param(
    [Parameter(Mandatory)][ValidateSet('seed','verify')][string]$Stage,
    [Parameter(Mandatory)][string]$Directory
)
$ErrorActionPreference = 'Stop'
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$trial = (wslc inspect n1x-trial-v033 | ConvertFrom-Json)[0]
if (-not $trial.State.Running -or $trial.Config.Image -ne 'n1x-ai:v033-serving-lmcache') {
    throw 'The 0.33 LMCache trial must be running'
}
if ($Stage -eq 'seed') {
    if (Test-Path $Directory) { throw 'Choose a new results directory for the cold seed' }
    $null = New-Item -ItemType Directory $Directory -Force
}
$dir = (Resolve-Path $Directory).Path
$metadata = Join-Path $dir 'seed-container.json'
if ($Stage -eq 'verify') {
    $seed = Get-Content $metadata -Raw | ConvertFrom-Json
    if ($trial.Id -eq $seed.id -or $trial.Image -ne $seed.image) {
        throw 'Recreate the trial with the same image and SSD volume before verification'
    }
}
$cache = @($trial.Mounts | Where-Object Destination -eq '/lmcache')[0].Name
if (-not $cache -or ($Stage -eq 'verify' -and $seed.volume -ne $cache)) {
    throw 'The seed and verification require the same named SSD volume'
}
$client = Join-Path $dir 'client'
if ($Stage -eq 'seed') {
    & dotnet build "$root/benchmarks/Client/Client.csproj" -c Release -o $client -p:UseAppHost=false
    if ($LASTEXITCODE) { throw 'C# benchmark client build failed' }
}
$failed = @()
foreach ($attempt in 1..3) {
    & wslc run --rm --network container:n1x-trial-v033 --volume "${dir}:/results" --entrypoint dotnet `
        mcr.microsoft.com/dotnet/sdk:10.0 /results/client/Client.dll restart --stage $Stage `
        --archive-tokens 17000 --out "/results/attempt-$attempt"
    if ($LASTEXITCODE) { $failed += $attempt }
}
if ($failed.Count) { throw "$Stage failed at attempts $($failed -join ', '). Inspect the per-attempt outputs." }
@{id=$trial.Id; image=$trial.Image; volume=$cache} | ConvertTo-Json |
    Set-Content (Join-Path $dir "$Stage-container.json") -Encoding utf8
