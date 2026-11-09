$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$root=Split-Path $PSScriptRoot -Parent
. "$root/scripts/native.ps1"
. "$root/scripts/myllmbox.ps1"
$temporary=Join-Path ([IO.Path]::GetTempPath()) ('n1x monitor fixture '+[guid]::NewGuid().ToString('N'))
$owned=[Collections.Generic.List[Diagnostics.Process]]::new()
try{
    New-Item -ItemType Directory -Path "$temporary/scripts" -Force|Out-Null
    Set-Content "$temporary/scripts/monitor-memory.ps1" 'param($Container,$OutputPath) Start-Sleep -Seconds 120'
    $config=@{Container='fixture-monitor';MyllmboxConfig='recipe.yaml';MyllmboxEnvironment='env.psd1';ModelRoot=$temporary;MyllmboxModel='model';MyllmboxDrafter='draft'}
    $record=Join-Path $temporary '.state/fixture-monitor/monitor.json'
    Start-N1xMyllmboxMonitor $temporary $config
    $first=Get-Process -Id (Get-Content $record -Raw|ConvertFrom-Json).pid
    $null=$first.Handle
    $owned.Add($first)
    Start-N1xMyllmboxMonitor $temporary $config
    $second=Get-Process -Id (Get-Content $record -Raw|ConvertFrom-Json).pid
    $null=$second.Handle
    $owned.Add($second)
    if(-not $first.HasExited -or $second.HasExited){throw 'Restart did not replace the owned monitor'}
    @{pid=$second.Id;startTicks=1}|ConvertTo-Json|Set-Content $record
    Start-N1xMyllmboxMonitor $temporary $config
    $third=Get-Process -Id (Get-Content $record -Raw|ConvertFrom-Json).pid
    $null=$third.Handle
    $owned.Add($third)
    if($second.HasExited -or $third.HasExited){throw 'Stale identity killed an unrelated process'}
    # Simulate the old monitor exiting naturally during its CIM identity read.
    function Get-CimInstance {
        param($ClassName,$Filter)
        if(-not $third.HasExited){$third.Kill();$null=$third.WaitForExit(5000)}
        return $null
    }
    try{Start-N1xMyllmboxMonitor $temporary $config}
    finally{Remove-Item Function:Get-CimInstance}
    $fourth=Get-Process -Id (Get-Content $record -Raw|ConvertFrom-Json).pid
    $null=$fourth.Handle
    $owned.Add($fourth)
    if($fourth.HasExited){throw 'Natural monitor exit prevented replacement'}
    Write-Host 'MyLLMBox monitor replacement and stale identity checks passed'
}finally{
    foreach($process in $owned){if(-not $process.HasExited){$process.Kill();$null=$process.WaitForExit(5000)};$process.Dispose()}
    $resolved=[IO.Path]::GetFullPath($temporary)
    $expected=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')+'\'
    if(-not $resolved.StartsWith($expected,[StringComparison]::OrdinalIgnoreCase)){throw 'Unsafe fixture cleanup path'}
    if(Test-Path -LiteralPath $resolved){Remove-Item -LiteralPath $resolved -Recurse -Force}
}
