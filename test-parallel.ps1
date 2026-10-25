param(
    [ValidateRange(1,16)][int]$Concurrency=8,
    [ValidatePattern('^[a-zA-Z0-9_-]+$')][string]$ResultName='parallel-smoke'
)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Net.Http
$config=Import-PowerShellDataFile "$PSScriptRoot/config.psd1"
$handler=[Net.Http.HttpClientHandler]::new(); $handler.UseProxy=$false
$handler.MaxConnectionsPerServer=$Concurrency
$client=[Net.Http.HttpClient]::new($handler); $client.Timeout=[TimeSpan]::FromMinutes(10)
$calls=@(); $results=@()
try {
    for ($i=1; $i -le $Concurrency; $i++) {
        $code='N1X-'+[Guid]::NewGuid().ToString('N').Substring(0,8).ToUpperInvariant()
        $body=@{model='qwen';messages=@(@{role='user';content="Copy this arbitrary label exactly: $code. Reply with only the label and no other text."});temperature=0;max_tokens=32;chat_template_kwargs=@{enable_thinking=$false}} | ConvertTo-Json -Depth 8 -Compress
        $content=[Net.Http.StringContent]::new($body,[Text.Encoding]::UTF8,'application/json')
        $calls+=@{code=$code;content=$content;task=$client.PostAsync("http://127.0.0.1:$($config.Port)/v1/chat/completions",$content)}
    }
    foreach ($call in $calls) {
        $response=$call.task.GetAwaiter().GetResult()
        try {
            $raw=$response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
            if (-not $response.IsSuccessStatusCode) { throw $raw }
            $reply=$raw | ConvertFrom-Json
            $answer=$reply.choices[0].message.content.Trim()
            $results+=[pscustomobject]@{expected=$call.code;actual=$answer;passed=($answer -eq $call.code);clientConnectionLimit=$handler.MaxConnectionsPerServer;finishReason=$reply.choices[0].finish_reason;usage=$reply.usage}
        } finally { $response.Dispose() }
    }
    $results | ConvertTo-Json -Depth 10 | Set-Content "$PSScriptRoot/results/$ResultName.json" -Encoding UTF8
    $results | Select-Object expected,actual,passed | Format-Table -AutoSize
    if (@($results | Where-Object { -not $_.passed }).Count) { throw 'Concurrent correctness check failed' }
    $null=Invoke-WebRequest "http://127.0.0.1:$($config.Port)/health" -UseBasicParsing -TimeoutSec 30
} finally {
    foreach ($call in $calls) { $call.content.Dispose() }
    $client.Dispose()
}
