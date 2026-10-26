function Set-N1xFirewall {
    param([string]$Root,[ValidateRange(1,65535)][int]$Port=8000,[switch]$Remove)
    $sha=[Security.Cryptography.SHA256]::Create()
    try {$id=([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes([IO.Path]::GetFullPath($Root).ToLowerInvariant())))).Replace('-','').Substring(0,16)}
    finally {$sha.Dispose()}
    $name="n1x-ai-$id"
    # Elevate only fixed firewall operations, never the WSLC lifecycle.
    $operation=if($Remove){''}else{@"
New-NetFirewallRule -Name '$name' -DisplayName 'N1X model API (LAN)' -Group 'n1x-ai' -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port -RemoteAddress LocalSubnet -Profile Any -EdgeTraversalPolicy Block | Out-Null
"@}
    $command=@"
`$ErrorActionPreference='Stop'
try {
    Get-NetFirewallRule -Name '$name' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    $operation
    exit 0
} catch { exit 1 }
"@
    if($Remove -and -not(Get-NetFirewallRule -Name $name -ErrorAction SilentlyContinue)){return}
    $encoded=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
    $process=Start-Process powershell.exe -Verb RunAs -WindowStyle Hidden -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-EncodedCommand',$encoded) -PassThru -Wait
    if($process.ExitCode -ne 0){throw 'Windows firewall update failed. The model container may still be running; retry start/stop and approve its firewall UAC prompt.'}
    if($Remove){Write-Host 'Removed N1X LAN firewall access.'}
    else{Write-Host "LAN access enabled for TCP $Port (local subnet only)."}
}
