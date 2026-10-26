$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
. "$PSScriptRoot/../scripts/firewall.ps1"
$script:commands=@()
function Start-Process {
    param($FilePath,$Verb,$WindowStyle,$ArgumentList,[switch]$PassThru,[switch]$Wait)
    if($Verb -ne 'RunAs' -or $WindowStyle -ne 'Hidden'){throw 'Expected isolated firewall elevation'}
    $script:commands+= [Text.Encoding]::Unicode.GetString([Convert]::FromBase64String($ArgumentList[-1]))
    return [pscustomobject]@{ExitCode=0}
}
function Get-NetFirewallRule {param($Name,$ErrorAction); return [pscustomobject]@{Name=$Name}}
Set-N1xFirewall -Root $PSScriptRoot -Port 8123
if($script:commands[0] -notmatch '-LocalPort 8123 -RemoteAddress LocalSubnet -Profile Any -EdgeTraversalPolicy Block'){throw 'Incorrect LAN scope'}
Set-N1xFirewall -Root $PSScriptRoot -Remove
if($script:commands[1] -match 'New-NetFirewallRule' -or $script:commands[1] -notmatch 'Remove-NetFirewallRule'){throw 'Stop must only remove owned rule'}
$names=@($script:commands|ForEach-Object {[regex]::Match($_,"n1x-ai-[A-F0-9]+").Value})
if($names[0] -ne $names[1]){throw 'Rule ownership changed'}
Write-Host 'Firewall scope and elevation checks passed.'
