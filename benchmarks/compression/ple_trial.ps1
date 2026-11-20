param([switch]$CheckOnly, [int]$Port = 18135)
$ErrorActionPreference = 'Stop'
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
. "$root/scripts/config.ps1"
. "$root/scripts/native.ps1"
. "$root/scripts/myllmbox.ps1"
$config = Get-N1xConfig -Root $root -Profile 'qwen38fn-best' -Port $Port
$id = 'ple-' + [guid]::NewGuid().ToString('N').Substring(0,12)
$relative = "results/benchmarks/$id"
$out = (New-Item -ItemType Directory -Path (Join-Path $root $relative)).FullName
$image = $config.ImageId
$config.Container = "n1x-$id"
$config.LmcacheVolume = "n1x-$id-l2"
$config.LmcacheNamespace = "qwen-$id-{settings}"
$config.LanAccess = $false
function Invoke-TrialWslc([string[]]$Argv) {
    & wslc @Argv
    if ($LASTEXITCODE) { throw "wslc $($Argv[0]) failed ($LASTEXITCODE)" }
}
$containerStarted = $false
$volumeCreated = $false
Push-Location $root
try {
    Invoke-TrialWslc @('volume','inspect',$config.CacheVolume) | Out-Null
    Copy-Item "$PSScriptRoot/*.py","$PSScriptRoot/hot.cpp" -Destination $out
    $helper = @('run','--rm','--pull','never','--volume',"${out}:/trial",
                '--volume',"$($config.CacheVolume):/cache:ro",'--entrypoint')
    Invoke-TrialWslc ($helper + @('g++',$image,'-std=c++17','-O3','-Wall','-Wextra','-shared','-fPIC',
        '/trial/hot.cpp','-o','/trial/hot.so','-Wl,--no-as-needed','/opt/mbx/lib/libmbx_ple_nvme.so',
        '-Wl,-rpath,/opt/mbx/lib','-ldl','-pthread'))
    foreach ($probe in 'check','footprint') {
        $name = if ($probe -eq 'check') {'parity'} else {'footprint'}
        Invoke-TrialWslc ($helper + @('python3',$image,"/trial/$probe.py")) | Set-Content "$out/$name.json"
    }
    if ($CheckOnly) { return }
    if (@(Invoke-TrialWslc @('list','--format','json') | Where-Object { $_.Trim() }).Count) {
        throw 'Full serving trial requires an idle GPU. Stop the running service before starting this comparison.'
    }
    Copy-Item (Join-Path $root $config.MyllmboxConfig) "$out/trial.yaml"
    $config.MyllmboxConfig = "$relative/trial.yaml"
    & python "$out/fixtures.py"
    if ($LASTEXITCODE) { throw 'Fixture generation failed' }
    @{revision=(git rev-parse HEAD); image=$image; profile=$config.Profile; port=$Port;
      cacheGiB=([long]$config.KvCacheBytes / 1GB); order='alternating pairs'; thinking=$false} |
        ConvertTo-Json | Set-Content "$out/protocol.json"
    Invoke-TrialWslc @('volume','create',$config.LmcacheVolume) | Out-Null
    $volumeCreated = $true
    Assert-N1xMyllmboxInstallation $root $config
    Start-N1xMyllmboxMonitor $root $config
    $launch = @(Get-N1xMyllmboxArguments $root $config $id)
    $index = [array]::IndexOf($launch,$image)
    if ($index -lt 1) { throw 'Missing image in server launch arguments' }
    Invoke-TrialWslc ($launch[0..($index-1)] + @('--env','MBX_PLE_LIB=/n1x-config/hot.so') + $launch[$index..($launch.Length-1)])
    $containerStarted = $true
    foreach ($test in @(@('serve_ab','requests'),@('serve_c2','concurrent'),@('serve_append','append'))) {
        Invoke-TrialWslc @('exec',$config.Container,'python3',"/n1x-config/$($test[0]).py") |
            Set-Content "$out/$($test[1]).jsonl"
    }
    & python "$out/analyze.py"
    if ($LASTEXITCODE) { throw 'Could not analyze the completed pairs' }
} finally {
    try {
        if ($containerStarted) {
            & wslc logs $config.Container *> "$out/serving.log"
            Invoke-TrialWslc @('stop',$config.Container) | Out-Null
            Invoke-TrialWslc @('rm',$config.Container) | Out-Null
        }
        if ($volumeCreated) { Invoke-TrialWslc @('volume','rm',$config.LmcacheVolume) | Out-Null }
    } finally {
        Pop-Location
        Write-Host "Trial records: $out"
    }
}
