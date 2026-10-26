# Current-user client registrations. Never change the user's default model.
function Write-N1xClientFile([string]$Path, [string]$Text) {
    $temporary=$Path+'.'+[guid]::NewGuid().ToString('N')+'.tmp'
    try {
        [IO.File]::WriteAllText($temporary,$Text,[Text.UTF8Encoding]::new($false))
        if(Test-Path -LiteralPath $Path){[IO.File]::Replace($temporary,$Path,[NullString]::Value)}
        else{[IO.File]::Move($temporary,$Path)}
    } finally {if(Test-Path -LiteralPath $temporary){Remove-Item -LiteralPath $temporary}}
}

function Update-N1xClientEntry {
    param([string]$Path,[string]$Owner,[object]$Value,[switch]$Remove,[switch]$WholeFile)
    $statePath=$Path+'.n1x-managed.json'
    $original=if(Test-Path -LiteralPath $Path){[IO.File]::ReadAllText($Path)}else{''}
    $state=if(Test-Path -LiteralPath $statePath){Get-Content -LiteralPath $statePath -Raw|ConvertFrom-Json}else{$null}
    if($WholeFile){$current=$original}
    else {
        try {$document=if($original){$original|ConvertFrom-Json}else{[pscustomobject]@{}}}
        catch {throw 'Invalid JSON; preserving the original client configuration'}
        if($document -isnot [pscustomobject]){throw 'Expected a JSON object'}
        $providersProperty=$document.PSObject.Properties['providers']
        if(-not $providersProperty){$document|Add-Member providers ([pscustomobject]@{})}
        if($document.providers -isnot [pscustomobject]){throw 'Expected a providers object'}
        $entry=$document.providers.PSObject.Properties['n1x']
        $current=if($entry){$entry.Value|ConvertTo-Json -Depth 50 -Compress}else{''}
    }
    if($state -and $state.owner -ne $Owner){throw 'N1X entry belongs to another checkout'}
    if($current -and (-not $state -or $current -cne $state.value)){throw 'Existing N1X entry is user-owned or edited; preserving it'}
    if($Remove -and -not $state){return}
    if($WholeFile){$replacement=[string]$Value}
    else {
        if($Remove){$document.providers.PSObject.Properties.Remove('n1x')}
        else{$document.providers|Add-Member n1x $Value -Force}
        $replacement=$document|ConvertTo-Json -Depth 50
    }
    # Do not overwrite a config saved by the application while we were reading it.
    $latest=if(Test-Path -LiteralPath $Path){[IO.File]::ReadAllText($Path)}else{''}
    if($latest -cne $original){throw 'Client config changed concurrently; retry the command'}
    if($Remove){
        if($WholeFile){if(Test-Path -LiteralPath $Path){Remove-Item -LiteralPath $Path}}
        elseif($current){Write-N1xClientFile $Path $replacement}
        Remove-Item -LiteralPath $statePath
    } else {
        $saved=if($WholeFile){$replacement}else{$Value|ConvertTo-Json -Depth 50 -Compress}
        # Save ownership first: interrupted writes remain recoverable when no entry exists.
        Write-N1xClientFile $statePath (@{owner=$Owner;value=$saved}|ConvertTo-Json -Depth 5)
        Write-N1xClientFile $Path $replacement
    }
}

