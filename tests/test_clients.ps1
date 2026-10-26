$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
. "$PSScriptRoot/../scripts/clients.ps1"
$temporary=Join-Path ([IO.Path]::GetTempPath()) ('n1x-clients-'+[guid]::NewGuid().ToString('N'))
$previous=$env:N1X_CLIENT_CONFIG
try {
    $env:N1X_CLIENT_CONFIG='on'
    foreach($name in @('opencode','codex','pi')){New-Item -ItemType Directory "$temporary/$name" -Force|Out-Null}
    $args=@{Root=$temporary;OpenCodeDirectory="$temporary/opencode";CodexDirectory="$temporary/codex";PiDirectory="$temporary/pi"}
    $path="$temporary/opencode/opencode.json"
    Set-Content $path '{"model":"other/model","providers":{"other":{"name":"keep"}}}'
    Set-Content "$temporary/codex/config.toml" '# preserve exactly'
    $base=[IO.File]::ReadAllText("$temporary/codex/config.toml")
    Sync-N1xClients @args -Port 8123 -Context 32768
    $doc=Get-Content $path -Raw|ConvertFrom-Json
    if($doc.model -ne 'other/model' -or $doc.providers.other.name -ne 'keep'){throw 'Existing config changed'}
    if($doc.providers.n1x.settings.baseURL -ne 'http://127.0.0.1:8123/v1' -or $doc.providers.n1x.models.qwen.limit.context -ne 32768){throw 'Active settings missing'}
    if($doc.providers.n1x.models.qwen.body.chat_template_kwargs.reasoning_effort -ne 'medium'){throw 'OpenCode default effort must be medium'}
    foreach($variant in $doc.providers.n1x.models.qwen.variants){
        if(-not $variant.body.chat_template_kwargs.enable_thinking -or $variant.body.chat_template_kwargs.reasoning_effort -ne 'medium'){throw 'OpenCode variant must use medium thinking'}
    }
    Sync-N1xClients @args -Port 8124
    $doc=Get-Content $path -Raw|ConvertFrom-Json
    if($doc.providers.n1x.settings.baseURL -notmatch ':8124/v1$'){throw 'Idempotent update failed'}
    $doc|Add-Member custom 'user edit'
    $doc|ConvertTo-Json -Depth 50|Set-Content $path
    Sync-N1xClients @args -Remove
    $doc=Get-Content $path -Raw|ConvertFrom-Json
    if($doc.providers.PSObject.Properties['n1x'] -or $doc.custom -ne 'user edit'){throw 'Removal damaged config'}
    if(Test-Path "$temporary/codex/n1x.config.toml"){throw 'Profile not removed'}
    if([IO.File]::ReadAllText("$temporary/codex/config.toml") -cne $base){throw 'Main Codex config changed'}
    Sync-N1xClients @args
    $doc=Get-Content $path -Raw|ConvertFrom-Json
    $doc.providers.n1x.name='manual override'
    $doc|ConvertTo-Json -Depth 50|Set-Content $path
    $before=[IO.File]::ReadAllText($path)
    Sync-N1xClients @args -Remove -WarningVariable warnings
    if([IO.File]::ReadAllText($path) -cne $before -or -not $warnings){throw 'User edit not protected'}
    Set-Content "$temporary/opencode/opencode.jsonc" '{/* user configuration */}'
    $jsoncBefore=[IO.File]::ReadAllText("$temporary/opencode/opencode.jsonc")
    Sync-N1xClients @args -WarningVariable warnings
    if([IO.File]::ReadAllText($path) -cne $before){throw 'JSONC migration overwrote user-edited JSON'}
    . "$PSScriptRoot/../scripts/jsonc.ps1"
    $jsonc=Read-N1xJsonc ([IO.File]::ReadAllText("$temporary/opencode/opencode.jsonc"))
    if(-not $jsonc.Document.providers.n1x.models.qwen.capabilities.reasoning.supported){throw 'JSONC integration missing reasoning'}
    Sync-N1xClients @args -Remove
    if([IO.File]::ReadAllText("$temporary/opencode/opencode.jsonc") -cne $jsoncBefore){throw 'JSONC integration did not unpatch'}
    Set-Content "$temporary/pi/models.json" '{invalid json'
    Sync-N1xClients @args -WarningVariable warnings
    if((Get-Content "$temporary/pi/models.json" -Raw).Trim() -ne '{invalid json' -or -not $warnings){throw 'Invalid config overwritten'}
    Sync-N1xClients @args -Remove
    $env:N1X_CLIENT_CONFIG='off'
    Sync-N1xClients @args
    if(Test-Path "$temporary/codex/n1x.config.toml"){throw 'Opt-out ignored'}
    Write-Host 'Client registration checks passed.'
} finally {
    $env:N1X_CLIENT_CONFIG=$previous
    if([IO.Path]::GetFullPath($temporary).StartsWith([IO.Path]::GetTempPath(),[StringComparison]::OrdinalIgnoreCase)){Remove-Item -LiteralPath $temporary -Recurse -Force}
}
