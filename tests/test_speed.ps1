$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$root=Split-Path $PSScriptRoot -Parent
$temporary=Join-Path ([IO.Path]::GetTempPath()) ('n1x-speed-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temporary | Out-Null
try {
    # No config, WSLC, model files or server are provided. Offline routing must
    # return before attempting to use any of them.
    Copy-Item -LiteralPath "$root/benchmark.ps1" -Destination "$temporary/benchmark.ps1"
    $speedCalls=[Collections.Generic.List[object]]::new()
    function Invoke-SpeedFixturePython {
        param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)
        $speedCalls.Add($Arguments)
        $global:LASTEXITCODE=0
    }
    & "$temporary/benchmark.ps1" -Suite speed -SpeedRuns 'saved run one','saved-run-two' -ReportOut 'saved comparison' -Python Invoke-SpeedFixturePython
    if($speedCalls.Count -ne 1){throw 'Offline report did not invoke the report client once'}
    $arguments=$speedCalls[0]
    if($arguments[0] -notlike '*speed_report.py' -or $arguments -notcontains 'saved run one' -or
        $arguments -notcontains 'saved-run-two' -or $arguments -notcontains 'saved comparison'){
        throw 'Offline report arguments were not preserved'
    }
    foreach($action in @(
        {& "$temporary/benchmark.ps1" -Suite agents -SpeedDepths 512},
        {& "$temporary/benchmark.ps1" -Suite speed -SpeedRuns 'saved' -Profile qwen38fn-best},
        {& "$temporary/benchmark.ps1" -Suite speed -SpeedRuns 'saved' -SpeedPlanOnly},
        {& "$temporary/benchmark.ps1" -Suite speed -SpeedRuns 'saved' -SpeedReasoningEffort low},
        {& "$temporary/benchmark.ps1" -Suite speed -NoThinking -SpeedReasoningEffort low},
        {& "$temporary/benchmark.ps1" -Suite speed -ReportOut 'unexpected'},
        {& "$temporary/benchmark.ps1" -Suite speed -Build},
        {& "$temporary/benchmark.ps1" -Suite agents -CapacityRepeats 1},
        {& "$temporary/benchmark.ps1" -Suite agents -CapacityConcurrency 1,6},
        {& "$temporary/benchmark.ps1" -Suite capacity -CapacityConcurrency 1,1},
        {& "$temporary/benchmark.ps1" -Suite capacity -CapacityConcurrency @()},
        {& "$temporary/benchmark.ps1" -Suite capacity -CapacityConcurrency 1,4},
        {& "$temporary/benchmark.ps1" -Suite capacity -NoThinking},
        {& "$temporary/benchmark.ps1" -Suite capacity -Build},
        {& "$temporary/benchmark.ps1" -Suite capacity -Smoke}
    )){
        $failed=$false
        try {& $action} catch {$failed=$true}
        if(-not $failed){throw 'Invalid speed options reached live execution'}
    }
    # Exercise real capacity argument routing using isolated service/hardware
    # fixtures; no Python model client, WSLC or API is actually called.
    New-Item -ItemType Directory "$temporary/scripts"|Out-Null
    @'
function Get-N1xConfig {
    param($Root,$Profile)
    return @{Profile='fixture';Context=262144;UseLMCache=$false;Port=12345;Container='fixture';Backend='wslc-myllmbox'}
}
'@ | Set-Content "$temporary/scripts/config.ps1"
    Set-Content "$temporary/scripts/benchmark-partition.ps1" '# Cache-off fixture; no partition prompt.'
    Set-Content "$temporary/n1x.ps1" 'param($Action,$Profile,$TimeoutSeconds); $global:LASTEXITCODE=0'
    function wslc { '{"Id":"fixture"}'; $global:LASTEXITCODE=0 }
    function git {if($args -notcontains 'status'){'fixture-commit'}; $global:LASTEXITCODE=0}
    function powercfg {'fixture power scheme'; $global:LASTEXITCODE=0}
    function nvidia-smi {'fixture, driver, 90112 MiB, 87000 MiB'; $global:LASTEXITCODE=0}
    function Invoke-RestMethod {return @{data=@()}}
    foreach($explicit in @($false,$true)){
        $speedCalls.Clear()
        $options=@{Suite='capacity';Python='Invoke-SpeedFixturePython'}
        if($explicit){$options.CapacityConcurrency=@(1,8)}
        & "$temporary/benchmark.ps1" @options
        $call=@($speedCalls|Where-Object {$_[0] -like '*context_capacity_probe.py'})
        if($call.Count -ne 1){throw 'Capacity client was not routed exactly once'}
        $arguments=[string[]]$call[0]
        $index=[Array]::IndexOf($arguments,'--concurrency')
        $high=if($explicit){'8'}else{'6'}
        if($index -lt 0 -or $arguments[$index+1] -ne '1' -or $arguments[$index+2] -ne $high -or $index+3 -ne $arguments.Count){
            throw 'Capacity concurrency defaults/explicit override were not preserved'
        }
    }
} finally {
    $resolved=[IO.Path]::GetFullPath($temporary)
    $tempRoot=[IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    if(-not $resolved.StartsWith($tempRoot,[StringComparison]::OrdinalIgnoreCase) -or
        [IO.Path]::GetFileName($resolved) -notlike 'n1x-speed-*'){throw 'Refusing unexpected fixture cleanup target'}
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
Write-Host 'Offline speed routing, capacity C1/C6 default and explicit C1/C8 override passed; no server calls.'
