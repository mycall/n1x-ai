#Requires -Version 5.1
param([string]$ModelRoot='')
$ErrorActionPreference='Stop'
. "$PSScriptRoot/scripts/config.ps1"
. "$PSScriptRoot/scripts/models.ps1"
$config=Get-N1xConfig -Root $PSScriptRoot -ModelRoot $ModelRoot
Get-N1xModelDownload 'incoai/Qwen3.8-Flash-Next-DFlash2' 'a22a1744e85c17364dcc54a6a420af7135d4c7f6' (Join-Path $config.ModelRoot 'Qwen3.8-Flash-Next-DFlash2') 'drafter'
