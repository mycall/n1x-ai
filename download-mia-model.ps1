#Requires -Version 5.1
<#
.SYNOPSIS
Download all files of Mia's default TensorFold recipe checkpoint (about 96 GiB).
.DESCRIPTION
Uses the NVIDIA FP4-Local revision pinned by Mia's recipe on 2026-11-15:
https://github.com/MiaAI-Lab/Qwen3.8-Flash-Next-Single-DGX-Spark-TensorFold/blob/main/scripts/config.sh
Downloads weights, tokenizer, configuration, vision/MTP assets and other repository
files without filtering. This does not install the patched TensorFold engine or
change the serving profile. The destination is a flat model directory; Mia's
unmodified Linux launcher instead expects a Hugging Face cache snapshot layout.
Rerun the same command to reuse completed downloads and resume missing files.
.EXAMPLE
.\download-mia-model.ps1
.EXAMPLE
.\download-mia-model.ps1 -DryRun
#>
[CmdletBinding()]
param(
    [string]$ModelRoot = (Join-Path ([Environment]::GetFolderPath('UserProfile')) 'models'),
    [switch]$DryRun,
    [switch]$PrintOnly
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repository = 'nvidia/Qwen3.8-Flash-Next-FP4-Local'
$revision = 'b9ce18a6887e18c089fdea8509a33e63429a3300'
$destination = Join-Path ([IO.Path]::GetFullPath($ModelRoot)) 'Qwen3.8-Flash-Next-FP4-Local'
$downloadArgs = @('download', $repository, '--revision', $revision, '--local-dir', $destination)
if($DryRun){$downloadArgs += '--dry-run'}
Write-Host "Checkpoint: $repository @ $revision"
Write-Host "Destination: $destination"
if($PrintOnly){
    Write-Output ('hf ' + (($downloadArgs | ForEach-Object { "'" + $_.Replace("'", "''") + "'" }) -join ' '))
    return
}
if(-not(Get-Command hf -ErrorAction SilentlyContinue)){
    throw 'Hugging Face CLI not found. Install with: uv tool install huggingface_hub'
}
& hf @downloadArgs
if($LASTEXITCODE -ne 0){throw 'Download failed. Rerun this script to resume; existing model files are retained.'}
if($DryRun){Write-Host 'Dry run complete; no model files downloaded.'}
else {Write-Host "Download complete: $destination"}
