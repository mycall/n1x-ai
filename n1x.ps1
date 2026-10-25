param(
    [ValidateSet('start', 'stop', 'restart', 'status', 'wait', 'logs', 'test', 'doctor')]
    [string]$Action = 'status',
    [ValidateSet('baseline', 'mtp', 'long-context', 'mtp-long-context', 'throughput', 'mtp-throughput', 'long-context-graphs', 'candidate-fast', 'candidate-16')]
    [string]$Profile = 'baseline',
    [ValidateSet('smoke', 'features', 'context', 'all')]
    [string]$Suite = 'smoke',
    [ValidateRange(1, 86400)]
    [int]$TimeoutSeconds = 3600,
    [switch]$PrintOnly
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$config = Import-PowerShellDataFile (Join-Path $PSScriptRoot 'config.psd1')
if ($Profile -ne 'baseline') {
    $overrides = Import-PowerShellDataFile (Join-Path $PSScriptRoot "profiles/$Profile.psd1")
    foreach ($key in $overrides.Keys) { $config[$key] = $overrides[$key] }
}
$name = $config.Container
$endpoint = "http://127.0.0.1:$($config.Port)"

function Invoke-Wslc([string[]]$Arguments) {
    & wslc @Arguments
    if ($LASTEXITCODE -ne 0) { throw "wslc failed ($LASTEXITCODE): $($Arguments -join ' ')" }
}

function Get-ManagedContainer {
    $rows = & wslc list --all --filter "name=$name" --format json
    if ($LASTEXITCODE -ne 0) { throw 'Cannot list WSLC containers' }
    # WSLC's name filter also matches profile suffixes; require an exact name.
    $matches = @($rows | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json } | Where-Object { $_.Names -eq $name })
    if (-not $matches.Count) { return $null }
    $raw = & wslc inspect $name
    if ($LASTEXITCODE -ne 0) { throw "Cannot inspect $name" }
    $container = @($raw | ConvertFrom-Json)[0]
    if ($container.Config.Labels.'n1x-ai.managed' -ne 'true') {
        throw "Container $name is not managed by n1x-ai; refusing to change it"
    }
    return $container
}

function Assert-NoOtherProfile {
    $rows = & wslc list --filter 'label=n1x-ai.managed=true' --format json
    if ($LASTEXITCODE -ne 0) { throw 'Cannot check running project containers' }
    $others = @($rows | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json } | Where-Object { $_.Names -ne $name })
    if ($others.Count) {
        throw "Another project profile is running: $($others.Names -join ', '). Stop it before starting $name."
    }
}

function Assert-ProfileRunning {
    $container = Get-ManagedContainer
    if (-not $container -or -not $container.State.Running) {
        throw "Selected profile '$Profile' is not running. Start it or select the active profile."
    }
}

