$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$root=Split-Path $PSScriptRoot -Parent
$fixture=Join-Path ([IO.Path]::GetTempPath()) ('n1x-tool-feature-'+[guid]::NewGuid().ToString('N'))
$requests=[Collections.Generic.List[object]]::new()
$reasonField='reasoning'
$fixtureReplyContent='23'
function Invoke-RestMethod($Uri,$Method,$ContentType,$Body,$TimeoutSec){
 $payload=[Text.Encoding]::UTF8.GetString($Body)|ConvertFrom-Json
 $requests.Add($payload)
 if(-not $payload.chat_template_kwargs.enable_thinking -or $payload.max_tokens -ne 1024){throw 'Tool feature must use thinking and the qualified 1024 allowance'}
 if($requests.Count -eq 1){
  $call=[pscustomobject]@{id='call-preserved';type='function';function=[pscustomobject]@{name='lookup_inventory';arguments='{"sku":"AX-42"}'}}
  $message=[pscustomobject]@{role='assistant';content=$null;tool_calls=@($call)}
  $message|Add-Member -NotePropertyName $reasonField -NotePropertyValue 'reason-to-preserve'
  return [pscustomobject]@{choices=@([pscustomobject]@{finish_reason='tool_calls';message=$message})}
 }
 if($requests.Count -ne 2){throw 'Unexpected tool request retry'}
 if($payload.messages[1].$reasonField -ne 'reason-to-preserve'){throw 'Returned reasoning was discarded'}
 if($payload.messages[1].tool_calls[0].id -ne 'call-preserved' -or $payload.messages[2].tool_call_id -ne 'call-preserved'){throw 'Tool-call identity changed'}
 return [pscustomobject]@{choices=@([pscustomobject]@{finish_reason='stop';message=[pscustomobject]@{content=$fixtureReplyContent}})}
}
function Invoke-WebRequest { [pscustomobject]@{StatusCode=200} }
try {
 New-Item -ItemType Directory -Force "$fixture/scripts"|Out-Null
 Copy-Item "$root/test.ps1","$root/config.psd1" $fixture
 Copy-Item "$root/scripts/config.ps1" "$fixture/scripts"
 foreach($fieldName in @('reasoning','reasoning_content')){
  $reasonField=$fieldName;$fixtureReplyContent='23';$requests.Clear()
  & "$fixture/test.ps1" -Tests tool_round_trip -Profile qwen38fn-baseline -ResultName "tool-$fieldName"
  $row=Get-Content "$fixture/.state/checks/tool-$fieldName.json" -Raw|ConvertFrom-Json
  if(-not $row.passed -or $requests.Count -ne 2 -or -not $row.evidence.thinking){throw 'Supported tool contract failed'}
 }
 $reasonField='reasoning';$fixtureReplyContent='The count is 23.';$requests.Clear()
 $rejected=$false
 try { & "$fixture/test.ps1" -Tests tool_round_trip -Profile qwen38fn-baseline -ResultName 'tool-format-negative' }
 catch {if($_.Exception.Message -like 'Some qualification checks failed*'){$rejected=$true}else{throw}}
 $row=Get-Content "$fixture/.state/checks/tool-format-negative.json" -Raw|ConvertFrom-Json
 if(-not $rejected -or $row.passed -or $requests.Count -ne 2){throw 'Strict final format was relaxed or retried'}
 Write-Output 'Tool feature thinking, reasoning preservation, tool IDs and strict final-format checks passed'
}finally{
 $resolved=[IO.Path]::GetFullPath($fixture)
 $temp=[IO.Path]::GetFullPath([IO.Path]::GetTempPath())
 if(-not $resolved.StartsWith($temp,[StringComparison]::OrdinalIgnoreCase) -or [IO.Path]::GetFileName($resolved) -notlike 'n1x-tool-feature-*'){throw 'Unsafe fixture cleanup target'}
 if(Test-Path -LiteralPath $resolved){Remove-Item -LiteralPath $resolved -Recurse -Force}
}
