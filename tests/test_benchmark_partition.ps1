$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
. "$(Split-Path $PSScriptRoot -Parent)/scripts/benchmark-partition.ps1"
$script:readings=[Collections.Generic.Queue[string]]::new()
$script:prompts=0
$script:answer='88'
function nvidia-smi { $global:LASTEXITCODE=0; return $script:readings.Dequeue() }
function Read-Host { param($Prompt); $script:prompts++; return $script:answer }
function Expect-Failure([scriptblock]$Action,[string]$Pattern){
    try {& $Action;throw 'Expected failure did not occur'}
    catch {if($_.Exception.Message -notlike $Pattern){throw}}
}
$script:readings.Enqueue('90112')
$result=Confirm-N1xBenchmarkPartition -Group 'test'
if($script:prompts -or $result.actualMiB -ne 90112){throw 'Matching partition should pass without a prompt'}
$script:readings.Enqueue('98304');$script:readings.Enqueue('90112')
$result=Confirm-N1xBenchmarkPartition -Group 'test'
if($script:prompts -ne 1 -or -not $result.changeConfirmed){throw 'Changed partition was not confirmed and rechecked'}
$script:readings.Enqueue('98304');$script:readings.Enqueue('98304')
Expect-Failure {Confirm-N1xBenchmarkPartition -Group 'test'} 'Partition still reports*'
$script:answer='cancel';$script:readings.Enqueue('98304')
Expect-Failure {Confirm-N1xBenchmarkPartition -Group 'test'} 'Cancelled*'
$script:readings.Enqueue('N/A')
Expect-Failure {Confirm-N1xBenchmarkPartition -Group 'test'} 'Cannot verify*'
function Read-Host {throw 'Noninteractive host'}
$script:readings.Enqueue('98304')
Expect-Failure {Confirm-N1xBenchmarkPartition -Group 'test'} 'Partition change required*'
Write-Host 'Benchmark partition confirmation and hardware recheck tests passed.'
