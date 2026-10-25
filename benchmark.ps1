param(
    [ValidateSet('long-context','mtp-long-context','long-context-graphs','mtp-throughput','candidate-fast','candidate-16')][string]$Profile = 'mtp-long-context',
    [string]$RunName = '',
    [int[]]$ContextTokens = @(1024, 8192, 32768),
    [ValidateRange(1,10)][int]$Repeats = 3,
    [ValidateRange(32,1024)][int]$OutputTokens = 256,
    [string]$WindowsPowerMode = 'Performance (user reported)',
    [string]$MsiMode = 'Performance (user reported)',
    [string]$RuntimeNote = ''
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Add-Type -AssemblyName System.Net.Http
$config = Import-PowerShellDataFile "$PSScriptRoot/config.psd1"
$profileConfig = Import-PowerShellDataFile "$PSScriptRoot/profiles/$Profile.psd1"
$base = "http://127.0.0.1:$($config.Port)"
if (-not $RunName) { $RunName = "benchmark-$Profile-$(Get-Date -Format yyyyMMdd-HHmmss)" }
$dir = Join-Path "$PSScriptRoot/results" $RunName
if (Test-Path -LiteralPath $dir) { throw 'Run directory already exists; choose another RunName' }
New-Item -ItemType Directory -Force $dir | Out-Null
$utf8 = [Text.UTF8Encoding]::new($false)
function Save($Value, $Name) { [IO.File]::WriteAllText((Join-Path $dir $Name), (ConvertTo-Json -InputObject $Value -Depth 30), $utf8) }
function Post($Path, $Body) { Invoke-RestMethod "$base$Path" -Method Post -ContentType 'application/json' -Body $utf8.GetBytes(($Body | ConvertTo-Json -Depth 20 -Compress)) -TimeoutSec 3600 }
function Metrics {
    $raw = (Invoke-WebRequest "$base/metrics" -UseBasicParsing -TimeoutSec 30).Content
    $values = @{}
    foreach ($line in ($raw -split "`n")) {
        if ($line -match '^(vllm:[a-zA-Z0-9_]+)(?:\{[^}]*\})?\s+([0-9.eE+-]+)\s*$') {
            $key = $Matches[1]
            if (-not $values.ContainsKey($key)) { $values[$key] = 0.0 }
            $values[$key] += [double]::Parse($Matches[2], [Globalization.CultureInfo]::InvariantCulture)
        }
    }
    return $values
}
function Stream-Request($Messages, [int]$Tokens) {
    $salt = [Guid]::NewGuid().ToString()
    $body = @{ model='qwen'; messages=$Messages; cache_salt=$salt; temperature=0; seed=42; max_tokens=$Tokens; min_tokens=$Tokens; ignore_eos=$true; stream=$true; stream_options=@{include_usage=$true}; chat_template_kwargs=@{enable_thinking=$false} }
    $request = [Net.Http.HttpRequestMessage]::new([Net.Http.HttpMethod]::Post, "$base/v1/chat/completions")
    $request.Content = [Net.Http.StringContent]::new(($body | ConvertTo-Json -Depth 20 -Compress), $utf8, 'application/json')
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $response = $null; $reader = $null; $first = $null; $last = $null; $usage = $null; $done = $false; $finish = $null
    $answer = [Text.StringBuilder]::new()
    try {
        $response = $client.SendAsync($request, [Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
        if (-not $response.IsSuccessStatusCode) { throw $response.Content.ReadAsStringAsync().GetAwaiter().GetResult() }
        $reader = [IO.StreamReader]::new($response.Content.ReadAsStreamAsync().GetAwaiter().GetResult())
        while ($null -ne ($line = $reader.ReadLineAsync().GetAwaiter().GetResult())) {
            if (-not $line.StartsWith('data: ')) { continue }
            if ($line -eq 'data: [DONE]') { $done = $true; break }
            $event = $line.Substring(6) | ConvertFrom-Json
            if ($event.PSObject.Properties['usage'] -and $event.usage) { $usage = $event.usage }
            foreach ($choice in $event.choices) {
                if ($choice.delta.PSObject.Properties['content'] -and $choice.delta.content) {
                    if ($null -eq $first) { $first = $watch.Elapsed.TotalSeconds }
                    $last = $watch.Elapsed.TotalSeconds
                    [void]$answer.Append($choice.delta.content)
                }
                if ($choice.finish_reason) { $finish = $choice.finish_reason }
            }
        }
        $elapsed = $watch.Elapsed.TotalSeconds
        if (-not $done -or -not $usage -or $usage.completion_tokens -ne $Tokens -or $null -eq $first) { throw 'Incomplete stream or unexpected output length' }
        return [ordered]@{ cacheSalt=$salt; promptTokens=$usage.prompt_tokens; outputTokens=$usage.completion_tokens; ttftSeconds=$first; totalSeconds=$elapsed; clientDecodeTokensPerSecond=($Tokens-1)/($last-$first); endToEndTokensPerSecond=$Tokens/$elapsed; finishReason=$finish; usage=$usage; answer=$answer.ToString() }
    } finally {
        if ($reader) { $reader.Dispose() }; if ($response) { $response.Dispose() }; $request.Dispose()
    }
}
$container = @((& wslc inspect $profileConfig.Container | ConvertFrom-Json))[0]
if (-not $container.State.Running) { throw 'Requested profile is not running' }
$models = Invoke-RestMethod "$base/v1/models" -TimeoutSec 30
if ($models.data[0].max_model_len -ne 262144) { throw 'Expected 262144-token capacity' }
Save @{ started=[DateTimeOffset]::Now.ToString('o'); profile=$Profile; runtimeNote=$RuntimeNote; windowsPowerMode=$WindowsPowerMode; msiMode=$MsiMode; underlyingPowerPlan=(& powercfg /getactivescheme | Out-String).Trim(); container=$container; contexts=$ContextTokens; repeats=$Repeats; outputTokens=$OutputTokens; methodology='Single sequence, execution mode recorded in container arguments, warm kernels, unique cache_salt per request prevents prompt cache reuse, fixed output length, thinking disabled. Client decode rate is approximate because SSE chunks may contain multiple tokens. Server rate uses (output tokens - 1) / request_decode_time_seconds. Startup excluded.' } 'conditions.json'
$handler = [Net.Http.HttpClientHandler]::new(); $handler.UseProxy = $false
$client = [Net.Http.HttpClient]::new($handler); $client.Timeout = [TimeSpan]::FromHours(1)
$stopFile = Join-Path $dir 'telemetry.stop'
if (Test-Path $stopFile) { throw 'Run directory already used; choose another RunName' }
$job = Start-Job -FilePath "$PSScriptRoot/capture-memory.ps1" -ArgumentList $profileConfig.Container,(Join-Path $dir 'memory.jsonl'),$stopFile,5
$results = [Collections.Generic.List[object]]::new()
try {
    Write-Host 'Warming up (excluded from measurements)...'
    $warm = Stream-Request @(@{role='user';content='Explain how a hash table resolves collisions, with practical examples and tradeoffs.'}) 128
    Save $warm 'warmup.json'
    Start-Sleep -Seconds 12
    foreach ($target in $ContextTokens) {
        if ($target + $OutputTokens -gt 262144) { throw 'Input plus output exceeds model capacity' }
        $lines = [Math]::Max(1,[int]($target/55))
        $messages = $null
        for ($attempt=0; $attempt -lt 5; $attempt++) {
            $builder = [Text.StringBuilder]::new('Review these engineering notes. ')
            for ($i=0; $i -lt $lines; $i++) { [void]$builder.AppendLine("Record $i describes service $($i % 37): cache entries expire after $($i % 89 + 10) seconds. Requests use bounded queues, retry transient errors with jitter, and report latency and memory metrics. Independent workers process immutable records and persist successful results.") }
            [void]$builder.AppendLine('Write a detailed engineering review of this design. Discuss concurrency, cache invalidation, retries, observability, memory limits, failure recovery, and concrete improvements. Use examples and continue with implementation guidance.')
            $messages = @(@{role='user';content=$builder.ToString()})
            $count = (Post '/tokenize' @{model='qwen'; messages=$messages; add_generation_prompt=$true; chat_template_kwargs=@{enable_thinking=$false}}).count
            if ([Math]::Abs($count-$target) -lt 100) { break }
            $lines = [Math]::Max(1,[int]($lines * ($target-60)/$count))
        }
        if ($count + $OutputTokens -gt 262144) { throw 'Actual token count exceeds capacity' }
        Save $messages "prompt-$target.json"
        for ($repeat=1; $repeat -le $Repeats; $repeat++) {
            $before = Metrics
            Write-Host "Measuring $Profile input~$count output=$OutputTokens repeat=$repeat ..."
            $result = Stream-Request $messages $OutputTokens
            Start-Sleep -Seconds 12
            $after = Metrics
            $delta = @{}
            foreach ($key in $after.Keys) { if ($key -match '(spec_decode.*total|request_decode_time_seconds_(sum|count)|prefix_cache_(hits|queries)_total|request_success_total)$') { $delta[$key] = $after[$key] - $before[$key] } }
            if ($delta['vllm:request_decode_time_seconds_count'] -ne 1) { throw 'Expected metrics from exactly one completed request' }
            if ($delta['vllm:prefix_cache_hits_total'] -gt 0) { throw 'Unexpected prefix cache reuse' }
            $result.targetInputTokens = $target; $result.repeat = $repeat; $result.metricsDelta = $delta
            $result.serverDecodeTokensPerSecond = ($OutputTokens-1)/$delta['vllm:request_decode_time_seconds_sum']
            $health = Invoke-WebRequest "$base/health" -UseBasicParsing -TimeoutSec 30
            $result.healthyAfter = $health.StatusCode -eq 200
            $results.Add([pscustomobject]$result)
            Save ($results.ToArray()) 'requests.json'
            Write-Host ('TTFT {0:N3}s; server decode {1:N2} tokens/s; total {2:N3}s' -f $result.ttftSeconds,$result.serverDecodeTokensPerSecond,$result.totalSeconds)
        }
    }
} finally {
    [IO.File]::WriteAllText($stopFile,'stop',$utf8)
    $null = Wait-Job $job -Timeout 15
    if ($job.State -eq 'Running') { Stop-Job $job }
    Receive-Job $job
    Remove-Job $job
    $client.Dispose()
    Save ($results.ToArray()) 'requests.json'
}
Write-Host "Saved benchmark: $dir"
