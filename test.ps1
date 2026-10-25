param(
    [ValidateSet('features', 'context', 'all')][string]$Suite = 'features',
    [int[]]$ContextTokens = @(4096, 16384, 31744),
    [string[]]$Tests = @(),
    [int]$Port = 0,
    [string]$ResultName = 'qualification',
    [string]$CacheSalt = ''
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
. "$PSScriptRoot/scripts/config.ps1"
$config=Get-N1xConfig -Root $PSScriptRoot -Port $Port
$base = "http://127.0.0.1:$($config.Port)"
$resultDir = Join-Path $PSScriptRoot '.state/checks'
New-Item -ItemType Directory -Force $resultDir | Out-Null
$script:results = [Collections.Generic.List[object]]::new()
$utf8 = [Text.UTF8Encoding]::new($false)

function Write-JsonFile($Value, [string]$Name) {
    [IO.File]::WriteAllText((Join-Path $resultDir $Name), (ConvertTo-Json -InputObject $Value -Depth 30), $utf8)
}
function Post-Json([string]$Path, $Body) {
    $json = ConvertTo-Json -InputObject $Body -Depth 30 -Compress
    Invoke-RestMethod "$base$Path" -Method Post -ContentType 'application/json; charset=utf-8' -Body $utf8.GetBytes($json) -TimeoutSec 3600
}
function Chat($Messages, $Extra = @{}) {
    $body = @{model='qwen'; messages=@($Messages); temperature=0; max_tokens=256; chat_template_kwargs=@{enable_thinking=$false}}
    if($CacheSalt){$body.cache_salt=$CacheSalt}
    foreach ($key in $Extra.Keys) { $body[$key] = $Extra[$key] }
    Post-Json '/v1/chat/completions' $body
}
function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}
function Run-Check([string]$Name, [scriptblock]$Check) {
    if ($Tests.Count -and $Name -notin $Tests) { return }
    Write-Host "Checking $Name ..."
    try {
        $evidence = & $Check
        $health = Invoke-WebRequest "$base/health" -UseBasicParsing -TimeoutSec 15
        Assert-True ($health.StatusCode -eq 200) 'API unhealthy after request'
        $script:results.Add([pscustomobject]@{test=$Name; passed=$true; evidence=$evidence})
        Write-Host "PASS $Name"
    } catch {
        $script:results.Add([pscustomobject]@{test=$Name; passed=$false; error=$_.Exception.Message})
        Write-Host "FAIL ${Name}: $($_.Exception.Message)"
    }
    Write-JsonFile ($script:results.ToArray()) "$ResultName.json"
}