function Sync-N1xClients {
    [CmdletBinding()]
    param([string]$Root,[int]$Port=8000,[int]$Context=262144,[switch]$Remove,
          [string]$OpenCodeDirectory='', [string]$CodexDirectory='', [string]$PiDirectory='')
    if($env:N1X_CLIENT_CONFIG -eq 'off'){return}
    if(-not $OpenCodeDirectory){
        $base=if($env:XDG_CONFIG_HOME){$env:XDG_CONFIG_HOME}else{Join-Path $env:USERPROFILE '.config'}
        $OpenCodeDirectory=Join-Path $base 'opencode'
    }
    if(-not $CodexDirectory){$CodexDirectory=if($env:CODEX_HOME){$env:CODEX_HOME}else{Join-Path $env:USERPROFILE '.codex'}}
    if(-not $PiDirectory){$PiDirectory=if($env:PI_CODING_AGENT_DIR){$env:PI_CODING_AGENT_DIR}else{Join-Path $env:USERPROFILE '.pi/agent'}}
    $url="http://127.0.0.1:$Port/v1"
    $output=[math]::Min(8192,[math]::Floor($Context/4))
    $openCode=[ordered]@{
        name='N1X local';package='@opencode/ai/providers/openai-compatible'
        settings=@{baseURL=$url}
        models=@{qwen=@{modelID='qwen';name='Qwen3.8 Flash Next (N1X)'
            capabilities=@{tools=$true;input=@('text','image');output=@('text');reasoning=@{supported=$true}}
            limit=@{context=$Context;output=$output}
            compatibility=@{reasoningField='reasoning'}
            body=@{chat_template_kwargs=@{enable_thinking=$true}}}}
    }
    $pi=[ordered]@{baseUrl=$url;api='openai-completions';apiKey='n1x-local'
        models=@(@{id='qwen';name='Qwen3.8 Flash Next (N1X)';reasoning=$true;input=@('text','image')
            contextWindow=$Context;maxTokens=$output
            cost=@{input=0;output=0;cacheRead=0;cacheWrite=0}
            samplingParams=@{chat_template_kwargs=@{enable_thinking=$true}}
            compat=@{supportsStore=$false;supportsDeveloperRole=$false;supportsReasoningEffort=$false;maxTokensField='max_tokens'}})}
    $compact=[math]::Floor($Context*0.85)
    $codex=@"
# Managed by n1x.ps1. Select with: codex --profile n1x
model = "qwen"
model_provider = "n1x"
model_context_window = $Context
model_auto_compact_token_limit = $compact
model_supports_reasoning_summaries = false

[model_providers.n1x]
name = "N1X local"
base_url = "$url"
wire_api = "responses"
requires_openai_auth = false
supports_websockets = false
stream_idle_timeout_ms = 3600000
"@
    foreach($client in @(
        @{name='OpenCode';directory=$OpenCodeDirectory;file='opencode.json';value=$openCode;whole=$false},
        @{name='Codex';directory=$CodexDirectory;file='n1x.config.toml';value=$codex;whole=$true},
        @{name='Pi';directory=$PiDirectory;file='models.json';value=$pi;whole=$false}
    )){
        if(-not(Test-Path -LiteralPath $client.directory -PathType Container)){continue}
        try {
            if($client.name -eq 'OpenCode' -and (Test-Path (Join-Path $client.directory 'opencode.jsonc'))){
                . "$PSScriptRoot/jsonc.ps1"
                Update-N1xJsoncEntry -Path (Join-Path $client.directory 'opencode.jsonc') -Owner ([IO.Path]::GetFullPath($Root)) -Value $client.value -Remove:$Remove
                # Retire our older JSON entry if the user has switched to JSONC.
                $jsonPath=Join-Path $client.directory 'opencode.json'
                if(Test-Path -LiteralPath ($jsonPath+'.n1x-managed.json')){
                    try {Update-N1xClientEntry -Path $jsonPath -Owner ([IO.Path]::GetFullPath($Root)) -Remove}
                    catch {Write-Warning "JSONC updated, but the older JSON registration was preserved: $($_.Exception.Message)"}
                }
            } else {
                Update-N1xClientEntry -Path (Join-Path $client.directory $client.file) -Owner ([IO.Path]::GetFullPath($Root)) -Value $client.value -WholeFile:$client.whole -Remove:$Remove
            }
            $verb=if($Remove){'Removed'}else{'Registered'}
            Write-Host "$verb N1X configuration for $($client.name). Reload the client to refresh its model list."
        } catch {Write-Warning "$($client.name) configuration unchanged: $($_.Exception.Message)"}
    }
}
