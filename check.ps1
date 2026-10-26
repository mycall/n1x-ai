$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$root=$PSScriptRoot
$files=@(Get-ChildItem -LiteralPath $root -File -Filter '*.ps1')+@(Get-ChildItem "$root/scripts" -File -Filter '*.ps1')+@(Get-ChildItem "$root/tests" -File -Filter '*.ps1')
foreach($file in $files){
    $errors=$null
    [void][Management.Automation.Language.Parser]::ParseFile($file.FullName,[ref]$null,[ref]$errors)
    if($errors){throw ($errors|Out-String)}
}
& python -m unittest discover -s "$root/tests" -p 'test_*.py'
if($LASTEXITCODE -ne 0){throw 'Python tests failed'}
& "$root/tests/test_configuration.ps1"
& "$root/tests/test_recovery.ps1"
& "$root/tests/test_maintenance.ps1"
& "$root/tests/test_proxy.ps1"
& "$root/tests/test_resources.ps1"
& "$root/tests/test_monitor.ps1"
& "$root/tests/test_clients.ps1"
& "$root/tests/test_firewall.ps1"
Write-Host 'All local checks passed. GPU integration tests are separate; see wiki/Development.md.'