if ($Suite -in @('features','all')) {
    Run-Check 'streaming' {
        $body = @{model='qwen'; messages=@(@{role='user'; content='Reply with exactly STREAM-OK and nothing else.'}); max_tokens=64; temperature=0; stream=$true; chat_template_kwargs=@{enable_thinking=$false}}
        $response = Invoke-WebRequest "$base/v1/chat/completions" -UseBasicParsing -Method Post -ContentType 'application/json; charset=utf-8' -Body $utf8.GetBytes(($body | ConvertTo-Json -Depth 10 -Compress)) -TimeoutSec 600
        $events = @($response.Content -split '\r?\n' | Where-Object { $_.StartsWith('data: ') })
        Assert-True ($events -contains 'data: [DONE]') 'Missing SSE completion marker'
        $text = [Text.StringBuilder]::new()
        $finish = $null
        foreach ($event in $events) {
            if ($event -eq 'data: [DONE]') { continue }
            $chunk = $event.Substring(6) | ConvertFrom-Json
            if ($chunk.choices.Count) {
                $choice = $chunk.choices[0]
                if ($choice.delta.PSObject.Properties['content']) { [void]$text.Append([string]$choice.delta.content) }
                if ($choice.finish_reason) { $finish = $choice.finish_reason }
            }
        }
        Assert-True ($text.ToString().Trim() -eq 'STREAM-OK') "Unexpected streamed answer: $text"
        Assert-True ($finish -eq 'stop') 'Stream did not finish normally'
        @{content=$text.ToString(); events=$events.Count; finish_reason=$finish}
    }
    Run-Check 'json_output' {
        $reply = Chat @(@{role='user'; content='Return a JSON object with exactly these values: color is green and count is 7.'}) @{response_format=@{type='json_object'}}
        Write-JsonFile $reply "$ResultName-json-response.json"
        $value = $reply.choices[0].message.content | ConvertFrom-Json
        Assert-True ($value.color -eq 'green' -and $value.count -eq 7) 'Incorrect JSON values'
        $value
    }
    Run-Check 'tool_round_trip' {
        $tools = @(@{type='function'; function=@{name='lookup_inventory'; description='Get the current inventory count for a product SKU.'; parameters=@{type='object'; properties=@{sku=@{type='string'}}; required=@('sku'); additionalProperties=$false}}})
        $messages = @(@{role='user'; content='Use lookup_inventory to look up product SKU AX-42. Do not guess the inventory. After the tool replies, report only the inventory count.'})
        $first = Chat $messages @{tools=$tools; tool_choice='auto'}
        Write-JsonFile $first "$ResultName-tool-call.json"
        $assistant = $first.choices[0].message
        Assert-True ($assistant.tool_calls.Count -eq 1) 'Expected exactly one tool call'
        $call = $assistant.tool_calls[0]
        Assert-True ($call.function.name -eq 'lookup_inventory') 'Incorrect tool name'
        $arguments = $call.function.arguments | ConvertFrom-Json
        Assert-True ($arguments.sku -eq 'AX-42') 'Incorrect tool arguments'
        $messages += @{role='assistant'; content=$assistant.content; tool_calls=@($call)}
        $messages += @{role='tool'; tool_call_id=$call.id; content='{"sku":"AX-42","count":23}'}
        $second = Chat $messages @{tools=$tools; tool_choice='none'}
        Write-JsonFile $second "$ResultName-tool-result.json"
        Assert-True ($second.choices[0].message.content.Trim() -match '^23[.!]?$') 'Incorrect tool-result answer'
        @{tool=$call.function.name; arguments=$arguments; answer=$second.choices[0].message.content}
    }
    Run-Check 'reasoning' {
        $reply = Chat @(@{role='user'; content='A box has 9 rows of 7 marbles. Think through the calculation, then give the total as a number.'}) @{max_tokens=512; chat_template_kwargs=@{enable_thinking=$true}}
        Write-JsonFile $reply "$ResultName-reasoning.json"
        $message = $reply.choices[0].message
        $reasoning = @($message.PSObject.Properties | Where-Object { $_.Name -in @('reasoning','reasoning_content') } | ForEach-Object { [string]$_.Value }) -join ''
        Assert-True (-not [string]::IsNullOrWhiteSpace($reasoning)) 'No separate reasoning field returned'
        Assert-True ($message.content -match '\b63\b') 'Incorrect final answer'
        @{content=$message.content; separate_reasoning=$true; finish_reason=$reply.choices[0].finish_reason}
    }

    # Deterministic local fixtures; no downloaded images or image-generation service.
    Add-Type -AssemblyName System.Drawing
    $bitmap = [Drawing.Bitmap]::new(640, 320)
    $graphics = [Drawing.Graphics]::FromImage($bitmap)
    $graphics.Clear([Drawing.Color]::White)
    $graphics.FillEllipse([Drawing.Brushes]::Red, 60, 50, 180, 180)
    $graphics.FillRectangle([Drawing.Brushes]::Blue, 390, 50, 180, 180)
    $font = [Drawing.Font]::new('Arial', 32, [Drawing.FontStyle]::Bold)
    $graphics.DrawString('N1X-742', $font, [Drawing.Brushes]::Black, 215, 250)
    $fixture = Join-Path $resultDir 'vision-fixture.png'
    $bitmap.Save($fixture, [Drawing.Imaging.ImageFormat]::Png)
    $font.Dispose(); $graphics.Dispose(); $bitmap.Dispose()
    $dataUri = 'data:image/png;base64,' + [Convert]::ToBase64String([IO.File]::ReadAllBytes($fixture))
    Run-Check 'vision_shapes' {
        $content = @(@{type='text'; text='Describe the shape and color on the left, then the shape and color on the right. Be brief.'}, @{type='image_url'; image_url=@{url=$dataUri}})
        $reply = Chat @(@{role='user'; content=$content})
        Write-JsonFile $reply "$ResultName-vision-shapes.json"
        $answer = $reply.choices[0].message.content
        Assert-True ($answer -match '(?is)red.*circle|circle.*red') 'Red circle not identified'
        Assert-True ($answer -match '(?is)blue.*square|square.*blue') 'Blue square not identified'
        @{content=$answer; fixture='vision-fixture.png'}
    }
    Run-Check 'vision_ocr' {
        $content = @(@{type='text'; text='Read the printed code at the bottom of this image. Reply with only that code.'}, @{type='image_url'; image_url=@{url=$dataUri}})
        $reply = Chat @(@{role='user'; content=$content})
        Write-JsonFile $reply "$ResultName-vision-ocr.json"
        $answer = $reply.choices[0].message.content
        Assert-True ($answer.Trim() -match '^N1X-742[.!]?$') 'Incorrect image text'
        @{content=$answer; fixture='vision-fixture.png'}
    }
}

