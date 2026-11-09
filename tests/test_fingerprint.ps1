$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$root=Split-Path $PSScriptRoot -Parent
$temporary=Join-Path ([IO.Path]::GetTempPath()) ('n1x-fingerprint-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path "$temporary/profiles","$temporary/runtime"|Out-Null
try {
    $ast=[Management.Automation.Language.Parser]::ParseFile("$root/n1x.ps1",[ref]$null,[ref]$null)
    $function=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Get-ConfigFingerprint'},$true)
    if(-not $function){throw 'Missing actual lifecycle fingerprint implementation'}
    # Run the actual function against isolated files; no service/model commands.
    $source=$function.Extent.Text.Replace('$PSScriptRoot',("'"+$temporary.Replace("'","''")+"'"))
    . ([scriptblock]::Create($source))
    $config=@{DefaultProfile='first';Context=262144;DFlashTokens=3;MyllmboxConfig='profiles/model.yaml';MyllmboxEnvironment='runtime/environment.psd1'}
    $myllmbox=$true
    Set-Content "$temporary/profiles/model.yaml" 'use-replayssm: true'
    Set-Content "$temporary/runtime/environment.psd1" '@{HF_HUB_OFFLINE="1"}'
    $first=Get-ConfigFingerprint
    $config.Remove('DFlashTokens')
    if((Get-ConfigFingerprint) -ne $first){throw 'The implicit historical K3 fingerprint changed'}
    $config.DFlashTokens=3
    $config.DefaultProfile='another-default'
    if((Get-ConfigFingerprint) -ne $first){throw 'Default selection changed an explicitly selected profile hash'}
    $config.DFlashTokens=5
    if((Get-ConfigFingerprint) -eq $first){throw 'Changed draft depth retained its running fingerprint'}
    $config.DFlashTokens=3
    Set-Content "$temporary/profiles/model.yaml" 'use-replayssm: false'
    if((Get-ConfigFingerprint) -eq $first){throw 'Changed server YAML retained its running configuration fingerprint'}
    Set-Content "$temporary/profiles/model.yaml" 'use-replayssm: true'
    Set-Content "$temporary/runtime/environment.psd1" '@{HF_HUB_OFFLINE="1";MBX_DRAFT_FP8="1"}'
    if((Get-ConfigFingerprint) -eq $first){throw 'Changed runtime environment retained its running fingerprint'}
    Remove-Item -LiteralPath "$temporary/profiles/model.yaml"
    if(-not (Get-ConfigFingerprint)){throw 'Missing recipe prevented fingerprinting for owned stop/cleanup'}
    $myllmbox=$false
    $plain=Get-ConfigFingerprint
    Set-Content "$temporary/profiles/model.yaml" 'unrelated recipe'
    if((Get-ConfigFingerprint) -ne $plain){throw 'A non-MyLLMBox profile depends on unrelated recipe files'}
} finally {
    $resolved=[IO.Path]::GetFullPath($temporary)
    $prefix=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')+'\'
    if(-not $resolved.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)){throw 'Unexpected fixture cleanup path'}
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
Write-Host 'Lifecycle fingerprints track YAML/environment bytes and preserve default-selection independence; no server calls.'
