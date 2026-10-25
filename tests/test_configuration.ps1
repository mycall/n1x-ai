$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$root=Split-Path $PSScriptRoot -Parent
. "$root/scripts/config.ps1"
$temporary=Join-Path ([IO.Path]::GetTempPath()) ('n1x-config-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force "$temporary/profiles"|Out-Null
try {
    Copy-Item "$root/config.psd1" "$temporary/config.psd1"
    Copy-Item "$root/profiles/cache-mtp.psd1" "$temporary/profiles/cache-mtp.psd1"
    $config=Get-N1xConfig -Root $temporary
    $expectedRoot=Join-Path ([Environment]::GetFolderPath('UserProfile')) 'models'
    if($config.ModelRoot -ne $expectedRoot){throw 'Default model path is not portable'}
    $overrideRoot=Join-Path $temporary 'model files'
    $escaped=$overrideRoot.Replace("'","''")
    [IO.File]::WriteAllText("$temporary/config.local.psd1","@{ ModelRoot='$escaped'; DefaultProfile='cache-mtp'; Port=8001 }")
    $config=Get-N1xConfig -Root $temporary
    if(-not $config.Mtp -or -not $config.UseLMCache -or $config.Port -ne 8001 -or $config.ModelRoot -ne $overrideRoot){throw 'Local configuration precedence failed'}
    $config=Get-N1xConfig -Root $temporary -Port 8002
    if($config.Port -ne 8002){throw 'CLI override failed'}
    try{Get-N1xConfig -Root $temporary -Profile '../escape';throw 'Traversal accepted'}catch{if($_.Exception.Message -ne 'Invalid profile name'){throw}}
    $preview=& "$root/n1x.ps1" start -Profile cache-mtp -ModelRoot $overrideRoot -PrintOnly
    if($preview -notmatch 'n1x-ai:lmcache' -or $preview -notmatch 'fp8_e4m3' -or $preview -notmatch '/profiles/mtp.yaml'){throw 'Portable launch preview failed'}
    Write-Output 'Configuration and launch checks passed'
} finally {
    # Only this explicitly created temporary directory may be removed.
    $resolved=[IO.Path]::GetFullPath($temporary)
    $prefix=[IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    if(-not $resolved.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)){throw 'Unsafe test cleanup path'}
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