if ($Suite -in @('context','all')) {
    foreach ($target in $ContextTokens) {
        Run-Check "context_$target" {
            $lineCount = [math]::Max(10, [int]($target / 18))
            $text = ''
            $tokenCount = 0
            for ($attempt=0; $attempt -lt 5; $attempt++) {
                $lines = [Collections.Generic.List[string]]::new()
                for ($i=0; $i -lt $lineCount; $i++) {
                    $lines.Add(('Record {0:D6}: warehouse item has batch {1:D6} and status archived.' -f $i, (($i * 7919 + 137) % 999983)))
                }
                $lines[[int]($lineCount * 0.1)] = 'SPECIAL RECORD: The cedar access code is CEDAR-5831.'
                $lines[[int]($lineCount * 0.5)] = 'SPECIAL RECORD: The maple access code is MAPLE-9264.'
                $lines[[int]($lineCount * 0.9)] = 'SPECIAL RECORD: The birch access code is BIRCH-1748.'
                $text = "Read this archive and answer the question at its end.`n" + ($lines -join "`n") + "`nQuestion: Return the cedar, maple, and birch access codes, in that order, and nothing else."
                $tokenized = Post-Json '/tokenize' @{model='qwen'; messages=@(@{role='user'; content=$text}); chat_template_kwargs=@{enable_thinking=$false}}
                $tokenCount = $tokenized.count
                if ($tokenCount -le $target -and $tokenCount -ge $target * 0.95) { break }
                $lineCount = [math]::Max(10, [int]($lineCount * ($target - 128) / $tokenCount))
            }
            Assert-True ($tokenCount -le $target) "Prompt exceeds target: $tokenCount"
            Write-Host "Sending $tokenCount input tokens; no throughput measurement."
            $reply = Chat @(@{role='user'; content=$text}) @{max_tokens=128}
            Write-JsonFile $reply "$ResultName-context-$target.json"
            $answer = $reply.choices[0].message.content
            Assert-True ($answer -match '(?s)CEDAR-5831.*MAPLE-9264.*BIRCH-1748') 'Failed to retrieve all three codes in order'
            @{input_tokens=$reply.usage.prompt_tokens; target_tokens=$target; content=$answer; finish_reason=$reply.choices[0].finish_reason}
        }
    }
}
$script:results.ToArray() | Select-Object test,passed | Format-Table -AutoSize
if (@($script:results.ToArray() | Where-Object { -not $_.passed }).Count) { throw 'Some qualification checks failed; inspect results.' }
