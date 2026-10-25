#Requires -Version 5.1
param([string]$ModelRoot='')
$ErrorActionPreference='Stop'
. "$PSScriptRoot/scripts/config.ps1"
$config=Get-N1xConfig -Root $PSScriptRoot -ModelRoot $ModelRoot
& hf download incoai/Qwen3.8-Flash-Next-DFlash2 `
    --revision a22a1744e85c17364dcc54a6a420af7135d4c7f6 `
    --local-dir (Join-Path $config.ModelRoot 'Qwen3.8-Flash-Next-DFlash2')
if($LASTEXITCODE -ne 0){throw 'Drafter download failed; rerun to resume'}