switch ($Action) {
    'start' {
        if (-not $PrintOnly) {
            Assert-NoOtherProfile
            $existing = Get-ManagedContainer
            if ($existing) {
                if ($existing.State.Running) { Write-Host "$name is already running. Check status for API readiness." }
                else { Invoke-Wslc @('start', $name); Write-Host "Starting $name with its existing configuration." }
                return
            }
        }
        $model = Join-Path $config.ModelRoot 'Qwen3.8-Flash-Next-W4A16-AutoRound-hybrid'
        $table = Join-Path $config.ModelRoot 'ple-table-fp8'
        foreach ($file in @("$model/config.json", "$model/model.safetensors.index.json", "$table/model-00005-of-00131.safetensors")) {
            if (-not (Test-Path -LiteralPath $file)) { throw "Missing model file: $file" }
        }
        $index = Get-Content "$model/model.safetensors.index.json" -Raw | ConvertFrom-Json
        foreach ($shard in ($index.weight_map.PSObject.Properties.Value | Sort-Object -Unique)) {
            if (-not (Test-Path -LiteralPath (Join-Path $model $shard))) { throw "Missing model shard: $shard" }
        }
        $tableMount=$table
        if ($config.ContainsKey('PleVolume')) {
            $tableMount=$config.PleVolume
            if (-not $PrintOnly) {
                $manifestRaw=& wslc run --rm --entrypoint cat --volume "${tableMount}:/table:ro" $config.Image /table/n1x-copy-manifest.json
                if ($LASTEXITCODE -ne 0) { throw 'Prepare the native PLE volume with prepare-native-ple.ps1 first' }
                $manifest=($manifestRaw -join "`n") | ConvertFrom-Json
                if ($manifest.sourceRevision -ne '50511b0a41aa1d34b8beb7e5d4bb06a0b650dc14') { throw 'Unexpected native PLE revision' }
                foreach ($sourceFile in (Get-ChildItem -LiteralPath $table -File)) {
                    $entry=@($manifest.files | Where-Object { $_.name -eq $sourceFile.Name })
                    if ($entry.Count -ne 1 -or $entry[0].bytes -ne $sourceFile.Length) { throw "Native PLE manifest mismatch: $($sourceFile.Name)" }
                }
            }
        }
        $run = @(
            'run', '-d', '--name', $name, '--label', 'n1x-ai.managed=true',
            '--gpus', 'all', '--shm-size', '1g', '--ulimit', 'memlock=-1:-1',
            '--publish', "127.0.0.1:$($config.Port):8000",
            '--volume', "${model}:/model:ro", '--volume', "${tableMount}:/ple-table-fp8:ro",
            '--volume', "$($config.CacheVolume):/root/.cache",
            '--env', 'HF_HUB_OFFLINE=1', '--env', 'TOKENIZERS_PARALLELISM=false',
            '--env', 'MAX_JOBS=1', '--env', 'FLASHINFER_NVCC_THREADS=1',
            '--env', 'TORCHINDUCTOR_COMPILE_THREADS=1',
            '--env', 'VLLM_PLE_MMAP_DIR=/ple-table-fp8', '--env', 'VLLM_PLE_MMAP_PREWARM=0',
            '--env', "VLLM_PLE_MMAP_WORKERS=$($config.PleWorkers)", '--env', 'VLLM_PLE_MMAP_CHUNK=2048',
            '--env', 'VLLM_FP8_HYBRID=1', '--env', 'VLLM_MARLIN_USE_ATOMIC_ADD=1',
            '--env', 'VLLM_USE_DEEP_GEMM=0', '--env', 'VLLM_USE_FLASHINFER_SAMPLER=1',
            '--volume', "${PSScriptRoot}/profiles:/profiles:ro",
            $config.Image,
            '--model', '/model', '--served-model-name', 'qwen', '--host', '0.0.0.0', '--port', '8000',
            '--max-model-len', [string]$config.Context, '--max-num-seqs', [string]$config.MaxSequences,
            '--gpu-memory-utilization', '0.01', '--kv-cache-memory-bytes', $config.KvCacheBytes,
            '--load-format', 'safetensors', '--safetensors-load-strategy', 'lazy',
            '--enable-prefix-caching', '--enable-chunked-prefill',
            '--max-num-batched-tokens', [string]$config.BatchedTokens,
            '--mamba-ssm-cache-dtype', 'bfloat16', '--kv-cache-dtype', 'auto',
            '--no-enable-flashinfer-autotune',
            '--enable-auto-tool-choice', '--tool-call-parser', 'qwen3_xml', '--reasoning-parser', 'qwen3'
        )
        if ($config.ContainsKey('CudaGraphMode')) { $run += "-cc.cudagraph_mode=$($config.CudaGraphMode)" }
        else { $run += '--enforce-eager' }
        if ($Profile -in @('mtp', 'mtp-long-context', 'mtp-throughput', 'candidate-fast', 'candidate-16')) { $run += @('--config', '/profiles/mtp.yaml') }
        if ($PrintOnly) { Write-Output ('wslc ' + (($run | ForEach-Object { '"' + $_ + '"' }) -join ' ')); return }
        # WSLC refuses a name collision if another process created it meanwhile.
        Invoke-Wslc $run
        Write-Host "Loading model. Check .\n1x.ps1 status -Profile $Profile and .\n1x.ps1 logs -Profile $Profile. API: $endpoint/v1"
    }
    'stop' { if (-not (Get-ManagedContainer)) { throw "No managed container $name" }; Invoke-Wslc @('stop', $name) }
    'restart' { Assert-NoOtherProfile; if (-not (Get-ManagedContainer)) { throw "No managed container $name" }; Invoke-Wslc @('restart', $name) }
    'logs' { Invoke-Wslc @('logs', '--tail', '100', $name) }
    'wait' {
        $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
        $lastNotice = [datetime]::MinValue
        Write-Host "Waiting up to $TimeoutSeconds seconds for $Profile at $endpoint ..."
        while ((Get-Date) -lt $deadline) {
            # A WSLC transport timeout does not mean the container has stopped.
            $raw = & wslc inspect $name
            if ($LASTEXITCODE -eq 0) {
                $selected = @($raw | ConvertFrom-Json)[0]
                if (-not $selected.State.Running) { throw "Container $name stopped before API readiness; inspect its logs." }
                try {
                    $remaining = [math]::Max(1, [int]($deadline - (Get-Date)).TotalSeconds)
                    $health = Invoke-WebRequest "$endpoint/health" -UseBasicParsing -TimeoutSec ([math]::Min(30, $remaining))
                    if ($health.StatusCode -eq 200) { Write-Host "READY: $endpoint/v1 ($Profile)"; return }
                } catch {
                    if (((Get-Date) - $lastNotice).TotalSeconds -ge 60) {
                        Write-Host "API not ready; retrying: $($_.Exception.Message)"
                        $lastNotice = Get-Date
                    }
                }
            } else { Write-Host 'WSLC temporarily unavailable; retrying without stopping the container.' }
            Start-Sleep -Seconds 10
        }
        throw "API did not become ready within $TimeoutSeconds seconds. Container left running for inspection."
    }
    'status' {
        $selected = Get-ManagedContainer
        if ($selected) { Write-Host "${name}: $($selected.State.Status)" }
        if (-not $selected -or -not $selected.State.Running) {
            Write-Host "Selected profile '$Profile' is stopped or has not been created."
            return
        }
        try {
            $models = Invoke-RestMethod "$endpoint/v1/models" -TimeoutSec 5
            Write-Host "READY: $endpoint/v1"
            $models.data | Select-Object id, max_model_len
        } catch { Write-Host "API not ready: $($_.Exception.Message)" }
    }
    'doctor' {
        Invoke-Wslc @('info')
        Invoke-Wslc @('images')
        & nvidia-smi
        Write-Host "Models: $($config.ModelRoot)"
    }
    'test' {
        Assert-ProfileRunning
        if ($Suite -ne 'smoke') {
            & (Join-Path $PSScriptRoot 'test.ps1') -Suite $Suite -ResultName "$Suite-$Profile"
            return
        }
        $tests = @(
            @{ Name='instruction'; Prompt='Reply with exactly OK and nothing else.'; Expected='^OK[.!]?$' },
            @{ Name='arithmetic'; Prompt='What is 17 plus 25? Reply with only the number.'; Expected='^42[.!]?$' },
            @{ Name='context'; Prompt='Remember this code: RIVER-729. What code did I ask you to remember? Reply with only the code.'; Expected='^RIVER-729[.!]?$' }
        )
        $results = @()
        foreach ($test in $tests) {
            $body = @{
                model='qwen'; messages=@(@{role='user'; content=$test.Prompt})
                max_tokens=128; temperature=0; chat_template_kwargs=@{enable_thinking=$false}
            } | ConvertTo-Json -Depth 8
            $reply = Invoke-RestMethod "$endpoint/v1/chat/completions" -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 600
            $content = [string]$reply.choices[0].message.content
            $passed = $content.Trim() -match $test.Expected
            $results += [pscustomobject]@{test=$test.Name; passed=$passed; content=$content; finish_reason=$reply.choices[0].finish_reason}
        }
        $resultDir = Join-Path $PSScriptRoot 'results'
        New-Item -ItemType Directory -Force $resultDir | Out-Null
        $results | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $resultDir "smoke-$Profile.json") -Encoding UTF8
        $results | Format-Table -AutoSize
        if (@($results | Where-Object { -not $_.passed }).Count) { throw "Model correctness check failed; see results/smoke-$Profile.json" }
    }
}
