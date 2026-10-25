param(
    [ValidateSet('throughput','mtp-throughput','candidate-fast','candidate-16')][string]$Profile = 'throughput',
    [string]$RunName = '',
    [int[]]$InputTokens = @(1024,8192),
    [int[]]$Concurrency = @(1,2,4,8),
    [ValidateRange(8,256)][int]$Requests = 8,
    [ValidateRange(32,1024)][int]$OutputTokens = 128,
    [string]$RuntimeNote = '',
    [string]$WindowsPowerMode = 'Performance (user reported)',
    [string]$MsiMode = 'Performance (user reported)'
)
$ErrorActionPreference = 'Stop'
$config = Import-PowerShellDataFile "$PSScriptRoot/config.psd1"
$profileConfig = Import-PowerShellDataFile "$PSScriptRoot/profiles/$Profile.psd1"
$base = "http://127.0.0.1:$($config.Port)"
$container = @((& wslc inspect $profileConfig.Container | ConvertFrom-Json))[0]
if (-not $container.State.Running) { throw 'Requested profile is not running' }
$argsList = @($container.Config.Cmd)
$seqIndex = [Array]::IndexOf($argsList, '--max-num-seqs')
if ($seqIndex -lt 0 -or [int]$argsList[$seqIndex+1] -lt ($Concurrency | Measure-Object -Maximum).Maximum) { throw 'Container active sequence limit is too small' }
if (-not $RunName) { $RunName = "vllm-concurrency-$Profile-$(Get-Date -Format yyyyMMdd-HHmmss)" }
if ($RunName -notmatch '^[a-zA-Z0-9_-]+$') { throw 'RunName must use letters, numbers, underscore or hyphen' }
$dir = Join-Path "$PSScriptRoot/results" $RunName
if (Test-Path $dir) { throw 'Run directory already exists; choose another RunName' }
New-Item -ItemType Directory -Force $dir | Out-Null
$utf8 = [Text.UTF8Encoding]::new($false)
function Save($Value,$Name) { [IO.File]::WriteAllText((Join-Path $dir $Name),($Value | ConvertTo-Json -Depth 30),$utf8) }
function Save-Metrics($Name) { [IO.File]::WriteAllText((Join-Path $dir $Name),(Invoke-WebRequest "$base/metrics" -UseBasicParsing -TimeoutSec 30).Content,$utf8) }
Save @{ started=[DateTimeOffset]::Now.ToString('o'); profile=$Profile; container=$container; runtimeNote=$RuntimeNote; windowsPowerMode=$WindowsPowerMode; msiMode=$MsiMode; underlyingPowerPlan=(& powercfg /getactivescheme | Out-String).Trim(); requests=$Requests; outputTokens=$OutputTokens; inputTokens=$InputTokens; concurrency=$Concurrency; methodology='Installed vLLM 0.32.0 bench serve, openai-chat endpoint, random synthetic dataset, fixed lengths, zero shared prefix, seed 42, no EOS stopping, thinking disabled. Independent warmup excluded. Unique cache_salt per CLI run prevents cross-run prefix reuse. Request rate infinity with bounded max-concurrency; small finite sweep, not a quality evaluation or sustained load qualification. Client runs in same WSLC container and consumes some guest CPU/RAM.' } 'conditions.json'
$stopFile = Join-Path $dir 'telemetry.stop'
$job = Start-Job -FilePath "$PSScriptRoot/capture-memory.ps1" -ArgumentList $profileConfig.Container,(Join-Path $dir 'memory.jsonl'),$stopFile,5,$base
try {
    $warm = @{model='qwen';messages=@(@{role='user';content='Explain bounded work queues and backpressure.'});max_tokens=128;min_tokens=128;ignore_eos=$true;chat_template_kwargs=@{enable_thinking=$false}}
    $null = Invoke-RestMethod "$base/v1/chat/completions" -Method Post -ContentType application/json -Body ($warm | ConvertTo-Json -Depth 10) -TimeoutSec 3600
    Start-Sleep -Seconds 12
    foreach ($length in $InputTokens) {
        foreach ($clients in $Concurrency) {
            $settingStarted = [DateTimeOffset]::Now.ToString('o')
            $stem = "input-$length-concurrency-$clients"
            $guestDir = "/root/.cache/n1x-bench/$RunName"
            $extra = @{chat_template_kwargs=@{enable_thinking=$false};temperature=0;seed=42;min_tokens=$OutputTokens;cache_salt=[Guid]::NewGuid().ToString()} | ConvertTo-Json -Depth 5 -Compress
            $benchArgs = @('vllm','bench','serve','--backend','openai-chat','--base-url','http://127.0.0.1:8000','--endpoint','/v1/chat/completions','--model','qwen','--tokenizer','/model','--dataset-name','random','--random-input-len',"$length",'--random-output-len',"$OutputTokens",'--random-prefix-len','0','--random-range-ratio','0','--num-prompts',"$Requests",'--max-concurrency',"$clients",'--request-rate','inf','--seed','42','--ignore-eos','--num-warmups','0','--ready-check-timeout-sec','0','--extra-body',$extra,'--save-result','--save-detailed','--result-dir',$guestDir,'--result-filename',"$stem.json",'--disable-tqdm')
            $benchArgs += @('--percentile-metrics','ttft,tpot,itl,e2el,client_queue_time,e2el_including_client_queue')
            Save $benchArgs "$stem-command.json"
            Save-Metrics "$stem-metrics-before.txt"
            $encoded = [Convert]::ToBase64String($utf8.GetBytes(($benchArgs | ConvertTo-Json -Compress)))
            Write-Host "vLLM benchmark: input=$length, output=$OutputTokens, concurrency=$clients, requests=$Requests"
            # Pass structured argv through base64 to avoid Windows native JSON quoting.
            $oldPreference = $ErrorActionPreference
            $ErrorActionPreference = 'Continue'
            & wslc exec $profileConfig.Container python -c 'import base64,json,subprocess,sys;sys.exit(subprocess.call(json.loads(base64.b64decode(sys.argv[1]))))' $encoded 2>&1 | Tee-Object -FilePath "$dir/$stem.log"
            $code = $LASTEXITCODE
            $ErrorActionPreference = $oldPreference
            if ($code -ne 0) { throw "vllm bench serve failed ($code)" }
            $raw = & wslc exec $profileConfig.Container cat "$guestDir/$stem.json"
            if ($LASTEXITCODE -ne 0) { throw 'Could not read benchmark results' }
            [IO.File]::WriteAllText((Join-Path $dir "$stem.json"),($raw -join "`n"),$utf8)
            $result = $raw -join "`n" | ConvertFrom-Json
            if ($result.completed -ne $Requests -or $result.failed -ne 0) { throw 'Some benchmark requests failed' }
            if ($result.total_output_tokens -ne $Requests*$OutputTokens) { throw 'Unexpected generated token total' }
            Start-Sleep -Seconds 12
            Save-Metrics "$stem-metrics-after.txt"
            $null = Invoke-WebRequest "$base/health" -UseBasicParsing -TimeoutSec 30
            Save @{started=$settingStarted; finished=[DateTimeOffset]::Now.ToString('o'); inputTokens=$length; concurrency=$clients; note='Includes CLI startup and final metrics flush; use for sampled memory peaks, not benchmark duration.'} "$stem-window.json"
        }
    }
} finally {
    Set-Content -LiteralPath $stopFile -Value stop
    $null = Wait-Job $job -Timeout 15
    if ($job.State -eq 'Running') { Stop-Job $job }
    Receive-Job $job
    Remove-Job $job
}
Write-Host "Saved vLLM concurrency benchmark: $dir"
