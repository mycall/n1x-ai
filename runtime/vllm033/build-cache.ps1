param()
$ErrorActionPreference = 'Stop'
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$dir = (New-Item -Force -ItemType Directory "$root/results/build/v033-cache").FullName
$sdist = Join-Path $dir 'lmcache-0.5.6.tar.gz'
$digest = 'd6951e60ce8818a76aa42d0866a4ba85f1c95cd919355fff30ff24dcc3243f1e'
if (-not (Test-Path $sdist) -or (Get-FileHash $sdist).Hash -ne $digest) {
    Invoke-WebRequest 'https://files.pythonhosted.org/packages/84/25/3ccd46844c94e08897aa8d72716a538c07e4583410d84dbc6cd12cb60dc1/lmcache-0.5.6.tar.gz' -OutFile $sdist
}
if ((Get-FileHash $sdist).Hash -ne $digest) { throw 'Unexpected LMCache 0.5.6 source digest' }
$patches = New-Item -Force -ItemType Directory "$dir/lmcache"
Copy-Item "$root/runtime/lmcache/*.py" $patches.FullName -Force
Copy-Item "$PSScriptRoot/Dockerfile.lmcache" "$dir/Dockerfile" -Force
foreach ($target in 'runtime','') {
    $tag = if ($target) { 'n1x-ai:v033-serving-runtime' } else { 'n1x-ai:v033-serving' }
    $options = if ($target) { @('--target',$target) } else { @() }
    & wslc build @options -t $tag -f "$PSScriptRoot/Dockerfile" "$root/runtime"
    if ($LASTEXITCODE) { throw '0.33 base image build failed' }
}
& wslc build -t n1x-ai:v033-serving-lmcache $dir
if ($LASTEXITCODE) { throw '0.33 LMCache image build failed' }
