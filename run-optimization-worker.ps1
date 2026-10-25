# Start this script with Start-Process -WindowStyle Hidden so host monitors
# survive replacement of an interactive tool session.
param(
    [string]$RunPrefix = ('opt-' + (Get-Date -Format yyyyMMdd-HHmmss)),
    [string]$CaseList = 'agents,eager,pressure-immediate,pressure-wait,prefill-8192,prefill-2048,prefill-4096,mtp-on,mtp-off',
    [switch]$AllowBattery,
    [switch]$SkipBuild,
    [ValidatePattern('^[a-zA-Z0-9_-]+$')][string]$AfterEfficiencyRun = ''
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($RunPrefix -notmatch '^[a-zA-Z0-9_-]+$') { throw 'Invalid RunPrefix' }
$cases = $CaseList.Split(',')
$out = Join-Path $PSScriptRoot 'results'
New-Item -ItemType Directory -Force $out | Out-Null
$statusPath = Join-Path $out "$RunPrefix-worker-status.json"
$record = @{status='running';processId=$PID;started=[DateTimeOffset]::Now.ToString('o');cases=$cases;runPrefix=$RunPrefix}
$record | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding UTF8
try {
    if ($AfterEfficiencyRun) {
        $dependencyPath=Join-Path $out "$AfterEfficiencyRun-status.json"
        $dependency=Get-Content -LiteralPath $dependencyPath -Raw | ConvertFrom-Json
        $process=Get-CimInstance Win32_Process -Filter "ProcessId=$($dependency.processId)"
        if ($null -ne $process) {
            if ($process.CommandLine -notmatch 'run-efficiency-tests\.ps1' -or
                $process.CommandLine -notmatch [regex]::Escape($AfterEfficiencyRun)) {
                throw 'Dependency PID belongs to a different command'
            }
            $handle=Get-Process -Id $dependency.processId -ErrorAction SilentlyContinue
            if ($null -ne $handle) {
                $record.status='waiting'; $record.waitingFor=$AfterEfficiencyRun
                $record | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding UTF8
                while (-not $handle.WaitForExit(30000)) { }
            }
        }
        $dependency=Get-Content -LiteralPath $dependencyPath -Raw | ConvertFrom-Json
        if ($dependency.status -ne 'complete') { throw "Efficiency dependency ended with status $($dependency.status)" }
        $record.status='running'
        $record | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding UTF8
    }
    & (Join-Path $PSScriptRoot 'run-optimization-matrix.ps1') -RunPrefix $RunPrefix -Cases $cases -AllowBattery:$AllowBattery -SkipBuild:$SkipBuild
    $record.status='complete'
} catch {
    $record.status='failed'
    $record.error=$_.Exception.Message
    Write-Output ($_ | Out-String)
} finally {
    $record.finished=[DateTimeOffset]::Now.ToString('o')
    $record | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding UTF8
}
if ($record.status -ne 'complete') { exit 1 }
